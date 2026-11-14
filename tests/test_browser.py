"""Browser overrides and kiosk launches with private profiles and stub processes."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import support

browser = support.load('desktop_browser', support.DESKTOP / 'ui/browser.py')
KIOSK = (
    support.REPO
    / 'modules/desktop/quickshell/symlinks/home/.local/bin/desktop-browser-kiosk'
)


class BrowserTests(unittest.TestCase):
    def test_default_shared_and_feature_commands_preserve_literal_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'browser.json'
            url = 'https://example.test/watch?title=a b&next=$(touch nope)'
            self.assertEqual(
                browser.browser_argv('movies', url, path), ['xdg-open', url]
            )
            path.write_text(
                json.dumps(
                    {
                        'command': 'firefox --kiosk "literal $HOME"',
                        'modules': {'games': ['xdg-open']},
                    }
                )
            )
            self.assertEqual(
                browser.browser_argv('movies', url, path),
                ['firefox', '--kiosk', 'literal $HOME', url],
            )
            self.assertEqual(
                browser.browser_argv('games', url, path), ['xdg-open', url]
            )
            self.assertEqual(
                browser.browser_argv('movies', url, path, 'custom --private'),
                ['custom', '--private', url],
            )
            for value in (
                [],
                {'modules': []},
                {'command': []},
                {'command': ['firefox', 1]},
                {'command': '"'},
            ):
                path.write_text(json.dumps(value))
                with self.subTest(value=value), self.assertRaises(ValueError):
                    browser.browser_argv('movies', url, path)
            for url in ('file:///tmp/example', '--flag', 'https://'):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    browser.browser_argv('movies', url, path)

    def test_kiosk_reuses_its_profile_and_setup_has_browser_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / 'chromium'
            executable.write_text(
                f'#!{sys.executable}\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n'
            )
            executable.chmod(0o700)
            env = dict(
                os.environ,
                PATH=f'{root}:{os.environ["PATH"]}',
                XDG_CONFIG_HOME=str(root / 'config with spaces'),
            )
            profile = root / 'config with spaces/quickshell/browser-profile'
            for url in (
                'https://example.test/?a=one two&x=$(literal)',
                'https://example.test/second',
            ):
                result = subprocess.run(
                    [str(KIOSK), url],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                argv = json.loads(result.stdout)
                self.assertIn(f'--user-data-dir={profile}', argv)
                self.assertIn('--app=' + url, argv)
                self.assertIn('--kiosk', argv)
                self.assertNotIn('--incognito', argv)
                if (profile / 'saved-login').exists():
                    self.assertEqual((profile / 'saved-login').read_text(), 'retained')
                (profile / 'saved-login').write_text('retained')
            result = subprocess.run(
                [str(KIOSK), '--setup'],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            argv = json.loads(result.stdout)
            self.assertIn(f'--user-data-dir={profile}', argv)
            self.assertIn('chrome://extensions', argv)
            self.assertNotIn('--kiosk', argv)


@unittest.skipUnless(support.QS, 'Quickshell is required')
class BrowserIntegrationTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_space_and_drawer_urls_use_the_configured_detached_browser(self):
        def setup(root):
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            uwsm = bin_dir / 'uwsm'
            uwsm.write_text('#!/bin/sh\nshift 4\nexec "$@"\n')
            uwsm.chmod(0o700)
            recorder = root / 'record.py'
            recorder.write_text(
                'import json,sys\nfrom pathlib import Path\nwith Path(__file__).with_name("opened").open("a") as log: log.write(json.dumps(sys.argv[1:])+"\\n")\n'
            )
            (root / 'config/quickshell/desktop/browser.json').write_text(
                json.dumps(
                    {
                        'command': [sys.executable, str(recorder), 'shared'],
                        'modules': {
                            'movies': [sys.executable, str(recorder), 'movies']
                        },
                    }
                )
            )
            os.environ['PATH'] = f'{bin_dir}:{os.environ["PATH"]}'

        with patch.dict(os.environ):
            self.run_qml(
                """import QtQuick
import Quickshell
import Quickshell.Io
import "ui"
import "spaces/movies" as Movies
ShellRoot {
 property int hidden:0
 property int ticks:0
 QtObject {id:host;function hide(){hidden++;}}
 Component.onCompleted:{
  Movies.Browser.open("https://example.test/watch?title=a b&x=$(literal)","movies","",host);
  Apps.openUrl("https://example.test/source","assistant");
  Movies.Browser.open("file:///tmp/unsupported","movies","",host);
 }
 FileView {id:opened;path:Qt.resolvedUrl("opened").toString().replace(/^file:\\/\\//,"");printErrors:false;blockLoading:true}
 Timer {interval:50;repeat:true;running:true;onTriggered:{
  opened.reload();const lines=opened.text().trim().split("\\n");
  if(lines.length<2){if(++ticks<80)return;console.error("DISPLAY_FAIL browser was not launched");Qt.quit();return;}
  const rows=lines.map(JSON.parse).sort((a,b)=>a[0].localeCompare(b[0]));
  if(hidden!==1||JSON.stringify(rows)!==JSON.stringify([["movies","https://example.test/watch?title=a b&x=$(literal)"],["shared","https://example.test/source"]]))console.error("DISPLAY_FAIL",hidden,JSON.stringify(rows));
  else console.log("DISPLAY_PASS");Qt.quit();
 }}
}""",
                setup,
            )
