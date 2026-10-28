# Mission: deep desktop-shell code review and targeted cleanup

You are an experienced production software engineer reviewing my PERSONAL Linux desktop shell. I want the kind of technically demanding, caring review that questions old assumptions and removes genuine maintenance burden, NOT an impressive-looking architecture rewrite. Be skeptical, concrete, pragmatic and willing to make substantial changes when evidence supports them.

Repository: local checkout of `arvigeus/dotfiles`; the public GitHub URL is for reference ONLY. Always review and modify the **local working tree**, never assume it matches GitHub. Main domain is `modules/desktop/{hyprland,quickshell,notifications}`. Other modules are contextual dependencies only as they affect the desktop shell.

## Your assigned target

**02-ui-primitives: Shared UI components, models and interactions** | sequence wave 0. This is a self-contained agent assignment. Work only in this checkout.

### Exclusive write ownership
- `modules/desktop/quickshell/symlinks/home/.config/quickshell/desktop/ui/** EXCEPT files exclusively assigned to 01, 03, 05, 09 and 10`

### Read-only neighbors / contracts to trace
- `modules/desktop/quickshell/symlinks/home/.config/quickshell/desktop/bar/**`
- `modules/desktop/quickshell/symlinks/home/.config/quickshell/desktop/drawers/**`
- `modules/desktop/quickshell/symlinks/home/.config/quickshell/desktop/spaces/movies/**`

### Existing tests to investigate and extend
- `tests/test_models.py`
- `tests/test_wheel_scroll.py`
- `tests/test_passive_tooltip.py`
- `tests/test_desktop_interactions.py`

### Target-specific investigation
Review shared components, accessibility/keyboard/pointer interaction, QML bindings, reactive ownership, keyed reconciliation, ScriptModel use, focus preservation and virtualization. Identify abstractions that save real duplication versus wrappers that only rename Qt primitives. Treat Movie UI as read-only and flag true cross-space reuse to its owner.

The scopes describe intended ownership; discover actual calls/imports and test dependencies instead of treating the scope as a file list. `QS`, `HY`, `QMOD`, `NMOD` expand as follows:

- `QS` = `modules/desktop/quickshell/symlinks/home/.config/quickshell/desktop`
- `HY` = `modules/desktop/hyprland`
- `QMOD` = `modules/desktop/quickshell`
- `NMOD` = `modules/desktop/notifications`

## Non-negotiable principles

1. Correctness, safety, coherent domain and lifecycle boundaries, native APIs, maintainability, performance, testability and operational reliability come before style. Keep existing visible behavior and established UX unless it is wrong; explain deliberate behavior changes.
2. Challenge the implementation, not the user's requirements. Existing abstractions are not sacred. Prefer idiomatic Hyprland Lua, modern supported Quickshell/Qt QML, systemd/UWSM, native service integrations and small understandable Python code to custom frameworks and parallel sources of truth. Conversely, NEVER replace a proven solution purely because a native API exists: verify that native API meets the real contract, including failure and lifetime semantics.
3. Do not generalize for hypothetical use cases or refactor merely because a file is large. Remove dead code, duplication, unnecessary adapters, redundant polling, stale compatibility layers and avoidable state only when evidence demonstrates they are no longer necessary. A large cohesive module is better than a fragmented one.
4. Honor the repo's `AGENTS.md` and architecture/documentation guidance. `README.md` describes practical use; `ARCHITECTURE.md` records non-obvious invariants, boundaries and development. Document the CURRENT design, not a change diary. Never invent cleanup/migration hooks for no-longer-managed legacy artifacts; desired state and live reconciliation own removal.
5. Verify installed `hyprctl version`, `qs --version`/Quickshell package version, Qt/Python versions and API availability if accessible; otherwise explicitly say which versions are unknown. Check **version-matching** official Hyprland and Quickshell documentation before replacing or declaring APIs obsolete. Do not assume newest upstream docs equal installed behavior; pay attention to Lua `require()` loading and QML lifecycle/version-specific quirks.
6. You own only the listed write scope plus relevant `tests/` files for regression coverage. Read across boundaries aggressively; when a root cause is elsewhere, document a **cross-module change request** with affected paths, callers, contract, proposed fix and risk. Do not edit neighbor files, shared modules, config/installer, package selections or a different agent's area without explicit ownership coordination. Do not overwrite unrelated local changes.
7. Safety: no host changes, reboots, logouts, monitor switches, account edits, service install/enable/disable/restart, real capture, hardware pairing, user notifications, package updates, destructive cleanup, network firewall writes or persistent credential writes during inspection/tests. Prefer isolated temporary XDG roots, fake process/D-Bus/systemd/Hyprland backends and safe offscreen QML. Hardware acceptance checks are a checklist, not automatic commands.

## Work sequence — investigate before modifying

**A. Reconstruct the system.** Record branch/HEAD and `git status`; read repo-level architecture, target README/ARCHITECTURE, module config, service units, entrypoints and existing tests. Inventory actual target files and consumers. Walk at least the important complete paths: UI input -> QML property/service -> Python or native backend -> IPC/D-Bus/process/systemd/files -> UI outcome. Write a compact boundary/lifetime map with state owner, command or signal contract, persistence and disposal. Include hotplug, reload and error/timeout flows; inspect dependencies on other desktop features.

**B. Review adversarially.** Test assumptions on actual code. Look for:
- correctness bugs, incomplete state transitions, partial updates and inconsistency across reloads;
- lifecycle/cleanup leaks, stale async results, subscriptions, QML bindings, hidden work, duplicate polling, object/model identity and cancelled operations that still mutate state;
- blocking shell GUI thread, resource/CPU/battery costs, unbounded caches/timers/processes and surprising host behavior;
- subprocess argv/quoting/exit-status/JSON protocol issues, process-group/socket/pipe boundaries, unsafe paths, privileges, secret disclosure, missing timeouts and failure recovery;
- misleading UI state, focus/keyboard/mouse errors, multi-monitor/hotplug issues, race conditions, offline/error behavior and unsupported hardware;
- incoherent domain ownership, cross-module duplication, unnecessary layers, QML/Python split that adds no value, non-idiomatic use of frameworks and obsolete code;
- test gaps, fragile fixtures, unverified assumptions and unnecessary documentation.

**C. Findings FIRST.** Before changing code, write a concise severity-ranked audit in your working notes. Each actionable issue includes EXACT file:line references, observed evidence or reproduction, consequence, confidence (confirmed/likely/hypothesis), simplest viable fix and any meaningful tradeoff. Distinguish P0 data loss/lockout/security, P1 correctness/reliability, P2 maintainability/performance, P3 optional polish. Do not inflate severity or invent findings to meet a quota. Identify features that are already sound. Say when there is insufficient evidence.

**D. Implement justified improvements.** Address high-confidence, within-scope issues directly, including regression tests. Small coherent refactors are welcome; larger structural changes require a documented end-state, migration/compatibility plan ONLY if actually necessary, and proven behavior-preserving checkpoints. If intent is genuinely ambiguous or a change is behaviorally disruptive/cross-owned, STOP that specific change and give a concrete proposal; continue other safe work. Keep changes focused and inspect your final diff for noise/accidental churn. Do not commit unless asked.

**E. Verify honestly.** Run smallest relevant existing tests first, add tests for failure paths and then the appropriate broader checks. Repository commands to consider (subject to safe local availability): `python3 -m unittest ...`, `./lint.sh` (read-only default), Bash syntax/ShellCheck, `luac -p`, Ruff, QML parsing/offscreen tests, and generated module validation when relevant. Use `dbus-run-session` and inaccessible `PIPEWIRE_REMOTE` for isolated notification/audio testing. `qmlformat` parsing does NOT prove live Quickshell behavior; mocks do NOT prove hardware support. Record exact commands and PASS/FAIL/SKIPPED with reasons. Never claim tests passed without running them. Do not silently apply autoformat to unowned files.

## Final response contract

Deliver in this order:

1. **Assessment**: target purpose and runtime map, correctness/maintainability grade in words, and most important risks (or 'no substantial issues found').
2. **Findings**: ranked table `priority | confirmed? | file:line | evidence/impact | recommended action | status (fixed/deferred)`, with no filler findings.
3. **Changes made**: files, before/after behavior, rationale, meaningful tradeoffs, and any intentional changes in functionality.
4. **Validation**: exactly what ran, results, key coverage gaps and what needs a real desktop/hardware session.
5. **Cross-module handoffs**: concrete actionable proposals for other agent owners, NOT unscoped edits.
6. **Remaining work**: at most the important outstanding risks, ordered by impact. Include a concise operator/manual-test checklist where relevant.

This is a CLEANUP AND HARDENING task, not merely a review. Do not stop after presenting findings when safe meaningful corrections are clear. Do not introduce a new general framework or force all modules into one pattern. Be thorough enough to justify what you changed and what you intentionally left alone.
