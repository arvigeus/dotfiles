# Blender module

The native `blender` package comes from Arch's extra repository. The upstream
Blender Lab MCP server is a `uv` tool installed from its `mcp/` subproject on
the repository's default branch. There is no PKGBUILD or pinned commit; Topgrade
upgrades the installed uv tool, and configuration apply runs
`uv tool install --upgrade` against the declared source.

The Blender add-on is a separate, per-user extension installed in the
`lab_blender_org` repository (`https://lab.blender.org/`). Blender owns the
add-on's update lifecycle and its Auto Start preference; dotfiles installs the
separate MCP server tool. The repo is registered with Blender under the ID
`lab_blender_org`.

Codex has a user-level stdio MCP entry named `blender` that launches
`~/.local/bin/blender-mcp` on connection. It is on-demand, not a system service;
the add-on's Auto Start preference starts the Blender-side bridge when Blender
opens.

`extra.uv_tools` entries have `name` and `source` fields. The package executor
records tool names it installed in `~/.local/state/dotfiles/uv-tools`; when a
managed declaration disappears it uninstalls only names in that record. This
keeps unrelated uv tools untouched and makes module selection the desired state.
