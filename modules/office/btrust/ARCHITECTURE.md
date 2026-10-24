# B-Trust BISS

BISS persists settings and logs under `~/AppData/Roaming/BISS`. The application
and `btrust-settings` use that path directly, so keep it as a real directory;
do not relocate it or replace it with a symlink.

BISS bundles OpenJFX. Its launcher adds `-Djavafx.cachedir` through
`JAVA_TOOL_OPTIONS` for this service only, placing extracted native libraries
under `$XDG_CACHE_HOME/btrust/openjfx` instead of OpenJFX's default
`~/.openjfx/cache`.
