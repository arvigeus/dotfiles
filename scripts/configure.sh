#!/usr/bin/env bash
# Apply user-configuration.json's custom part: assets, AUR/Flatpak packages,
# module hooks and the staged home. --check and --pre run only those hooks.
# CONFIG_MODE=install (default, inside archinstall's target) or live.
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'Run through ./apply.sh or archinstall.' >&2; exit 1; }
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
config=$repo_dir/user-configuration.json
mode=${CONFIG_MODE:-install}
[[ $mode == live || $mode == install ]] || { echo "Unknown CONFIG_MODE: $mode" >&2; exit 1; }
user=${SUDO_USER:-}

run_hooks() {
    local script
    while IFS= read -r script; do
        printf '[%s] %s\n' "$1" "$script"
        bash -Eeuo pipefail "$repo_dir/$script" "$user"
    done < <(jq -r --arg kind "$1" '.extra[$kind][]' "$config")
}

case ${1:-} in
    --check) run_hooks checks; exit 0 ;;
    --pre) run_hooks pre; exit 0 ;;
    '') ;;
    *) echo "Unknown action: $1" >&2; exit 1 ;;
esac

if [[ -z $user ]]; then
    mapfile -t users < <(getent passwd | awk -F: '$3 >= 1000 && $3 < 65534 { print $1 }')
    ((${#users[@]} == 1)) || { echo 'Expected one regular user; set SUDO_USER to select one.' >&2; exit 1; }
    user=${users[0]}
fi
IFS=: read -r _ _ user_uid user_gid _ user_home _ < <(getent passwd "$user")
[[ $user_uid != 0 && $user_home == /* && $user_home != / ]] || { echo "Unsuitable user: $user" >&2; exit 1; }

if [[ $mode == install ]]; then
    # Continue from the user's own checkout so symlinked assets point into it.
    destination=$user_home/Projects/dotfiles
    [[ ! -e $destination && ! -L $destination ]] || { echo "Checkout already exists: $destination" >&2; exit 1; }
    install -d -o "$user_uid" -g "$user_gid" "$user_home/Projects"
    cp -a -- "$repo_dir" "$destination"
    jq -r '.extra.host' "$config" > "$destination/host"
    chown -R "$user_uid:$user_gid" "$destination"
    repo_dir=$destination
    config=$repo_dir/user-configuration.json
    ln -sfn -- "$config" /run/system-configuration.json
fi

# Hooks write home configuration into a staging home that is published at the end.
staging=$(mktemp -d)
trap 'rm -rf -- "$staging"' EXIT
export DOTFILES_REPO=$repo_dir USERNAME=$user DOTFILES_DESKTOP
DOTFILES_DESKTOP=$(jq -r '.extra.desktop' "$config")
export HOME=$staging/home
export XDG_CONFIG_HOME=$HOME/.config XDG_DATA_HOME=$HOME/.local/share
export XDG_STATE_HOME=$HOME/.local/state XDG_CACHE_HOME=$HOME/.local/cache
mkdir -p -- "$HOME"

while IFS=$'\t' read -r source target file_mode; do
    if [[ $target == home/* ]]; then
        install -D -m "$file_mode" -- "$repo_dir/$source" "$HOME/${target#home/}"
    else
        [[ ! -L $target ]] || { echo "Refusing to replace a symlink: $target" >&2; exit 1; }
        install -D -o root -g root -m "$file_mode" -- "$repo_dir/$source" "$target"
    fi
done < <(jq -r '.extra.files[] | [.source, .target, .mode] | @tsv' "$config")
while IFS=$'\t' read -r source target; do
    [[ $target != home/* ]] || target=$HOME/${target#home/}
    mkdir -p -- "$(dirname -- "$target")"
    ln -sfnT -- "$repo_dir/$source" "$target"
done < <(jq -r '.extra.symlinks[] | [.source, .target] | @tsv' "$config")

# Package builds run in the shell environment installed above.
bash "$repo_dir/scripts/extra-packages.sh" "$config" "$user"
run_hooks scripts
python3 "$repo_dir/scripts/publish-home.py" "$HOME" "$user_home" "$user_uid" "$user_gid"
