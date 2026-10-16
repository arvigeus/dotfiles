# Configuration tools

Use [the root commands](../README.md) to configure, install or apply the system.
Preview the live adapter's execution scope without running commands:

```sh
python3 scripts/apply-config.py user-configuration.json --dry-run
```

Changes to module scripts or shared helpers require regeneration before apply.
See [ARCHITECTURE.md](ARCHITECTURE.md) for executor and adapter details.
