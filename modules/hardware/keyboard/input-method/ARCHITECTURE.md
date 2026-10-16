# Input language integration

`symlinks/home/.config/hypr/input-method.lua` configures English/Bulgarian
phonetic and Alt+Shift directly in Hyprland. The main Hyprland config loads it
after its generic input settings. The input-method controller writes the selected
pair to `$XDG_RUNTIME_DIR/hypr/input-language-INSTANCE.lua`; this override is
loaded last, preserving selection across config reloads and resetting it for a
new compositor instance.

`files/home/.config/quickshell/input-language.json` declares the provider
command for the integrated Quickshell UI. This is our UI's configuration, not a
built-in Quickshell setting. The provider supports `status [keyboard]` and
`select en|bg|vi`, returning `available`, `secondary`, `language`, and `running`
as JSON. No separate shell checkout is needed for Hyprland keyboard defaults.
