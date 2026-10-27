# mpv configuration

## Provisioning and defaults

The module installs base `mpv.conf` / `input.conf` assets, then `50_mpv.sh` appends
Linux-compatible shader profiles and uosc menu entries from the package-owned
`pack-next.json`. Generated outputs are regular files, rebuilt from their base
assets during apply. Windows-only profiles are omitted.

The default `standard` profile uses built-in Lanczos luma/chroma scaling,
Hermite downscaling and linear-light downscaling, without custom shaders. Every
generated shader profile applies `standard` first so profile changes cannot
retain another shader's scaler settings. Returning to Standard resets the shader
list and those settings together; interpolation, debanding and other user controls
remain independent.

FSR is a separate option with its own sharpening pass. All upstream Linux
profiles, including `generic-high` (FSRCNNX x16), remain selectable; their upstream
IDs stay intact while menu labels group Neural and Anime options. Anime labels
describe the source: Blurry (A), Ringing (B) and Sharp (C); Strong adds the second
restoration pass and Fast uses smaller networks. `Ctrl+0` selects Standard and
`Ctrl+1` selects FSR. The base uses `vo=gpu-next`; GA402RK selects OpenGL and
`hwdec=auto-safe`. Codec/device discovery stays automatic. Startup GPU/context
selection and [Powersave overrides](../../../hardware/power/ARCHITECTURE.md)
are independent of shader-profile selection.

## Fullscreen render budget

FSRCNNX's supplied shader starts when both target dimensions exceed 1.3 times
the source. Enlarging 1920×1080 video to a 2560×1440 display crosses that threshold;
a window smaller than the source does not run the neural passes. The stream's
source resolution stays unchanged by fullscreen. Lower source resolutions can
also invoke the shader, so lowering YouTube quality does not reliably avoid it.

60 fps video has about 16.7 ms per frame, compared with 41.7 ms for 23.976 fps.
Built-in scaling avoids the neural pipeline's GPU cost as the default for all
videos, while leaving heavier profiles available for deliberate use. Do not compensate
for shader overload by changing stream resolution, disabling hardware decode or
adding frame-synchronization/VRR overrides without corresponding measurements.

## Validation

`python3 -m unittest discover -s tests -p 'test_mpv_power.py' -v` covers shader/menu
generation, native profile switching and Powersave restoration. `test_apply.py` covers repeatable
generation without accumulated profile sections or unexpected symlinks.

For physical render checks, compare the same local sample in windowed/fullscreen
mode through mpv IPC. Temporarily use a different shader list/profile in the owned
test player; keep its source, codec, display, power mode and decoder constant.
Measure deltas for `frame-drop-count`, `decoder-frame-drop-count`, A/V sync and
cache pauses after a warm-up. `vo-passes/fresh` supplies per-pass GPU time in
nanoseconds; sum average pass times to compare against the source frame budget.
Capture `video-params`, `osd-dimensions`, `hwdec-current` and active shader paths
to distinguish decoding, presentation-size and scaling changes. Use muted owned
players, disable resume writes and stop the test processes afterwards. Native
display tests require the real Wayland session; null/offscreen rendering cannot
establish fullscreen performance.
