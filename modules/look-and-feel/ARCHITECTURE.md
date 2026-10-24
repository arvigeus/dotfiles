# Appearance integration

## Source and ownership

The appearance [palette module](palette/symlinks/etc/desktop-palette.json) owns
`/etc/desktop-palette.json`, linked to the checkout as the single palette source.
The shell's [ui directory](../desktop/quickshell/symlinks/home/.config/quickshell/desktop/ui/)
owns `Theme.qml` and the adapter/compiler `theme.py`; both read the global palette.
The palette contains
`font`, `monospaceFont`, `fontSize` in points and `palettes.dark`/`palettes.light`.
Each palette has exactly `background`, `surface`, `raised`, `border`, `text`,
`muted`, `accent`, `accentText`, `danger`, `warning`, `success` and `visited`, all
opaque `#RRGGBB`. Solid accent fills use `accentText` when contrast is at least
4.5; otherwise adapters and the shell choose a readable foreground. Translucent
KDE selections retain normal text.

`Theme.qml` consumes the source and retains the last valid in-memory palette
when an edit fails validation. Initial startup requires a valid source. The
user-owned `quickshell/desktop/theme-mode` remains the mode preference, defaulting
to dark when absent. Provisioning does not seed or reset it. Both files are
watched, including atomic replacements. The shell converts points to logical
pixels at 96/72; compositor scaling remains independent.

`Theme.start()` is called only by production `shell.qml`. It enables debounced,
serialized `ui/theme.py` application on startup and mode/palette changes. Changes
during application request another pass. Previews import Theme without starting
synchronization. The helper also backs `desktop-theme [dark|light]`. Failures
appear beside the appearance control; another change or CLI apply retries.

The helper locks under XDG state, validates and renders before writing, rejects
symlink destinations, writes atomically and skips identical content. Background
application never writes the mode preference, so a concurrent toggle cannot be
lost. Explicit CLI mode changes publish the preference after generating files.
Publication is atomic per file, not a transaction across toolkits; a filesystem
failure may require reapplying to finish the remaining outputs.

GTK and Qt modules own dependencies and session environment. Quickshell owns the
source, compiler and command. Application modules select generated themes in
provisioned settings; synchronization does not rewrite editor settings or files
linked into the checkout. Unrelated KDE/GTK INI keys and user CSS are preserved.
Generated user theme families remain until manually removed. The system-wide
Papirus variants are rebuilt as complete directories.

## Native toolkit integration

Qt 5/6 use `QT_QPA_PLATFORMTHEME=kde` and matching Plasma integration plugins.
`kdeglobals` selects `widgetStyle=Union`: Qt 6 uses Union, while Qt 5's platform
theme falls back to Breeze because Union has no Qt 5 plugin. Both paths have been
verified with native applications in light and dark modes. KDE color schemes live
in XDG data's
`color-schemes/Dotfiles{Dark,Light}.colors`; active colors and fonts merge into
`kdeglobals`. KGlobalSettings signals announce palette, font and style changes
without a Plasma session. Apps may override palettes or require reopening. Quick
apps drawing custom components must consume the system palette themselves. No
global Quick Controls style is forced: Qt 5 and 6 have different available styles.
VLC's provisioned setting disables its forced dark palette. The shell uses the
platform icon theme instead of forcing Adwaita.

### Papirus icon variants

The `icons` module installs `papirus-icon-theme`, Python and
`gtk-update-icon-cache`. The root-owned `/usr/local/bin/desktop-icons` reads
only the validated dark/light accents from `/etc/desktop-palette.json` and
builds `DotfilesPapirusDark` and `DotfilesPapirusLight` in `/usr/share/icons/`.
They inherit `Papirus-Dark` and `Papirus-Light`; application logos and other
unmodified icons come from the packaged themes. Breeze icons remain installed
as Papirus's recommended KDE fallback. No upstream files are modified.

The generator reads Papirus's index for size/scale metadata and resolves places
aliases to upstream `folder-blue`/`user-blue` SVGs. It replaces the front blue
with that mode's exact `accent`, the rear blue with 78% of its RGB channels and
the emblem blue with 35%. Upstream shadows, highlights, paper and other colors
remain intact. HiDPI entries are generated too. SVGs are not vendored.

Both variants and their caches are built in a temporary directory before
replacing the generated theme directories, which also removes obsolete aliases.
Failed rendering or cache generation leaves the installed themes intact.
A root lock serializes builds. Unsupported upstream layouts fail visibly.
Publication replaces each directory separately; running applications may need
reopening after an icon update.

The post-transaction `95-desktop-icons.hook` invokes `desktop-icons` directly
after a Papirus install/upgrade. The module's setup script invokes the same
command after assets are installed. No watcher, user service or session bus is
needed for generation. The global palette is data; the hook executes only the
installed root-owned generator. Palette changes require `sudo desktop-icons`
to rebuild icons. The shell continues watching the global palette for its other
colors; `desktop-theme` only selects the prebuilt icon variant in KDE, GTK and
GNOME interface settings and sends the usual notifications. User theme changes
never rebuild icons or modify system files.

KDE selection colors keep the accent RGB with native QColor alpha `41/255`,
with regular text. KDE derives icon Accent from Highlight too: do not replace
Highlight with preblended RGB, which makes folder icons disappear into selections.
Vivid accents remain in focus/hover decoration roles. Dolphin draws labels
from `HighlightedText` itself, so CSS foreground alone cannot fix its selection.
`theme.py::union_css` generates `union/styles/dotfiles`, importing the installed
Union Breeze CSS and applying the shell's 16% tint over `surface` to native
list/table selections and Dolphin, with a one-pixel focus outline. Native menus
(including `QsMenuAnchor` tray menus) use `surface` and the same selection policy.
`UNION_STYLE_NAME=dotfiles` selects this
native style package without copying upstream rules or forcing a platform plugin.
Reopen apps after initial environment changes; palette colors remain dynamic.
Existing processes may retain the earlier palette/style; quit/reopen the app,
and reload the shell or log in again for tray menus. Firefox's own chrome/content
does not consume Union; further matching would need a separate browser theme or
userChrome CSS, which this setup does not install.

GTK 3/4 named `DotfilesDark`/`DotfilesLight` themes import packaged Breeze CSS,
then override named colors, retaining geometry and assets. Switching theme names
through GNOME interface settings loads the correct palette. GTK settings.ini
files supply startup defaults. Meld leaves its source style scheme at the
application default instead of forcing the light Classic scheme.

Libadwaita does not load arbitrary GTK themes. Its documented color variables
are supplied through GTK 4 user CSS containing **both** palettes in
`prefers-color-scheme` media queries (GTK >=4.20). The toolkit re-evaluates these
on mode changes, avoiding stale single-mode CSS in running apps. The generated
sheet is imported before existing user rules. Palette edits may need reopening;
older sandbox runtimes may ignore media queries. Application-specific styles
can override colors.

GNOME interface settings advertise explicit `prefer-dark`/`prefer-light`, the
GTK theme, icons and fonts. Hyprland's portals select GTK for Settings and file
selection, and Hyprland for screen capture/sharing. Browsers, Electron,
libadwaita and Flatpaks can consume the standard appearance preference. Arbitrary
exact colors are not exported as a portal accent. No Flatpak permission
overrides, client modifications, app restarts or per-toggle environment changes
are used. Host palette files are not guaranteed to be visible in sandboxes.

Compositor borders use generated `hypr/theme.lua`, loaded from `appearance.lua`,
and `hyprctl eval` updates the running compositor.

## Application themes

Kitty's `dark-theme.auto.conf`, `light-theme.auto.conf` and
`no-preference-theme.auto.conf` contain palette and ANSI colors. No-preference
defaults to dark, matching the shell. Kitty >=0.38 follows the portal without
remote control or process signaling. Its main config includes a generated
monospace font fragment.

Zed loads `zed/themes/dotfiles.json`. Code - OSS discovers a local declarative
theme extension in `$XDG_DATA_HOME/vscode-oss/extensions/dotfiles.desktop-theme-1.0.0`.
Both variants are generated together; their settings follow system mode. Editor
fonts remain settings owned by the application after setup; provisioned defaults
match the shell. Themes cover UI surfaces and common syntax roles using shared
semantic colors. Code may need Reload Window after extension creation or palette
edits. Workspaces/profiles can override user theme choices.

## KDE Union baseline

Reference baseline: Union **6.8.1**, not a version pin or permanent constraint.
Its outputs cover Qt 6 Quick Controls,
Kirigami and Qt Widgets, with no GTK, terminal or editor output. Extension points
include input plugins (CSS is supplied), platform integration plugins and toolkit
outputs consuming Union's intermediate style representation. Recheck these
capabilities on upgrades; do not maintain a custom renderer for missing support.

Union is the selected Qt Widgets style and consumes the generated KDE palette
through our small overlay on its bundled `breeze` Union style. That name does not mean Qt 6
is using the separate Breeze Widgets plugin. Union 6.8.1 uses QCommonStyle for
unsupported widget rendering; recheck that fallback when upgrading.

Breeze currently supplies Qt 5 fallback, GTK theme assets and KDE dependencies.
Icons are separate assets. The shell draws custom QML, so selecting a Controls
style alone does not restyle it.

To select Union directly in a Qt 6 Quick app, use
`QT_QUICK_CONTROLS_STYLE=org.kde.union UNION_STYLE_NAME=<id> <application>`.
`union-styletool` creates, installs and inspects style packages. Validate a real
style and both modes before forcing a session-wide Quick Controls style: Qt 5
cannot load `org.kde.union`. Desktop Controls using the native QStyle can use the
selected Widgets style without that environment override.

## Union upgrade policy

### Accepted visual limits

The user accepts matching palette, readable text and subtle selections while
apps retain native layout, spacing and icons. Exact shell parity is possible in
some places but can require disproportionate overrides. If asked again about
residual visual differences, remind them of this accepted stopping point and
check for new native support before proposing more customization. This is not a
reason to ignore unreadable text, broken mode switching or straightforward fixes.
Union cannot restyle Firefox chrome/web content, custom app skins or sandboxed
toolkits without their cooperation; native tray menus follow the shell process's
Qt style. Running apps can retain old palettes/environment until reopened.

### Adoption

**Progressively adopt supported Union features; this implementation is temporary
where upstream can replace it.** On theming work or Union/toolkit upgrades:

1. Check the installed version/files (`pacman -Q union`, `pacman -Ql union`),
   dependency requirements (`pacman -Qi`), and upstream
   [outputs](https://invent.kde.org/plasma/union/-/tree/master/src/output),
   [platform integration](https://invent.kde.org/plasma/union/-/tree/master/src/platform)
   and [style APIs](https://api.kde.org/working-with-styles.html).
   Installed styles are in `/usr/share/union/styles/`; distinguish shipped support
   from unreleased plans. Revalidate the baseline above rather than assuming it.
2. Use new native support and **delete the superseded adapter**, dependencies and
   fallback assertions in the same change. Keep a fallback only for a remaining
   app/toolkit need, recording that reason here. Do not preserve obsolete code as
   a compatibility layer or add adapter code before checking native support.
3. Verify both palettes, custom colors, running-app mode changes, the appearance
   portal and affected native/sandboxed apps. Update tests to the new contract;
   current assertions about Breeze or plugin paths are not permanent requirements.
4. Remove obsolete generated files and managed CSS imports without disturbing
   unrelated user configuration. Apply leaves omitted assets/packages installed,
   so include explicit cleanup and update this document's baseline/coverage.

Retirement points in `theme.py` (package owners: [qt](qt/config.json),
[gtk](gtk/config.json); application selections live in their own modules):

| Current integration | Revisit when upstream supplies |
| --- | --- |
| `kde_colors`, `render`'s KDE output; Qt 5 Breeze fallback | Native palette/settings integration or broader Qt support; retain palette export only where still consumed |
| `union_css` and the `dotfiles` style package | Native settings can express the same selection policy; keep upstream imports instead of vendoring its style |
| `gtk_css`, `gtk_dynamic_css`, `render`'s named themes; `breeze-gtk` | GTK/libadwaita support that preserves our colors and live mode switching |
| `kitty_colors`, `zed_style`, `code_colors`, `syntax_tokens` and generated app themes | Supported app/toolkit consumers of the shared style; remove each adapter independently |
| `notify` and `Theme.qml` synchronization | Native settings/portal propagation; preserve one authoritative mode and palette |
| Breeze packages/icons and Plasma integration | Verified replacement of each consumer and package dependency; a Union style named `breeze` alone is not evidence either way |

References: [Union overview](https://api.kde.org/overview.html),
[application integration](https://api.kde.org/applications.html),
[style packages](https://api.kde.org/working-with-styles.html),
[build/output dependencies](https://github.com/KDE/union/blob/master/CMakeLists.txt),
[Arch package](https://archlinux.org/packages/extra/x86_64/union/),
[GTK CSS queries](https://docs.gtk.org/gtk4/css-properties.html),
[libadwaita colors](https://gnome.pages.gitlab.gnome.org/libadwaita/doc/main/css-variables.html),
[appearance portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Settings.html),
[Kitty automatic themes](https://sw.kovidgoyal.net/kitty/kittens/themes/),
[Zed themes](https://zed.dev/docs/extensions/themes).

## Verification

`python3 -m unittest discover -s tests -p test_desktop_theme.py` covers palette
compilation, configuration preservation, idempotence, invalid input, symlink
protection, concurrent mode ownership, native GTK 3/4 CSS parsers, GTK 4 queries
switching in one provider, and isolated QML watching/production synchronization.
Icon tests cover accent shades, alias resolution, HiDPI metadata, inheritance,
upstream changes, stale alias cleanup, preservation after a failed build, and
user theme switching without icon generation.
The native Qt probe checks Union selection in Qt 6, Breeze fallback in Qt 5,
both palettes, rendered Papirus folder accents and inherited application icons,
and actual Dolphin-style selected/hovered panel pixels, text roles
and accent borders without a session bus. It requires the declared platform
plugins, styles and development headers. Production tests replace notification
commands and isolate HOME and all XDG paths. Generation and desktop interaction
suites cover provisioning and the existing switch. Live Qt propagation, GTK
assets, portals and sandbox behavior
require the declared packages and a graphical session.
