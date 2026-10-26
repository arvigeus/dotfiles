"""Theme compilation, native parsers, and shell mode/palette propagation."""
import json
import importlib.machinery
import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import DESKTOP, PALETTE, QS, REPO, copy_theme_ui, load, run_qml

theme = load('desktop_theme', DESKTOP / 'ui/theme.py')
theme.SOURCE = PALETTE
loader = importlib.machinery.SourceFileLoader('desktop_icons', str(REPO / 'modules/look-and-feel/icons/files/usr/local/bin/desktop-icons'))
icons = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(sys, 'dont_write_bytecode', True):
    loader.exec_module(icons)


class IconTests(unittest.TestCase):
    def setUp(self):
        fixture = tempfile.TemporaryDirectory()
        self.addCleanup(fixture.cleanup)
        self.papirus = Path(fixture.name)
        (self.papirus / 'index.theme').write_text('''[Icon Theme]
Directories=16x16/places,48x48/places
ScaledDirectories=24x24@2x/places
[16x16/places]
Size=16
Type=Fixed
[48x48/places]
Size=48
Type=Fixed
[24x24@2x/places]
Size=24
Scale=2
Type=Fixed
''')
        for folder in ('16x16/places', '48x48/places', '24x24@2x/places'):
            path = self.papirus / folder
            path.mkdir(parents=True)
            (path / 'folder-blue.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><path fill="#5294e2"/><path fill="#4877b1"/><path fill="#1d344f"/><path fill="#ffffff"/></svg>\n')
            (path / 'folder.svg').symlink_to('folder-blue.svg')
            (path / 'user-home.svg').symlink_to('folder.svg')
            (path / 'folder-red.svg').write_text('<svg fill="#ff0000"/>')
        # Small monochrome icons must remain inherited, not acquire a solid accent.
        (self.papirus / '16x16/places/folder.svg').unlink()
        (self.papirus / '16x16/places/folder.svg').write_text('<svg fill="currentColor"/>')
        patched = patch.object(icons, 'PAPIRUS', self.papirus)
        patched.start()
        self.addCleanup(patched.stop)

    def test_papirus_aliases_shading_hidpi_and_inheritance(self):
        data = Path('/unused')
        output = icons.render(icons.load_accents(PALETTE), data / 'icons')
        for mode, colors in theme.load()['palettes'].items():
            root = data / 'icons' / theme.icon_theme(mode)
            folder = output[root / '48x48/places/folder.svg']
            self.assertIn(colors['accent'], folder)
            self.assertNotIn('#5294e2', folder)
            self.assertNotIn('#4877b1', folder)
            self.assertNotIn('#1d344f', folder)
            self.assertIn('#ffffff', folder)
            self.assertEqual(folder, output[root / '48x48/places/user-home.svg'])
            self.assertIn('Scale=2', output[root / 'index.theme'])
            self.assertIn('Inherits=Papirus-' + mode.title(), output[root / 'index.theme'])
            self.assertNotIn(root / '16x16/places/folder.svg', output)
            self.assertNotIn(root / '48x48/places/folder-red.svg', output)

    def test_package_update_rebuilds_icons_and_removes_obsolete_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            accents = icons.load_accents(PALETTE)
            icons.generate(accents, output)
            root = output / 'DotfilesPapirusDark'
            alias = root / '48x48/places/user-home.svg'
            self.assertTrue(alias.exists())
            source = self.papirus / '48x48/places/folder-blue.svg'
            source.write_text(source.read_text().replace('</svg>', '<!-- updated package --></svg>'))
            (self.papirus / '48x48/places/user-home.svg').unlink()
            icons.generate(accents, output)
            self.assertIn('updated package', (root / '48x48/places/folder.svg').read_text())
            self.assertFalse(alias.exists())
            self.assertTrue((root / 'icon-theme.cache').is_file())

    def test_failed_build_preserves_installed_variants(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            accents = icons.load_accents(PALETTE)
            icons.generate(accents, output)
            before = {p: p.read_bytes() for p in output.rglob('*') if p.is_file()}
            with patch.object(icons.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'gtk-update-icon-cache')):
                with self.assertRaises(subprocess.CalledProcessError):
                    icons.generate(dict(dark='#123456', light='#654321'), output)
            self.assertEqual(before, {p: p.read_bytes() for p in output.rglob('*') if p.is_file()})


class ThemeTests(unittest.TestCase):
    def test_modes_preserve_settings_and_generate_native_themes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config, data, state = home / 'config', home / 'data', home / 'state'
            config.mkdir()
            (config / 'kdeglobals').write_text('# keep\n[General]\nTerminalApplication=kitty\nfont=old\n[Other]\nsetting=yes\n')
            gtk = config / 'gtk-3.0'; gtk.mkdir()
            (gtk / 'gtk.css').write_text('button { padding: 3px; }\n')
            with patch.dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(config),
                            XDG_DATA_HOME=str(data), XDG_STATE_HOME=str(state)):
                for mode in ('dark', 'light', 'dark'):
                    result = theme.apply(mode, notifications=False)
                    self.assertEqual(result, {'mode': mode, 'warnings': []})
                    self.assertFalse((data / 'icons').exists())
                    c = theme.load()['palettes'][mode]
                    kde = (config / 'kdeglobals').read_text()
                    self.assertIn('widgetStyle=Union', kde)
                    self.assertIn('Theme=' + theme.icon_theme(mode), kde)
                    self.assertIn('gtk-icon-theme-name=' + theme.icon_theme(mode),
                                  (config / 'gtk-3.0/settings.ini').read_text())
                    selection = theme.kde_colors(c, 'test')['Colors:Selection']
                    self.assertEqual(selection['ForegroundNormal'], theme.rgb(c['text']))
                    self.assertEqual(selection['BackgroundNormal'], theme.rgb(c['accent']) + ',41')
                    self.assertEqual(selection['DecorationFocus'], theme.rgb(c['accent']))
                    self.assertIn('BackgroundNormal=' + theme.rgb(c['background']), kde)
                    self.assertIn('TerminalApplication=kitty', kde)
                    self.assertIn('[Other]\nsetting=yes', kde)
                    self.assertIn('# keep', kde)
                    self.assertIn('--window-bg-color: ' + c['background'], (config / 'gtk-4.0/desktop-theme.css').read_text())
                    self.assertEqual((config / 'quickshell/desktop/theme-mode').read_text(), mode + '\n')
                    before = {p: p.stat().st_mtime_ns for p in home.rglob('*') if p.is_file() and p.name != 'desktop-theme.lock'}
                    theme.apply(mode, notifications=False)
                    self.assertEqual(before, {p: p.stat().st_mtime_ns for p in before})
                self.assertEqual((gtk / 'gtk.css').read_text(), 'button { padding: 3px; }\n')
                css = (config / 'gtk-4.0/gtk.css').read_text()
                self.assertEqual(css.count('@import'), 1)
                for mode in ('dark', 'light'):
                    self.assertIn('background ' + theme.load()['palettes'][mode]['background'],
                                  (config / f'kitty/{mode}-theme.auto.conf').read_text())
                family = json.loads((config / 'zed/themes/dotfiles.json').read_text())
                self.assertEqual({t['appearance'] for t in family['themes']}, {'light', 'dark'})
                extension = data / 'vscode-oss/extensions/dotfiles.desktop-theme-1.0.0'
                manifest = json.loads((extension / 'package.json').read_text())
                self.assertEqual(len(manifest['contributes']['themes']), 2)
                union = data / 'union/styles/dotfiles'
                self.assertEqual(json.loads((union / 'metadata.json').read_text())['input-type'], 'css')
                self.assertIn('/usr/share/union/styles/breeze/contents/css/style.css',
                              (union / 'contents/css/style.css').read_text())
                self.assertEqual(json.loads((extension / 'light.json').read_text())['colors']['editor.background'],
                                 theme.load()['palettes']['light']['background'])

    def test_gtk4_media_queries_switch_without_reloading_files(self):
        probe = '''import gi,sys
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
provider=Gtk.CssProvider()
errors=[]
provider.connect('parsing-error',lambda *a: errors.append(str(a[-1])))
provider.load_from_path(sys.argv[1])
assert not errors, errors
for mode,color in ((Gtk.InterfaceColorScheme.DARK,'#1b2021'),(Gtk.InterfaceColorScheme.LIGHT,'#e4dde0'),(Gtk.InterfaceColorScheme.DARK,'#1b2021')):
 provider.props.prefers_color_scheme=mode
 assert '--window-bg-color: '+color in provider.to_string(), provider.to_string()
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'theme.css'
            source.write_text(theme.gtk_dynamic_css(theme.load()))
            result = subprocess.run(['python3', '-c', probe, str(source)], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_palette_and_symlinks_do_not_change_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'config'; config.mkdir()
            source = root / 'palette.json'
            value = theme.load()
            value['palettes']['light']['accent'] = 'red; background: white'
            source.write_text(json.dumps(value))
            destination = config / 'kdeglobals'; destination.write_text('original')
            with patch.dict(os.environ, HOME=str(root), XDG_CONFIG_HOME=str(config),
                            XDG_DATA_HOME=str(root / 'data'), XDG_STATE_HOME=str(root / 'state')):
                with patch.object(theme, 'SOURCE', source), self.assertRaises(ValueError):
                    theme.apply('light', False)
                self.assertEqual(destination.read_text(), 'original')
                target = root / 'target'; target.write_text('untouched')
                destination.unlink(); destination.symlink_to(target)
                with self.assertRaises(ValueError): theme.apply('dark', False)
                self.assertEqual(target.read_text(), 'untouched')

    def test_native_gtk_css_parsers(self):
        # Separate processes: GTK 3 and GTK 4 cannot be loaded together.
        for version in (3, 4):
            for mode, c in theme.load()['palettes'].items():
                with tempfile.TemporaryDirectory() as directory:
                    source = Path(directory) / 'theme.css'
                    source.write_text(theme.gtk_css(dict(c, accentText=theme.selection_text(c)), version))
                    probe = '''import gi,sys
gi.require_version('Gtk', sys.argv[1])
from gi.repository import Gtk
errors=[]
provider=Gtk.CssProvider()
provider.connect('parsing-error',lambda *args: errors.append(str(args[-1])))
provider.load_from_path(sys.argv[2])
assert not errors, errors
'''
                    result = subprocess.run(['python3', '-c', probe, f'{version}.0', str(source)], check=False, capture_output=True, text=True)
                    if 'No module named' in result.stderr or 'Namespace Gtk not available' in result.stderr:
                        self.skipTest('GTK introspection bindings are required')
                    self.assertEqual(result.returncode, 0, f'{version}/{mode}: {result.stderr}')

    def test_notifications_publish_explicit_light_and_dark_preferences(self):
        for mode in ('dark', 'light'):
            with patch.object(theme.subprocess, 'run') as run:
                self.assertEqual(theme.notify(theme.load(), mode), [])
            argv = [call.args[0] for call in run.call_args_list]
            self.assertIn(['gsettings', 'set', 'org.gnome.desktop.interface', 'color-scheme', f"'prefer-{mode}'"], argv)
            self.assertIn(['gsettings', 'set', 'org.gnome.desktop.interface', 'icon-theme',
                           "'" + theme.icon_theme(mode) + "'"], argv)

    def test_background_apply_does_not_overwrite_a_newer_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'config'
            mode_path = config / 'quickshell/desktop/theme-mode'
            mode_path.parent.mkdir(parents=True)
            mode_path.write_text('dark\n')
            render = theme.render

            def changed(*args):
                mode_path.write_text('light\n')
                return render(*args)

            with (patch.dict(os.environ, HOME=str(root), XDG_CONFIG_HOME=str(config),
                             XDG_DATA_HOME=str(root / 'data'), XDG_STATE_HOME=str(root / 'state')),
                  patch.object(theme, 'render', side_effect=changed)):
                theme.apply(notifications=False)
            self.assertEqual(mode_path.read_text(), 'light\n')


@unittest.skipUnless(shutil.which('g++') and shutil.which('pkg-config'), 'Qt development tools are required')
class ThemeNativeQtTests(unittest.TestCase):
    def test_union_and_qt5_fallback_follow_the_same_palette(self):
        required = (
            '/usr/lib/qt6/plugins/styles/UnionWidgetsStyle.so',
            '/usr/lib/qt6/plugins/platformthemes/KDEPlasmaPlatformTheme6.so',
            '/usr/lib/qt/plugins/platformthemes/KDEPlasmaPlatformTheme5.so',
            '/usr/share/icons/Papirus/index.theme',
        )
        if not all(Path(path).exists() for path in required):
            self.skipTest('Union and Qt 5/6 KDE platform themes are required')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'probe.cpp'
            source.write_text('''#include <QApplication>
#include <QGraphicsView>
#include <QListView>
#include <QTreeView>
#include <QImage>
#include <QIcon>
#include <QPainter>
#include <QPalette>
#include <QStyle>
#include <QStyleOption>
#include <iostream>
int main(int argc, char** argv) {
    QApplication app(argc, argv);
    std::cout << app.style()->objectName().toStdString() << " "
              << app.palette().color(QPalette::Window).name().toStdString() << " "
              << app.palette().color(QPalette::Text).name().toStdString() << " "
              << QIcon::themeName().toStdString() << " "
              << QIcon::fromTheme("folder").pixmap(48,48).toImage().pixelColor(8,30).name().toStdString() << " "
              << !QIcon::fromTheme("org.kde.dolphin").isNull() << std::endl;
    if (argc > 1) {
        QGraphicsView graphics;
        QListView list;
        QTreeView table;
        QWidget& view = argc > 2 && QString::fromLocal8Bit(argv[2]) == "list" ? static_cast<QWidget&>(list)
            : argc > 2 && QString::fromLocal8Bit(argv[2]) == "table" ? static_cast<QWidget&>(table)
            : static_cast<QWidget&>(graphics);
        view.ensurePolished();
        QImage image(160, 96, QImage::Format_ARGB32_Premultiplied);
        image.fill(app.palette().color(QPalette::Base));
        QPainter painter(&image);
        QStyleOptionViewItem option;
        option.initFrom(&view);
        option.rect = image.rect();
        option.viewItemPosition = QStyleOptionViewItem::OnlyOne;
        option.state = QStyle::State_Enabled | QStyle::State_Selected;
        if (argc > 2) option.state |= QStyle::State_Active | QStyle::State_MouseOver;
        app.style()->drawPrimitive(QStyle::PE_PanelItemViewItem, &option, &painter, &view);
        QStyleOptionFocusRect focus;
        focus.initFrom(&view); focus.rect = image.rect();
        focus.state = QStyle::State_HasFocus | QStyle::State_Selected;
        app.style()->drawPrimitive(QStyle::PE_FrameFocusRect, &focus, &painter, &view);
        painter.end();
        int borderPixels = 0;
        const QColor accent = app.palette().color(QPalette::Link);
        for (int y = 0; y < image.height(); ++y)
            for (int x = 0; x < image.width(); ++x)
                if (image.pixelColor(x, y) == accent) ++borderPixels;
#if QT_VERSION >= QT_VERSION_CHECK(6, 6, 0)
        const QColor iconAccent = app.palette().color(QPalette::Accent);
#else
        const QColor iconAccent = app.palette().color(QPalette::Highlight);
#endif
        std::cout << image.pixelColor(20, 48).name().toStdString() << " "
                  << app.palette().color(QPalette::HighlightedText).name().toStdString()
                  << " " << borderPixels << " "
                  << iconAccent.name().toStdString()
                  << " " << app.palette().color(QPalette::Highlight).alpha() << std::endl;
        image.save(QString::fromLocal8Bit(argv[1]));
    }
}
''')
            for major in (5, 6):
                flags = subprocess.run(['pkg-config', '--cflags', '--libs', f'Qt{major}Widgets'],
                                       check=False, capture_output=True, text=True)
                if flags.returncode:
                    self.skipTest(f'Qt {major} development headers are required')
                subprocess.run(['g++', '-fPIC', str(source), '-o', str(root / f'qt{major}'),
                                *shlex.split(flags.stdout)], check=True, capture_output=True, text=True)
            env = dict(os.environ, HOME=str(root), XDG_CONFIG_HOME=str(root / 'config'),
                       XDG_DATA_HOME=str(root / 'data'), XDG_STATE_HOME=str(root / 'state'),
                       QT_QPA_PLATFORM='offscreen', QT_QPA_PLATFORMTHEME='kde',
                       UNION_STYLE_NAME='dotfiles',
                       DBUS_SESSION_BUS_ADDRESS='unix:path=' + str(root / 'no-session-bus'))
            env.pop('QT_STYLE_OVERRIDE', None)
            icons.generate(icons.load_accents(PALETTE), root / 'data/icons')
            for mode in ('dark', 'light'):
                with patch.dict(os.environ, env):
                    theme.apply(mode, notifications=False)
                colors = theme.load()['palettes'][mode]
                for major, style in ((5, 'breeze'), (6, 'union')):
                    result = subprocess.run([str(root / f'qt{major}')], check=False, env=env,
                                            capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip().split(),
                                     [style, colors['background'], colors['text'], theme.icon_theme(mode),
                                      colors['accent'], '1'], result.stderr)
                for state in ([], ['hovered'], ['list'], ['table']):
                    result = subprocess.run([str(root / 'qt6'), str(root / 'selection.png'), *state],
                                            check=False, env=env, capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    fill, foreground, border_pixels, accent, opacity = result.stdout.strip().splitlines()[-1].split()
                    # Union mixes floating point channels; allow one byte of
                    # rounding relative to the shell's 16% accent tint.
                    for offset in (1, 3, 5):
                        actual = int(fill[offset:offset + 2], 16)
                        expected = (int(colors['surface'][offset:offset + 2], 16) * 0.84
                                    + int(colors['accent'][offset:offset + 2], 16) * 0.16)
                        self.assertLessEqual(abs(actual - expected), 1, result.stderr)
                    self.assertEqual(foreground, colors['text'])
                    self.assertGreater(int(border_pixels), 10, result.stderr)
                    self.assertEqual(accent, colors['accent'], 'selection tint must preserve folder/icon accent RGB')
                    self.assertEqual(int(opacity), 41)


@unittest.skipUnless(QS, 'Quickshell is required')
class ThemeQmlTests(unittest.TestCase):
    def test_production_sync_coalesces_rapid_toggles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_theme_ui(root)
            runtime = root / 'runtime'; runtime.mkdir(mode=0o700)
            binary = root / 'bin'; binary.mkdir()
            for name in ('gsettings', 'gdbus', 'hyprctl'):
                command = binary / name
                command.write_text('#!/bin/sh\nexit 0\n'); command.chmod(0o755)
            (root / 'shell.qml').write_text('''import QtQuick
import Quickshell
import "ui"
ShellRoot {
 property int stage: 0
 Component.onCompleted: Theme.start()
 Timer { interval: 50; repeat: true; running: true; onTriggered: {
  if (stage < 12) { Theme.setMode(stage % 2 ? "dark" : "light"); stage++; }
  else if (!Theme.busy) {
   if (Theme.error || Theme.mode !== "dark") console.error("THEME_FAIL", Theme.error, Theme.mode);
   else console.log("THEME_PASS");
   Qt.quit();
  }
 } }
}
''')
            env = dict(os.environ, HOME=str(root), XDG_CONFIG_HOME=str(root / 'config'),
                       XDG_DATA_HOME=str(root / 'data'), XDG_STATE_HOME=str(root / 'state'),
                       XDG_RUNTIME_DIR=str(runtime), QT_QPA_PLATFORM='offscreen',
                       PATH=str(binary) + ':' + os.environ['PATH'])
            env.pop('HYPRLAND_INSTANCE_SIGNATURE', None)
            env.pop('WAYLAND_DISPLAY', None)
            result = subprocess.run([QS, '--no-color', '-p', str(root / 'shell.qml')],
                                    env=env, check=False, capture_output=True, text=True, timeout=15)
            log = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, log)
            self.assertIn('THEME_PASS', log)
            for error in ('THEME_FAIL', 'TypeError', 'ReferenceError', 'Binding loop'):
                self.assertNotIn(error, log)
            self.assertIn('ColorScheme=DotfilesDark', (root / 'config/kdeglobals').read_text())
            self.assertEqual((root / 'config/quickshell/desktop/theme-mode').read_text(), 'dark\n')

    def test_palette_and_external_mode_changes_and_invalid_edit_recovery(self):
        def setup(root):
            # Drive edits via a helper so the QML watcher sees atomic replacements.
            (root / 'edit.py').write_text('''import json,os,pathlib,sys
root=pathlib.Path(sys.argv[1]); stage=int(sys.argv[2])
source=root/'ui/palette.json'
if stage==1:
 p=root/'config/quickshell/desktop/theme-mode'; p.write_text('light\\n')
elif stage==2:
 value=json.loads(source.read_text()); value['palettes']['light']['accent']='#123456'
 (root/'valid.json').write_text(json.dumps(value)); temp=source.with_suffix('.tmp'); temp.write_text(json.dumps(value)); os.replace(temp,source)
elif stage==3:
 source.write_text('{broken')
elif stage==4:
 source.write_text((root/'valid.json').read_text())
''')
        run_qml(self, '''import QtQuick
import Quickshell
import Quickshell.Io
import "ui"
ShellRoot {
 id: root
 property int stage: 0
 Process { id: edit; command: ["python3", Quickshell.shellPath("edit.py"), Quickshell.shellPath(""), String(root.stage)] }
 Timer { interval: 250; running: true; repeat: true; onTriggered: {
  if (edit.running) return;
  try {
   if (root.stage===0 && (Theme.mode!=="dark" || Theme.background.toString()!=="#1b2021")) throw Error("initial palette");
   if (root.stage===1 && (Theme.mode!=="light" || Theme.background.toString()!=="#e4dde0")) throw Error("external light mode");
   if (root.stage===2 && Theme.accent.toString()!=="#123456") throw Error("palette edit");
   if (root.stage===3 && (!Theme.paletteError || Theme.accent.toString()!=="#123456")) throw Error("invalid edit lost palette");
   if (root.stage===4) {
    if (Theme.paletteError || Theme.accent.toString()!=="#123456") throw Error("recovery");
    Theme.setMode("dark");
   }
   if (root.stage===5) {
    if (Theme.mode!=="dark") throw Error("switch mode");
    console.log("DISPLAY_PASS"); Qt.quit(); return;
   }
   root.stage++; edit.running=true;
  } catch(e) { console.error("DISPLAY_FAIL", root.stage, e.message); Qt.quit(); }
 } }
}
''', setup)
