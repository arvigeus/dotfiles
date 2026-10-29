# Input language integration

`symlinks/home/.config/hypr/input-method.lua` owns the Hyprland layout policy:
`InputMethod.apply("vi")` selects plain US keys for Fcitx/UniKey, any other value
EN/BG phonetic with Alt+Shift. The main config loads it after its generic input
settings. The controller records the selected pair in
`$XDG_RUNTIME_DIR/input-method/hyprland-INSTANCE/secondary` and applies it with
`hyprctl eval`; config reloads reapply that file, and a new compositor instance
starts from EN/BG. `vietnamese.service` is a user unit in `/etc/systemd/user`,
started only on request.

`files/home/.config/quickshell/input-language.json` declares the provider
command for the integrated Quickshell UI. This is our UI's configuration, not a
built-in Quickshell setting. The provider supports `status [keyboard]` and
`select en|bg|vi`, returning `available`, `secondary`, `language`, and `running`
as JSON. A failure exits non-zero with its reason as the first stderr line; the
shell shows that line, and `--notify` sends it. No separate shell checkout is
needed for Hyprland keyboard defaults.
