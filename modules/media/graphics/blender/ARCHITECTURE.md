# Blender module

The native `blender` package comes from Arch's extra repository. The upstream
Blender Lab MCP server is a `uv` tool installed from its `mcp/` subproject on
the repository's default branch. There is no PKGBUILD or pinned commit; Topgrade
upgrades the installed uv tool, and configuration apply runs
`uv tool install --upgrade` against the declared source.

`scripts/50_blender.sh` runs `configure.py` in background Blender as the regular
user, with the real home and XDG paths rather than the executor's staging home.
The hook requires Blender to be closed so an open instance cannot overwrite the
saved preferences. `--disable-autoexec` disables blend-file Python execution;
`-noaudio` avoids starting an audio client during setup, and
`--python-exit-code 1` makes configuration errors fail the hook.

The helper registers and enables the `lab_blender_org` extension repository
(`https://lab.blender.org/`), installs its `mcp` extension if absent, and enables
the add-on. It preserves other preferences while setting Allow Online Access,
Auto Start, and the bridge address `localhost:9876`, then saves `userpref.blend`
through Blender. Online access is required by the add-on even for loopback.
Blender owns subsequent extension updates; apply does not reinstall an existing
extension or add an always-running service.

When Codex is installed, the hook uses `codex mcp add` to configure a user-level
stdio entry named `blender`, launching `~/.local/bin/blender-mcp` on connection.
It uses `CODEX_HOME=~/.local/share/codex`, matching the Codex module. The ChatGPT
desktop app and local Codex clients share that configuration. The MCP process
runs on demand; the add-on's Auto Start preference starts the Blender-side bridge
when Blender opens.

Validate changes with background Blender in a disposable home: exercise a fresh
extension installation and repeated setup, check that unrelated preferences
survive, and read the saved preferences in a second process. After live setup,
open Blender and call an MCP scene-summary tool to verify the bridge.

`extra.uv_tools` entries have `name` and `source` fields. The package executor
records tool names it installed in `~/.local/state/dotfiles/uv-tools`; when a
managed declaration disappears it uninstalls only names in that record. This
keeps unrelated uv tools untouched and makes module selection the desired state.
