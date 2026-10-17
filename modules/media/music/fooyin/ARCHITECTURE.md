# fooyin configuration

The native package reads the managed preferences and layout from
`$XDG_CONFIG_HOME/fooyin/`. The commented declaration in `config.jsonc` retains the
official Flatpak option. Selecting that option also requires placing these assets
under its sandbox configuration directory and restoring its shell launcher.

The shell launches the native `fooyin` executable directly.
