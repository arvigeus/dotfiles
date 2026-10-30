#!/usr/bin/env bash
set -Eeuo pipefail
user=${1:?Username required}
IFS=: read -r _ _ user_uid _ _ user_home _ < <(getent passwd "$user")
[[ $user_uid != 0 && $user_home == /* && $user_home != / ]]

# A running instance can overwrite preferences saved by the background setup.
if pgrep -u "$user" -x blender > /dev/null; then
    echo 'Save your work and close Blender before applying its configuration.' >&2
    exit 1
fi

run_as_user() {
    local launcher=()
    if ((EUID != user_uid)); then
        launcher=(runuser -u "$user" --)
    fi
    "${launcher[@]}" env HOME="$user_home" \
        XDG_CONFIG_HOME="$user_home/.config" XDG_DATA_HOME="$user_home/.local/share" \
        XDG_STATE_HOME="$user_home/.local/state" XDG_CACHE_HOME="$user_home/.local/cache" \
        CODEX_HOME="$user_home/.local/share/codex" "$@"
}

run_as_user blender --background -noaudio --disable-autoexec \
    --python-exit-code 1 \
    --python "${DOTFILES_REPO:?}/modules/media/graphics/blender/configure.py"

if command -v codex > /dev/null 2>&1; then
    run_as_user codex mcp add blender -- "$user_home/.local/bin/blender-mcp"
fi
