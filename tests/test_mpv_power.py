"""Generate the shipped shader profiles without leaking Windows-only options."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
POWER = REPO / 'modules/hardware/power/files/etc/mpv'


@unittest.skipUnless(
    shutil.which('mpv'), 'mpv is required for native profile restoration'
)
class MpvQuality(unittest.TestCase):
    def test_only_powersave_changes_quality_and_exit_restores_user_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            wrapper = Path(directory) / 'test.lua'
            wrapper.write_text(
                """local mp = require('mp')
local active = 'zephyrus-balanced'
local update
local original_open, original_getenv = io.open, os.getenv
io.open = function(path, ...)
    if path == '/etc/tuned/active_profile' then
        return {read = function() return active end, close = function() end}
    end
    return original_open(path, ...)
end
-- Exercise the actual quality controls without opening any IPC/network sockets.
os.getenv = function(name)
    if name == 'XDG_RUNTIME_DIR' then return nil end
    return original_getenv(name)
end
local register = mp.register_script_message
mp.register_script_message = function(name, callback)
    if name == 'dotfiles-power' then update = callback end
    return register(name, callback)
end
dofile(SCRIPT)
local original = {scale='spline36', cscale='spline36', dscale='mitchell',
                  deband=true, interpolation=true}
local function quality(expected)
    for name, value in pairs(expected) do
        local actual = mp.get_property_native('options/' .. name)
        assert(actual == value, name .. ': expected ' .. tostring(value) .. ', got ' .. tostring(actual))
    end
end
local function switch(profile)
    active = profile
    update()
end
mp.add_timeout(0, function()
    local ok, err = pcall(function()
        quality(original)
        for _, target in ipairs({'zephyrus-balanced', 'zephyrus-battery',
                'zephyrus-performance', 'zephyrus-performance-battery'}) do
            switch('zephyrus-powersave-battery')
            quality({scale='bilinear', cscale='bilinear', dscale='bilinear',
                     deband=false, interpolation=false})
            switch(target)
            quality(original)
        end
        -- Preserve a manual edit made while the Powersave overlay is active.
        switch('zephyrus-powersave')
        mp.set_property('options/scale', 'lanczos')
        switch('zephyrus-balanced')
        original.scale = 'lanczos'
        quality(original)
    end)
    print(ok and 'MPV_PASS' or ('MPV_FAIL ' .. tostring(err)))
    mp.commandv('quit', ok and 0 or 1)
end)
""".replace('SCRIPT', json.dumps(str(POWER / 'scripts/dotfiles-power.lua')))
            )
            result = subprocess.run(
                [
                    'mpv',
                    '--no-config',
                    '--load-scripts=no',
                    '--idle=yes',
                    '--vo=null',
                    '--ao=null',
                    '--terminal=yes',
                    '--scale=spline36',
                    '--cscale=spline36',
                    '--dscale=mitchell',
                    '--deband=yes',
                    '--interpolation=yes',
                    '--include=' + str(POWER / 'power-profiles.conf'),
                    '--script=' + str(wrapper),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            log = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, log)
            self.assertIn('MPV_PASS', log)
            self.assertNotIn('MPV_FAIL', log)


@unittest.skipUnless(shutil.which('jq'), 'jq is required by mpv provisioning')
class MpvGeneration(unittest.TestCase):
    def test_platform_filter_and_profile_switching(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack = root / 'pack.json'
            pack.write_text(
                json.dumps(
                    {
                        'profiles': {
                            'generic-high': {
                                'displayname': 'High',
                                'shaders': ['hq.glsl'],
                                'setting-groups': ['neural'],
                            },
                            'AMD FidelityFX Super Resolution': {
                                'displayname': 'FSR',
                                'shaders': ['fsr.glsl'],
                            },
                            'AMD FidelityFX Contrast Adaptive Sharpening': {
                                'shaders': ['cas.glsl']
                            },
                            'windows-only': {
                                'displayname': 'Windows',
                                'platforms': ['windows'],
                                'setting-groups': ['windows'],
                            },
                            'linux-only': {
                                'displayname': 'Linux',
                                'platforms': ['linux'],
                                'shaders': ['linux.glsl'],
                            },
                        },
                        'setting-groups': {
                            'windows': {
                                'settings': [['gpu_api', 'd3d11'], ['vf', 'd3d11vpp']]
                            },
                            'neural': {
                                'settings': [
                                    ['scale', 'ewa_lanczos'],
                                    ['cscale', 'mitchell'],
                                    ['dscale', 'mitchell'],
                                    ['linear_downscaling', False],
                                ]
                            },
                        },
                    }
                )
            )
            env = dict(
                os.environ,
                DOTFILES_REPO=str(REPO),
                MPV_CONF_DIR=str(root / 'config'),
                MPV_SHADER_PACK=str(pack),
                MPV_SHADERS_DIR=str(root),
            )
            (root / 'config').mkdir()
            for filename in ('mpv.conf', 'input.conf'):
                shutil.copyfile(
                    REPO / 'modules/media/video/mpv/files/home/.config/mpv' / filename,
                    root / 'config' / filename,
                )
            result = subprocess.run(
                ['bash', str(REPO / 'modules/media/video/mpv/scripts/50_mpv.sh')],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            config = (root / 'config/mpv.conf').read_text()
            menu = (root / 'config/input.conf').read_text()
            self.assertNotIn('d3d11', config)
            self.assertNotIn('windows-only', menu)
            self.assertIn('[linux-only]', config)
            self.assertIn('linux-only', menu)
            self.assertIn('Profiles > Standard', menu)
            self.assertIn('Profiles > FSR', menu)
            self.assertNotIn('Profiles > AMD FidelityFX', menu)
            self.assertNotIn('fsr-cas', config + menu)
            default = config.rsplit('[default]', 1)[1]
            self.assertIn('profile=standard', default)
            self.assertNotIn('profile=generic-high', default)
            self.assertNotIn('profile=AMD FidelityFX Super Resolution', default)
            self.assertIn('[generic-high]', config)
            if not shutil.which('mpv'):
                return
            wrapper = root / 'switch.lua'
            wrapper.write_text("""local mp = require('mp')
local function check(name, expected)
    local actual = mp.get_property_native('options/' .. name)
    assert(actual == expected, name .. ': expected ' .. tostring(expected) .. ', got ' .. tostring(actual))
end
local function standard()
    check('scale', 'lanczos')
    check('cscale', 'lanczos')
    check('dscale', 'hermite')
    check('linear-downscaling', true)
end
mp.add_timeout(0, function()
    local ok, err = pcall(function()
        standard()
        assert(#mp.get_property_native('options/glsl-shaders') == 0)
        mp.commandv('apply-profile', 'generic-high')
        check('scale', 'ewa_lanczos')
        check('linear-downscaling', false)
        mp.commandv('apply-profile', 'fsr')
        standard()
        local shaders = mp.get_property_native('options/glsl-shaders')
        assert(#shaders == 1 and shaders[1]:match('/fsr.glsl$'))
        mp.commandv('apply-profile', 'generic-high')
        mp.commandv('apply-profile', 'standard')
        standard()
        assert(#mp.get_property_native('options/glsl-shaders') == 0)
    end)
    print(ok and 'MPV_PASS' or ('MPV_FAIL ' .. tostring(err)))
    mp.commandv('quit', ok and 0 or 1)
end)
""")
            result = subprocess.run(
                [
                    'mpv',
                    '--no-config',
                    '--include=' + str(root / 'config/mpv.conf'),
                    '--load-scripts=no',
                    '--idle=yes',
                    '--vo=null',
                    '--ao=null',
                    '--terminal=yes',
                    '--script-opts=dotfiles-power-enabled=no',
                    '--script=' + str(wrapper),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('MPV_PASS', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
