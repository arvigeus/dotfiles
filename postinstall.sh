#!/usr/bin/env bash
set -euo pipefail

user=${1:?Usage: postinstall.sh USER}
dotfiles_host=${2:-$(cat "$(dirname -- "${BASH_SOURCE[0]}")/host")}
[[ $EUID == 0 ]] || { echo 'Run postinstall as root in the installed system.' >&2; exit 1; }
entry=$(getent passwd "$user")
IFS=: read -r name password uid gid gecos user_home shell <<< "$entry"
[[ $uid != 0 && $user_home == /* && $user_home != / ]] || {
    echo 'Expected a regular user with an absolute home directory.' >&2
    exit 1
}
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
destination="$user_home/Projects/dotfiles"
[[ ! -e $destination && ! -L $destination ]] || {
    echo "Refusing to overwrite existing checkout: $destination" >&2
    exit 1
}
install -d -o "$uid" -g "$gid" "$user_home/Projects"
cp -a -- "$repo_dir" "$destination"
printf '%s\n' "$dotfiles_host" > "$destination/host"
chown -R "$uid:$gid" "$destination"
SUDO_USER="$user" DOTFILES_HOST="$dotfiles_host" DOTFILES_INSTALLING=1 bash "$destination/scripts/apply-system.sh"
runuser -u "$user" -- env HOME="$user_home" DOTFILES_HOST="$dotfiles_host" "$destination/scripts/link-home.sh"
