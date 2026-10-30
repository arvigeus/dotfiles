# Dolphin

Dolphin opens files with a single click, browses archives as folders, and shows
file sizes below names in Icons view (beside names in Compact view). The size
option is under **View → Show Additional Information → Size**. Single-click
opening also applies to other KDE file views.

Image previews include iPhone HEIC/HEIF photos through the shared image-format
plugins, which also let Koko open them.

The menubar is hidden; press **Ctrl+M** to show or hide it. Its actions remain
available from Dolphin's Control button.

Keep the embedded Terminal panel hidden with **F4**; it requires Konsole, while
the separate terminal action uses Kitty.

File workflows live in normal **Open with** applications:

- [PDF tools](../../media/tools/pdf/README.md): pages, passwords and batch processing.
- [gImageReader](../../media/tools/ocr/README.md): recognize text in images and PDFs.
- [File tools](../tools/general/README.md): rename previews, checksums, links and file discovery.
- [Encryption tools](../tools/encryption/README.md): OpenPGP encryption, signatures and keys.

Use the installed apps for their workflows:

| Task | App |
| --- | --- |
| Archives, including password-protected ZIP/7-Zip | Ark, through **Compress to…** |
| Audio conversion | [Audio tools](../../media/tools/audio/README.md) |
| Tags and cover art | Audio tools |
| ReplayGain, music organization | Fooyin |
| Video information and common conversions | [Video tools](../../media/tools/video/README.md) |
| Video playback and filters | VLC |
| Remuxing, joining MKVs, selecting/removing tracks | MKVToolNix GUI |
| Image editing/export; SVG editing/export | GIMP; Inkscape |
| Document conversion; PDF annotations and print layouts | LibreOffice; Okular |
| File comparisons; disk usage | Meld; Filelight |
| Clone a Git repository | VS Code's **Git: Clone** |

Individual hashes are available in Dolphin's file properties; File tools creates
and verifies checksum manifests and copies text/image contents to the clipboard.

**Open with** offers [Project tools](../../dev/tools/projects/README.md)
on folders for project-local tasks and Git maintenance. Audio tools and Video
tools are also normal Open with applications. Network discovery lives in the WiFi
drawer.

See [ARCHITECTURE.md](ARCHITECTURE.md) for integration details.
