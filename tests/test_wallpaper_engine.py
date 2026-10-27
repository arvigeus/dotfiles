import support
import sys

sys.path.insert(0, str(support.DESKTOP))
import io
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from spaces.pictures import backend as pictures
from spaces.pictures import wallpaper_engine as engine
from spaces.pictures import workshop


class WallpaperEngineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(
            os.environ,
            {
                'HOME': str(self.root),
                'XDG_CONFIG_HOME': str(self.root / 'config'),
                'XDG_CACHE_HOME': str(self.root / 'cache'),
                'XDG_DATA_HOME': str(self.root / 'data'),
                'XDG_RUNTIME_DIR': str(self.root / 'runtime'),
                'WALLPIPER_STEAM_ROOT': str(self.root / 'Steam'),
            },
        )
        environment.start()
        self.addCleanup(environment.stop)
        self.folder = self.root / 'Steam/steamapps/workshop/content/431960/123456'
        self.folder.mkdir(parents=True)
        self.project = self.folder / 'project.json'
        self.project.write_text(
            json.dumps(
                {
                    'title': 'Clouds',
                    'type': 'scene',
                    'file': 'scene.json',
                    'preview': 'preview.png',
                }
            )
        )
        (self.folder / 'preview.png').write_bytes(b'preview')
        self.engine_executable = (
            self.root / 'Steam/steamapps/common/wallpaper_engine/wallpaper64.exe'
        )
        self.engine_executable.parent.mkdir(parents=True)
        self.engine_executable.write_bytes(b'fixture')
        proton = self.root / 'Steam/steamapps/common/Proton Fixture/proton'
        proton.parent.mkdir(parents=True)
        proton.write_bytes(b'fixture')
        proton.chmod(0o755)

    def setting(self, value):
        engine.config_dir().mkdir(parents=True, exist_ok=True)
        (engine.config_dir() / 'wallpaper.json').write_text(json.dumps(value))

    def fixture_environment(self):
        binary_dir = self.root / 'bin'
        binary_dir.mkdir(exist_ok=True)
        fixture = binary_dir / 'fixture'
        shutil.copyfile(Path(__file__).parent / 'fixtures/wallpaper-engine.py', fixture)
        fixture.chmod(0o755)
        for command in ('hyprctl', 'wallpiperd', 'wallpiperctl'):
            (binary_dir / command).symlink_to(fixture)
        return dict(
            os.environ,
            ENGINE_FIXTURE_ROOT=str(self.root),
            HYPRLAND_INSTANCE_SIGNATURE='fixture',
            PATH=str(binary_dir) + ':' + os.environ['PATH'],
        )

    def spawn_worker(self, environment):
        worker = subprocess.Popen(
            [sys.executable, '-u', str(Path(engine.__file__).resolve())],
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        def cleanup():
            if worker.poll() is None:
                worker.terminate()
                worker.wait(timeout=20)
            for stream in (worker.stdin, worker.stdout, worker.stderr):
                stream.close()

        self.addCleanup(cleanup)
        return worker

    def sync_worker(self, worker, clients=None, monitors=None):
        worker.stdin.write(
            json.dumps(
                {
                    'id': 1,
                    'op': 'sync',
                    'monitors': monitors
                    if monitors is not None
                    else [{'name': 'TEST', 'id': 0, 'activeWorkspace': {'id': 1}}],
                    'clients': clients or [],
                }
            )
            + '\n'
        )
        worker.stdin.flush()
        self.assertTrue(
            select.select([worker.stdout], [], [], 5)[0], 'worker did not answer'
        )
        return json.loads(worker.stdout.readline())

    def wait_worker_ready(self, worker):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            response = self.sync_worker(worker)
            if response.get('result', {}).get('screens') == ['TEST']:
                return
            time.sleep(0.05)
        self.fail('Worker did not become ready: ' + str(response))

    def test_runtime_rejects_symlink_and_public_runtime_directories(self):
        folder = engine.state_file().parent
        folder.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'private'):
            engine.state_file()
        folder.chmod(0o700)
        folder.rmdir()
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        folder.symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'private'):
            engine.state_file()
        self.assertFalse(list(elsewhere.iterdir()))

    def test_runtime_lock_rejects_symlinks_without_modifying_target(self):
        self.setting({})
        target = self.root / 'untouched'
        target.write_text('keep')
        (engine.config_dir() / '.engine-runtime.lock').symlink_to(target)
        with self.assertRaises(OSError):
            engine.Runtime()
        self.assertEqual(target.read_text(), 'keep')

    def test_corrupt_ownership_is_preserved_and_runtime_lease_is_released(self):
        self.setting({})
        journal = engine.config_dir() / '.engine-ownership.json'
        for data in ('bad json', '[]', '{}', '{"owner":""}'):
            journal.write_text(data)
            with self.assertRaises(ValueError):
                engine.Runtime()
            self.assertEqual(journal.read_text(), data)
        journal.unlink()
        runtime = engine.Runtime()
        runtime.close()

    def test_unexpected_daemon_exit_restarts_and_reaps_detached_helpers(self):
        environment = self.fixture_environment()
        self.setting(
            {
                'mode': 'wallpaper_engine',
                'workshop_id': '123456',
                'selection': 'restore',
            }
        )
        worker = self.spawn_worker(environment)
        self.wait_worker_ready(worker)
        old_pids = json.loads((self.root / 'pids.json').read_text())
        owner = json.loads(
            (engine.config_dir() / '.engine-ownership.json').read_text()
        )['owner']
        self.addCleanup(engine.reap_owned, owner)
        os.kill(old_pids[0], 9)
        deadline = time.monotonic() + 3
        while engine.process_identity(old_pids[0]) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.sync_worker(worker)['result']['recovering'])
        self.wait_worker_ready(worker)
        self.assertFalse(any(engine.process_identity(pid) for pid in old_pids))
        self.assertTrue((engine.state_file().parent / 'daemon.previous.log').exists())

    def native_selection(self, selections):
        path = self.engine_executable.parent / 'config.json'
        path.write_text(
            json.dumps(
                {
                    'steamuser': {
                        'general': {
                            'wallpaperconfig': {'selectedwallpapers': selections}
                        }
                    }
                }
            )
        )

    def test_native_playback_override_restores_preferences_and_preserves_scene_changes(
        self,
    ):
        config = self.engine_executable.parent / 'config.json'
        config.write_text(
            json.dumps(
                {
                    'steamuser': {
                        'general': {'user': {'playbacksleep': 'stop', 'fps': 15}}
                    }
                }
            )
        )
        self.setting(
            {'mode': 'wallpaper_engine', 'workshop_id': '123456', 'selection': 'boot'}
        )
        worker = self.spawn_worker(self.fixture_environment())
        self.wait_worker_ready(worker)
        native = json.loads(config.read_text())
        self.assertTrue(
            all(
                native['steamuser']['general']['user'][key] == 'run'
                for key in engine.NATIVE_PLAYBACK_RULES
            )
        )
        self.assertTrue(engine.native_playback_policy_file().exists())
        # Native edits while playing must survive shutdown, including the new
        # selected wallpaper written by the real Set command fixture.
        native['steamuser']['general']['user']['fps'] = 30
        config.write_text(json.dumps(native))
        self.setting({'image': 'file:///still.png'})
        self.assertEqual(self.sync_worker(worker)['result']['screens'], [])
        native = json.loads(config.read_text())['steamuser']['general']
        self.assertEqual(native['user'], {'playbacksleep': 'stop', 'fps': 30})
        self.assertIn('Monitor0', native['wallpaperconfig']['selectedwallpapers'])
        self.assertFalse(engine.native_playback_policy_file().exists())

    def test_controller_crash_does_not_lose_native_playback_preferences(self):
        config = self.engine_executable.parent / 'config.json'
        config.write_text(
            json.dumps({'steamuser': {'general': {'user': {'playbacksleep': 'stop'}}}})
        )
        self.setting(
            {'mode': 'wallpaper_engine', 'workshop_id': '123456', 'selection': 'boot'}
        )
        environment = self.fixture_environment()
        worker = self.spawn_worker(environment)
        self.wait_worker_ready(worker)
        worker.kill()
        worker.wait(timeout=3)
        replacement = self.spawn_worker(environment)
        self.wait_worker_ready(replacement)
        self.assertEqual(
            json.loads(config.read_text())['steamuser']['general']['user'][
                'playbacksleep'
            ],
            'run',
        )
        replacement.terminate()
        replacement.wait(timeout=20)
        self.assertEqual(
            json.loads(config.read_text())['steamuser']['general']['user'][
                'playbacksleep'
            ],
            'stop',
        )
        self.assertFalse(engine.native_playback_policy_file().exists())

    def test_native_playback_restore_respects_new_preference_and_missing_default(self):
        self.setting({})
        config = self.engine_executable.parent / 'config.json'
        for original in ({}, {'playbacksleep': 'stop'}, {'playbacksleep': 'run'}):
            config.write_text(
                json.dumps({'steamuser': {'general': {'user': original}}})
            )
            engine.install_native_playback_policy(self.engine_executable)
            engine.restore_native_playback_policy()
            self.assertEqual(
                json.loads(config.read_text())['steamuser']['general']['user'], original
            )
        engine.install_native_playback_policy(
            self.engine_executable
        )  # Already run; no override.
        engine.restore_native_playback_policy()
        self.assertFalse(engine.native_playback_policy_file().exists())
        config.write_text(
            json.dumps({'steamuser': {'general': {'user': {'playbacksleep': 'stop'}}}})
        )
        engine.install_native_playback_policy(self.engine_executable)
        config.write_text(
            json.dumps({'steamuser': {'general': {'user': {'playbacksleep': 'pause'}}}})
        )
        engine.restore_native_playback_policy()
        self.assertEqual(
            json.loads(config.read_text())['steamuser']['general']['user'][
                'playbacksleep'
            ],
            'pause',
        )

    def test_sleep_pauses_owned_renderer_and_wake_resumes_without_reloading(self):
        self.setting(
            {'mode': 'wallpaper_engine', 'workshop_id': '123456', 'selection': 'boot'}
        )
        worker = self.spawn_worker(self.fixture_environment())
        self.wait_worker_ready(worker)
        renderer = json.loads((self.root / 'pids.json').read_text())[1]
        sleeping = [{'name': 'TEST', 'id': 0, 'dpmsStatus': False}]
        for _ in range(2):
            self.assertEqual(
                self.sync_worker(worker, monitors=sleeping)['result']['screens'], []
            )
            self.assertEqual(
                Path(f'/proc/{renderer}/stat').read_text().rsplit(')', 1)[1].split()[0],
                'T',
            )
        self.assertEqual(engine.read_state()['status'], 'waiting')
        self.assertEqual(self.sync_worker(worker)['result']['screens'], ['TEST'])
        self.assertNotEqual(
            Path(f'/proc/{renderer}/stat').read_text().rsplit(')', 1)[1].split()[0], 'T'
        )
        commands = [
            json.loads(line)['command']
            for line in (self.root / 'commands.jsonl').read_text().splitlines()
        ]
        self.assertEqual(commands, ['mute', 'set', 'play', 'mute', 'pause', 'play'])
        self.assertEqual(
            len((self.root / 'all-pids.jsonl').read_text().splitlines()), 1
        )

    def test_startup_uses_native_restored_scene_without_reloading_media(self):
        self.native_selection(
            {'Monitor0': {'file': 'Z:' + str(self.folder / 'scene.pkg')}}
        )
        self.setting(
            {'mode': 'wallpaper_engine', 'workshop_id': '123456', 'selection': 'boot'}
        )
        # A pre-existing crash from yesterday does not prevent a new launch.
        (self.engine_executable.parent / 'wallpaper64_old.mdmp').write_bytes(b'old')
        worker = self.spawn_worker(self.fixture_environment())
        self.wait_worker_ready(worker)
        commands = [
            json.loads(line)['command']
            for line in (self.root / 'commands.jsonl').read_text().splitlines()
        ]
        self.assertEqual(commands, ['mute', 'play', 'mute'])

    def test_native_selection_skips_only_matching_slots_and_assets(self):
        for kind, asset in (
            ('scene', 'scene.pkg'),
            ('video', 'movie.mp4'),
            ('web', 'index.html'),
        ):
            with self.subTest(kind=kind):
                metadata = {
                    'type': kind,
                    'file': 'scene.json' if kind == 'scene' else asset,
                }
                self.project.write_text(json.dumps(metadata))
                self.native_selection(
                    {
                        'Monitor0': {'file': 'Z:' + str(self.folder / asset)},
                        'Monitor1': {'file': 'Z:' + str(self.folder / 'different.mp4')},
                    }
                )
                environment = {'WALLPIPER_WE_EXE': str(self.engine_executable)}
                with patch.object(engine, 'control') as control:
                    engine.apply_project('123456', 2, environment, restored=True)
                self.assertEqual(
                    [call.args for call in control.call_args_list],
                    [('set', str(self.project), 1)],
                )
        for native in ('bad json', '[]', '{}', '{"steamuser": null}'):
            (self.engine_executable.parent / 'config.json').write_text(native)
            with patch.object(engine, 'control') as control:
                engine.apply_project('123456', 1, environment, restored=True)
            self.assertEqual(control.call_count, 1)

    def test_saved_selection_without_frames_still_loads_the_project(self):
        self.native_selection(
            {'Monitor0': {'file': 'Z:' + str(self.folder / 'scene.pkg')}}
        )
        (self.root / 'require-first-set').touch()
        self.setting(
            {'mode': 'wallpaper_engine', 'workshop_id': '123456', 'selection': 'boot'}
        )
        worker = self.spawn_worker(self.fixture_environment())
        self.wait_worker_ready(worker)
        commands = [
            json.loads(line)['command']
            for line in (self.root / 'commands.jsonl').read_text().splitlines()
        ]
        self.assertEqual(commands, ['mute', 'set', 'play', 'mute'])

    def test_recreated_portal_does_not_reload_the_wallpaper(self):
        self.setting(
            {'mode': 'wallpaper_engine', 'workshop_id': '123456', 'selection': 'boot'}
        )
        worker = self.spawn_worker(self.fixture_environment())
        self.wait_worker_ready(worker)
        initial = (self.root / 'commands.jsonl').read_text()
        (self.root / 'surface-address').write_text('replacement-surface')
        self.assertEqual(self.sync_worker(worker)['result']['screens'], ['TEST'])
        self.assertEqual((self.root / 'commands.jsonl').read_text(), initial)

    def test_new_native_crash_stops_retrying_and_survives_controller_reload(self):
        environment = dict(self.fixture_environment(), ENGINE_FIXTURE_CRASH='1')
        self.setting(
            {'mode': 'wallpaper_engine', 'workshop_id': '123456', 'selection': 'boot'}
        )
        worker = self.spawn_worker(environment)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = self.sync_worker(worker)['result']
            if result.get('error'):
                break
            time.sleep(0.05)
        self.assertIn('Wallpaper Engine crashed', result['error'])
        self.assertIn('wallpaper64_fixture.mdmp', result['error'])
        self.assertFalse(
            any(
                engine.process_identity(pid)
                for pid in json.loads((self.root / 'pids.json').read_text())
            )
        )
        self.assertIn(
            'Wallpaper Engine crashed', self.sync_worker(worker)['result']['error']
        )
        with patch.dict(os.environ, environment):
            status = engine.installation_status(engine.clean_item({'id': '123456'}))
        self.assertTrue(status['ready'])
        self.assertIn('Wallpaper Engine crashed', status['message'])
        worker.terminate()
        worker.wait(timeout=20)
        replacement = self.spawn_worker(environment)
        self.assertIn(
            'Wallpaper Engine crashed', self.sync_worker(replacement)['result']['error']
        )
        self.assertEqual(
            len((self.root / 'all-pids.jsonl').read_text().splitlines()), 1
        )
        # Explicit Apply changes the selection, resets failure, and ignores old dumps.
        self.setting(
            {'mode': 'wallpaper_engine', 'workshop_id': '123456', 'selection': 'retry'}
        )
        self.wait_worker_ready(replacement)
        self.assertEqual(
            len((self.root / 'all-pids.jsonl').read_text().splitlines()), 2
        )

    def test_proton_resolution_rejects_non_executable_and_searches_extra_libraries(
        self,
    ):
        proton = self.root / 'Steam/steamapps/common/Proton Fixture/proton'
        proton.chmod(0o600)
        self.assertIsNone(engine.proton_executable())
        extra = self.root / 'extra'
        custom = extra / 'compatibilitytools.d/GE-Proton11/proton'
        custom.parent.mkdir(parents=True)
        custom.write_bytes(b'fixture')
        custom.chmod(0o755)
        self.setting({})
        (engine.config_dir() / 'pictures.json').write_text(
            json.dumps({'wallpaper_engine': {'library_paths': [str(extra)]}})
        )
        self.assertEqual(engine.proton_executable(), custom)
        with patch.dict(os.environ, {'WALLPIPER_PROTON_BIN': str(proton)}):
            self.assertIsNone(engine.proton_executable())

    def test_transient_compositor_errors_recover_without_restarting_daemon(self):
        self.setting(
            {'mode': 'wallpaper_engine', 'workshop_id': '123456', 'selection': 'first'}
        )
        runtime = engine.Runtime()
        self.addCleanup(runtime.close)
        with (
            patch.object(
                runtime,
                'sync_engine',
                side_effect=[
                    engine.TransientError('IPC unavailable'),
                    {'screens': ['TEST']},
                ],
            ),
            patch.object(runtime, 'stop') as stop,
        ):
            self.assertTrue(runtime.sync({})['recovering'])
            self.assertEqual(engine.read_state()['status'], 'recovering')
            self.assertEqual(runtime.sync({})['screens'], ['TEST'])
            self.assertIsNone(runtime.transient_since)
            stop.assert_not_called()

    def test_persistent_failures_have_bounded_restart_budget(self):
        self.setting(
            {'mode': 'wallpaper_engine', 'workshop_id': '123456', 'selection': 'first'}
        )
        runtime = engine.Runtime()
        self.addCleanup(runtime.close)
        with (
            patch.object(
                runtime,
                'sync_engine',
                side_effect=engine.TransientError('IPC unavailable'),
            ),
            patch.object(engine.time, 'monotonic', return_value=100),
        ):
            runtime.sync({})
            for attempt in range(engine.MAX_RESTARTS):
                runtime.restart_at = 0
                runtime.transient_since = 0
                self.assertTrue(runtime.sync({})['recovering'])
                self.assertEqual(runtime.restarts, attempt + 1)
                self.assertEqual(runtime.restart_at, 100 + 2**attempt)
            runtime.restart_at = 0
            runtime.transient_since = 0
            result = runtime.sync({})
            self.assertIn('IPC unavailable', result['error'])
            self.assertEqual(engine.read_state()['status'], 'error')
        self.assertIn('IPC unavailable', runtime.sync({})['error'])
        self.setting(
            {'mode': 'wallpaper_engine', 'workshop_id': '123456', 'selection': 'second'}
        )
        with patch.object(runtime, 'sync_engine', return_value={'screens': ['TEST']}):
            self.assertEqual(runtime.sync({})['screens'], ['TEST'])
        self.assertEqual(runtime.restarts, 0)

    def test_healthy_runtime_regains_restart_budget(self):
        self.setting(
            {'mode': 'wallpaper_engine', 'workshop_id': '123456', 'selection': 'first'}
        )
        with patch.dict(os.environ, self.fixture_environment()):
            runtime = engine.Runtime()
            self.addCleanup(runtime.close)
            request = {'monitors': [{'name': 'TEST', 'id': 0}], 'clients': []}
            deadline = time.monotonic() + 10
            while not runtime.sync(request)['screens'] and time.monotonic() < deadline:
                time.sleep(0.05)
            runtime.restarts = engine.MAX_RESTARTS - 1
            runtime.sync(request)
            self.assertEqual(runtime.restarts, engine.MAX_RESTARTS - 1)
            runtime.started_at -= engine.HEALTHY_SECONDS + 1
            self.assertEqual(runtime.sync(request)['screens'], ['TEST'])
            self.assertEqual(runtime.restarts, 0)

    def test_absent_or_sleeping_outputs_do_not_start_or_fail_renderer(self):
        self.setting(
            {'mode': 'wallpaper_engine', 'workshop_id': '123456', 'selection': 'first'}
        )
        runtime = engine.Runtime()
        self.addCleanup(runtime.close)
        with patch.object(runtime, 'start') as start:
            for monitors in (
                [],
                [{'name': 'TEST', 'dpmsStatus': False}],
                [{'name': 'TEST', 'disabled': True}],
            ):
                self.assertEqual(runtime.sync({'monitors': monitors}), {'screens': []})
                self.assertEqual(engine.read_state()['status'], 'waiting')
            start.assert_not_called()

    def test_sigkill_recovery_reaps_stopped_helpers_and_preserves_other_sessions(self):
        environment = self.fixture_environment()
        self.setting(
            {
                'mode': 'wallpaper_engine',
                'workshop_id': '123456',
                'selection': 'restore',
            }
        )
        worker = self.spawn_worker(environment)
        unrelated = subprocess.Popen(
            [sys.executable, '-c', 'import time;time.sleep(300)'],
            env=dict(os.environ, DESKTOP_WALLPAPER_OWNER='a' * 32),
        )

        def cleanup_unrelated():
            unrelated.kill()
            unrelated.wait(timeout=3)

        self.addCleanup(cleanup_unrelated)
        self.wait_worker_ready(worker)
        pids = json.loads((self.root / 'pids.json').read_text())
        old_owner = json.loads(
            (engine.config_dir() / '.engine-ownership.json').read_text()
        )['owner']
        self.addCleanup(engine.reap_owned, old_owner)
        self.sync_worker(
            worker, [{'monitor': 0, 'workspace': {'id': 1}, 'fullscreen': 2}]
        )
        self.assertEqual(
            Path(f'/proc/{pids[1]}/stat').read_text().rsplit(')', 1)[1].split()[0], 'T'
        )
        worker.kill()
        worker.wait(timeout=3)
        # The daemon follows its worker; detached helpers wait for the next runtime.
        deadline = time.monotonic() + 3
        while engine.process_identity(pids[0]) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(engine.process_identity(pids[0]))
        self.assertTrue(engine.process_identity(pids[1]))
        replacement = self.spawn_worker(environment)
        self.wait_worker_ready(replacement)
        self.assertFalse(any(engine.process_identity(pid) for pid in pids))
        self.assertIsNone(unrelated.poll())
        replacement.terminate()
        replacement.wait(timeout=20)
        self.assertFalse((engine.config_dir() / '.engine-ownership.json').exists())

    def test_static_startup_reconciles_orphans_even_with_new_runtime_directory(self):
        environment = self.fixture_environment()
        self.setting(
            {
                'mode': 'wallpaper_engine',
                'workshop_id': '123456',
                'selection': 'restore',
            }
        )
        worker = self.spawn_worker(environment)
        self.wait_worker_ready(worker)
        pids = json.loads((self.root / 'pids.json').read_text())
        owner = json.loads(
            (engine.config_dir() / '.engine-ownership.json').read_text()
        )['owner']
        self.addCleanup(engine.reap_owned, owner)
        worker.kill()
        worker.wait(timeout=3)
        self.setting({'image': 'file:///still.png'})
        replacement = self.spawn_worker(
            dict(environment, XDG_RUNTIME_DIR=str(self.root / 'new-runtime'))
        )
        self.assertEqual(self.sync_worker(replacement)['result'], {'screens': []})
        self.assertFalse(any(engine.process_identity(pid) for pid in pids))
        replacement.terminate()
        replacement.wait(timeout=20)

    def test_provider_search_and_favorites_keep_identity_without_accepting_paths(self):
        catalog = pictures.run({'op': 'providers'})['providers']
        self.assertEqual(
            next(p for p in catalog if p['id'] == 'wallpaper_engine')['name'],
            'Wallpaper Engine',
        )
        item = pictures.run(
            {'op': 'browse', 'provider': 'wallpaper_engine', 'query': 'cloud'}
        )['items'][0]
        self.assertEqual(item['preview'], (self.folder / 'preview.png').as_uri())
        pictures.run(
            {
                'op': 'favorite',
                'wallpaper': dict(item, path='file:///etc/passwd'),
                'favorite': True,
            }
        )
        saved = pictures.run({'op': 'browse', 'favorites': True})['items'][0]
        self.assertEqual(saved['path'], item['path'])
        self.project.unlink()
        saved = pictures.run({'op': 'browse', 'favorites': True})['items'][0]
        self.assertFalse(saved['installed'])
        self.assertEqual(saved['title'], 'Clouds')
        self.assertEqual(saved['path'], '')

    def test_preview_traversal_and_symlink_projects_are_rejected(self):
        outside = self.root / 'outside.png'
        outside.write_bytes(b'outside')
        self.project.write_text(json.dumps({'preview': str(outside)}))
        self.assertEqual(engine.browse({})['items'][0]['preview'], '')
        self.project.unlink()
        self.project.symlink_to(outside)
        self.assertEqual(engine.browse({})['items'], [])
        self.assertIsNone(engine.clean_item({'id': '../../etc/passwd'}))

    def test_extra_steam_libraries_are_discovered(self):
        extra = self.root / 'another library'
        folder = extra / 'steamapps/workshop/content/431960/654321'
        folder.mkdir(parents=True)
        (folder / 'project.json').write_text('{"title":"Forest"}')
        (self.root / 'Steam/steamapps/libraryfolders.vdf').write_text(
            '"libraryfolders" { "1" { "path" "' + str(extra) + '" } }'
        )
        self.assertEqual(
            {item['id'] for item in engine.browse({})['items']}, {'123456', '654321'}
        )

    def test_search_combines_metadata_with_type_tag_and_sort_filters_without_runtime(
        self,
    ):
        self.project.write_text(
            json.dumps(
                {
                    'title': 'Clouds',
                    'type': 'scene',
                    'description': 'A peaceful sunrise',
                    'tags': ['Relaxing', 'Nature', 'nature', 5],
                }
            )
        )
        other = self.folder.parent / '654321'
        other.mkdir()
        (other / 'project.json').write_text(
            json.dumps({'title': 'Aurora', 'type': 'video', 'tags': ['Nature']})
        )
        with (
            patch.object(engine, 'control') as control,
            patch.object(engine.subprocess, 'Popen') as spawn,
        ):
            descriptor = pictures.run({'op': 'providers'})['providers'][-1]
            self.assertEqual(
                [entry['value'] for entry in descriptor['filters'][1]['options']],
                ['', 'nature', 'relaxing'],
            )
            request = {'op': 'browse', 'provider': 'wallpaper_engine'}
            self.assertEqual(
                [
                    item['id']
                    for item in pictures.run(dict(request, query='SUNRISE'))['items']
                ],
                ['123456'],
            )
            self.assertEqual(
                [
                    item['id']
                    for item in pictures.run(dict(request, query='relaxing'))['items']
                ],
                ['123456'],
            )
            self.assertEqual(
                [
                    item['id']
                    for item in pictures.run(
                        dict(request, filters={'type': 'video', 'tag': 'Nature'})
                    )['items']
                ],
                ['654321'],
            )
            self.assertEqual(
                pictures.run(
                    dict(request, filters={'type': 'video', 'tag': 'relaxing'})
                )['items'],
                [],
            )
            self.assertEqual(
                [
                    item['title']
                    for item in pictures.run(
                        dict(request, filters={'sorting': 'title_desc'})
                    )['items']
                ],
                ['Clouds', 'Aurora'],
            )
            self.assertEqual(
                len(
                    pictures.run(
                        dict(request, filters={'type': 'invalid', 'sorting': 'invalid'})
                    )['items']
                ),
                2,
            )
        control.assert_not_called()
        spawn.assert_not_called()

    def test_fullscreen_excludes_maximized_hidden_workspaces_and_dpms_off(self):
        monitors = [
            {'id': 0, 'activeWorkspace': {'id': 1}, 'specialWorkspace': {'id': 0}}
        ]
        client = {'monitor': 0, 'workspace': {'id': 1}, 'fullscreen': 2, 'mapped': True}
        self.assertTrue(engine.visible_fullscreen(monitors, [client]))
        for change in (
            {'fullscreen': 1},
            {'hidden': True},
            {'mapped': False},
            {'workspace': {'id': 2}},
        ):
            self.assertFalse(
                engine.visible_fullscreen(monitors, [dict(client, **change)])
            )
        self.assertFalse(
            engine.visible_fullscreen([dict(monitors[0], dpmsStatus=False)], [client])
        )
        special = [dict(monitors[0], specialWorkspace={'id': -99})]
        self.assertFalse(engine.visible_fullscreen(special, [client]))
        self.assertTrue(
            engine.visible_fullscreen(special, [dict(client, workspace={'id': -99})])
        )

    def test_workshop_reuses_games_key_filters_cursor_and_preserves_remote_favorites(
        self,
    ):
        folder = engine.config_dir()
        folder.mkdir(parents=True)
        (folder.parent / 'games').mkdir(exist_ok=True)
        (folder.parent / 'games/games.json').write_text(
            '{"steam_api_key":"private-test-key"}'
        )
        data = {
            'response': {
                'total': 50,
                'next_cursor': 'opaque+cursor/==',
                'publishedfiledetails': [
                    {
                        'result': 1,
                        'consumer_appid': 431960,
                        'publishedfileid': '999999',
                        'title': 'Forest',
                        'short_description': 'Morning birds',
                        'preview_url': 'https://images.steamusercontent.com/ugc/123/preview/',
                        'tags': [{'tag': 'Scene'}, {'tag': 'Nature'}],
                    },
                    {
                        'result': 1,
                        'consumer_appid': 123,
                        'publishedfileid': '888888',
                        'title': 'Other app',
                    },
                ],
            }
        }
        request = {
            'op': 'browse',
            'provider': 'wallpaper_engine',
            'query': 'forest',
            'page': 'previous+cursor/==',
            'filters': {
                'source': 'workshop',
                'type': 'scene',
                'workshopTag': 'Nature',
                'workshopSort': 'newest',
            },
        }
        with (
            patch.object(
                workshop, 'urlopen', return_value=io.BytesIO(json.dumps(data).encode())
            ) as http,
            patch.object(engine, 'control') as control,
            patch.object(engine.subprocess, 'Popen') as spawn,
        ):
            self.assertEqual(
                engine.descriptor()['defaultFilters']['source'], 'workshop'
            )
            result = pictures.run(request)
            params = parse_qs(urlparse(http.call_args.args[0].full_url).query)
            self.assertEqual(params['key'], ['private-test-key'])
            query = json.loads(params['input_json'][0])
            self.assertEqual(query['cursor'], request['page'])
            self.assertEqual(query['requiredtags'], ['Everyone', 'Scene', 'Nature'])
            self.assertEqual(query['query_type'], 1)
            self.assertEqual(query['appid'], 431960)
            self.assertTrue(query['return_previews'])
            self.assertEqual(result['next'], 'opaque+cursor/==')
            self.assertEqual([item['id'] for item in result['items']], ['999999'])
            item = result['items'][0]
            self.assertFalse(item['installed'])
            self.assertNotIn('private-test-key', json.dumps(result))
            pictures.run({'op': 'favorite', 'wallpaper': item, 'favorite': True})
            saved = pictures.run({'op': 'browse', 'favorites': True, 'query': 'birds'})[
                'items'
            ][0]
            self.assertEqual(saved['preview'], item['preview'])
            self.assertEqual(saved['url'], item['url'])
            self.assertEqual(
                pictures.run(
                    {
                        'op': 'browse',
                        'provider': 'wallpaper_engine',
                        'filters': {'source': 'installed'},
                    }
                )['items'][0]['id'],
                '123456',
            )
            self.assertEqual(http.call_count, 1)
        control.assert_not_called()
        spawn.assert_not_called()

    def test_workshop_missing_key_errors_are_redacted_and_previews_are_restricted(self):
        with patch.object(workshop, 'urlopen') as http:
            with self.assertRaisesRegex(ValueError, 'steam_api_key'):
                engine.browse({'filters': {'source': 'workshop'}})
            http.assert_not_called()
        for value in (
            'file:///etc/passwd',
            'https://example.com/image.png',
            'https://images.steamusercontent.com.evil.test/a',
            'https://user@images.steamusercontent.com/a',
            'http://images.steamusercontent.com/a',
        ):
            self.assertEqual(workshop.preview_url(value), '')
        with (
            patch.object(workshop, 'api_key', return_value='private-test-key'),
            patch.object(
                workshop,
                'urlopen',
                side_effect=HTTPError(
                    'https://test/?key=private-test-key',
                    403,
                    'private-test-key',
                    {},
                    None,
                ),
            ),
        ):
            with self.assertRaisesRegex(ValueError, 'Steam rejected') as error:
                engine.browse({'filters': {'source': 'workshop'}})
            self.assertNotIn('private-test-key', str(error.exception))

    def test_workshop_installed_item_uses_local_metadata_and_rejects_bad_response(self):
        data = {
            'response': {
                'publishedfiledetails': [
                    {
                        'result': 1,
                        'consumer_appid': 431960,
                        'publishedfileid': '123456',
                        'title': 'Remote title',
                        'preview_url': 'file:///etc/passwd',
                    }
                ],
                'next_cursor': '*',
            }
        }
        with (
            patch.object(workshop, 'api_key', return_value='key'),
            patch.object(
                workshop, 'urlopen', return_value=io.BytesIO(json.dumps(data).encode())
            ),
        ):
            result = engine.browse({'filters': {'source': 'workshop'}})
            self.assertTrue(result['items'][0]['installed'])
            self.assertEqual(result['items'][0]['title'], 'Clouds')
            self.assertEqual(
                result['items'][0]['preview'], (self.folder / 'preview.png').as_uri()
            )
            self.assertEqual(result['next'], 0)
        with (
            patch.object(workshop, 'api_key', return_value='key'),
            patch.object(
                workshop,
                'urlopen',
                return_value=io.BytesIO(b'{"response":{"publishedfiledetails":false}}'),
            ),
        ):
            with self.assertRaisesRegex(ValueError, 'unexpected'):
                engine.browse({'filters': {'source': 'workshop'}})

    def test_workshop_full_stills_are_separate_from_thumbnails_and_survive_favorites(
        self,
    ):
        primary = 'https://images.steamusercontent.com/ugc/123/primary/?imw=200&imh=200'
        original = 'https://images.steamusercontent.com/ugc/123/still/'
        row = {
            'result': 1,
            'consumer_appid': 431960,
            'publishedfileid': '999999',
            'title': 'Forest',
            'preview_url': primary,
            'previews': [
                {'preview_type': 1, 'youtubevideoid': 'video'},
                {'preview_type': 0, 'url': 'file:///etc/passwd'},
                {'preview_type': 0, 'url': original + '?imw=128&imh=128'},
            ],
        }
        with patch.object(workshop, 'query', return_value=([row], 0, 1)):
            item = pictures.run(
                {
                    'op': 'browse',
                    'provider': 'wallpaper_engine',
                    'filters': {'source': 'workshop'},
                }
            )['items'][0]
        self.assertEqual(item['path'], original)
        self.assertEqual(item['thumbLarge'], item['preview'])
        self.assertIn('imw=400', item['preview'])
        self.assertNotEqual(item['path'], item['preview'])
        pictures.run({'op': 'favorite', 'wallpaper': item, 'favorite': True})
        favorite = pictures.run({'op': 'browse', 'favorites': True})['items'][0]
        self.assertEqual(favorite['path'], original)
        self.assertEqual(favorite['preview'], item['preview'])
        self.assertEqual(
            workshop.full_preview(
                {'preview_url': primary, 'previews': [{'preview_type': 1}]}
            ),
            workshop.original_preview(primary),
        )
        self.assertEqual(
            workshop.full_preview({'preview_url': primary, 'previews': None}),
            workshop.original_preview(primary),
        )

    def test_workshop_page_invokes_steam_directly_and_reports_launch_errors(self):
        with (
            patch.object(engine.shutil, 'which', return_value='/test/steam'),
            patch.object(engine.subprocess, 'Popen') as spawn,
            patch.object(engine, 'control') as control,
        ):
            spawn.return_value.wait.return_value = 0
            result = pictures.run(
                {'op': 'openWorkshop', 'id': 7, 'workshopId': '999999'}
            )
            self.assertIn('Subscribe', result['message'])
            self.assertEqual(
                spawn.call_args.args[0],
                [
                    '/test/steam',
                    'steam://openurl/https://steamcommunity.com/sharedfiles/filedetails/?id=999999',
                ],
            )
            self.assertTrue(spawn.call_args.kwargs['start_new_session'])
            spawn.reset_mock()
            with self.assertRaisesRegex(ValueError, 'Invalid Steam Workshop'):
                pictures.run({'op': 'openWorkshop', 'workshopId': '999999&other=1'})
            spawn.assert_not_called()
            spawn.return_value.wait.return_value = 1
            with self.assertRaisesRegex(ValueError, 'could not open'):
                pictures.run({'op': 'openWorkshop', 'workshopId': '999999'})
            spawn.side_effect = OSError()
            with self.assertRaisesRegex(ValueError, 'could not open'):
                pictures.run({'op': 'openWorkshop', 'workshopId': '999999'})
            control.assert_not_called()
        with patch.object(engine.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'PATH'):
                pictures.run({'op': 'openWorkshop', 'workshopId': '999999'})

    def test_installation_status_reports_missing_setup_and_rechecks_completed_download(
        self,
    ):
        self.engine_executable.unlink()
        item = {
            'provider': 'wallpaper_engine',
            'id': '999999',
            'title': 'Subscribed wallpaper',
        }
        with (
            patch.object(engine.shutil, 'which', return_value=None),
            patch.object(engine.subprocess, 'Popen') as spawn,
            patch.object(engine, 'hypr_query') as hypr,
        ):
            status = pictures.run({'op': 'installationStatus', 'wallpaper': item})
            self.assertFalse(status['ready'])
            self.assertFalse(status['wallpaper']['installed'])
            self.assertIn('Install Wallpaper Engine in Steam', status['message'])
            self.assertIn('paru -S wallpiper-hyprland', status['message'])
            self.assertIn('not downloaded', status['message'])
            with self.assertRaisesRegex(
                ValueError, 'Install Wallpaper Engine in Steam'
            ):
                pictures.run({'op': 'set', 'wallpaper': item})
            spawn.assert_not_called()
            hypr.assert_not_called()
        self.engine_executable.write_bytes(b'fixture')
        downloaded = self.folder.parent / '999999'
        downloaded.mkdir()
        (downloaded / 'project.json').write_text(
            '{"title":"Subscribed wallpaper","type":"scene"}'
        )
        with (
            patch.object(engine.shutil, 'which', return_value='fixture'),
            patch.object(engine.subprocess, 'Popen') as spawn,
        ):
            status = pictures.run({'op': 'installationStatus', 'wallpaper': item})
            self.assertTrue(status['ready'])
            self.assertTrue(status['wallpaper']['installed'])
            self.assertEqual(status['message'], '')
            spawn.assert_not_called()

    def test_current_distribution_layout_is_detected_and_passed_to_daemon(self):
        renderer = self.engine_executable.parent / 'distribution/wallpaper64.exe'
        renderer.parent.mkdir()
        self.engine_executable.rename(renderer)
        self.assertEqual(engine.engine_executable(), renderer)
        with patch.object(engine.shutil, 'which', return_value='fixture'):
            status = engine.installation_status(engine.clean_item({'id': '123456'}))
            self.assertTrue(status['ready'])
            runtime = engine.Runtime()
            self.addCleanup(runtime.close)
            with (
                patch.object(engine, 'existing_engine', return_value=False),
                patch.object(engine.subprocess, 'Popen') as spawn,
            ):
                runtime.start()
                self.assertEqual(
                    spawn.call_args.kwargs['env']['WALLPIPER_WE_EXE'],
                    str(self.engine_executable),
                )
                self.assertEqual(
                    spawn.call_args.kwargs['env']['WALLPIPER_FORCE_LINEAR'], '1'
                )
                runtime.daemon = None
                runtime.log.close()

    def test_picker_with_exited_main_thread_is_owned_and_removed(self):
        # Reproduce Wine/Chromium's live thread group with a zombie main thread.
        script = self.root / 'picker.py'
        script.write_text(
            'import ctypes,threading,time\n'
            'libc=ctypes.CDLL(None)\n'
            'def ui():\n'
            ' libc.prctl(15,b"wallpaperui.exe",0,0,0)\n'
            ' time.sleep(300)\n'
            'threading.Thread(target=ui).start()\n'
            'libc.pthread_exit(None)\n'
        )
        owned = subprocess.Popen(
            [sys.executable, str(script)],
            env=dict(os.environ, DESKTOP_WALLPAPER_OWNER='fixture-picker'),
        )
        unrelated = subprocess.Popen(
            [sys.executable, str(script)],
            env=dict(os.environ, DESKTOP_WALLPAPER_OWNER='other-session'),
        )

        def cleanup():
            for process in (owned, unrelated):
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=3)

        self.addCleanup(cleanup)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = (
                Path(f'/proc/{owned.pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
            )
            if status == 'Z':
                break
            time.sleep(0.01)
        self.assertEqual(status, 'Z')
        self.assertTrue(engine.process_identity(owned.pid))
        self.assertIn(owned.pid, engine.owned_processes('fixture-picker'))
        engine.dismiss_owned_picker(engine.owned_processes('fixture-picker'))
        self.assertEqual(owned.wait(timeout=3), -9)
        self.assertIsNone(unrelated.poll())
        self.assertTrue(engine.process_identity(unrelated.pid))

    def test_owned_chromium_web_renderer_is_not_a_picker(self):
        process = subprocess.Popen(
            [
                sys.executable,
                '-c',
                'import ctypes,time; ctypes.CDLL(None).prctl(15,b"CrBrowserMain",0,0,0); time.sleep(300)',
            ],
            env=dict(os.environ, DESKTOP_WALLPAPER_OWNER='fixture-web'),
        )

        def cleanup():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)

        self.addCleanup(cleanup)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if Path(f'/proc/{process.pid}/comm').read_text().strip() == 'CrBrowserMain':
                break
            time.sleep(0.01)
        engine.dismiss_owned_picker(engine.owned_processes('fixture-web'))
        self.assertIsNone(process.poll())

    def test_renderer_manifest_and_explicit_override(self):
        moved = self.engine_executable.parent.with_name('Wallpaper Engine')
        self.engine_executable.parent.rename(moved)
        manifest = self.root / 'Steam/steamapps/appmanifest_431960.acf'
        manifest.write_text('"AppState" { "installdir" "Wallpaper Engine" }')
        self.assertEqual(engine.engine_executable(), moved / 'wallpaper64.exe')
        with patch.dict(
            os.environ, {'WALLPIPER_WE_EXE': str(moved / 'wallpaper64.exe')}
        ):
            self.assertEqual(engine.engine_executable(), moved / 'wallpaper64.exe')
        with patch.dict(os.environ, {'WALLPIPER_WE_EXE': str(moved / 'missing.exe')}):
            self.assertIsNone(engine.engine_executable())
        manifest.write_text('"AppState" { "installdir" "../../../../outside" }')
        self.assertIsNone(engine.engine_executable())

    def test_missing_proton_warning_and_provider_only_configuration(self):
        proton = self.root / 'Steam/steamapps/common/Proton Fixture/proton'
        proton.unlink()
        item = engine.clean_item({'id': '123456'})
        with (
            patch.object(engine.shutil, 'which', return_value='fixture'),
            patch.object(engine.subprocess, 'Popen') as spawn,
        ):
            status = engine.installation_status(item)
            self.assertFalse(status['ready'])
            self.assertIn('Proton is not installed', status['message'])
            engine.config_dir().mkdir(parents=True, exist_ok=True)
            custom = self.root / 'GE-Proton/proton'
            custom.parent.mkdir()
            custom.write_bytes(b'fixture')
            custom.chmod(0o755)
            (engine.config_dir() / 'pictures.json').write_text(
                json.dumps({'wallpaper_engine': {'proton_bin': str(custom)}})
            )
            self.assertTrue(engine.installation_status(item)['ready'])
            self.assertEqual(engine.configured_proton(), str(custom))
            spawn.assert_not_called()

    def test_background_surface_verification(self):
        surface = {
            'namespace': 'wallpiper-portal-hyprland',
            'w': 1920,
            'h': 1080,
            'address': 'abc',
        }
        self.assertEqual(
            engine.portal_surfaces({'TEST': {'levels': {'0': [surface]}}}),
            {'TEST': ['abc']},
        )
        self.assertFalse(engine.portal_surfaces({'TEST': {'levels': {'2': [surface]}}}))
        self.assertFalse(
            engine.portal_surfaces({'TEST': {'levels': {'0': [dict(surface, w=0)]}}})
        )
        transparent = {'TEST': {'levels': {'0': [dict(surface, alpha=0)]}}}
        self.assertFalse(engine.portal_surfaces(transparent))
        self.assertTrue(engine.portal_surfaces(transparent, visible_only=False))

    def test_static_runtime_never_starts_or_queries_wallpiper(self):
        self.setting({'image': 'file:///still.png'})
        runtime = engine.Runtime()
        self.addCleanup(runtime.close)
        with (
            patch.object(runtime, 'start') as start,
            patch.object(engine, 'hypr_query') as query,
        ):
            self.assertEqual(runtime.sync({}), {'screens': []})
        start.assert_not_called()
        query.assert_not_called()

    def test_still_wallpaper_does_not_check_steam_only_requirements(self):
        item = {
            'provider': 'wallhaven',
            'id': 'fixture',
            'path': 'https://w.wallhaven.cc/full/fi/wallhaven-fixture.png',
        }
        with (
            patch.object(
                pictures, 'download_wallpaper', return_value=self.folder / 'preview.png'
            ),
            patch.object(
                engine,
                'installation_status',
                side_effect=AssertionError('Steam setup checked for still image'),
            ),
            patch.object(engine.subprocess, 'Popen') as spawn,
        ):
            result = pictures.run({'op': 'set', 'wallpaper': item})
            self.assertEqual(result['service'], 'desktop shell')
            self.assertNotEqual(engine.read_setting().get('mode'), 'wallpaper_engine')
            spawn.assert_not_called()

    def test_apply_failure_restores_static_setting(self):
        previous = {'image': 'file:///still.png'}
        self.setting(previous)

        def failure():
            return {
                'selection': engine.read_setting().get('selection'),
                'status': 'error',
                'error': 'bad Proton',
            }

        with (
            patch.object(engine.shutil, 'which', return_value='fixture'),
            patch.object(engine, 'hypr_query', return_value=[]),
            patch.object(engine, 'read_state', side_effect=failure),
        ):
            with self.assertRaisesRegex(ValueError, 'bad Proton'):
                engine.apply(engine.browse({})['items'][0])
        self.assertEqual(engine.read_setting(), previous)

    def test_apply_failure_does_not_automatically_relaunch_previous_animated_choice(
        self,
    ):
        previous = {
            'mode': 'wallpaper_engine',
            'workshop_id': '123456',
            'selection': 'boot',
            'image': 'file:///still.png',
        }
        self.setting(previous)

        def failure():
            return {
                'selection': engine.read_setting().get('selection'),
                'status': 'error',
                'error': 'native crash',
            }

        with (
            patch.object(engine.shutil, 'which', return_value='fixture'),
            patch.object(engine, 'hypr_query', return_value=[]),
            patch.object(engine, 'read_state', side_effect=failure),
        ):
            with self.assertRaisesRegex(ValueError, 'native crash'):
                engine.apply(engine.browse({})['items'][0])
        self.assertNotEqual(engine.read_setting()['selection'], 'boot')
        self.assertEqual(engine.read_setting()['image'], 'file:///still.png')

    def test_owned_daemon_helpers_stop_on_static_selection(self):
        binary = self.root / 'wallpiperd'
        pidfile = self.root / 'pids.json'
        binary.write_text(
            '#!' + sys.executable + '\n'
            'import json,os,subprocess,sys,time\nfrom pathlib import Path\n'
            'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(300)"],start_new_session=True)\n'
            'open(os.environ["ENGINE_TEST_PIDS"],"w").write(json.dumps([os.getpid(),child.pid]))\n'
            'time.sleep(0.15)\n'
            'folder=Path(os.environ["WALLPIPER_TEMP_DIR"]);folder.mkdir(parents=True,exist_ok=True)\n'
            '(folder/"wallpiper-renderer-pid").write_text(str(child.pid))\n'
            'time.sleep(300)\n'
        )
        binary.chmod(0o755)
        monitors = [{'name': 'TEST', 'id': 0, 'activeWorkspace': {'id': 1}}]
        surface = {
            'TEST': {
                'levels': {
                    '0': [{'namespace': 'wallpiper-portal-hyprland', 'w': 10, 'h': 10}]
                }
            }
        }
        self.setting(
            {'mode': 'wallpaper_engine', 'workshop_id': '123456', 'selection': 'first'}
        )
        with (
            patch.dict(os.environ, {'ENGINE_TEST_PIDS': str(pidfile)}),
            patch.object(engine, 'existing_engine', return_value=False),
            patch.object(engine.shutil, 'which', return_value=str(binary)),
            patch.object(engine, 'hypr_query', return_value=surface),
            patch.object(engine, 'control') as control,
        ):
            runtime = engine.Runtime()
            self.addCleanup(runtime.close)
            self.assertEqual(
                runtime.sync({'monitors': monitors, 'clients': []})['screens'], []
            )
            control.assert_not_called()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                result = runtime.sync({'monitors': monitors, 'clients': []})
                if result['screens']:
                    break
                time.sleep(0.02)
            self.assertEqual(result['screens'], ['TEST'])
            self.assertEqual(
                [call.args[0] for call in control.call_args_list],
                ['mute', 'set', 'play', 'mute'],
            )
            control.reset_mock()
            client = {'monitor': 0, 'workspace': {'id': 1}, 'fullscreen': 2}
            runtime.sync({'monitors': monitors, 'clients': [client]})
            self.assertTrue(runtime.suspended)
            for pid in runtime.suspended:
                self.assertEqual(
                    Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0],
                    'T',
                )
            runtime.sync({'monitors': monitors, 'clients': [client]})
            runtime.sync({'monitors': monitors, 'clients': []})
            self.assertFalse(runtime.suspended)
            self.assertEqual(
                [call.args[0] for call in control.call_args_list], ['pause', 'play']
            )
            deadline = time.monotonic() + 3
            while not pidfile.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            pids = json.loads(pidfile.read_text())
            runtime.sync({'monitors': monitors, 'clients': [client]})
            self.setting({'image': 'file:///still.png'})
            runtime.sync({})
            self.assertIsNone(runtime.daemon)
            self.assertFalse(any(engine.process_identity(pid) for pid in pids))
            self.assertEqual(engine.read_state()['status'], 'idle')

    def test_worker_shutdown_cleans_up_daemon_and_detached_helpers(self):
        binary_dir = self.root / 'bin'
        binary_dir.mkdir()
        source = Path(__file__).parent / 'fixtures/wallpaper-engine.py'
        fixture = binary_dir / 'fixture'
        shutil.copyfile(source, fixture)
        fixture.chmod(0o755)
        for command in ('hyprctl', 'wallpiperd', 'wallpiperctl'):
            (binary_dir / command).symlink_to(fixture)
        self.setting(
            {
                'mode': 'wallpaper_engine',
                'workshop_id': '123456',
                'selection': 'restore',
            }
        )
        environment = dict(
            os.environ,
            ENGINE_FIXTURE_ROOT=str(self.root),
            HYPRLAND_INSTANCE_SIGNATURE='fixture',
            PATH=str(binary_dir) + ':' + os.environ['PATH'],
        )
        worker = subprocess.Popen(
            [sys.executable, '-u', str(Path(engine.__file__).resolve())],
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 10
            ready = False
            while time.monotonic() < deadline:
                worker.stdin.write(
                    json.dumps(
                        {
                            'id': 1,
                            'op': 'sync',
                            'monitors': [
                                {'name': 'TEST', 'id': 0, 'activeWorkspace': {'id': 1}}
                            ],
                            'clients': [],
                        }
                    )
                    + '\n'
                )
                worker.stdin.flush()
                self.assertTrue(
                    select.select([worker.stdout], [], [], 5)[0],
                    'worker did not answer',
                )
                response = json.loads(worker.stdout.readline())
                if response.get('result', {}).get('screens') == ['TEST']:
                    ready = True
                    break
                time.sleep(0.05)
            self.assertTrue(ready, response)
            pids = json.loads((self.root / 'pids.json').read_text())
            worker.terminate()
            self.assertEqual(worker.wait(timeout=20), 0)
            self.assertFalse(any(engine.process_identity(pid) for pid in pids))
            self.assertEqual(engine.read_state()['status'], 'idle')
        finally:
            if worker.poll() is None:
                worker.terminate()
                worker.wait(timeout=20)
            worker.stdin.close()
            worker.stdout.close()
            worker.stderr.close()


if __name__ == '__main__':
    unittest.main()
