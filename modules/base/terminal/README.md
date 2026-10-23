# Terminal

Kitty's built-in command palette opens with **Ctrl+Shift+P** in every kitty
window. Its default shortcut, **Ctrl+Shift+F3**, also works.

Add custom commands to `~/.config/kitty/kitty.conf`, using kitty action aliases.
This file links to the configuration in this module, so edits update the checkout:

```conf
action_alias project_shell launch --type=tab --cwd=~/Projects
action_alias git_status launch --type=tab --cwd=current --hold git status
action_alias system_update launch --type=tab topgrade
```

Aliases appear in the palette without needing individual keyboard shortcuts.
Reload with **Ctrl+Shift+F5** after editing the configuration.
