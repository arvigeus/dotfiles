"""Check native settings on disk and favorite ordering in Qt's JS engine."""

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
class LauncherFavoritesTests(unittest.TestCase):
    def run_qt(self, root, body):
        # Keep Quickshell's static plugins out of the Qt-only test engine.
        shutil.copyfile(LAUNCHER / 'Favorites.qml', root / 'Favorites.qml')
        shutil.copyfile(LAUNCHER / 'Search.js', root / 'Search.js')
        qml = (
            """import QtQuick
import QtCore
import QtTest
import "Search.js" as Search
TestCase {
    name: "LauncherFavorites"
    Component { id: factory; Favorites {} }
    function store(name) {
        return factory.createObject(this, {location: Qt.resolvedUrl(name + ".ini")});
    }
"""
            + body
            + '\n}\n'
        )
        (root / 'tst_favorites.qml').write_text(qml)
        result = subprocess.run(
            [RUNNER, '-input', str(root / 'tst_favorites.qml')],
            text=True,
            capture_output=True,
            timeout=30,
            env={
                **os.environ,
                'QT_QPA_PLATFORM': 'offscreen',
                'XDG_CONFIG_HOME': str(root / 'config'),
            },
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_preferences_across_fresh_processes_and_first_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_qt(
                root,
                """
    function test_save() {
        const untouched = store("untouched");
        compare(untouched.ids, []); untouched.destroy();
        const one = store("one"); one.toggle("firefox");
        compare(one.ids, ["firefox"]);
        const many = store("many"); many.toggle("kitty"); many.toggle("missing-app");
        compare(many.ids, ["kitty", "missing-app"]);
        const empty = store("empty"); empty.toggle("firefox"); empty.toggle("firefox");
        compare(empty.ids, []);
        // Desktop IDs follow file names: list and INI syntax must stay data.
        const odd = store("odd");
        for (const id of ["Portal 2", "a,b", "x;y", "@Variant(x)", "q\\"uote", " lead", "ünï"])
            odd.toggle(id);
        store("single").toggle("a, b");
        // Native settings should retain unrelated values in the same file.
        many.preferences.setValue("otherPreference", "keep"); many.preferences.sync();
    }
""",
            )
            self.assertFalse((root / 'untouched.ini').exists())
            for name in ('one', 'many', 'empty', 'odd', 'single'):
                self.assertTrue((root / (name + '.ini')).is_file())
            self.run_qt(
                root,
                """
    function test_restore_from_disk() {
        compare(store("one").ids, ["firefox"]);
        const many = store("many"); compare(many.ids, ["kitty", "missing-app"]);
        compare(many.preferences.value("otherPreference", ""), "keep");
        compare(store("empty").ids, []);
        compare(store("odd").ids, ["Portal 2", "a,b", "x;y", "@Variant(x)", "q\\"uote", " lead", "ünï"]);
        compare(store("single").ids, ["a, b"]);
    }
""",
            )

    def test_normalization_ranking_and_reinstalled_apps(self):
        with tempfile.TemporaryDirectory() as directory:
            self.run_qt(
                Path(directory),
                """
    function test_normalize_and_reload_immediately() {
        const original = store("dirty");
        original.preferences.setValue("favoriteIds", ["kitty", "", 4, "kitty", "missing-app"]);
        original.preferences.sync();
        const cleaned = store("dirty");
        compare(cleaned.ids, ["kitty", "missing-app"]);
        cleaned.toggle("firefox");
        compare(store("dirty").ids, ["kitty", "missing-app", "firefox"]);
        cleaned.toggle(""); compare(cleaned.ids, ["kitty", "missing-app", "firefox"]);
        const invalid = store("invalid");
        invalid.preferences.setValue("favoriteIds", 42); invalid.preferences.sync();
        compare(store("invalid").ids, []);
    }
    function app(id, name, genericName) { return {id, name, genericName}; }
    function ids(entries, query, favorites) {
        return Search.matches(Search.catalogue(entries), query, favorites).map(entry => entry.id);
    }
    function test_browse_and_search_order() {
        const entries = [app("z", "Zulu"), app("a", "Alpha"), app("b", "Beta")];
        compare(ids(entries, "", ["z"]), ["z", "a", "b"]);
        compare(ids(entries, "  ", ["z", "b", "missing"]), ["b", "z", "a"]);
        compare(ids(entries, "", []), ["a", "b", "z"]);
        compare(ids(entries, "a", ["z", "b"]), ["a", "b"]);
        const browsers = [app("meta", "Browser", "Firefox"), app("prefix", "Firefox Developer"),
            app("exact", "Firefox"), app("substring", "Open Firefox")];
        compare(ids(browsers, " FiReFoX ", ["meta", "substring"]),
            ["exact", "prefix", "substring", "meta"]);
    }
    function test_missing_and_reinstalled() {
        const saved = ["missing", "z"];
        const installed = [app("a", "Alpha"), app("z", "Zulu")];
        compare(ids(installed, "", saved), ["z", "a"]);
        installed.push(app("missing", "Missing returned"));
        compare(ids(installed, "", saved), ["missing", "z", "a"]);
        compare(saved, ["missing", "z"]);
        compare(ids(installed, "absent", saved), []);
    }
""",
            )
