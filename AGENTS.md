# Repository guidance

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
