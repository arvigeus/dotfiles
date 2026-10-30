# Blender

Installs Blender, Blender Lab's MCP add-on and its MCP server for the ChatGPT
desktop app and Codex. The add-on starts its local bridge automatically when
Blender opens; the AI client launches the separate MCP server when it connects.

Close Blender before applying configuration. Setup enables **Allow Online
Access**, which the add-on requires even for localhost, and **Auto Start**.
Open Blender afterward to use its MCP tools; `/mcp` shows the connection in
ChatGPT or Codex.

Topgrade upgrades the MCP server from its upstream Git source; reapplying the
dotfiles configuration also updates it. The add-on updates through Blender's
extension system. If a uv update fails, choose **Continue** in Topgrade to run
the remaining updates; the run will still report that failure. Rerun when the
network is available. See [ARCHITECTURE.md](ARCHITECTURE.md) for lifecycle details.

The server can execute Python inside Blender. Use it only with projects and data
you are comfortable exposing to AI-generated code.
