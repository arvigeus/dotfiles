# Project tools

The normal desktop entry registers `inode/directory` for Open with and the app
launcher. `project-tools` retains CLI operations and loads the PySide6 dialog
from `/usr/local/lib/project-tools/project_dashboard.py`. Its worker reads a
stateless snapshot through `project_inspector.py` and `project_tasks.py`.
Tasks and tools occupy the first (left) column and stretch to the bottom of the
content area. Both tab lists expand without height caps; the outer scroll area
handles windows too small for the remaining cards.
No activity history/database or project settings are written; desktop MIME
defaults are unchanged.

The Git root is used inside a repository, otherwise the selected folder.
Identity/description/version come from manifests or a short README paragraph.
Known local favicons/logos up to 2 MiB provide the icon, falling back to a theme
icon. Text labels are plain text. Manifest reads are limited to 1 MiB and resolved
paths must remain inside the project. Framework badges follow dependencies and
root markers; explicit Cargo workspace members are checked up to 48 entries.
Detection evidence stays in the inspector snapshot. No package/config expressions
are evaluated.

## Language analysis

[Tokei](https://github.com/XAMPPRocky/tokei) supplies language detection and file
reports through `tokei --output json`. `project_inspector.py` sums the sizes of
reported files, including comments/whitespace, so percentages remain byte based
rather than Tokei's usual line counts. Each file is counted once under its outer
language; embedded-language reports are not counted again. All recognized file
languages are included, including data and documentation formats. Detection and
ignore behavior follow Tokei, rather than GitHub Linguist. Known badge colors come
from the dashboard's technology palette, with neutral colors for other languages.
Framework detection remains manifest based.

Language percentages appear inside the matching technology badges. Languages
found only by the scanner receive their own badges; framework/tool badges without
measured source have no percentage. Combined language badges sum their matching
language shares. Every detected technology and language is included, without a
top-language cutoff. Badges have no tooltips; partial-scan information appears in
the status line. There is no separate language bar or text legend.

Tokei honors `.ignore`/`.tokeignore` and native Git ignore rules (Git ignore files
apply inside repositories). Explicit excludes cover common dependency/build
folders, and symlinks are not followed. The inspector also rejects reported paths
outside the project. A 15-second subprocess timeout reports unavailable analysis;
files that disappear during aggregation and Tokei's inaccurate flag mark the
report partial. Scanning does not compile or execute project code, fetch data,
or persist results.

The module declares `tokei` in `extra.cargo_packages`; the shared package installer
runs Cargo as the selected user, using the Rust toolchain module. The inspector
finds Tokei on PATH or in `$CARGO_HOME/bin` (default `~/.local/share/cargo/bin`).
`50_project-tools.sh` refreshes the desktop database for the application entry.
No local Rust project or committed binary is needed.

## Task discovery and execution

Mise declarations merge `.tool-versions`, supported base/local TOML configs and
bounded executable file-task directories. Hidden tasks are omitted; includes,
environment values and templates are not evaluated. Displayed tool versions are
declarations, not installed/resolved versions.

package.json scripts use `packageManager` first, then Bun/pnpm/Yarn lockfiles,
otherwise npm. Just uses native `--dump --dump-format json`: it parses recipes,
modules, aliases, docs and parameters without evaluating variables/backticks or
executing recipes. Missing Just or parse errors yield a note. Make is parsed
statically: literal targets and bounded literal local includes are supported;
patterns, computed targets and macro bodies are omitted. Make is never executed
for inspection, since even dry-run/database modes can evaluate shell expressions.

Tasks retain a runner identity, so same-name Mise/package/Just/Make entries stay
distinct. Search covers runner, name and description. Optional arguments use
`shlex.split` in the UI and separate argv entries throughout, with no shell
interpolation. Declarations are reread before execution. Mise additionally checks
`mise tasks --json --local` before `mise run`. Other runners use native commands;
when local Mise configuration exists, `mise exec --` provides its environment.
Native task runners control their own scripts/hooks once the user runs a task.

All explicit actions launch through `uwsm app` and `xdg-terminal-exec --hold`.
Mise install/upgrade use `mise install` / `mise upgrade --local`; configuration
trust stays native and interactive. Quick actions use Zed (`zeditor`, then `zed`),
the default folder handler, a terminal, or a sanitized remote browser URL.

## Git

Read-only Git inspection uses porcelain v2/NUL records, optional-lock suppression,
disabled fsmonitor hooks/prompts and five-second timeouts. It shows changes,
upstream counts, latest commit, detached/unborn HEADs and active operations.
Remote URLs are stripped of credentials/query/fragments. Opening/refreshing
never fetches; ahead/behind uses cached tracking refs.

The smart button chooses Pull when only behind, Push when only ahead, otherwise
Fetch. Divergence keeps Fetch with a tooltip directing reconciliation to Zed.
An upstream/remote is required as appropriate. Actions recheck current state;
Pull uses `--ff-only`, Push explicitly targets the configured upstream branch
without force, and Fetch updates the selected remote. Native `git commit` handles
only already-staged changes and preserves editor, signing/pinentry, hooks and
Git configuration. Signing errors leave HEAD/staging intact; unsigned fallback
is never injected. Conflicts/active operations block these actions. The UI also
disables commit for detached HEAD. Refresh rereads changes after terminal actions.

## Maintenance

Cleanup adapts Syntaxis's project-local ignored-file selection rather than its
global runtime cleanup. `git ls-files` supplies a NUL-delimited ignored inventory.
Protected names include `.env`, `.env.*`, `.envrc`, `.direnv`, `*.local`, and
`*.local.*`, including inside ignored parents. Nested repositories are protected.
The preview expands parent entries when necessary to avoid deleting a protected
child. Selection is revalidated against a fresh inventory before exact-path
filesystem deletion. Git clean's `-X` pathspec behavior can broaden a selected
child to an ignored parent, so it is not used to delete the selection.

The reset workflow is intentionally distinct. It refuses an active merge,
rebase, cherry-pick or revert, requires an upstream branch, fetches before changing
files, and freezes the target commit and current branch for confirmation. After
the user types the project name, it resets to that commit and uses one-force
`git clean -fdx` with explicit exclusions. Tracked files follow the target commit;
only untracked local settings are protected. A branch change invalidates the
preview. It never deletes local branches, expires reflogs, prunes Git objects or
forces through an in-progress operation. Home/root repositories are rejected for
cleanup/reset.

`tests/test_project_tools.py` uses disposable Git repositories to exercise local
settings, selection changes, nested repositories, reflog retention and selected
task dispatch. `tests/test_project_overview.py` checks manifest/framework/tool
inspection, bounded/external/malformed files, Git state, credential removal and
absence of project-code execution. `tests/test_project_dashboard.py` drives the
real offscreen dialog, task filtering/launch, panel visibility and refresh.
No real project cleanup/reset is performed by deployment or validation.
