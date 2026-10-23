# Desktop appearance

The Display drawer's Dark mode switch applies the shell's colors to supported
applications and publishes the system appearance preference. After applying
these dotfiles, log in again to load the Qt integration and portal settings.

```sh
desktop-theme light
desktop-theme dark
desktop-theme             # Reapply the saved mode
```

Edit the shared [palette](palette/symlinks/etc/desktop-palette.json)
to customize colors and shell/toolkit fonts. It is linked at
`/etc/desktop-palette.json`. The running shell watches it;
without the shell, run `desktop-theme` after editing.

Papirus folders use the palette's accent in each mode. Package updates rebuild
both global icon variants automatically. After editing the palette, rebuild with:

```sh
sudo desktop-icons
```

Dark/light switching selects the corresponding prebuilt variant. Application
logos retain their original colors. Reopen apps that keep cached icons.

| Applications | Appearance |
| --- | --- |
| Dolphin, Okular, Kate, qBittorrent, Fooyin, MKVToolNix and other native Qt apps | Union on Qt 6, Breeze on Qt 5; shared KDE colors and accent-colored Papirus folders |
| GTK apps such as Meld, virt-manager and GIMP | Matching Breeze themes; application-selected themes can override them |
| GTK 4/libadwaita apps | Matching colors through GTK CSS and the system appearance preference |
| Kitty | Matching light/dark palettes selected automatically |
| Zed and Code - OSS | Generated Dotfiles Light/Dark themes, selected automatically |
| Browsers, Electron and Flatpak apps | System preference where supported; choose System/Automatic in the app |

Some apps need reopening after initial setup or palette edits. Older sandbox
runtimes may lack the host theme or GTK's newer appearance support. Sandbox
permissions remain with the application's normal desktop integration.

Application skins, browser content and games retain their own colors. Telegram,
Discord, Steam, Heroic, Kodi and OnlyOffice cannot all consume an arbitrary desktop
palette through a common setting. Widget layouts also remain toolkit-specific.

See [ARCHITECTURE.md](ARCHITECTURE.md) for adapter details, coverage limits and
the assessment of KDE Union.
