"""Exercise launcher search in Qt's JavaScript engine with native-entry identities."""

import os
from pathlib import Path
import shutil
import subprocess
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
