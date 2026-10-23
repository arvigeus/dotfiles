# Repository guidance

## Configuration lifecycle

- Treat the selected modules and generated configuration as the desired state,
  not a transaction history. When a project-managed artifact is removed from the
  configuration, remove that artifact from the live system as part of the same
  change, then prune any one-off migration or cleanup hook from the repository.
  Do not retain cleanup logic solely to support configurations from the past.

## Documentation

- Keep `README.md` files concise and useful to people using the system: what a
  feature offers, handy commands, setup, and non-obvious practical caveats.
- Assume a technically competent reader. Omit explanations of controls and
  behavior that are apparent from the interface or standard conventions. A brief
  feature overview is enough for discovery; add instructions only when they
  convey something readers would otherwise need to look up or infer incorrectly.
- Put implementation details, design decisions, internal state and lifecycle
  rules, configuration schemas, development notes, and test procedures in the
  nearest relevant `ARCHITECTURE.md`. This is also where agent-facing technical
  context belongs.
- Link to `ARCHITECTURE.md` when a README needs to point readers to technical
  detail. Move that detail rather than duplicating it in both files.
- Document the current behavior; keep implementation histories and test output
  out of READMEs.
