#!/usr/bin/env bash
# Generated executor; declarations and hook bodies come from user-configuration.json.
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'Run through ./apply.sh or archinstall.' >&2; exit 1; }
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
config="$repo_dir/user-configuration.json"
mode=${CONFIG_MODE:-install}
[[ $mode == live || $mode == install ]] || exit 1
export DOTFILES_REPO="$repo_dir"
export DOTFILES_DESKTOP
DOTFILES_DESKTOP=$(jq -r '.extra.desktop' "$config")
run_steps() {
    local phase=$1 row label script module
    while IFS= read -r row; do
        label=$(jq -r '.module' <<< "$row")
        script=$(jq -r '.script' <<< "$row")
        module="$repo_dir/$label"
        printf '[%s] %s\n' "$phase" "$label"
        MODULE_DIR="$module" bash -Eeuo pipefail -c "$script" bash "$user"
    done < <(jq -c --arg phase "$phase" '.extra[$phase][]?' "$config")
}
if [[ ${1:-} == --pre ]]; then
    user=${SUDO_USER:-}
    run_steps pre
    exit 0
fi
if [[ ${1:-} == --check ]]; then
    user=${SUDO_USER:-}
    run_steps checks
    exit 0
fi
action=${1:---prepare}
context=/run/system-configuration-context
if [[ $action == --run || $action == --finish ]]; then
    [[ -f $context ]] || { echo 'Configuration preparation has not completed.' >&2; exit 1; }
    # shellcheck disable=SC1090
    source "$context"
    if [[ $action == --run ]]; then
        MODULE_DIR="$repo_dir/${2:?Module required}" bash -Eeuo pipefail -c "${3:?Script required}" bash "$user"
        exit 0
    fi
    python3 - "$HOME" "$user_home" "$user_uid" "$user_gid" <<'PUBLISH_HOME'
#!/usr/bin/env python3
"""Copy staged generated files and install staged links into the user's home."""
import os
from pathlib import Path
import shutil
import sys
import tempfile

staging, home = map(Path, sys.argv[1:3])
uid, gid = map(int, sys.argv[3:5])


def check_parents(target):
    for parent in target.parents:
        if parent == home:
            break
        if parent.is_symlink():
            sys.exit(f'Refusing to write through directory symlink: {parent}')


def mkdir_owned(directory):
    if directory.exists():
        return
    mkdir_owned(directory.parent)
    directory.mkdir()
    os.chown(directory, uid, gid)



sources = sorted(staging.rglob('*'))
# Validate all destinations before publishing anything.
for source in sources:
    target = home / source.relative_to(staging)
    check_parents(target)
    if source.is_dir() and not source.is_symlink():
        if target.is_symlink() or (target.exists() and not target.is_dir()):
            sys.exit(f'Refusing to replace home path with a directory: {target}')
    elif target.is_dir() and not target.is_symlink():
        sys.exit(f'Refusing to replace home directory: {target}')

for source in sources:
    relative = source.relative_to(staging)
    target = home / relative
    if source.is_dir() and not source.is_symlink():
        mkdir_owned(target)
        continue
    mkdir_owned(target.parent)
    fd, name = tempfile.mkstemp(prefix='.tmp-', dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        if source.is_symlink():
            temporary.unlink()
            temporary.symlink_to(os.readlink(source))
            os.lchown(temporary, uid, gid)
        else:
            shutil.copyfile(source, temporary)
            temporary.chmod(source.stat().st_mode & 0o777)
            os.chown(temporary, uid, gid)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


PUBLISH_HOME
    rm -rf -- "$staging"
    rm -f -- "$context"
    exit 0
fi
[[ $action == --prepare ]] || { echo "Unknown action: $action" >&2; exit 1; }
# Recover temporary staging left by an interrupted application.
if [[ -f $context ]]; then
    # shellcheck disable=SC1090
    ( source "$context"; rm -rf -- "$staging" )
    rm -f -- "$context"
fi
user=${SUDO_USER:-}
if [[ -z $user ]]; then
    mapfile -t users < <(getent passwd | awk -F: '$3 >= 1000 && $3 < 65534 { print $1 }')
    ((${#users[@]} == 1)) || { echo 'Expected one regular user; set SUDO_USER to select one.' >&2; exit 1; }
    user=${users[0]}
fi
entry=$(getent passwd "$user")
IFS=: read -r _ _ user_uid user_gid _ user_home _ <<< "$entry"
[[ $user_uid != 0 && $user_home == /* && $user_home != / ]] || exit 1
if [[ $mode == install ]]; then
    destination="$user_home/Projects/dotfiles"
    [[ ! -e $destination && ! -L $destination ]] || {
        echo "Checkout already exists: $destination" >&2; exit 1;
    }
    install -d -o "$user_uid" -g "$user_gid" "$user_home/Projects"
    cp -a -- "$repo_dir" "$destination"
    jq -r '.extra.host' "$config" > "$destination/host"
    chown -R "$user_uid:$user_gid" "$destination"
    repo_dir="$destination"
    config="$repo_dir/user-configuration.json"
    ln -sfn -- "$config" /run/system-configuration.json
fi
# archinstall gives each custom command a fresh /tmp through arch-chroot -S.
# Staging must survive until the separate --finish command publishes it.
staging=$(mktemp -d /var/tmp/system-configuration.XXXXXXXX)
trap 'rm -rf -- "$staging"' EXIT
export DOTFILES_REPO="$repo_dir" USERNAME="$user"
export DOTFILES_DESKTOP
DOTFILES_DESKTOP=$(jq -r '.extra.desktop' "$config")
export DOTFILES_INSTALLING=0
[[ $mode == live ]] || DOTFILES_INSTALLING=1
export HOME="$staging/home"
export XDG_CONFIG_HOME="$HOME/.config" XDG_DATA_HOME="$HOME/.local/share"
export XDG_STATE_HOME="$HOME/.local/state" XDG_CACHE_HOME="$HOME/.local/cache"
mkdir -p -- "$HOME"

run_steps checks
install_extra_packages() (
#!/usr/bin/env bash
# archinstall/pacman own repository packages. These are the remaining app formats.
set -euo pipefail
run_as_user() {
    runuser -u "$user" -- env HOME="$user_home" \
        XDG_CONFIG_HOME="$user_home/.config" XDG_DATA_HOME="$user_home/.local/share" \
        XDG_STATE_HOME="$user_home/.local/state" XDG_CACHE_HOME="$user_home/.local/cache" \
        bash -lc 'exec "$@"' bash "$@"
}
mapfile -t aur < <(jq -r '.extra.aur_packages[]?' "$config")
if ((${#aur[@]})); then
    build_dir=$(mktemp -d)
    sudoers=/etc/sudoers.d/package-build
    [[ ! -e $sudoers && ! -L $sudoers ]] || { echo "Build sudoers file already exists: $sudoers" >&2; exit 1; }
    trap 'rm -rf -- "$build_dir"; rm -f -- "$sudoers"' EXIT
    printf '%s ALL=(root) NOPASSWD: /usr/bin/pacman\n' "$user" > "$build_dir/sudoers"
    chmod 0440 "$build_dir/sudoers"
    visudo --check
    grep -Eq '^[[:space:]]*(@includedir|#includedir)[[:space:]]+/etc/sudoers.d([[:space:]]|$)' /etc/sudoers || {
        echo 'Expected /etc/sudoers to include /etc/sudoers.d.' >&2; exit 1;
    }
    visudo --check --file "$build_dir/sudoers"
    install -o root -g root -m 0440 "$build_dir/sudoers" "$sudoers"
    chown "$user:" "$build_dir"
    build() {
        local directory=$1
        shift
        # shellcheck disable=SC2016
        run_as_user bash -c \
            'cd -- "$1"; shift; makepkg --noconfirm --syncdeps --install --clean "$@"' bash "$directory" "$@"
    }
    if ((${#aur[@]})); then
        if ! run_as_user paru --version >/dev/null 2>&1; then
            run_as_user git clone --depth 1 https://aur.archlinux.org/paru.git "$build_dir/paru"
            build "$build_dir/paru"
        fi
        run_as_user paru --version
        run_as_user paru --noconfirm --needed -S -- "${aur[@]}"
    fi

fi
flatpak_command() (
    flatpak_home=$(mktemp -d /home/.flatpak.XXXXXX)
    trap 'rm -rf -- "$flatpak_home"' EXIT
    HOME="$flatpak_home" XDG_CONFIG_HOME="$flatpak_home/.config" XDG_DATA_HOME="$flatpak_home/.local/share" flatpak "$@"
)
while IFS=$'\t' read -r remote url; do
    flatpak_command remote-add --system --if-not-exists "$remote" "$url"
done < <(jq -r '.extra.flatpak.remotes | to_entries[] | [.key, .value] | @tsv' "$config")
while IFS=$'\t' read -r remote app; do
    flatpak_command install --system --noninteractive -y "$remote" "$app"
done < <(jq -r '.extra.flatpak.packages[] | [.remote, .app] | @tsv' "$config")

)
while IFS=$'\t' read -r source target file_mode; do
    source="$repo_dir/$source"
    if [[ $target == home/* ]]; then
        target="$HOME/${target#home/}"
        mkdir -p -- "$(dirname -- "$target")"
        install -D -m "$file_mode" -- "$source" "$target"
        continue
    fi
    [[ ! -L $target ]] || { echo "Refusing system file symlink: $target" >&2; exit 1; }
    previous=
    if [[ $target == /etc/sudoers.d/* ]]; then
        visudo --check
        visudo --check --file "$source"
        grep -Eq '^[[:space:]]*(@includedir|#includedir)[[:space:]]+/etc/sudoers.d([[:space:]]|$)' /etc/sudoers || {
            echo 'Expected /etc/sudoers to include /etc/sudoers.d.' >&2; exit 1;
        }
        if [[ -e $target ]]; then
            previous="$staging/previous"
            cp -a -- "$target" "$previous"
        fi
    fi
    install -D -o root -g root -m "$file_mode" -- "$source" "$target"
    if [[ $target == /etc/sudoers.d/* ]] && ! visudo --check; then
        if [[ -n $previous ]]; then
            cp -a --remove-destination -- "$previous" "$target"
        else
            rm -f -- "$target"
        fi
        exit 1
    fi
    [[ -z $previous ]] || rm -f -- "$previous"
done < <(jq -r '.extra.files[] | [.source, .target, .mode] | @tsv' "$config")
while IFS=$'\t' read -r source target; do
    source="$repo_dir/$source"
    if [[ $target == home/* ]]; then
        target="$HOME/${target#home/}"
    fi
    mkdir -p -- "$(dirname -- "$target")"
    ln -sfnT -- "$source" "$target"
done < <(jq -r '.extra.symlinks[]? | [.source, .target] | @tsv' "$config")
# Package builds inherit the declared shell environment installed above.
install_extra_packages
# Save only this invocation's temporary execution context, never desired state.
( umask 077
  for name in repo_dir config mode user user_uid user_gid user_home staging DOTFILES_REPO USERNAME DOTFILES_DESKTOP DOTFILES_INSTALLING HOME XDG_CONFIG_HOME XDG_DATA_HOME XDG_STATE_HOME XDG_CACHE_HOME; do
      printf 'export %s=%q\n' "$name" "${!name}"
  done > "$context"
)
trap - EXIT
