"""Hardware brightness routing against fake sysfs and mocked clients."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import DESKTOP, backend, display, state

SPEC = importlib.util.spec_from_file_location(
    'desktop_brightness', DESKTOP / 'drawers/displays/brightness.py'
)
brightness = importlib.util.module_from_spec(SPEC)
_bytecode_disabled = sys.dont_write_bytecode
sys.dont_write_bytecode = True
with patch.dict(sys.modules, {'backend': backend}):
    SPEC.loader.exec_module(brightness)
sys.dont_write_bytecode = _bytecode_disabled


class DisplayBrightnessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.drm = self.root / 'drm'
        self.drm.mkdir()
        self.backlight = self.root / 'backlight'
        self.backlight.mkdir()
        self.panel = self.drm / 'card2-eDP-1'
        self.panel.mkdir()
        (self.panel / 'status').write_text('connected\n')
        light = self.panel / 'amdgpu_bl0'
        light.mkdir()
        (light / 'brightness').write_text('200')
        (light / 'max_brightness').write_text('1000')
        (self.backlight / 'amdgpu_bl0').symlink_to(light)
        self.external = self.drm / 'card2-DP-1'
        self.external.mkdir()
        (self.external / 'status').write_text('connected\n')
        bus = self.root / 'i2c-10'
        bus.mkdir()
        (self.external / 'ddc').symlink_to(bus)
        self.rows = [display(), display('DP-1', x=1920)]
        self.patches = [
            patch.object(brightness, 'DRM', self.drm),
            patch.object(brightness, 'BACKLIGHT', self.backlight),
            patch.object(backend, 'snapshot', side_effect=lambda: state(self.rows)),
            patch.object(brightness.shutil, 'which', return_value='/usr/bin/ddcutil'),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def request(self, name='eDP-1', **values):
        row = next(row for row in self.rows if row['name'] == name)
        return dict(
            dict(
                op='brightness',
                name=name,
                identity=row['identity'],
                value=30,
                kind='backlight' if name == 'eDP-1' else 'ddc',
                key='amdgpu_bl0' if name == 'eDP-1' else '10',
            ),
            **values,
        )

    def test_output_matching_uses_connector_ancestry_and_ddc_bus(self):
        internal = brightness.controller(self.rows[0])
        external = brightness.controller(self.rows[1])
        self.assertEqual(
            (internal['kind'], internal['key']), ('backlight', 'amdgpu_bl0')
        )
        self.assertEqual((external['kind'], external['key']), ('ddc', '10'))
        with patch.object(brightness, 'run', return_value='VCP 10 C 42 100') as run:
            result = brightness.handle(dict(op='status'))
        self.assertEqual([row['value'] for row in result], [20, 42])
        run.assert_called_once_with('ddcutil', '--bus', '10', '--terse', 'getvcp', '10')

    def test_displayport_prefers_connector_aux_bus_over_physical_ddc_link(self):
        (self.external / 'i2c-19').mkdir()
        self.assertEqual(brightness.controller(self.rows[1])['key'], '19')

    def test_backlight_write_uses_exact_device_and_native_range(self):
        with patch.object(brightness, 'run') as run:
            brightness.handle(self.request())
        run.assert_called_once_with(
            'brightnessctl', '--class=backlight', '--device', 'amdgpu_bl0', 'set', '300'
        )

    def test_ddc_write_scales_native_max_and_rechecks_readback(self):
        with patch.object(brightness, 'run', return_value='VCP 10 C 70 200') as run:
            result = brightness.handle(self.request('DP-1'))
        self.assertEqual(
            run.call_args_list[1].args, ('ddcutil', '--bus', '10', 'setvcp', '10', '60')
        )
        self.assertEqual(result[0]['value'], 35)
        self.assertEqual(run.call_count, 3)

    def test_stale_identity_unknown_controller_and_invalid_values_never_write(self):
        requests = [
            self.request(identity=['changed']),
            self.request(key='another'),
            dict(self.request(), name='gone'),
        ]
        requests += [
            self.request(value=value) for value in (0, 101, True, float('nan'), '30')
        ]
        with patch.object(brightness, 'run') as run:
            for request in requests:
                with self.subTest(request=request), self.assertRaises(ValueError):
                    brightness.handle(request)
            run.assert_not_called()

    def test_disabled_output_is_not_mutated(self):
        self.rows[0]['enabled'] = False
        with (
            patch.object(brightness, 'run') as run,
            self.assertRaisesRegex(ValueError, 'Enable'),
        ):
            brightness.handle(self.request())
        run.assert_not_called()

    def test_unavailable_ddc_keeps_other_brightness_working(self):
        with patch.object(
            brightness, 'run', side_effect=ValueError('Permission denied')
        ):
            result = brightness.handle(dict(op='status'))
        self.assertTrue(result[0]['available'])
        self.assertFalse(result[1]['available'])
        self.assertIn('Permission', result[1]['reason'])

    def test_ambiguous_connector_never_uses_arbitrary_hardware(self):
        duplicate = self.drm / 'card1-eDP-1'
        duplicate.mkdir()
        (duplicate / 'status').write_text('connected')
        with patch.object(brightness, 'run') as run:
            result = brightness.describe(self.rows[0])
        self.assertFalse(result['available'])
        run.assert_not_called()

    def test_unsupported_vcp_response_and_invalid_backlight_range(self):
        with patch.object(brightness, 'run', return_value='VCP 10 ERR'):
            self.assertFalse(brightness.describe(self.rows[1])['available'])
        (self.panel / 'amdgpu_bl0/max_brightness').write_text('0')
        self.assertFalse(brightness.describe(self.rows[0])['available'])

    def test_hotplug_after_write_is_reported_without_retargeting(self):
        def write(*args):
            if args[0] == 'brightnessctl':
                self.rows.clear()

        with (
            patch.object(brightness, 'run', side_effect=write) as run,
            self.assertRaisesRegex(ValueError, 'disconnected'),
        ):
            brightness.handle(self.request())
        self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
