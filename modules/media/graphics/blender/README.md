# Blender

Installs Blender and configures Blender Lab's MCP server for Codex. The Blender
add-on starts its local bridge automatically when Blender opens; Codex launches
the separate MCP server when it connects.

Topgrade upgrades the MCP server from its upstream Git source; reapplying the
dotfiles configuration also updates it. The add-on updates through Blender's
extension system. If a uv update fails, choose **Continue** in Topgrade to run
the remaining updates; the run will still report that failure. Rerun when the
network is available. See [ARCHITECTURE.md](ARCHITECTURE.md) for lifecycle details.

The server can execute Python inside Blender. Use it only with projects and data
you are comfortable exposing to AI-generated code.
