"""Exercise launcher search in Qt's JavaScript engine with native-entry identities,
and the mapping of desktop IDs that uwsm cannot resolve back to their files."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


LAUNCHER = (
    Path(__file__).resolve().parents[1]
    / 'modules/desktop/quickshell'
    / 'symlinks/home/.config/quickshell/desktop/launcher'
)
RUNNER = shutil.which('qmltestrunner6')
if not RUNNER and Path('/usr/lib/qt6/bin/qmltestrunner').is_file():
    RUNNER = '/usr/lib/qt6/bin/qmltestrunner'


@unittest.skipUnless(RUNNER, 'Qt 6 Quick Test is required')
class LauncherSearchTests(unittest.TestCase):
    def test_search_and_catalogue_updates(self):
        qml = """import QtQuick
import QtTest
import "Search.js" as Search
TestCase {
    name: "LauncherSearch"
    function app(id, name, metadata = {}) { return Object.assign({id, name}, metadata); }
    function ids(entries, query) {
        return Search.matches(Search.catalogue(entries), query).map(entry => entry.id);
    }
    function test_blank_and_tie_order() {
        const entries = [app("z", "Zulu"), app("b", "Alpha"), app("a", "Alpha")];
        compare(ids(entries, ""), ["a", "b", "z"]);
        compare(ids(entries, "  \\t  "), ["a", "b", "z"]);
    }
    function test_name_ranking() {
        const entries = [app("metadata", "Browser", {genericName: "Firefox"}),
            app("substring", "Open Firefox"), app("prefix", "Firefox Developer"),
            app("exact", "Firefox")];
        compare(ids(entries, " FiReFoX "), ["exact", "prefix", "substring", "metadata"]);
    }
    function test_all_words_and_metadata() {
        const entries = [app("editor", "Writer", {genericName: "Text editor",
            comment: "Edit documents", keywords: ["notes", "office"]}),
            app("player", "Music", {keywords: ["office"]})];
        compare(ids(entries, "office   editor"), ["editor"]);
        compare(ids(entries, "DOCUMENTS notes"), ["editor"]);
        compare(ids(entries, "editor player"), []);
        compare(ids(entries, "player"), ["player"]);
    }
    function test_unicode_and_optional_metadata() {
        compare(ids([app("cafe", "CAFÉ")], "café"), ["cafe"]);
        compare(ids([app("bg", "БЕЛЕЖКИ")], "бележки"), ["bg"]);
        compare(ids([app("plain", "Plain"), app("null", "Other",
            {genericName: null, comment: null, keywords: null})], "plain"), ["plain"]);
    }
    function test_empty_and_no_match() {
        compare(ids([], ""), []);
        compare(ids([], "query"), []);
        compare(ids([app("a", "Alpha")], "missing"), []);
    }
    function test_identity_and_catalogue_refresh() {
        const alpha = app("a", "Alpha");
        const zulu = app("z", "Zulu");
        const candidates = Search.catalogue([zulu, alpha]);
        compare(Search.matches(candidates, "")[0], alpha);
        compare(Search.matches(candidates, "zulu")[0], zulu);
        compare(candidates[0].entry, zulu); // sorting leaves the cached catalogue alone
        alpha.name = "Renamed";
        compare(ids([alpha, zulu], "alpha"), []);
        compare(Search.matches(Search.catalogue([alpha]), "renamed")[0], alpha);
    }
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(LAUNCHER / 'Search.js', root / 'Search.js')
            (root / 'tst_search.qml').write_text(qml)
            result = subprocess.run(
                [RUNNER, '-input', directory],
                text=True,
                capture_output=True,
                env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
                timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class EntryPathTests(unittest.TestCase):
    """Quickshell's IDs map to the file that wins XDG precedence."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.home = self.root / 'home/applications'
        self.system = self.root / 'system/applications'
        self.record = self.root / 'argv.json'
        self.recorder = self.root / 'record.py'
        self.recorder.write_text(
            'import json, sys\nopen(sys.argv[1], "w").write(json.dumps(sys.argv[2:]))\n'
        )

    def write(self, base, name):
        path = base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('[Desktop Entry]\nType=Application\nName=X\nExec=true\n')
        return path

    def run_helper(self, entry_id, data_dirs=None):
        self.record.unlink(missing_ok=True)
        command = [sys.executable, str(self.recorder), str(self.record)]
        result = subprocess.run(
            [sys.executable, str(LAUNCHER / 'entry_path.py'), entry_id, *command]
            + ['app', '-t', 'service', '--'],
            cwd=self.root,
            env={
                **os.environ,
                'XDG_DATA_HOME': str(self.home.parent),
                'XDG_DATA_DIRS': data_dirs or str(self.system.parent),
            },
            text=True,
            capture_output=True,
            timeout=10,
        )
        argv = json.loads(self.record.read_text()) if self.record.exists() else None
        return result, argv

    def test_unusual_and_nested_ids(self):
        for name, entry_id in (
            ('Portal 2.desktop', 'Portal 2'),
            ('ünï.desktop', 'ünï'),
            ('a:b.desktop', 'a:b'),
            ('-dash.desktop', '-dash'),
            (
                'wine/Programs/Notepad++/Notepad++.desktop',
                'wine-Programs-Notepad++-Notepad++',
            ),
        ):
            with self.subTest(entry_id):
                path = self.write(self.home, name)
                result, argv = self.run_helper(entry_id)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(argv, ['app', '-t', 'service', '--', str(path)])

    def test_precedence_and_data_dirs(self):
        home = self.write(self.home, 'Same Name.desktop')
        self.write(self.system, 'Same Name.desktop')
        system = self.write(self.system, 'kde/Only System.desktop')
        self.assertEqual(self.run_helper('Same Name')[1][-1], str(home))
        self.assertEqual(self.run_helper('kde-Only System')[1][-1], str(system))
        # Relative and empty XDG_DATA_DIRS entries are invalid and ignored.
        self.write(self.root / 'relative/applications', 'Relative App.desktop')
        result, argv = self.run_helper(
            'Relative App', 'relative::' + str(self.system.parent)
        )
        self.assertEqual((result.returncode, argv), (1, None))

    def test_missing_entry_does_not_run_command(self):
        self.write(self.home, 'wine/Programs.desktop')
        for entry_id in ('Missing App', 'wine', 'Programs'):
            with self.subTest(entry_id):
                result, argv = self.run_helper(entry_id)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(
                    result.stderr, f'Desktop entry not found: {entry_id}\n'
                )
                self.assertIsNone(argv)
