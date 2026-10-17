# XDG configuration

The module owns shared user-directory paths and MIME defaults. Shell startup and
the systemd user environment use the same XDG paths. Package dependencies remain
in the modules that install the selected applications.

`files/etc/xdg/mimeapps.list` provides system defaults using desktop entry IDs,
including Flatpak-exported entries. Native Qt applications use their native
desktop IDs; Okular owns EPUB files with `ebook-tools` installed. User associations override these defaults.
MIME types are explicit: wildcards such as `image/*` do not define defaults.
Firefox and Kate own web and text files; specialized document, music, video, mail
and torrent applications take their respective formats. Koko opens common images;
GIMP retains its editable document formats. Ark owns archive formats;
the archive module also provides command-line tools and optional format backends.

`45_user-directories.sh` reads the staged `user-dirs.dirs` asset and creates its
directories before home publication, including the custom Projects directory.
The publisher assigns user ownership. Paths remain `$HOME`-relative in the
configuration, so they never retain staging paths or a machine-specific username.

KDE's [Places model](https://github.com/KDE/kio/blob/master/src/filewidgets/kfileplacesmodel.cpp)
adds standard directory bookmarks only when those directories exist during its
initial setup. Creating directories before first login prevents a partially
initialized Dolphin sidebar. Existing `user-places.xbel` bookmarks are user-owned
and are not replaced during provisioning.

Validate generation and staged directory publication with:

```sh
python3 -m unittest discover -s tests -p test_generation.py
python3 -m unittest discover -s tests -p test_execution.py
```

For native sidebar checks, instantiate `KFilePlacesModel` with an isolated home
after publication; expect Home, Desktop, Documents, Downloads, Music, Pictures
and Videos. Keep the real user's bookmarks out of fixtures.
