#!/usr/bin/env python3
"""Compile the shell palette into native desktop and application themes."""

import argparse
import copy
import fcntl
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

SOURCE = Path('/etc/desktop-palette.json')
TOKENS = {
    'background',
    'surface',
    'raised',
    'border',
    'text',
    'muted',
    'accent',
    'accentText',
    'danger',
    'warning',
    'success',
    'visited',
}


def load():
    theme = json.loads(SOURCE.read_text())
    if set(theme) != {'font', 'monospaceFont', 'fontSize', 'palettes'}:
        raise ValueError('Expected font, monospaceFont, fontSize and palettes')
    for key in ('font', 'monospaceFont'):
        if not isinstance(theme[key], str) or not re.fullmatch(
            r'[\w .+()-]{1,100}', theme[key]
        ):
            raise ValueError(f'{key} must be a plain font family name')
    if type(theme['fontSize']) not in (int, float) or not 6 <= theme['fontSize'] <= 24:
        raise ValueError('fontSize must be between 6 and 24 points')
    if set(theme['palettes']) != {'dark', 'light'}:
        raise ValueError('Expected dark and light palettes')
    for palette in theme['palettes'].values():
        if set(palette) != TOKENS:
            raise ValueError('Incomplete palette or unknown color token')
        if any(
            not isinstance(c, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', c)
            for c in palette.values()
        ):
            raise ValueError('Colors must use #RRGGBB')
    return theme


def locations():
    home = Path.home()
    return tuple(
        Path(os.environ.get(key, home / fallback))
        for key, fallback in (
            ('XDG_CONFIG_HOME', '.config'),
            ('XDG_DATA_HOME', '.local/share'),
            ('XDG_STATE_HOME', '.local/state'),
        )
    )


def read(path):
    return path.read_text() if path.exists() else ''


def write(path, text):
    """Publish atomically, without changing mtimes for identical output."""
    if read(path) == text:
        return False
    # Generated outputs must never write through a checkout-owned symlink.
    if path.is_symlink():
        raise ValueError(f'Refusing to replace symlink: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(text)
        os.chmod(temporary, path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


def ini_merge(text, groups):
    """Change owned INI keys while preserving comments and unrelated settings."""
    remaining = copy.deepcopy(groups)
    lines, section = [], ''

    def finish():
        for key, value in remaining.pop(section, {}).items():
            lines.append(f'{key}={value}\n')

    for line in text.splitlines(keepends=True):
        match = re.fullmatch(r'\s*\[([^\n]+)\]\s*', line)
        if match:
            finish()
            section = match[1]
        key = (
            line.split('=', 1)[0].strip()
            if '=' in line and not line.lstrip().startswith(('#', ';'))
            else None
        )
        if key in remaining.get(section, {}):
            lines.append(f'{key}={remaining[section].pop(key)}\n')
        else:
            lines.append(line if line.endswith('\n') else line + '\n')
    finish()
    for group, values in remaining.items():
        lines.append(f'\n[{group}]\n')
        lines.extend(f'{key}={value}\n' for key, value in values.items())
    return ''.join(lines)


def css_import(text):
    line = '@import url("desktop-theme.css");'
    if line not in text:
        # CSS imports precede rules; leave any user overrides afterwards.
        text = line + '\n' + text
    return text


def rgb(color):
    return ','.join(str(int(color[i : i + 2], 16)) for i in (1, 3, 5))


def selection_text(c):
    def luminance(color):
        values = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        return sum(
            (v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4) * w
            for v, w in zip(values, (0.2126, 0.7152, 0.0722))
        )

    def contrast(color):
        first, second = sorted((luminance(color), luminance(c['accent'])))
        return (second + 0.05) / (first + 0.05)

    # Preserve the requested color when readable (dark red needs dark text).
    return next(
        (v for v in (c['accentText'], c['text']) if contrast(v) >= 4.5),
        max(('#000000', '#ffffff'), key=contrast),
    )


def union_css():
    # Inherit upstream geometry and fixes; share the shell's selection policy.
    return """@import url("/usr/share/union/styles/breeze/contents/css/style.css");

itemviewitem:highlighted,
itemdelegate:highlighted,
treeviewdelegate:highlighted,
tableviewdelegate:highlighted,
treeviewdelegate.selected,
tableviewdelegate.selected,
graphicsview itemviewitem:highlighted {
    background-color: mix(var(--view-background-alternate-color), custom-color("kcolorscheme", "active", "selection", "decoration", "focus"), 0.16);
    color: var(--view-text-color);
}
graphicsview itemviewitem:highlighted,
focusframe:highlighted,
graphicsview focusframe:highlighted {
    border: 1px solid custom-color("kcolorscheme", "active", "selection", "decoration", "focus");
}
menu, popup {
    background-color: custom-color("kcolorscheme", "active", "tooltip", "background", "normal");
    color: var(--window-text-color);
}
menuitem:hovered, menuitem:highlighted, menuitem:pressed,
menubaritem:hovered, menubaritem:highlighted, menubaritem:pressed {
    background-color: mix(var(--view-background-alternate-color), custom-color("kcolorscheme", "active", "selection", "decoration", "focus"), 0.16);
    border: 1px solid custom-color("kcolorscheme", "active", "selection", "decoration", "focus");
    color: var(--window-text-color);
}
"""


def kde_colors(c, name):
    groups = {
        'General': {'Name': name, 'ColorScheme': name},
        'ColorEffects:Inactive': {'Enable': 'false'},
    }
    for section, background in (
        ('Window', 'background'),
        ('View', 'background'),
        ('Button', 'raised'),
        ('Tooltip', 'surface'),
        ('Complementary', 'surface'),
        ('Header', 'surface'),
        ('Selection', 'accent'),
    ):
        values = {
            'BackgroundNormal': background,
            'BackgroundAlternate': 'surface',
            'ForegroundNormal': 'text',
            'ForegroundInactive': 'muted',
            'ForegroundActive': 'accent',
            'ForegroundLink': 'accent',
            'ForegroundVisited': 'visited',
            'ForegroundNegative': 'danger',
            'ForegroundNeutral': 'warning',
            'ForegroundPositive': 'success',
            'DecorationFocus': 'accent',
            'DecorationHover': 'accent',
        }
        groups['Colors:' + section] = {
            key: rgb(c[token]) for key, token in values.items()
        }
        if section == 'Selection':
            # Dolphin paints labels itself using HighlightedText, independently
            # of Union CSS. Both the palette and selected panel must agree.
            # KDE also derives icon Accent from Highlight. Keep its vivid RGB
            # and express the selection tint as native QColor alpha, rather
            # than baking a muted RGB color into both selections and icons.
            highlight = rgb(c['accent']) + ',41'
            groups['Colors:Selection'].update(
                BackgroundNormal=highlight,
                BackgroundAlternate=highlight,
                ForegroundNormal=rgb(c['text']),
                ForegroundInactive=rgb(c['text']),
            )
    groups['ColorEffects:Disabled'] = {
        'Color': rgb(c['surface']),
        'ColorEffect': '0',
        'ContrastEffect': '1',
        'ContrastAmount': '0.65',
        'IntensityEffect': '2',
        'IntensityAmount': '0.1',
    }
    return groups


def gtk_css(c, version):
    colors = {
        'theme_bg_color': 'background',
        'theme_fg_color': 'text',
        'theme_base_color': 'background',
        'theme_text_color': 'text',
        'theme_selected_bg_color': 'accent',
        'theme_selected_fg_color': 'accentText',
        'theme_unfocused_bg_color': 'background',
        'theme_unfocused_fg_color': 'muted',
        'theme_unfocused_base_color': 'background',
        'theme_unfocused_text_color': 'muted',
        'theme_unfocused_selected_bg_color': 'raised',
        'theme_unfocused_selected_fg_color': 'text',
        'borders': 'border',
        'unfocused_borders': 'border',
        'content_view_bg': 'background',
        'theme_view_active_decoration_color': 'accent',
        'theme_view_hover_decoration_color': 'accent',
        'tooltip_background': 'surface',
        'tooltip_text': 'text',
        'tooltip_border': 'border',
        'link_color': 'accent',
        'link_visited_color': 'visited',
        'error_color': 'danger',
        'warning_color': 'warning',
        'success_color': 'success',
    }
    # Breeze exposes these named colors; preserve its native widget geometry.
    for widget, token in (
        ('button', 'raised'),
        ('header', 'surface'),
        ('titlebar', 'surface'),
    ):
        for suffix in (
            '',
            '_normal',
            '_backdrop',
            '_light',
            '_insensitive',
            '_backdrop_insensitive',
        ):
            colors[f'theme_{widget}_background{suffix}'] = token
            colors[f'theme_{widget}_foreground{suffix}'] = (
                'muted' if 'insensitive' in suffix else 'text'
            )
        for kind in ('focus', 'hover'):
            colors[f'theme_{widget}_decoration_{kind}'] = 'accent'
    result = ''.join(
        f'@define-color {name}{suffix} {c[token]};\n'
        for suffix in ('', '_breeze')
        for name, token in colors.items()
    )
    variables = {
        'window_bg_color': 'background',
        'window_fg_color': 'text',
        'view_bg_color': 'background',
        'view_fg_color': 'text',
        'headerbar_bg_color': 'surface',
        'headerbar_fg_color': 'text',
        'headerbar_backdrop_color': 'surface',
        'headerbar_border_color': 'border',
        'sidebar_bg_color': 'background',
        'sidebar_fg_color': 'text',
        'sidebar_backdrop_color': 'background',
        'card_bg_color': 'raised',
        'card_fg_color': 'text',
        'dialog_bg_color': 'surface',
        'dialog_fg_color': 'text',
        'popover_bg_color': 'surface',
        'popover_fg_color': 'text',
        'accent_bg_color': 'accent',
        'accent_fg_color': 'accentText',
        'destructive_bg_color': 'danger',
        'destructive_fg_color': 'accentText',
    }
    result += ''.join(
        f'@define-color {name} {c[token]};\n' for name, token in variables.items()
    )
    if version == 3:
        # Hyprland draws top-level shadows. GTK shadow extents can leave drawing
        # and pointer coordinates out of sync after an output scale change.
        result += (
            'window.csd:not(.popup):not(.tooltip) > decoration '
            '{ box-shadow: none; margin: 0; }\n'
        )
    if version == 4:
        result += (
            ':root {\n'
            + ''.join(
                f'  --{name.replace("_", "-")}: {c[token]};\n'
                for name, token in variables.items()
            )
            + '}\n'
        )
    return result


def kitty_colors(c):
    result = {
        key: c[token]
        for key, token in {
            'background': 'background',
            'foreground': 'text',
            'cursor': 'accent',
            'cursor_text_color': 'background',
            'selection_background': 'accent',
            'selection_foreground': 'accentText',
            'active_tab_background': 'surface',
            'active_tab_foreground': 'text',
            'inactive_tab_background': 'background',
            'inactive_tab_foreground': 'muted',
            'url_color': 'accent',
        }.items()
    }
    tokens = (
        'surface',
        'danger',
        'success',
        'warning',
        'accent',
        'visited',
        'muted',
        'text',
    )
    result.update({f'color{i}': c[token] for i, token in enumerate(tokens * 2)})
    return ''.join(f'{key} {value}\n' for key, value in result.items())


def zed_style(c):
    mapping = {
        'background': 'background',
        'border': 'border',
        'border.variant': 'border',
        'border.focused': 'accent',
        'border.selected': 'accent',
        'text': 'text',
        'text.muted': 'muted',
        'text.accent': 'accent',
        'icon': 'text',
        'icon.muted': 'muted',
        'icon.accent': 'accent',
        'surface.background': 'surface',
        'elevated_surface.background': 'raised',
        'element.background': 'surface',
        'element.hover': 'raised',
        'element.selected': 'raised',
        'panel.background': 'surface',
        'status_bar.background': 'surface',
        'title_bar.background': 'surface',
        'toolbar.background': 'background',
        'tab_bar.background': 'surface',
        'tab.active_background': 'background',
        'tab.inactive_background': 'surface',
        'editor.background': 'background',
        'editor.foreground': 'text',
        'editor.gutter.background': 'background',
        'editor.line_number': 'muted',
        'editor.active_line_number': 'accent',
        'terminal.background': 'background',
        'terminal.foreground': 'text',
        'error': 'danger',
        'warning': 'warning',
        'success': 'success',
    }
    return {key: c[token] for key, token in mapping.items()} | {
        'syntax': {
            scope: {'color': c[token]} for scope, token in syntax_tokens().items()
        }
    }


def syntax_tokens():
    return {
        'comment': 'muted',
        'string': 'success',
        'number': 'warning',
        'boolean': 'warning',
        'keyword': 'accent',
        'operator': 'text',
        'function': 'visited',
        'type': 'accent',
        'variable': 'text',
        'constant': 'warning',
        'punctuation': 'muted',
    }


def code_colors(c):
    mapping = {
        'foreground': 'text',
        'disabledForeground': 'muted',
        'focusBorder': 'accent',
        'editor.background': 'background',
        'editor.foreground': 'text',
        'editorCursor.foreground': 'accent',
        'editorLineNumber.foreground': 'muted',
        'sideBar.background': 'surface',
        'sideBar.foreground': 'text',
        'activityBar.background': 'raised',
        'activityBar.foreground': 'text',
        'titleBar.activeBackground': 'surface',
        'titleBar.activeForeground': 'text',
        'statusBar.background': 'surface',
        'statusBar.foreground': 'text',
        'panel.background': 'surface',
        'panel.border': 'border',
        'input.background': 'raised',
        'input.foreground': 'text',
        'input.border': 'border',
        'button.background': 'accent',
        'button.foreground': 'accentText',
        'list.activeSelectionBackground': 'accent',
        'list.activeSelectionForeground': 'accentText',
        'terminal.background': 'background',
        'terminal.foreground': 'text',
        'tab.activeBackground': 'background',
        'tab.inactiveBackground': 'surface',
        'textLink.foreground': 'accent',
        'errorForeground': 'danger',
    }
    return {key: c[token] for key, token in mapping.items()} | {
        'editor.selectionBackground': c['accent'] + '55'
    }


def json_text(value):
    return json.dumps(value, indent=2) + '\n'


def icon_theme(mode):
    return 'DotfilesPapirus' + mode.title()


def render(theme, mode, config, data, home):
    """Compute every output before publishing any files."""
    c = dict(theme['palettes'][mode])
    c['accentText'] = selection_text(c)
    name = 'Dotfiles' + mode.title()
    kde = kde_colors(c, name)
    font = f'{theme["font"]},{theme["fontSize"]:g},-1,5,50,0,0,0,0,0'
    fixed = font.replace(theme['font'], theme['monospaceFont'], 1)
    kde['General'].update(font=font, fixed=fixed)
    kde.update(KDE={'widgetStyle': 'Union'}, Icons={'Theme': icon_theme(mode)})
    output = {config / 'kdeglobals': ini_merge(read(config / 'kdeglobals'), kde)}
    union = data / 'union/styles/dotfiles'
    output[union / 'metadata.json'] = json_text(
        {
            'input-type': 'css',
            'input-version': 1,
            'name': 'Dotfiles',
            'description': 'Shell selections and menus over the installed Union Breeze style.',
            'version': '1.0',
            'license': 'MIT',
            'authors': ['dotfiles'],
        }
    )
    output[union / 'contents/css/style.css'] = union_css()
    zed_themes, code_themes = [], []
    extension = data / 'vscode-oss/extensions/dotfiles.desktop-theme-1.0.0'
    for variant, colors in theme['palettes'].items():
        colors = dict(colors, accentText=selection_text(colors))
        label = 'Dotfiles ' + variant.title()
        scheme = 'Dotfiles' + variant.title()
        breeze = 'Breeze-Dark' if variant == 'dark' else 'Breeze'
        for version in (3, 4):
            css = (
                f'@import url("/usr/share/themes/{breeze}/gtk-{version}.0/gtk.css");\n'
                + gtk_css(colors, version)
            )
            output[data / f'themes/{scheme}/gtk-{version}.0/gtk.css'] = css
            dark = dict(
                theme['palettes']['dark'],
                accentText=selection_text(theme['palettes']['dark']),
            )
            output[data / f'themes/{scheme}/gtk-{version}.0/gtk-dark.css'] = (
                f'@import url("/usr/share/themes/Breeze-Dark/gtk-{version}.0/gtk.css");\n'
                + gtk_css(dark, version)
            )
        output[data / f'color-schemes/{scheme}.colors'] = ini_merge(
            '', kde_colors(colors, scheme)
        )
        output[config / f'kitty/{variant}-theme.auto.conf'] = kitty_colors(colors)
        zed_themes.append(
            {'name': label, 'appearance': variant, 'style': zed_style(colors)}
        )
        code_themes.append(
            {
                'label': label,
                'uiTheme': 'vs-dark' if variant == 'dark' else 'vs',
                'path': f'./{variant}.json',
            }
        )
        output[extension / f'{variant}.json'] = json_text(
            {
                'name': label,
                'colors': code_colors(colors),
                'tokenColors': [
                    {
                        'scope': {
                            'number': 'constant.numeric',
                            'boolean': 'constant.language.boolean',
                            'function': 'entity.name.function, support.function',
                            'type': 'entity.name.type, support.type',
                            'operator': 'keyword.operator',
                        }.get(scope, scope),
                        'settings': {'foreground': colors[token]},
                    }
                    for scope, token in syntax_tokens().items()
                ],
            }
        )
    output[config / 'kitty/no-preference-theme.auto.conf'] = kitty_colors(
        dict(
            theme['palettes']['dark'],
            accentText=selection_text(theme['palettes']['dark']),
        )
    )
    output[config / 'kitty/desktop-font.conf'] = (
        f'font_family {theme["monospaceFont"]}\nfont_size {theme["fontSize"]:g}\n'
    )
    output[config / 'zed/themes/dotfiles.json'] = json_text(
        {'name': 'Dotfiles', 'author': 'dotfiles', 'themes': zed_themes}
    )
    output[extension / 'package.json'] = json_text(
        {
            'name': 'desktop-theme',
            'publisher': 'dotfiles',
            'displayName': 'Dotfiles appearance',
            'version': '1.0.0',
            'engines': {'vscode': '^1.80.0'},
            'categories': ['Themes'],
            'contributes': {'themes': code_themes},
        }
    )
    for version in (3, 4):
        folder = config / f'gtk-{version}.0'
        settings = {
            'gtk-theme-name': name,
            'gtk-icon-theme-name': icon_theme(mode),
            'gtk-font-name': f'{theme["font"]} {theme["fontSize"]:g}',
            'gtk-application-prefer-dark-theme': 'true' if mode == 'dark' else 'false',
        }
        output[folder / 'settings.ini'] = ini_merge(
            read(folder / 'settings.ini'), {'Settings': settings}
        )
        if version == 4:
            # GTK >=4.20 re-evaluates media queries on appearance changes. Both
            # palettes stay loaded, including in libadwaita's user CSS provider.
            output[folder / 'desktop-theme.css'] = gtk_dynamic_css(theme)
            output[folder / 'gtk.css'] = css_import(read(folder / 'gtk.css'))
    output[config / 'hypr/theme.lua'] = borders(c) + '\n'
    return output


def borders(c):
    return (
        'hl.config({ general = { col = { '
        f'active_border = "rgba({c["accent"][1:]}cc)", inactive_border = "rgba({c["border"][1:]}ff)"'
        ' } } })'
    )


def gtk_dynamic_css(theme):
    return ''.join(
        f'@media (prefers-color-scheme: {mode}) {{\n'
        + gtk_css(dict(c, accentText=selection_text(c)), 4)
        + '}\n'
        for mode, c in theme['palettes'].items()
    )


def notify(theme, mode):
    errors = []

    def run(argv):
        try:
            subprocess.run(argv, check=True, text=True, capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as error:
            errors.append(f'{argv[0]}: {getattr(error, "stderr", None) or error}')

    for key, value in {
        'color-scheme': 'prefer-' + mode,
        'gtk-theme': 'Dotfiles' + mode.title(),
        'icon-theme': icon_theme(mode),
        'font-name': f'{theme["font"]} {theme["fontSize"]:g}',
        'monospace-font-name': f'{theme["monospaceFont"]} {theme["fontSize"]:g}',
    }.items():
        run(['gsettings', 'set', 'org.gnome.desktop.interface', key, "'" + value + "'"])
    for kind in (0, 1, 2, 4):
        run(
            [
                'gdbus',
                'emit',
                '--session',
                '--object-path',
                '/KGlobalSettings',
                '--signal',
                'org.kde.KGlobalSettings.notifyChange',
                str(kind),
                '0',
            ]
        )
    if os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'):
        run(['hyprctl', 'eval', borders(theme['palettes'][mode])])
    return errors


def apply(mode=None, notifications=True):
    config, data, state = locations()
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'desktop-theme.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        theme = load()
        requested_mode = mode is not None
        mode_path = config / 'quickshell/desktop/theme-mode'
        saved = read(mode_path).strip()
        mode = mode or (saved if saved in ('dark', 'light') else 'dark')
        output = render(theme, mode, config, data, Path.home())
        # Preflight symlinks before any output is changed.
        for path in (*output, *((mode_path,) if requested_mode else ())):
            if path.is_symlink():
                raise ValueError(f'Refusing to replace symlink: {path}')
        for path, content in output.items():
            write(path, content)
        # Publish mode after its toolkit configuration is ready.
        if requested_mode:
            write(mode_path, mode + '\n')
        warnings = notify(theme, mode) if notifications else []
        return {'mode': mode, 'warnings': warnings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'mode', nargs='?', choices=('dark', 'light', 'apply'), default='apply'
    )
    parser.add_argument(
        '--no-notify',
        action='store_true',
        help='Generate files without contacting desktop services',
    )
    args = parser.parse_args()
    try:
        result = apply(None if args.mode == 'apply' else args.mode, not args.no_notify)
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(1, f'{error}\n')
    print(json_text(result), end='')


if __name__ == '__main__':
    main()
