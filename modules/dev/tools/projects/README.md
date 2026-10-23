# Project tools

Choose **Open with → Project tools** on a folder, or launch **Project tools**,
to see its icon, description, detected technologies, language percentages, Git changes,
upstream status and latest commit. **Refresh** rereads the project; no activity
history is stored.

The task browser combines Mise tasks, package.json scripts, Just recipes and
literal Make targets. It shows the runner and accepts optional arguments. Package
scripts use the declared package manager or lockfile; local Mise environments are
used when configured. Tool versions are declarations, not installation checks.
Language percentages use the sizes of files recognized by Tokei.

**Open in Zed** opens the project. The Git button switches between **Fetch**,
**Push**, and fast-forward-only **Pull** using the last fetched state. Diverged
branches stay on Fetch; reconcile them in Zed. **Commit staged…** uses native
`git commit`, including your editor, signing and hooks. Refresh after changes.

Cleanup preserves `.env`, `.direnv`, local settings, and nested repositories.
**Reset and update from upstream…** fetches the configured upstream, previews
changes, and requires typing the project name before discarding tracked changes,
local branch commits, and other untracked/build files. It keeps untracked local
settings and Git reflogs. Global cache/tool cleanup stays in the Disks drawer.

```sh
project-tools /path/to/project
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for inspection scope and execution details.
