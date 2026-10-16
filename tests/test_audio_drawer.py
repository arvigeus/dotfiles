"""Exercise audio boundaries and the real drawer without mutating host audio."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

DESKTOP = Path(__file__).resolve().parents[1] / 'modules/desktop/quickshell/symlinks/home/.config/quickshell/desktop'
SPEC = importlib.util.spec_from_file_location('desktop_audio', DESKTOP / 'drawers/audio/backend.py')
backend = importlib.util.module_from_spec(SPEC)
_bytecode_disabled = sys.dont_write_bytecode
sys.dont_write_bytecode = True
SPEC.loader.exec_module(backend)
sys.dont_write_bytecode = _bytecode_disabled
QS = shutil.which('qs')

SINK = dict(index=7, name='laptop', description='Generic audio', mute=False,
            properties={'device.name': 'card'}, active_port='speaker',
            volume={'left': {'value': 32768}, 'right': {'value': 32768}},
            ports=[dict(name='speaker', description='Speakers', type='Speaker', availability='availability unknown'),
                   dict(name='jack', description='Headphones', type='Headphones', availability='not available')])
CARD = dict(index=4, name='card', active_profile='duplex', profiles={
    'duplex': dict(description='Stereo + microphone', sinks=1, available=True),
    'surround': dict(description='Surround', sinks=1, available=True),
    'off': dict(description='Off', sinks=0, available=True),
    'missing': dict(description='Disconnected', sinks=1, available=False)})
STREAM = dict(index=23, sink=7, mute=False, volume={'left': {'value': 65536}},
              properties={'application.name': '<Music & sound>', 'application.process.binary': 'test-player',
                          'media.name': 'Track', 'object.serial': '100'})
CONFIG = dict(rules=[dict(match={'node.name': 'laptop', 'port.name': 'speaker'}, label='Laptop speakers'),
                          dict(match={'node.name': 'laptop', 'port.name': 'jack'}, label='Laptop headphones', maxVolume=85)])


def fake_read(kind):
    return {'sinks': [SINK], 'cards': [CARD], 'sink-inputs': [STREAM], 'sources': [], 'source-outputs': []}[kind]


class AudioBackendTests(unittest.TestCase):
    def test_names_match_ports_and_bad_file_falls_back(self):
        self.assertEqual(backend.describe(SINK, SINK['ports'][0], CONFIG)['label'], 'Laptop speakers')
        self.assertEqual(backend.describe(SINK, SINK['ports'][1], CONFIG)['label'], 'Laptop headphones')
        other = dict(SINK, name='another-device')
        self.assertIn('Generic audio', backend.describe(other, SINK['ports'][0], CONFIG)['label'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'audio.json'
            self.assertEqual(backend.load_config(path.parent), ({'rules': [], 'profiles': {}}, ''))
            path.write_text(json.dumps({'rules': [{'label': 'x', 'contains': {'node.name': 'a'}, 'maxVolume': True}]}))
            self.assertIn('maxVolume', backend.load_config(path.parent)[1])
            path.write_text('{')
            self.assertIn('audio.json', backend.load_config(path.parent)[1])

    def test_snapshot_ports_profiles_stream_identity_and_default(self):
        with patch.object(backend, 'load_config', return_value=(CONFIG, '')), patch.object(backend, 'read', side_effect=fake_read), \
                patch.object(backend, 'command', return_value=json.dumps({'default_sink_name': 'laptop'})):
            state = backend.snapshot()
        self.assertTrue(state['outputs'][0]['selected'])
        self.assertEqual(state['outputs'][0]['volume'], 50)
        self.assertEqual(len(state['outputs']), 1)
        self.assertEqual([r['name'] for r in state['outputs'][0]['routes']], ['speaker'])
        self.assertEqual(len(state['outputDevices'][0]['profiles']), 2)
        self.assertEqual(state['streams'][0]['key'], '23:100')
        self.assertEqual(state['streams'][0]['label'], '<Music & sound>')
        self.assertEqual(state['streams'][0]['applicationBinary'], 'test-player')

    def test_disconnected_port_and_stale_stream_never_mutate(self):
        with patch.object(backend, 'load_config', return_value=(CONFIG, '')), patch.object(backend, 'read', side_effect=fake_read), \
                patch.object(backend, 'command') as command:
            for request, message in [(dict(op='output-port', name='laptop', port='jack'), 'disconnected'),
                                     (dict(op='mute', kind='stream', index=23, token='99', muted=True), 'stream has ended'),
                                     (dict(op='output-default', name='gone'), 'disconnected'),
                                     (dict(op='profile', name='laptop', card='other', previous='duplex', profile='surround'), 'changed')]:
                with self.assertRaisesRegex(ValueError, message):
                    backend.control(request)
            command.assert_not_called()

    def test_volume_cap_boost_and_mute_independence(self):
        with patch.object(backend, 'load_config', return_value=(CONFIG, '')), patch.object(backend, 'read', side_effect=fake_read), \
                patch.object(backend, 'command') as command:
            backend.control(dict(op='volume', name='laptop', value=75))
            command.assert_called_once_with('set-sink-volume', 'laptop', '75%')
            backend.control(dict(op='volume', name='laptop', value=140, boost=True))
            for value in [101, -1, float('nan'), True]:
                with self.assertRaises(ValueError):
                    backend.control(dict(op='volume', name='laptop', value=value))
            with patch.object(backend, 'read', return_value=[dict(SINK, active_port='jack')]):
                with self.assertRaisesRegex(ValueError, '85'):
                    backend.control(dict(op='volume', name='laptop', value=90, boost=True))
            backend.control(dict(op='mute', name='laptop', muted=True))
            command.assert_called_with('set-sink-mute', 'laptop', '1')

    def test_default_connection_and_explicit_app_routing_are_separate(self):
        with patch.object(backend, 'load_config', return_value=(CONFIG, '')), patch.object(backend, 'read', side_effect=fake_read), \
                patch.object(backend, 'command') as command:
            backend.control(dict(op='output-default', name='laptop'))
            command.assert_called_once_with('set-default-sink', 'laptop')
            command.reset_mock()
            backend.control(dict(op='output-port', name='laptop', port='speaker'))
            self.assertEqual([c.args for c in command.call_args_list], [
                ('set-sink-port', 'laptop', 'speaker'), ('set-sink-mute', 'laptop', '0')])
            command.reset_mock()
            backend.control(dict(op='move', kind='stream', index=23, token='100', destination='laptop'))
            command.assert_called_once_with('move-sink-input', '23', 'laptop')

    def test_output_inventory_groups_shared_ports_and_independent_sinks(self):
        jack = dict(SINK['ports'][1], availability='available')
        first = dict(SINK, ports=[SINK['ports'][0], jack])
        second = dict(SINK, name='second', index=8)
        virtual = dict(SINK, name='virtual', index=10, properties={}, ports=[])
        config = dict(rules=CONFIG['rules'] + [dict(match={'device.name': 'card'}, label='Laptop audio', deviceLabel='Laptop audio device')])
        outputs, devices = backend.output_inventory([first, second, virtual], [CARD], config, 'second')
        self.assertEqual(len(outputs), 3)
        self.assertEqual(len(devices), 2)
        self.assertEqual({r['name'] for r in next(o for o in outputs if o['name']=='laptop')['routes']}, {'speaker', 'jack'})
        self.assertEqual(sum(o['selected'] for o in outputs), 1)
        self.assertTrue(next(o for o in outputs if o['name']=='second')['selected'])
        self.assertEqual(next(d for d in devices if d['key']=='card')['label'], 'Laptop audio device')
        self.assertEqual(next(d for d in devices if d['key']=='virtual')['profiles'], [])

    def test_disabling_boost_caps_only_that_device_and_its_streams_without_unmuting(self):
        boosted = dict(SINK, mute=True, volume={'left': {'value': 98304}, 'right': {'value': 49152}})
        other = dict(boosted, name='display', index=8, properties={'device.name': 'other'})
        owned_second = dict(boosted, name='second', index=11)
        app = dict(STREAM, volume={'left': {'value': 81920}, 'right': {'value': 40960}})
        other_app = dict(app, index=24, sink=8)
        second_app = dict(app, index=25, sink=11)
        data = {'cards': [CARD], 'sinks': [boosted, other, owned_second], 'sink-inputs': [app, other_app, second_app]}
        with patch.object(backend, 'load_config', return_value=(CONFIG, '')), \
                patch.object(backend, 'read', side_effect=lambda kind: data[kind]), patch.object(backend, 'command') as command:
            backend.control(dict(op='output-boost', device='card', enabled=False))
            self.assertEqual([c.args for c in command.call_args_list], [
                ('set-sink-volume', 'laptop', 65536, 32768), ('set-sink-volume', 'second', 65536, 32768),
                ('set-sink-input-volume', 23, 65536, 32768), ('set-sink-input-volume', 25, 65536, 32768)])
            command.reset_mock()
            backend.control(dict(op='output-boost', device='card', enabled=True))
            command.assert_not_called()
            for request in (dict(op='output-boost', device='gone', enabled=False), dict(op='output-boost', device='card', enabled='no')):
                with self.assertRaises(ValueError): backend.control(request)
            command.assert_not_called()

    def test_changing_connection_applies_route_cap_and_keeps_default_and_mute(self):
        sink = dict(SINK, mute=True, volume={'left': {'value': 65536}},
                    ports=[SINK['ports'][0], dict(SINK['ports'][1], availability='available')])
        def mutate(*args):
            if args[0] == 'set-sink-port':
                sink['active_port'] = args[2]
                sink['volume'] = {'left': {'value': 65536}}  # remembered route gain
                sink['mute'] = False  # remembered route mute
            elif args[0] == 'set-sink-volume':
                sink['volume'] = {'left': {'value': args[2]}}
            elif args[0] == 'set-sink-mute':
                sink['mute'] = args[2] == '1'
        with patch.object(backend, 'load_config', return_value=(CONFIG, '')), \
                patch.object(backend, 'read', return_value=[sink]), patch.object(backend, 'command', side_effect=mutate) as command:
            backend.control(dict(op='output-port', name='laptop', port='jack', boost=True))
            self.assertEqual([c.args for c in command.call_args_list], [
                ('set-sink-volume', 'laptop', int(85 * 65536 / 100)), ('set-sink-port', 'laptop', 'jack'),
                ('set-sink-volume', 'laptop', int(85 * 65536 / 100)), ('set-sink-mute', 'laptop', '1')])
            self.assertLessEqual(backend.gain(sink), 85)
            self.assertTrue(sink['mute'])

    def test_route_waits_for_delayed_policy_restoration(self):
        clock = [0.0]
        def read(kind):
            self.assertEqual(kind, 'sinks')
            restored = clock[0] >= 0.08
            return [dict(SINK, active_port='jack' if clock[0] >= 0.04 else 'speaker',
                         mute=not restored, volume={'left': {'value': 65536 if restored else 32768}})]
        with patch.object(backend, 'read', side_effect=read), patch.object(backend, 'command'), \
                patch.object(backend.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(backend.time, 'sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)):
            updated = backend.select_port('sink', SINK, 'jack')
        self.assertGreaterEqual(clock[0], 0.20)
        self.assertFalse(updated['mute'])
        self.assertEqual(backend.volume(updated), 100)

    def test_route_wait_reports_disconnect_and_timeout(self):
        with patch.object(backend, 'command'), patch.object(backend, 'read', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'disconnected'):
                backend.select_port('sink', SINK, 'jack')
        with patch.object(backend, 'command'), patch.object(backend, 'read', return_value=[SINK]), \
                patch.object(backend.time, 'monotonic', side_effect=[0, 3]):
            with self.assertRaisesRegex(ValueError, 'did not finish'):
                backend.select_port('sink', SINK, 'jack')

    def test_external_boosted_gain_can_be_lowered_without_allowing_further_increase(self):
        sink = dict(SINK, volume={'left': {'value': 81920}})
        with patch.object(backend, 'load_config', return_value=(CONFIG, '')), \
                patch.object(backend, 'read', return_value=[sink]), patch.object(backend, 'command') as command:
            backend.control(dict(op='volume', name='laptop', value=120, boost=False))
            command.assert_called_once_with('set-sink-volume', 'laptop', '120%')
            command.reset_mock()
            with self.assertRaises(ValueError): backend.control(dict(op='volume', name='laptop', value=126, boost=False))
            command.assert_not_called()

    def test_moving_boosted_app_to_normal_device_caps_only_the_moved_stream(self):
        app = dict(STREAM, volume={'left': {'value': 81920}})
        with patch.object(backend, 'load_config', return_value=(CONFIG, '')), \
                patch.object(backend, 'read', side_effect=lambda kind: [app] if kind=='sink-inputs' else [SINK]), patch.object(backend, 'command') as command:
            backend.control(dict(op='move', kind='stream', index=23, token='100', destination='laptop', boost=False))
            self.assertEqual([c.args for c in command.call_args_list], [
                ('set-sink-input-volume', 23, 65536), ('move-sink-input', '23', 'laptop')])
            command.reset_mock()
            backend.control(dict(op='move', kind='stream', index=23, token='100', destination='laptop', boost=True))
            command.assert_called_once_with('move-sink-input', '23', 'laptop')

    def test_profile_reduction_does_not_overlay_two_outputs_or_their_apps(self):
        card = dict(CARD, active_profile='pro-audio', profiles={
            'pro-audio': dict(sinks=2, sources=0), 'output:analog-stereo': dict(sinks=1, sources=0)})
        first = dict(SINK, name='old-first', properties={'device.name': 'card', 'alsa.device': '0'})
        second = dict(first, name='old-second', index=8, properties={'device.name': 'card', 'alsa.device': '1'}, volume={'left': {'value': 52428}})
        recreated = dict(first, name='new-first', index=17)
        apps = [STREAM, dict(STREAM, index=24, sink=8, properties={'object.serial': '101'})]
        changed = [False]
        mutations = []
        def read(kind):
            return {'sinks': [recreated] if changed[0] else [first, second], 'sources': [],
                    'sink-inputs': apps, 'source-outputs': []}[kind]
        def command(*args):
            if args == ('-f', 'json', 'info'): return json.dumps({'default_sink_name': 'old-first'})
            mutations.append(args)
            if args[0] == 'set-card-profile': changed[0] = True
            return ''
        with patch.object(backend, 'read', side_effect=read), patch.object(backend, 'command', side_effect=command):
            backend.change_profile(card, dict(name='output:analog-stereo', sinks=1, sources=0))
        self.assertEqual([c for c in mutations if c[0]=='set-sink-volume'], [('set-sink-volume', 'new-first', 32768, 32768)])
        self.assertEqual([c for c in mutations if c[0]=='move-sink-input'], [('move-sink-input', 23, 'new-first')])

    def test_profile_checks_current_card_and_profile(self):
        with patch.object(backend, 'load_config', return_value=(CONFIG, '')), patch.object(backend, 'read', side_effect=fake_read), \
                patch.object(backend, 'command') as command, patch.object(backend, 'change_profile') as change:
            for previous, profile in [('stale', 'surround'), ('duplex', 'off'), ('duplex', 'missing')]:
                with self.assertRaises(ValueError):
                    backend.control(dict(op='profile', name='laptop', card='card', previous=previous, profile=profile))
            command.assert_not_called()
            backend.control(dict(op='profile', name='laptop', card='card', previous='duplex', profile='surround'))
            change.assert_called_once_with(CARD, dict(CARD['profiles']['surround'], name='surround'))


class MicrophoneBackendTests(unittest.TestCase):
    def setUp(self):
        self.stereo = 'output:analog-stereo'
        self.surround = 'output:analog-surround-40'
        self.capture = 'input:analog-stereo'
        profiles = {
            self.stereo: dict(description='Analog Stereo Output', sinks=1, sources=0, priority=6500),
            self.stereo + '+' + self.capture: dict(description='Analog Stereo Duplex', sinks=1, sources=1, priority=6565),
            self.surround: dict(description='Analog Surround 4.0 Output', sinks=1, sources=0, priority=1200),
            self.surround + '+' + self.capture: dict(description='Analog Surround 4.0 Output + Analog Stereo Input', sinks=1, sources=1, priority=1265),
            self.capture: dict(description='Analog Stereo Input', sinks=0, sources=1, priority=65),
            'off': dict(sinks=0, sources=0),
            'pro-audio': dict(description='Pro Audio', sinks=1, sources=1),
        }
        self.card = dict(CARD, active_profile=self.stereo, profiles=profiles, ports={
            'speaker': dict(type='Speaker', profiles=[self.stereo, self.stereo+'+'+self.capture, self.surround, self.surround+'+'+self.capture]),
            'jack': dict(type='Headphones', profiles=[self.stereo, self.stereo+'+'+self.capture]),
            'mic': dict(type='Mic', availability='available', profiles=[self.capture, self.stereo+'+'+self.capture, self.surround+'+'+self.capture]),
            'headset-mic': dict(type='Mic', availability='not available', profiles=[self.capture, self.stereo+'+'+self.capture]),
        })
        self.source = dict(name='microphone', index=9, description='Built-in microphone', mute=True,
                           properties={'device.name': 'card', 'media.class': 'Audio/Source', 'alsa.device': '0'},
                           volume={'left': {'value': 24576}}, active_port='mic',
                           ports=[dict(name='mic', type='Mic', availability='available')])

    def test_layout_choices_group_capture_variants_and_preserve_capabilities(self):
        config = {'profiles': {self.stereo: 'Stereo playback', self.surround: 'Four-channel playback'}}
        modes = backend.playback_profiles(self.card, config, 'speaker')
        self.assertEqual([p['name'] for p in modes], [self.stereo, self.surround, 'pro-audio'])
        self.assertTrue(modes[0]['selected'])
        self.assertTrue(modes[1]['enabled'])
        self.assertFalse(modes[2]['enabled'])
        self.assertEqual(backend.resolve_profile(self.card, (self.surround,))['name'], self.surround)
        self.card['active_profile'] = self.stereo + '+' + self.capture
        self.assertEqual(backend.resolve_profile(self.card, (self.surround,))['name'], self.surround+'+'+self.capture)
        self.assertIsNone(backend.resolve_profile(self.card, (self.surround,), port='jack'))
        self.card['profiles'][self.surround+'+'+self.capture]['available'] = False
        self.assertIsNone(backend.resolve_profile(self.card, (self.surround,)))
        self.card['active_profile'] = 'pro-audio'
        self.assertIsNone(backend.resolve_profile(self.card, capture=False))
        self.assertEqual(backend.resolve_profile(self.card, (self.stereo,))['name'], self.stereo+'+'+self.capture)

    def test_disabled_devices_have_no_fake_sources_and_monitors_are_excluded(self):
        monitor = dict(self.source, name='laptop.monitor', properties={'device.class': 'monitor'})
        data = {'cards': [self.card], 'sinks': [SINK], 'sources': [monitor], 'sink-inputs': [], 'source-outputs': []}
        with patch.object(backend, 'load_config', return_value=(CONFIG, '')), \
                patch.object(backend, 'read', side_effect=lambda kind: data[kind]), \
                patch.object(backend, 'command', return_value='{}'):
            state = backend.snapshot()
            self.assertEqual(state['inputs'], [])
            device = state['inputDevices'][0]
            self.assertTrue(device['available'] and device['canToggle'])
            self.assertFalse(device['enabled'])
            self.assertEqual(device['port'], 'mic')
            self.assertEqual(len(device['inputSlots']), 1)
            self.assertNotIn('name', device['inputSlots'][0])
            data['sources'].append(self.source)
            state = backend.snapshot()
            self.assertEqual(len(state['inputs']), 1)
            self.assertEqual(state['inputs'][0]['icon'], 'mic')
            self.assertTrue(state['inputs'][0]['muted'])
            self.assertTrue(state['inputDevices'][0]['canToggle'])
            self.card['active_profile'] = 'pro-audio'
            state = backend.snapshot()
            self.assertFalse(state['inputDevices'][0]['canToggle'])
            self.assertIn('playback mode', state['inputDevices'][0]['toggleReason'])
            data['cards'] = []
            self.assertFalse(backend.snapshot()['inputDevices'][0]['canToggle'])

    def test_independent_sources_and_shared_routes_are_distinct(self):
        headset = dict(name='headset-mic', type='Mic', description='Headset microphone', availability='available')
        disconnected = dict(headset, name='missing', availability='not available')
        source = dict(self.source, ports=self.source['ports'] + [headset, disconnected])
        usb = dict(self.source, name='usb', index=10, properties={'media.class': 'Audio/Source'}, description='USB microphone', ports=[])
        inputs, devices = backend.input_inventory([source, usb], [self.card], CONFIG, 'usb')
        self.assertEqual(len(inputs), 2)
        shared = next(n for n in inputs if n['name'] == 'microphone')
        self.assertEqual({r['name'] for r in shared['routes']}, {'mic', 'headset-mic'})
        self.assertEqual(sum(n['selected'] for n in inputs), 1)
        self.assertTrue(next(n for n in inputs if n['name'] == 'usb')['selected'])
        self.assertEqual(len(devices), 2)
        second = dict(source, name='second-channel', index=11)
        inputs, devices = backend.input_inventory([source, second], [self.card], CONFIG, 'microphone')
        self.assertEqual(len(inputs), 2)
        self.assertEqual(len(devices), 1)
        self.assertEqual({n['deviceKey'] for n in inputs}, {'card'})

    def test_bluetooth_mode_changes_are_visible_but_not_silently_applied(self):
        card = dict(index=5, name='bluetooth', active_profile='a2dp-sink', profiles={
            'a2dp-sink': dict(sinks=1, sources=0),
            'headset-head-unit': dict(sinks=1, sources=1),
            'off': dict(sinks=0, sources=0)})
        inputs, devices = backend.input_inventory([], [card], CONFIG, '')
        self.assertEqual(inputs, [])
        self.assertTrue(devices[0]['available'])
        self.assertFalse(devices[0]['enabled'] or devices[0]['canToggle'])
        self.assertIn('playback mode', devices[0]['toggleReason'])
        card['active_profile'] = 'headset-head-unit'
        source = dict(self.source, name='bluetooth-input', properties={'device.name': 'bluetooth'}, ports=[])
        inputs, devices = backend.input_inventory([source], [card], CONFIG, 'bluetooth-input')
        self.assertTrue(devices[0]['enabled'])
        self.assertFalse(devices[0]['canToggle'])
        self.assertTrue(inputs[0]['selected'])

    def test_default_and_connection_actions_do_not_reroute_other_recordings(self):
        port = dict(name='headset-mic', availability='available')
        source = dict(self.source, ports=self.source['ports'] + [port])
        def mutate(*args):
            if args[0] == 'set-source-port':
                source.update(active_port=args[2], mute=False)
            elif args[0] == 'set-source-mute':
                source['mute'] = args[2] == '1'
        with patch.object(backend, 'load_config', return_value=(CONFIG, '')), \
                patch.object(backend, 'read', return_value=[source]), patch.object(backend, 'command', side_effect=mutate) as command:
            backend.control(dict(op='input-default', name='microphone'))
            command.assert_called_once_with('set-default-source', 'microphone')
            command.reset_mock()
            backend.control(dict(op='input-port', name='microphone', port='headset-mic'))
            self.assertEqual([c.args for c in command.call_args_list], [
                ('set-source-port', 'microphone', 'headset-mic'), ('set-source-mute', 'microphone', '1')])
            self.assertTrue(source['mute'])
            command.reset_mock()
            for request in (dict(op='input-default', name='gone'), dict(op='input-port', name='microphone', port='missing')):
                with self.assertRaises(ValueError): backend.control(request)
            command.assert_not_called()

    def test_app_recording_route_validates_serial_and_moves_only_that_stream(self):
        recording = dict(STREAM, source=9)
        second = dict(recording, index=24, properties={'object.serial': '101'})
        usb = dict(self.source, name='usb', index=10)
        monitor = dict(usb, name='display.monitor')
        data = {'source-outputs': [recording, second], 'sources': [self.source, usb, monitor]}
        with patch.object(backend, 'load_config', return_value=(CONFIG, '')), \
                patch.object(backend, 'read', side_effect=lambda kind: data[kind]), patch.object(backend, 'command') as command:
            backend.control(dict(op='move', kind='recording', index=23, token='100', destination='usb'))
            command.assert_called_once_with('move-source-output', '23', 'usb')
            command.reset_mock()
            for token, destination in [('99', 'usb'), ('100', 'gone'), ('100', 'display.monitor')]:
                with self.assertRaises(ValueError):
                    backend.control(dict(op='move', kind='recording', index=23, token=token, destination=destination))
            command.assert_not_called()

    def test_microphone_power_is_only_mute_and_gain_never_unmutes(self):
        with patch.object(backend, 'load_config', return_value=(CONFIG, '')), \
                patch.object(backend, 'read', return_value=[self.source]), patch.object(backend, 'command') as command:
            backend.control(dict(op='mute', kind='source', name='microphone', muted=False))
            command.assert_called_once_with('set-source-mute', 'microphone', '0')
            command.reset_mock()
            backend.control(dict(op='mute', kind='source', name='microphone', muted=True))
            command.assert_called_once_with('set-source-mute', 'microphone', '1')
            command.reset_mock()
            backend.control(dict(op='volume', kind='source', name='microphone', value=65))
            command.assert_called_once_with('set-source-volume', 'microphone', '65%')
            for value in (101, -1, True):
                with self.assertRaises(ValueError):
                    backend.control(dict(op='volume', kind='source', name='microphone', value=value, boost=True))

    def test_enabling_input_selects_matching_profile_without_silently_changing_layout(self):
        reads = {'cards': [self.card], 'source-outputs': []}
        sources = []
        def change(card, target):
            self.assertEqual(target['name'], self.stereo+'+'+self.capture)
            sources.append(self.source)
        def mutate(*args):
            if args[0] == 'set-source-port':
                self.source['mute'] = False
            elif args[0] == 'set-source-mute':
                self.source['mute'] = args[2] == '1'
        with patch.object(backend, 'load_config', return_value=(CONFIG, '')), \
                patch.object(backend, 'read', side_effect=lambda kind: sources if kind=='sources' else reads[kind]), \
                patch.object(backend, 'change_profile', side_effect=change) as transition, patch.object(backend, 'command', side_effect=mutate) as command:
            backend.control(dict(op='input-enabled', card='card', previous=self.stereo, port='mic', enabled=True))
            transition.assert_called_once()
            self.assertEqual([c.args for c in command.call_args_list], [
                ('set-source-port', 'microphone', 'mic'), ('set-source-mute', 'microphone', '1')])
            self.assertTrue(self.source['mute'])
            sources.clear()
            command.reset_mock()
            for request in (
                dict(op='input-enabled', card='card', previous='stale', port='mic', enabled=True),
                dict(op='input-enabled', card='card', previous=self.stereo, port='headset-mic', enabled=True),
                dict(op='input-enabled', card='card', previous=self.stereo, enabled='invalid'),
            ):
                with self.assertRaises(ValueError): backend.control(request)
            command.assert_not_called()
            self.card['profiles'][self.stereo+'+'+self.capture]['available'] = False
            with self.assertRaisesRegex(ValueError, 'keeping its playback mode'):
                backend.control(dict(op='input-enabled', card='card', previous=self.stereo, port='mic', enabled=True))

    def test_profile_mutes_unmatched_inputs_and_preserves_matched_mute(self):
        self.card['active_profile'] = self.stereo + '+' + self.capture
        for muted in (False, True):
            with self.subTest(muted=muted):
                old = dict(self.source, mute=muted)
                recreated = dict(old, name='recreated', index=90, ports=[])
                extra = dict(recreated, name='extra', index=91, mute=False,
                             properties={'device.name': 'card', 'alsa.device': '1'}, ports=self.source['ports'])
                changed = [False]
                def read(kind):
                    return ([recreated, extra] if changed[0] else [old]) if kind == 'sources' else {'sinks': [SINK], 'sink-inputs': [], 'source-outputs': []}[kind]
                def mutate(*args):
                    if args == ('-f', 'json', 'info'):
                        return '{}'
                    if args[0] == 'set-card-profile':
                        changed[0] = True
                    elif args[0] == 'set-source-port':
                        extra['mute'] = False
                    elif args[0] == 'set-source-mute':
                        next(n for n in (recreated, extra) if n['name'] == args[1])['mute'] = args[2] == '1'
                    return ''
                with patch.object(backend, 'read', side_effect=read), patch.object(backend, 'command', side_effect=mutate):
                    backend.change_profile(self.card, dict(name='pro-audio', sinks=1, sources=2))
                self.assertEqual(recreated['mute'], muted)
                self.assertTrue(extra['mute'])

    def test_hardware_disable_removes_capture_and_preserves_each_playback_layout(self):
        for mode in (self.stereo, self.surround):
            self.card['active_profile'] = mode + '+' + self.capture
            capture_enabled = [True]
            mutations = []
            display = dict(SINK, name='display', index=8, properties={'device.name': 'other-card'})
            def read(kind):
                return {'cards': [self.card], 'sinks': [SINK, display],
                        'sources': [self.source] if capture_enabled[0] else [],
                        'sink-inputs': [], 'source-outputs': []}[kind]
            def command(*args):
                if args == ('-f', 'json', 'info'):
                    return json.dumps({'default_sink_name': 'display', 'default_source_name': 'microphone'})
                mutations.append(args)
                if args[0] == 'set-card-profile': capture_enabled[0] = False
                return ''
            with patch.object(backend, 'load_config', return_value=(CONFIG, '')), \
                    patch.object(backend, 'read', side_effect=read), patch.object(backend, 'command', side_effect=command):
                backend.control(dict(op='input-enabled', card='card', previous=self.card['active_profile'], enabled=False))
            self.assertFalse(capture_enabled[0])
            self.assertEqual(mutations[0], ('set-card-profile', 'card', mode))
            self.assertIn(('set-default-sink', 'display'), mutations)
            self.assertIn(('set-sink-volume', 'laptop', 32768, 32768), mutations)
            self.assertFalse(any(c[0] == 'set-source-mute' for c in mutations))

        self.card['active_profile'] = 'pro-audio'
        with patch.object(backend, 'load_config', return_value=(CONFIG, '')), \
                patch.object(backend, 'read', return_value=[self.card]), patch.object(backend, 'command') as command:
            with self.assertRaisesRegex(ValueError, 'Use mute'):
                backend.control(dict(op='input-enabled', card='card', previous='pro-audio', enabled=False))
            with self.assertRaisesRegex(ValueError, 'changed'):
                backend.control(dict(op='input-enabled', card='card', previous='stale', enabled=False))
            command.assert_not_called()

    def test_first_activation_restores_playback_and_stays_muted_without_selecting(self):
        activated = [False]
        mutations = []
        sink = dict(SINK, mute=True)
        display = dict(SINK, name='display', index=8, properties={'device.name': 'other-card'})
        data = {'cards': [self.card], 'sinks': [sink, display], 'sink-inputs': [], 'source-outputs': []}
        def read(kind):
            return ([self.source] if activated[0] else []) if kind=='sources' else data[kind]
        def command(*args):
            if args == ('-f', 'json', 'info'):
                return json.dumps({'default_sink_name': 'display'})
            mutations.append(args)
            if args[0]=='set-card-profile': activated[0] = True
            return ''
        with patch.object(backend, 'load_config', return_value=(CONFIG, '')), \
                patch.object(backend, 'read', side_effect=read), patch.object(backend, 'command', side_effect=command):
            backend.control(dict(op='input-enabled', card='card', previous=self.stereo, port='mic', enabled=True))
        self.assertEqual(mutations[0], ('set-card-profile', 'card', self.stereo+'+'+self.capture))
        self.assertIn(('set-default-sink', 'display'), mutations)
        self.assertIn(('set-sink-mute', 'laptop', '1'), mutations)
        self.assertIn(('set-source-mute', 'microphone', '1'), mutations)
        self.assertNotIn(('set-source-mute', 'microphone', '0'), mutations)
        self.assertNotIn(('set-default-source', 'microphone'), mutations)

    def test_profile_transition_preserves_endpoint_state_routes_and_other_default(self):
        import copy
        card = copy.deepcopy(self.card)
        card['active_profile'] = self.stereo+'+'+self.capture
        old_sink = copy.deepcopy(SINK)
        old_sink.update(mute=True, properties={'device.name': 'card', 'alsa.device': '0'})
        display = dict(SINK, name='display', index=8, properties={'device.name': 'display-card'})
        old_source = copy.deepcopy(self.source)
        state = {'sinks': [old_sink, display], 'sources': [old_source],
                 'sink-inputs': [dict(STREAM)],
                 'source-outputs': [dict(STREAM, index=24, source=9)]}
        info = {'default_sink_name': 'display', 'default_source_name': 'microphone'}
        mutations = []
        fail_once = [False]
        def command(*args):
            if args == ('-f', 'json', 'info'): return json.dumps(info)
            mutations.append(args)
            op, *values = args
            if op=='set-card-profile':
                card['active_profile'] = values[1]
                state['sinks'][0] = dict(old_sink, name='recreated-output', index=70, mute=False, volume={'left': {'value': 65536}, 'right': {'value': 65536}})
                state['sources'][0] = dict(old_source, name='recreated-input', index=90, mute=False, volume={'left': {'value': 65536}})
                info['default_sink_name'] = 'recreated-output'
            if op=='set-sink-volume' and fail_once[0]:
                fail_once[0] = False
                raise ValueError('simulated restoration failure')
            return ''
        with patch.object(backend, 'read', side_effect=lambda kind: state[kind]), patch.object(backend, 'command', side_effect=command):
            backend.change_profile(card, dict(card['profiles'][self.surround+'+'+self.capture], name=self.surround+'+'+self.capture))
            for expected in (
                ('set-sink-volume', 'recreated-output', 32768, 32768),
                ('set-sink-mute', 'recreated-output', '1'),
                ('set-source-volume', 'recreated-input', 24576),
                ('set-source-mute', 'recreated-input', '1'),
                ('set-default-sink', 'display'),
                ('set-default-source', 'recreated-input'),
                ('move-sink-input', 23, 'recreated-output'),
                ('move-source-output', 24, 'recreated-input'),
            ): self.assertIn(expected, mutations)
            # A failed restoration rolls the profile back, rather than claiming success.
            previous = card['active_profile']
            fail_once[0] = True
            with self.assertRaisesRegex(ValueError, 'previous mode was restored'):
                backend.change_profile(copy.deepcopy(card), dict(card['profiles'][self.stereo+'+'+self.capture], name=self.stereo+'+'+self.capture))
            self.assertEqual(card['active_profile'], previous)


class AudioConfigurationTests(unittest.TestCase):
    def test_modules_publish_dropins_and_remain_host_specific(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / 'repo'
            repo.mkdir()
            original = Path(__file__).resolve().parents[1]
            for name in ('scripts', 'modules'):
                shutil.copytree(original / name, repo / name)
            shutil.copy(original / 'generate-config.py', repo)

            def generate(host, answers=''):
                result = subprocess.run(['python3', str(repo / 'generate-config.py'), host],
                                        input=answers, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads((repo / 'user-configuration.json').read_text())

            def stage(config, host):
                directory = root / host / '.config/devices/audio'
                directory.mkdir(parents=True)
                for entry in config['extra']['symlinks']:
                    if entry['target'].startswith('home/.config/devices/audio/'):
                        (directory / Path(entry['target']).name).symlink_to(repo / entry['source'])
                return directory

            config = generate('zephyrus')
            self.assertNotIn('audio', config['extra'].get('quickshell', {}))
            directory = stage(config, 'zephyrus')
            self.assertEqual({p.name for p in directory.iterdir()}, {'profiles.json', 'zephyrus.json', 'dell-s2722dc.json'})
            self.assertTrue(all(p.is_symlink() for p in directory.iterdir()))
            audio, warning = backend.load_config(directory)
            self.assertEqual(warning, '')
            self.assertEqual(len(audio['rules']), 9)
            self.assertIn('pro-audio', audio['profiles'])
            self.assertFalse(any(e['target'] == 'home/.config/quickshell/desktop/audio.json'
                                 for kind in ('files', 'symlinks') for e in config['extra'][kind]))
            command = next(c for c in config['custom_commands'] if '--run modules/desktop/quickshell ' in c)
            self.assertNotIn('audio.json', command)

            # Exercise real merged aliases against profile-dependent node names.
            laptop = {'properties': {'device.name': 'alsa_card.pci-0000_07_00.6'}}
            for profile in ('analog-stereo', 'analog-surround-40'):
                sink = dict(laptop, name='alsa_output.pci-0000_07_00.6.' + profile)
                self.assertEqual(backend.describe(sink, {'name': 'analog-output-speaker'}, audio)['label'], 'Laptop speakers')
                self.assertEqual(backend.describe(sink, {'name': 'analog-output-headphones'}, audio)['maxVolume'], 100)
            sink = dict(laptop, name='alsa_output.pci-0000_07_00.6.pro-output-0')
            self.assertEqual(backend.describe(sink, {}, audio)['label'], 'Laptop audio (all channels)')
            display = dict(name='alsa_output.pci-0000_07_00.1.hdmi-stereo', description='Radeon [DELL S2722DC]',
                           properties={'device.name': 'alsa_card.pci-0000_07_00.1'})
            port = {'name': 'hdmi-output-0', 'description': 'HDMI / DisplayPort'}
            self.assertEqual(backend.describe(display, port, audio)['label'], 'Dell S2722DC speakers')
            display['description'] = 'Another monitor'
            self.assertEqual(backend.describe(display, port, audio)['label'],
                             'Display audio (integrated graphics) · Display connection 1')

            # Actual profiles keep native identifiers for dispatch and hover details.
            card = dict(CARD, active_profile='output:analog-stereo+input:analog-stereo', profiles={
                'output:analog-stereo+input:analog-stereo': dict(description='Analog Stereo Duplex', sinks=1, sources=1),
                'pro-audio': dict(description='Pro Audio', sinks=1),
                'future-profile': dict(description='Future driver mode', sinks=1)})
            with patch.object(backend, 'load_config', return_value=(audio, '')), \
                    patch.object(backend, 'read', side_effect=lambda kind: {'sinks': [SINK], 'cards': [card], 'sink-inputs': [], 'sources': [], 'source-outputs': []}[kind]), \
                    patch.object(backend, 'command', return_value='{}'):
                profiles = backend.snapshot()['outputDevices'][0]['profiles']
            self.assertEqual(profiles[0]['name'], 'output:analog-stereo')
            self.assertEqual(profiles[0]['label'], 'Stereo playback')
            self.assertEqual(profiles[0]['description'], 'Analog Stereo Duplex')
            self.assertEqual(profiles[1]['label'], 'Manual channel routing (advanced)')
            self.assertEqual(profiles[2]['label'], 'Future driver mode')

            vm_config = generate('vm', '\n64\n')
            vm_directory = stage(vm_config, 'vm')
            self.assertEqual({p.name for p in vm_directory.iterdir()}, {'profiles.json', 'dell-s2722dc.json'})
            vm_audio, warning = backend.load_config(vm_directory)
            self.assertEqual(warning, '')
            self.assertEqual(len(vm_audio['rules']), 1)
            self.assertEqual(vm_audio['rules'][0]['label'], 'Dell S2722DC speakers')
            self.assertEqual(vm_audio['profiles'], audio['profiles'])

    def test_invalid_profile_labels_and_rule_priorities_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'audio.json'
            for profiles in ([], {'pro-audio': ''}, {'pro-audio': 42}):
                path.write_text(json.dumps({'profiles': profiles, 'rules': []}))
                self.assertIn('profile names', backend.load_config(path.parent)[1])
            for device_label in ('', 42, False, []):
                path.write_text(json.dumps({'rules': [dict(CONFIG['rules'][0], deviceLabel=device_label)]}))
                self.assertIn('deviceLabel', backend.load_config(path.parent)[1])
            for priority in (True, 'first', float('inf')):
                path.write_text(json.dumps({'rules': [dict(CONFIG['rules'][0], priority=priority)]}))
                self.assertIn('priority', backend.load_config(path.parent)[1])

    def test_directory_changes_and_bad_files_do_not_discard_valid_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = {'rules': [], 'profiles': {}}
            self.assertEqual(backend.load_config(root / 'missing'), (empty, ''))
            first = root / '10-first.json'
            first.write_text(json.dumps({'rules': CONFIG['rules'], 'profiles': {'pro-audio': 'Manual routing'}}))
            (root / '20-broken.json').write_text('{')
            (root / 'ignored.txt').write_text('{')
            conflicting = root / '30-conflict.json'
            conflicting.write_text(json.dumps({'rules': [dict(CONFIG['rules'][0], label='Conflicting rule')],
                                                'profiles': {'pro-audio': 'Different label'}}))
            config, warning = backend.load_config(root)
            self.assertEqual(config['rules'], CONFIG['rules'])
            self.assertEqual(config['profiles']['pro-audio'], 'Manual routing')
            self.assertIn('20-broken.json', warning)
            self.assertIn('30-conflict.json', warning)
            self.assertNotIn('ignored.txt', warning)
            first.write_text(json.dumps({'rules': [dict(CONFIG['rules'][0], label='Updated name')]}))
            config, warning = backend.load_config(root)
            self.assertEqual(config['rules'][0]['label'], 'Updated name')
            self.assertEqual(len(config['rules']), 2)
            self.assertNotIn('30-conflict.json', warning)
            first.unlink()
            conflicting.unlink()
            config, warning = backend.load_config(root)
            self.assertEqual(config, empty)
            self.assertIn('20-broken.json', warning)


@unittest.skipUnless(QS, 'Quickshell is required')
class AudioDrawerTests(unittest.TestCase):
    def run_qml(self, qml, setup=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('ui', 'icons', 'drawers', 'bar'):
                shutil.copytree(DESKTOP / name, root / name)
            (root / 'shell.qml').write_text(qml)
            config = root / 'config/quickshell/desktop'
            config.mkdir(parents=True)
            (config / 'theme-mode').write_text('dark\n')
            runtime = root / 'runtime'
            runtime.mkdir(mode=0o700)
            if setup:
                setup(root)
            platform = os.environ.get('AUDIO_PREVIEW_PLATFORM', 'offscreen')
            env = {**os.environ, 'QT_QPA_PLATFORM': platform, 'XDG_CONFIG_HOME': str(root / 'config'),
                   'XDG_RUNTIME_DIR': str(runtime) if platform == 'offscreen' else os.environ['XDG_RUNTIME_DIR']}
            for key in (('WAYLAND_DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE') if platform == 'offscreen' else ('HYPRLAND_INSTANCE_SIGNATURE',)):
                env.pop(key, None)
            result = subprocess.run([QS, '--no-color', '-p', str(root / 'shell.qml')], env=env, text=True, capture_output=True, timeout=20)
        log = result.stdout + result.stderr
        if os.environ.get('AUDIO_PREVIEW_PLATFORM'):
            print(log)
        self.assertEqual(result.returncode, 0, log)
        self.assertIn('AUDIO_PASS', log)
        for error in ('AUDIO_FAIL', 'TypeError', 'ReferenceError', 'Binding loop', 'Unable to assign', 'polish() loop', 'Polish loop', 'Failed to load'):
            self.assertNotIn(error, log)

    def test_service_serializes_slider_changes_and_finishes_after_dismissal(self):
        def setup(root):
            service = root / 'drawers/audio/AudioService.qml'
            source = service.read_text().replace('Qt.resolvedUrl("backend.py")', 'Qt.resolvedUrl("fake.py")')
            source = source.replace('command: ["pactl", "subscribe"]', 'command: ["python3", "-c", "import time; time.sleep(10)"]')
            service.write_text(source)
            (root / 'drawers/audio/fake.py').write_text('''import json,sys,time
from pathlib import Path
request=json.loads(sys.stdin.readline())
with (Path(__file__).parent / 'requests.jsonl').open('a') as log:
 log.write(json.dumps(request)+'\\n')
time.sleep(0.15)
if request['op'] == 'fail' or (request['op'] == 'output-boost' and not request['enabled']): print(json.dumps({'ok': False, 'error': 'Device disconnected'}))
else: print(json.dumps({'ok': True, 'data': {'available': True, 'outputs': [], 'streams': [], 'warning': '', 'last': request}}))
''')

        self.run_qml(r'''import QtQuick
import Quickshell
import "drawers/audio"
ShellRoot {
 property int stage: 0
 function check(value, message) { if (!value) throw new Error(message); }
 Timer { interval: 60; repeat: true; running: true; onTriggered: {
  try {
   if (stage === 0) {
    check(!AudioService.loaded && !AudioService.request, "audio started before observation");
    const first = {}, second = {};
    AudioService.observe(first, true); AudioService.observe(second, true);
    AudioService.observe(first, false);
    check(AudioService.observing, "closing old drawer stopped the new drawer observer");
    AudioService.observe(second, false);
    check(!AudioService.observing, "last observer did not stop observation");
    AudioService.observing = true;
    AudioService.run("volume", {name: "laptop", value: 10});
    AudioService.run("volume", {name: "laptop", value: 20});
    AudioService.run("volume", {name: "laptop", value: 30});
    check(AudioService.queue.length === 1 && AudioService.queue[0].value === 30, "slider queue not coalesced");
    AudioService.run("mute", {name: "laptop", muted: true});
    check(AudioService.queue.length === 2, "mute ordering lost");
    AudioService.subscription.running = false;
    AudioService.recovery.triggered();
    check(AudioService.subscription.running, "subscription did not recover");
    AudioService.observing = false;
    stage++;
   } else if (stage === 1 && !AudioService.request && !AudioService.queue.length) {
    check(AudioService.state.last.op === "mute", "dismissal cancelled accepted action");
    check(!AudioService.observing, "observation restarted");
    check(!AudioService.subscription.running, "recovered subscription survived dismissal");
    AudioService.setBoost("card", true);
    check(!AudioService.boostFor("card") && AudioService.boostPending("card") && !AudioService.boostPending("other"), "boost changed before backend confirmation or pending scope lost");
    stage++;
   } else if (stage === 2 && !AudioService.request && !AudioService.queue.length) {
    check(AudioService.boostFor("card") && !AudioService.boostFor("other") && !AudioService.boostPending("card"), "boost preference scope/pending state lost");
    check(JSON.parse(AudioService.preferences.value("boostDevices", "{}")).card, "boost preference not persisted");
    AudioService.observing = true;
    AudioService.setBoost("card", false); stage++;
   } else if (stage === 3 && AudioService.error && !AudioService.request && !AudioService.queue.length) {
    check(AudioService.boostFor("card"), "failed boost disable changed confirmed preference");
    check(AudioService.error === "Device disconnected", "refresh erased action error");
    check(AudioService.state.last.op === "status", "failed action did not refresh inventory");
    console.log("AUDIO_PASS"); Qt.quit();
   }
  } catch (error) { console.error("AUDIO_FAIL", error.message); Qt.quit(); }
 } }
}
''', setup)

    def test_boost_preferences_migrate_to_device_overrides(self):
        for legacy in ('true', 'false'):
            def setup(root):
                (root / 'config/quickshell/desktop/audio.ini').write_text('[Playback]\nboost=' + legacy + '\n')
            self.run_qml(r'''import QtQuick
import Quickshell
import "drawers/audio"
ShellRoot {
 Timer { interval: 100; running: true; onTriggered: {
  try {
   const inherited = LEGACY;
   if (AudioService.boostFor("card") !== inherited || AudioService.boostFor("other") !== inherited) throw new Error("legacy boost preference not inherited");
   AudioService.rememberBoost("card", !inherited);
   const saved = JSON.parse(AudioService.preferences.value("boostDevices", "{}"));
   if (AudioService.boostFor("card") !== !inherited || AudioService.boostFor("other") !== inherited || saved.card !== !inherited || saved["*"] !== inherited) throw new Error("device override discarded legacy defaults");
   console.log("AUDIO_PASS"); Qt.quit();
  } catch (error) { console.error("AUDIO_FAIL", error.message); Qt.quit(); }
 } }
}
'''.replace('LEGACY', legacy), setup)

    def test_microphone_independent_controls_routes_default_and_lifetime(self):
        device = dict(key='card', card='card', profile='output:analog-stereo', label='Laptop microphones', port='mic',
                      enabled=False, available=True, canToggle=True, toggleReason='')
        usb_device = dict(device, key='usb-card', card='usb-card', label='USB audio', enabled=True, port='')
        usb = dict(key='usb', name='usb', index=10, deviceKey='usb-card', port='', portLabel='',
                   available=True, selected=True, volume=70, muted=False, label='USB microphone', icon='mic', routes=[])
        builtin = dict(usb, key='microphone', name='microphone', index=9, deviceKey='card', port='mic',
                       selected=False, volume=55, muted=True, label='Built-in microphone',
                       routes=[dict(name='mic', label='Built-in microphone', selected=True),
                               dict(name='headset', label='Headset microphone', selected=False)])
        device['inputSlots'] = [dict(key='card/input/0', label=builtin['label'], routes=builtin['routes'])]
        state = dict(available=True, inputDevices=[device, usb_device], inputs=[usb], outputs=[], streams=[], recordings=[], warning='')
        self.run_qml(r'''import QtQuick
import QtTest
import Quickshell
import "drawers"
import "ui" as UI
FloatingWindow {
 id: window
 implicitWidth: 480; implicitHeight: 720; color: UI.Theme.background
 QtObject {
  id: fake
  property bool observing: false
  property bool loaded: true
  property bool busy: false
  property string error: ""
  property var state: STATE
  property var calls: []
  function observe(owner, active) { observing = active; }
  function run(op, values) { calls = calls.concat([{op, values}]); }
  function refresh() {}
 }
 MicrophoneDrawer { id: drawer; width: 448; height: 688; x: 16; y: 16; service: fake; active: true
  Rectangle { anchors.fill: parent; color: UI.Theme.background; z: -1 }
 }
 TestCase { id: input; when: false; parent: window.contentItem }
 function find(item, name) {
  if (item.objectName === name) return item;
  for (const child of item.children || []) { const result = find(child, name); if (result) return result; }
  return null;
 }
 function check(value, message) { if (!value) throw new Error(message); }
 function click(item) { input.mouseClick(item, item.width/2, item.height/2); }
 function last() { return fake.calls[fake.calls.length-1]; }
 function capture(name) { drawer.grabToImage(result => result.saveToFile((Quickshell.env("AUDIO_PREVIEW_DIR") || "/tmp") + "/" + name)); }
 property int stage: 0
 property var savedInput: null
 property var savedSlider: null
 property real singleHeight: 0
 property real multiHeight: 0
 Timer { interval: 180; running: true; repeat: true; onTriggered: {
  try {
   const enabled = find(drawer, "inputEnabled:card");
   const slider = find(drawer, "inputVolume:microphone:slider");
   const mute = find(drawer, "inputVolume:microphone:mute");
   const usbSlider = find(drawer, "inputVolume:usb:slider");
   if (stage === 0) {
    check(fake.observing && enabled.enabled && !enabled.checked && usbSlider.enabled, "disabled card blocked an independent microphone");
    check(!find(drawer, "inputVolume:microphone"), "disabled card has a fake independent source");
    const disabledSlider = find(drawer, "inputVolume:card/input/0:slider");
    check(!find(drawer, "inputDefault:card/input/0").enabled, "disabled presentation slot offers a default action");
    singleHeight = find(drawer, "inputDevice:card").height;
    check(disabledSlider && disabledSlider.visible && !disabledSlider.enabled, "disabled hardware lost its visible inactive slider");
    click(enabled);
    check(last().op === "input-enabled" && last().values.enabled && last().values.previous === "output:analog-stereo", "input activation dispatch/guard");
    check(!enabled.checked, "hardware enabled before confirmation");
    capture("microphone-off.png");
    fake.state = Object.assign({}, fake.state, {inputDevices: fake.state.inputDevices.map(n => n.key === "card" ? Object.assign({}, n, {enabled: true, profile: "output:analog-stereo+input:analog-stereo"}) : n),
      inputs: fake.state.inputs.concat([BUILTIN]),
      recordings: [{key: "24:101", index: 24, token: "101", label: "Voice call", icon: "", source: 9, muted: false, recording: true}]});
   } else if (stage === 1) {
    check(Math.abs(find(drawer, "inputDevice:card").height - singleHeight) < 1, "single-input card jumped when enabled");
    check(enabled.mapToItem(drawer, 0, 0).y < slider.mapToItem(drawer, 0, 0).y, "single-input switch is not in device header");
    check(enabled.checked && !slider.enabled && slider.visible && mute.enabled && usbSlider.enabled && mute.iconName === "mic-off", "independent microphone controls missing");
    check(find(drawer, "inputDefault:usb").checked && !find(drawer, "inputDefault:microphone").checked, "enabling stole default");
    click(mute);
    check(last().op === "mute" && last().values.kind === "source" && last().values.name === "microphone" && !last().values.muted, "unmute changed default or targeted wrong microphone");
    fake.state = Object.assign({}, fake.state, {inputs: fake.state.inputs.map(n => n.name === "microphone" ? Object.assign({}, n, {muted: false}) : n)});
    check(slider.enabled, "unmuting did not enable gain");
    slider.forceActiveFocus(); input.keyClick(Qt.Key_Right);
    check(last().op === "volume" && last().values.name === "microphone", "nondefault source gain dispatch");
    savedInput = find(drawer, "audioInput:microphone"); savedSlider = slider;
    fake.state = Object.assign({}, fake.state, {inputs: fake.state.inputs.map(n => n.name === "microphone" ? Object.assign({}, n, {muted: false, volume: 60}) : n)});
   } else if (stage === 2) {
    check(find(drawer, "audioInput:microphone") === savedInput && slider === savedSlider && slider.activeFocus, "refresh recreated microphone/focus");
    check(find(drawer, "inputState:microphone").text === "In use" && find(drawer, "inputState:usb").text === "Ready", "activity confused with default");
    check(find(drawer, "inputConnection:microphone").visible, "shared input connections not grouped");
    const connection = find(drawer, "inputConnection:microphone");
    connection.currentIndex = 1; connection.activated(1);
    check(connection.currentIndex === 0, "connection changed before confirmation");
    check(last().op === "input-port" && last().values.port === "headset" && last().values.name === "microphone", "connection switch changed default or wrong input");
    click(find(drawer, "inputDefault:microphone"));
    check(last().op === "input-default" && last().values.name === "microphone", "default selection missing");
    fake.state = Object.assign({}, fake.state, {inputs: fake.state.inputs.map(n => Object.assign({}, n, {selected: n.name === "microphone"}))});
    capture("microphone-on.png");
   } else if (stage === 3) {
    check(find(drawer, "inputDefault:microphone").checked && !find(drawer, "inputDefault:usb").checked && slider === savedSlider, "default marker/independent control identity");
    const route = find(drawer, "recordingInput:24:101");
    check(route.displayText === "Built-in microphone" && route.count === 2, "recording destination list missing");
    route.currentIndex = drawer.destinations.findIndex(n => n.name === "usb");
    route.activated(route.currentIndex);
    check(route.currentIndex === drawer.destinations.findIndex(n => n.index === 9), "app route changed before confirmation");
    check(last().op === "move" && last().values.kind === "recording" && last().values.index === 24 && last().values.token === "101" && last().values.destination === "usb", "per-app routing lost stream identity");
    fake.state = Object.assign({}, fake.state, {recordings: fake.state.recordings.map(n => Object.assign({}, n, {source: 10}))});
   } else if (stage === 4) {
    check(find(drawer, "recordingInput:24:101").displayText === "USB microphone", "app route did not update");
    enabled.forceActiveFocus(); input.keyClick(Qt.Key_Space);
    check(last().op === "input-enabled" && !last().values.enabled && enabled.checked, "disable action/profile confirmation");
    fake.error = "Profile change failed";
   } else if (stage === 5) {
    check(enabled.checked && slider.enabled, "failed hardware change left UI disabled");
    fake.state = Object.assign({}, fake.state, {inputs: fake.state.inputs.map(n => n.name === "microphone" ? Object.assign({}, n, {muted: true}) : n)});
    check(!slider.enabled && slider.visible && mute.enabled && usbSlider.enabled, "mute did not disable only its gain slider");
    fake.error = ""; fake.state = STATE;
   } else if (stage === 6) {
    check(!enabled.checked && slider && !slider.enabled && usbSlider.enabled && slider === savedSlider, "disabling removed the retained slider or affected another device");
    check(Math.abs(find(drawer, "inputDevice:card").height - singleHeight) < 1, "single-input card jumped when disabled");
    check(!find(drawer, "inputDefault:microphone").enabled && !find(drawer, "inputConnection:microphone").enabled, "disabled input retained live routing actions");
    const second = Object.assign({}, BUILTIN, {key: "second", name: "second", index: 11, label: "Second channel", routes: [], port: "", muted: false});
    fake.state = Object.assign({}, fake.state, {inputs: fake.state.inputs.concat([Object.assign({}, BUILTIN, {muted: false}), second]),
      inputDevices: fake.state.inputDevices.map(n => n.key === "card" ? Object.assign({}, n, {enabled: true, canToggle: false, toggleReason: "Changing microphone availability requires a different playback mode."}) : n)});
   } else if (stage === 7) {
    check(find(drawer, "inputVolume:second:slider").enabled && slider.enabled && !enabled.enabled, "multiple sources on one card share a misleading slider/switch");
    check(find(drawer, "inputEnablementReason:card").visible, "unsupported hardware toggle unexplained");
    const count = fake.calls.length; click(enabled); check(fake.calls.length === count, "unsupported switch dispatched");
    fake.state = Object.assign({}, fake.state, {inputDevices: fake.state.inputDevices.map(n => n.key === "card" ? Object.assign({}, n, {canToggle: true, toggleReason: ""}) : n)});
    check(enabled.width >= 38, "shared device switch has no clickable width");
    click(enabled);
    check(last().op === "input-enabled" && last().values.card === "card" && !last().values.enabled, "shared switch did not target its whole device");
    fake.busy = true;
    check(!mute.enabled && !find(drawer, "inputDefault:usb").enabled && !find(drawer, "inputConnection:microphone").enabled && slider.enabled, "busy action/gain handling");
    fake.busy = false;
    drawer.active = false; check(!fake.observing, "observation survived dismissal"); drawer.active = true;
   } else if (stage === 8) {
    multiHeight = find(drawer, "inputDevice:card").height;
    fake.state = Object.assign({}, fake.state, {inputs: [STATE.inputs[0]], inputDevices: fake.state.inputDevices.map(n => n.key === "card" ? Object.assign({}, n, {enabled: false}) : n)});
   } else if (stage === 9) {
    check(Math.abs(find(drawer, "inputDevice:card").height - multiHeight) < 1, "multi-input card jumped when disabled");
    check(slider && !slider.enabled && !find(drawer, "inputVolume:second:slider").enabled && drawer.destinations.length === 1, "retained inputs are live or rows disappeared");
    capture("microphone-multi-disabled.png");
    fake.state = Object.assign({}, fake.state, {inputDevices: [STATE.inputDevices[1]]});
   } else if (stage === 10) {
    check(!enabled && !slider && usbSlider.enabled, "unplug removed unrelated microphone or retained stale controls");
    fake.state = Object.assign({}, fake.state, {inputs: [], inputDevices: [], recordings: []});
   } else if (stage === 11) {
    check(find(drawer, "microphoneInputsEmpty").visible && find(drawer, "recordingAppsEmpty").visible, "empty state missing");
    capture("microphone-empty.png");
    UI.Theme.setMode("light"); fake.state = STATE;
   } else if (stage === 12) {
    capture("microphone-light.png");
    drawer.width = 220; fake.error = "Microphone disconnected";
   } else if (stage === 13) {
    capture("microphone-narrow.png"); fake.loaded = false;
   } else {
    console.log("AUDIO_PASS"); Qt.quit();
   }
   stage++;
  } catch (error) { console.error("AUDIO_FAIL", error.message); Qt.quit(); }
 } }
}
'''.replace('STATE', json.dumps(state)).replace('BUILTIN', json.dumps(builtin)))

    def test_status_icon_volume_mute_boost_and_theme(self):
        def setup(root):
            # Substitute the native sink/tracker only; keep production presentation bindings.
            path = root / 'bar/AudioStatus.qml'
            source = path.read_text().replace('readonly property var sink: Pipewire.defaultAudioSink', 'property var sink: null')
            source = source.replace('objects: [sink].filter(n => n)', 'objects: []')
            path.write_text(source)
            path = root / 'bar/MicrophoneStatus.qml'
            source = path.read_text().replace('readonly property var source: Pipewire.defaultAudioSource', 'property var source: null')
            source = source.replace('objects: [source].filter(node => node)', 'objects: []')
            path.write_text(source)

        self.run_qml(r'''import QtQuick
import Quickshell
import "bar"
import "ui" as UI
FloatingWindow {
 implicitWidth: 80; implicitHeight: 40
 QtObject { id: audio; property real volume: 0; property bool muted: false }
 AudioStatus { id: status; sink: ({audio, nickname: "Dell S2722DC", description: "Graphics audio", name: "display"}) }
 MicrophoneStatus { id: micStatus; source: ({audio, nickname: "Built-in microphone", name: "microphone", properties: {}}) }
 StatusButton {
  id: button
  entry: BarEntry { key: "sound"; title: "Sound"; iconName: status.iconName; iconColor: status.iconColor }
 }
 function check(value, message) { if (!value) throw new Error(message); }
 property int stage: 0
 Timer { interval: 100; running: true; repeat: true; onTriggered: {
  try {
   const icon = button.contentItem.children[0];
   if (stage === 0) {
   for (const [level, name] of [[0, "volume"], [0.2, "volume-1"], [0.5, "volume-1"], [0.51, "volume-2"], [1, "volume-2"], [1.25, "volume-2"]]) {
    audio.volume = level;
    check(icon.name === name, "status volume icon " + level);
    check(icon.color.toString() === (level > 1 ? UI.Theme.accent : UI.Theme.text).toString(), "status volume color " + level);
    check(status.description === "Volume: " + Math.round(level * 100) + "%\nDell S2722DC", "volume/device tooltip " + level);
   }
   check(micStatus.iconName === "mic", "microphone bar icon missing");
   audio.muted = true;
   check(micStatus.iconName === "mic-off" && micStatus.description.includes("muted"), "microphone bar missed mute");
   check(micStatus.iconColor.toString() === UI.Theme.text.toString(), "enabled muted microphone is grayed out");
   check(icon.name === "volume-x" && icon.color.toString() === UI.Theme.accent.toString(), "boosted mute state");
   check(status.description === "Volume: 125% (muted)\nDell S2722DC", "muted tooltip lost volume/device");
   UI.Theme.setMode("light"); stage++; return;
   }
   check(UI.Theme.mode === "light" && icon.color.toString() === UI.Theme.accent.toString(), "status color missed theme change");
   check(micStatus.iconColor.toString() === UI.Theme.text.toString(), "muted microphone missed theme change");
   audio.volume = 0.5; audio.muted = false;
   check(icon.name === "volume-1" && icon.color.toString() === UI.Theme.text.toString(), "boost color survived normal volume");
   status.sink = {audio, description: "Laptop speakers", name: "laptop"};
   check(status.description === "Volume: 50%\nLaptop speakers", "tooltip did not follow default output change");
   status.sink = {audio, name: "laptop"};
   check(status.description === "Volume: 50%\nlaptop", "tooltip device fallback");
   micStatus.source = {audio, name: "output.monitor", properties: {"device.class": "monitor"}};
   check(!micStatus.available && micStatus.iconName === "mic-off", "loopback source presented as a microphone");
   micStatus.source = null;
   check(micStatus.description === "No microphone available", "missing microphone status");
   check(micStatus.iconName === "mic-off" && micStatus.iconColor.toString() === UI.Theme.muted.toString(), "disabled microphone is not grayed out");
   status.sink = null;
   check(icon.name === "volume-x", "missing output icon");
   check(status.description === "No audio output", "missing output tooltip");
   console.log("AUDIO_PASS"); Qt.quit();
  } catch (error) { console.error("AUDIO_FAIL", error.message); Qt.quit(); }
 } }
}
''', setup)

    def test_media_association_and_menu_order_after_inventory_changes(self):
        outputs, devices = backend.output_inventory([SINK], [CARD], CONFIG, 'laptop')
        first = dict(STREAM, properties={**STREAM['properties'], 'application.id': 'test.player'})
        second = dict(STREAM, index=24, properties={'application.name': 'Browser', 'application.process.binary': 'browser', 'object.serial': '101'})
        state = dict(available=True, outputs=outputs, outputDevices=devices, streams=backend.stream_records([first, second], 'sink'), warning='')
        self.run_qml(r'''import QtQuick
import QtTest
import Quickshell
import "drawers"
FloatingWindow {
 id: window
 implicitWidth: 480; implicitHeight: 1000
 QtObject {
  id: fake
  property bool loaded: true
  property bool busy: false
  property string error: ""
  property var state: ({available:true, outputs:[], outputDevices:[], streams:[], warning:""})
  function observe(owner, active) {}
  function run(op, values) {}
  function refresh() {}
  function boostFor(device) { return false; }
  function boostPending(device) { return false; }
  function setBoost(device, enabled) {}
 }
 component Player: QtObject {
  required property string dbusName
  required property string desktopEntry
  property string identity: "Player"
  property string trackTitle: "<Track & title>"
  property string trackArtist: "Artist"
  property bool isPlaying: true
  property bool canControl: true
  property bool canGoPrevious: true
  property bool canGoNext: true
  property bool canTogglePlaying: true
  property int previousCalls: 0
  property int nextCalls: 0
  function previous() { previousCalls++; }
  function next() { nextCalls++; }
  function togglePlaying() { isPlaying = !isPlaying; }
 }
 Player { id: first; dbusName:"org.mpris.MediaPlayer2.first"; desktopEntry:"test.player.desktop" }
 Player { id: browser; dbusName:"org.mpris.MediaPlayer2.browser"; desktopEntry:"browser" }
 Player { id: twin; dbusName:"org.mpris.MediaPlayer2.twin"; desktopEntry:"test.player"; isPlaying:false }
 SoundDrawer { id: drawer; width:448; height:968; service:fake; active:true; players:[first, browser] }
 TestCase { id: input; when:false; parent:window.contentItem }
 function find(item, name) {
  if (item.objectName === name) return item;
  for (const child of item.children || []) { const result=find(child,name); if (result) return result; }
  return null;
 }
 function count(item, name) { return (item.objectName === name ? 1 : 0) + Array.from(item.children || []).reduce((n,child) => n + count(child,name),0); }
 function check(value, message) { if (!value) throw new Error(message); }
 function click(item) { input.mouseClick(item,item.width/2,item.height/2); }
 function footer(profiles) {
  const menu=find(drawer,"outputOptions:card").menu;
  check(menu.count === profiles+2,"menu count after refresh: " + menu.count);
  for (let i=0; i<profiles; i++) check(menu.itemAt(i).objectName.startsWith("audioProfile:"),"profile follows separator");
  check(menu.itemAt(profiles).objectName === "outputOptionsSeparator:card" && menu.itemAt(profiles+1).objectName === "audioBoost:card","separator is not immediately before boost");
 }
 function profiles(modes) { fake.state=Object.assign({},fake.state,{outputDevices:fake.state.outputDevices.map(device => Object.assign({},device,{profiles:modes}))}); }
 property int stage:0
 Timer { interval:160; running:true; repeat:true; onTriggered: {
  try {
   const playback=find(drawer,"audioPlayback");
   const firstName="audioPlayer:"+first.dbusName;
   const browserName="audioPlayer:"+browser.dbusName;
   if (stage === 0) {
    // Devices arrive after page construction in production, not as initial data.
    fake.state=STATE;
   } else if (stage === 1) {
    footer(2);
    const firstApp=find(drawer,"appPlayback:23:100"), browserApp=find(drawer,"appPlayback:24:101");
    check(find(firstApp,firstName) && find(browserApp,browserName) && !playback.visible,"independent apps did not receive their own player");
    click(find(firstApp,firstName+":playPause")); click(find(browserApp,browserName+":next"));
    check(!first.isPlaying && browser.isPlaying && browser.nextCalls === 1 && first.nextCalls === 0,"transport controls affect another player");
    check(count(drawer,firstName) === 1 && count(drawer,browserName) === 1,"player duplicated beside app and in playback");
    find(drawer,"outputOptions:card").menu.open();
    profiles(fake.state.outputDevices[0].profiles.concat([{name:"third",label:"Third layout",enabled:true,selected:false}]));
   } else if (stage === 2) {
    footer(3); profiles(fake.state.outputDevices[0].profiles.slice(1,2));
   } else if (stage === 3) {
    footer(1); profiles([]);
    fake.state=Object.assign({},fake.state,{streams:fake.state.streams.concat([Object.assign({},fake.state.streams[0],{key:"25:102",index:25,token:"102"})])});
   } else if (stage === 4) {
    footer(0); find(drawer,"outputOptions:card").menu.close();
    check(playback.visible && find(playback,firstName) && !find(find(drawer,"appPlayback:23:100"),firstName),"ambiguous streams assigned to an arbitrary app row");
    check(find(find(drawer,"appPlayback:24:101"),browserName) && count(drawer,firstName) === 1,"unrelated app lost controls or ambiguous player duplicated");
    fake.state=STATE; drawer.players=[first,twin,browser];
   } else if (stage === 5) {
    check(find(playback,firstName) && find(playback,"audioPlayer:"+twin.dbusName) && !find(find(drawer,"appPlayback:23:100"),firstName),"multiple sessions falsely attached to one stream");
    fake.state=Object.assign({},fake.state,{streams:[]});
   } else if (stage === 6) {
    check(playback.visible && playback.players.length === 3 && find(drawer,"audioAppsEmpty").visible,"paused or streamless players disappeared");
    drawer.players=[twin];
   } else if (stage === 7) {
    check(!find(drawer,firstName) && !find(drawer,browserName) && find(playback,"audioPlayer:"+twin.dbusName),"disappeared player retained controls");
    drawer.players=[];
   } else {
    check(!playback.visible,"empty playback section visible");
    console.log("AUDIO_PASS"); Qt.quit();
   }
   stage++;
  } catch(error) { console.error("AUDIO_FAIL",error.message); Qt.quit(); }
 } }
}
'''.replace('STATE', json.dumps(state)))

    def test_sound_independent_outputs_routes_profiles_boost_and_lifetime(self):
        jack = dict(SINK['ports'][1], availability='available')
        laptop = dict(SINK, ports=[SINK['ports'][0], jack, dict(jack, name='missing', availability='not available')])
        aux = dict(SINK, name='aux', index=12, description='Auxiliary speakers', ports=[])
        display = dict(SINK, name='display', index=8, description='Dell S2722DC speakers', properties={'device.name': 'display-card'},
                       active_port='hdmi', ports=[dict(name='hdmi', description='HDMI / DisplayPort', availability='available')])
        card = dict(CARD, properties={'device.description': 'Laptop audio'})
        display_card = dict(CARD, name='display-card', index=5, properties={'device.description': 'Display audio'})
        outputs, devices = backend.output_inventory([laptop, aux, display], [card, display_card], CONFIG, 'laptop')
        state = dict(available=True, outputs=outputs, outputDevices=devices, streams=backend.stream_records([STREAM], 'sink'), inputs=[], inputDevices=[], recordings=[], warning='')
        self.run_qml(r'''import QtQuick
import QtTest
import Quickshell
import "drawers"
import "ui" as UI
FloatingWindow {
 id: window
 implicitWidth: 480; implicitHeight: 1000; color: UI.Theme.background
 QtObject {
  id: fake
  property bool observing: false
  property bool loaded: true
  property bool busy: false
  property var boosts: ({})
  property string pendingBoost: ""
  property string error: ""
  property var state: STATE
  property var calls: []
  function run(op, values) { calls = calls.concat([{op, values}]); }
  function refresh() {}
  function boostFor(device) { return !!boosts[device]; }
  function boostPending(device) { return pendingBoost === device; }
  function setBoost(device, enabled) { pendingBoost = device; run("output-boost", {device, enabled}); }
  function observe(owner, active) { observing = active; }
 }
 QtObject {
  id: media
  property string dbusName: "org.mpris.MediaPlayer2.test"
  property string desktopEntry: "test-player"
  property string identity: "Music player"
  property string trackTitle: "Test track"
  property string trackArtist: "Test artist"
  property bool isPlaying: true
  property bool canControl: true
  property bool canGoPrevious: true
  property bool canGoNext: true
  property bool canTogglePlaying: true
  property int previousCalls: 0
  property int nextCalls: 0
  function previous() { previousCalls++; }
  function next() { nextCalls++; }
  function togglePlaying() { isPlaying = !isPlaying; }
 }
 SoundDrawer { id: drawer; width: 448; height: 968; x: 16; y: 16; service: fake; active: true
  Rectangle { anchors.fill: parent; color: UI.Theme.background; z: -1 }
 }
 TestCase { id: input; when: false; parent: window.contentItem }
 function find(item, name) {
  if (item.objectName === name) return item;
  for (const child of item.children || []) { const result = find(child, name); if (result) return result; }
  return null;
 }
 function check(value, message) { if (!value) throw new Error(message); }
 function click(item) { input.mouseClick(item, item.width/2, item.height/2); }
 function last() { return fake.calls[fake.calls.length-1]; }
 function capture(name) { drawer.grabToImage(result => result.saveToFile((Quickshell.env("AUDIO_PREVIEW_DIR") || "/tmp") + "/" + name)); }
 property int stage: 0
 property var savedOutput: null
 property var savedSlider: null
 Timer { interval: 180; repeat: true; running: true; onTriggered: {
  try {
   const slider = find(drawer, "outputVolume:laptop:slider");
   if (stage === 0) {
    drawer.players = [media];
    check(find(drawer, "appPlayback:23:100").visible && !find(drawer, "audioPlayback").visible, "media controls not beside matching application");
    const prefix = "audioPlayer:" + media.dbusName;
    click(find(drawer, prefix + ":previous")); click(find(drawer, prefix + ":playPause")); click(find(drawer, prefix + ":next"));
    check(media.previousCalls === 1 && media.nextCalls === 1 && !media.isPlaying && find(drawer, prefix + ":playPause").iconName === "play", "media transport dispatch/state");
    media.canGoNext = false; check(!find(drawer, prefix + ":next").enabled, "unsupported next action enabled");
    check(fake.observing && !find(drawer, "masterVolume"), "observation or global-volume assumption");
    check(find(drawer, "outputDevice:card") && find(drawer, "outputDevice:display-card"), "physical output grouping missing");
    check(slider.enabled && find(drawer, "outputVolume:aux:slider").enabled && find(drawer, "outputVolume:display:slider").enabled, "independent output sliders missing");
    check(drawer.destinations.length === 3 && find(drawer, "outputConnection:laptop").count === 2, "shared or disconnected ports treated as independent outputs");
    check(find(drawer, "outputDefault:laptop").checked && !find(drawer, "outputDefault:display").checked, "default markers incorrect");
    click(find(drawer, "outputVolume:aux:mute"));
    check(last().op === "mute" && last().values.name === "aux" && last().values.muted, "nondefault output mute dispatch");
    savedOutput = find(drawer, "audioOutput:laptop"); savedSlider = slider;
    slider.forceActiveFocus(); input.keyClick(Qt.Key_Right);
    check(last().op === "volume" && last().values.name === "laptop", "per-output gain dispatch");
    capture("audio-drawer.png");
   } else if (stage === 1) {
    fake.state = Object.assign({}, fake.state, {outputs: fake.state.outputs.map(n => Object.assign({}, n, {volume: 60}))});
    check(find(drawer, "audioOutput:laptop") === savedOutput && slider === savedSlider && slider.activeFocus, "refresh recreated output row or lost focus");
    const connection = find(drawer, "outputConnection:laptop");
    connection.currentIndex = 1; connection.activated(1);
    check(last().op === "output-port" && last().values.port === "jack" && connection.currentIndex === 0, "connection change conflated with default/optimistic state");
    click(find(drawer, "outputDefault:display"));
    check(last().op === "output-default" && last().values.name === "display", "default output dispatch");
    click(find(drawer, "appVolume:23:100:mute"));
    check(last().values.token === "100", "stream identity missing");
    click(find(drawer, "appOptions:23:100"));
   } else if (stage === 2) {
    const menu = find(drawer, "appOptions:23:100").menu;
    check(menu.visible && menu.count === 3, "app output menu duplicated shared ports");
    const option = Array.from({length: menu.count}, (_, index) => menu.itemAt(index)).find(item => item.objectName === "appOutput:23:100:display");
    check(option && !option.marked, "app route incorrectly follows default request");
    click(option);
    check(last().op === "move" && last().values.destination === "display" && last().values.token === "100" && !last().values.boost, "app routing/identity/boost scope");
    click(find(drawer, "outputOptions:card"));
   } else if (stage === 3) {
    const menu = find(drawer, "outputOptions:card").menu;
    check(menu.visible && menu.itemAt(0).objectName === "audioProfile:card:duplex" && menu.itemAt(0).marked, "device profile menu/default");
    check(menu.itemAt(menu.count-2).objectName === "outputOptionsSeparator:card" && menu.itemAt(menu.count-1).objectName === "audioBoost:card", "boost does not follow device profiles");
    click(menu.itemAt(1));
    check(last().op === "profile" && last().values.card === "card" && last().values.previous === "duplex" && last().values.profile === "surround", "card-level profile action/guard");
    click(find(drawer, "outputOptions:card"));
   } else if (stage === 4) {
    const menu = find(drawer, "outputOptions:card").menu;
    check(menu.itemAt(0).marked && !menu.itemAt(1).marked, "unconfirmed profile changed checkmarks");
    click(menu.itemAt(menu.count-1));
    check(last().op === "output-boost" && last().values.device === "card" && last().values.enabled && !fake.boostFor("card"), "boost was global or changed before acknowledgement");
    check(!slider.enabled && !find(drawer, "appVolume:23:100:slider").enabled && find(drawer, "outputVolume:display:slider").enabled, "boost transition permits stale queued gains or blocks unrelated device");
    fake.boosts = {card: true}; fake.pendingBoost = "";
    fake.state = Object.assign({}, fake.state, {outputs: fake.state.outputs.map(n => Object.assign({}, n, {volume: n.name === "display" ? 140 : 125})),
      streams: fake.state.streams.map(n => Object.assign({}, n, {volume: 125}))});
   } else if (stage === 5) {
    check(find(drawer, "outputVolume:laptop").maximum === 150 && find(drawer, "outputVolume:aux").maximum === 150 && find(drawer, "outputVolume:display").maximum === 100, "device boost scope/range");
    check(find(drawer, "appVolume:23:100").maximum === 150, "app boost does not follow destination device");
    check(find(drawer, "outputVolume:display:slider").value === 140 && find(drawer, "outputVolume:display:slider").to >= 140, "external boosted gain clamped in presentation");
    check(find(drawer, "outputVolume:laptop:mute").iconColor.toString() === UI.Theme.accent.toString(), "boosted output icon is not red");
    capture("audio-boost.png");
   } else if (stage === 6) {
    click(find(drawer, "outputOptions:card"));
   } else if (stage === 7) {
    const menu = find(drawer, "outputOptions:card").menu;
    check(menu.itemAt(menu.count-1).marked, "boost checkmark not confirmed");
    click(menu.itemAt(menu.count-1));
    check(last().op === "output-boost" && !last().values.enabled && fake.boostFor("card"), "boost disabled before gain normalization acknowledgement");
    fake.state = Object.assign({}, fake.state, {outputs: fake.state.outputs.map(n => n.deviceKey === "card" ? Object.assign({}, n, {volume: 100}) : n),
      streams: fake.state.streams.map(n => Object.assign({}, n, {volume: 100}))});
    fake.boosts = {card: false}; fake.pendingBoost = "";
   } else if (stage === 8) {
    check(slider.value === 100 && slider.to === 100 && find(drawer, "appVolume:23:100:slider").value === 100, "boost off left slider/gain mismatch");
    check(find(drawer, "outputVolume:display:slider").value === 140 && !fake.boostFor("display-card"), "boost off altered another device or concealed its native level");
    fake.state = Object.assign({}, fake.state, {outputs: fake.state.outputs.map(n => Object.assign({}, n, {selected: n.name === "display"}))});
    check(find(drawer, "outputDefault:display").checked && !find(drawer, "outputDefault:laptop").checked && fake.state.streams[0].sink === 7 && slider === savedSlider, "default selection changed explicit app routing or slider identity");
    capture("audio-mixer.png");
   } else if (stage === 9) {
    click(find(drawer, "outputOptions:card"));
    drawer.active = false;
    check(!fake.observing && !find(drawer, "outputOptions:card").menu.visible, "dismissed device menu/service still active");
    check(!find(drawer, "audioPlayer:" + media.dbusName + ":playPause").enabled, "dismissed player still active");
    drawer.active = true;
    fake.state = Object.assign({}, fake.state, {outputs: fake.state.outputs.filter(n => n.name !== "laptop")});
    check(!find(drawer, "outputVolume:laptop") && find(drawer, "outputVolume:aux") && find(drawer, "outputDefault:display").checked, "unplug removed unrelated independent outputs");
   } else if (stage === 10) {
    fake.state = Object.assign({}, fake.state, {outputs: [], outputDevices: [], streams: []});
    check(find(drawer, "audioOutputsEmpty").visible && find(drawer, "audioAppsEmpty").visible && find(drawer, "audioPlayback").visible, "empty states or paused player missing");
    capture("audio-empty.png");
   } else if (stage === 11) {
    UI.Theme.setMode("light"); fake.state = STATE; drawer.width = 220;
   } else if (stage === 12) {
    capture("audio-drawer-light.png");
   } else if (stage === 13) {
    drawer.players = [];
    check(!find(drawer, "audioPlayback").visible, "empty player remains visible");
    fake.loaded = false; fake.error = "Output disconnected";
   } else {
    console.log("AUDIO_PASS"); Qt.quit();
   }
   stage++;
  } catch (error) { console.error("AUDIO_FAIL", error.message); Qt.quit(); }
 } }
}
'''.replace('STATE', json.dumps(state)))


if __name__ == '__main__':
    unittest.main()
