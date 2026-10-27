# mpv

Video playback uses hardware decoding and built-in scaling by default, with uosc
controls. The Profiles menu offers Standard, FSR, Sharpen, Neural and Anime
options. Neural and anime shaders can cause dropped frames on demanding videos.

`Ctrl+0` returns to Standard; `Ctrl+1` selects FSR.

Powersave temporarily lowers rendering quality; leaving it restores your chosen
settings. See [ARCHITECTURE.md](ARCHITECTURE.md) for provisioning and diagnostics.
