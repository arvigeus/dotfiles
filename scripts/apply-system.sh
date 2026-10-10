#!/usr/bin/env bash
set -euo pipefail

[[ $EUID == 0 ]] || { echo 'Run system setup as root.' >&2; exit 1; }
user=${SUDO_USER:?Expected the calling user in SUDO_USER}
[[ $(id -u -- "$user") != 0 ]] || { echo 'Select a regular user.' >&2; exit 1; }
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
sources=()
declare -A destinations=()
staging=$(mktemp -d)
trap 'rm -rf -- "$staging"' EXIT

while IFS= read -r -d '' source; do
    relative=${source#"$repo_dir/modules/"}
    relative=${relative#*/files/}
    [[ $relative != home/* ]] || continue
    [[ ! -v destinations[$relative] ]] || {
        echo "Multiple modules provide /$relative" >&2; exit 1;
    }
    destinations[$relative]=$source
    sources+=("$source")
done < <(find "$repo_dir/modules" -type f -path '*/files/*' -print0 | sort -z)

for source in "${sources[@]}"; do
    relative=${source#"$repo_dir/modules/"}
    relative=${relative#*/files/}
    target="/$relative"
    mode=0644
    [[ ! -x $source ]] || mode=0755
    if [[ $relative == etc/sudoers.d/* ]]; then
        mode=0440
        visudo --check
        visudo --check --file "$source"
        grep -Eq '^[[:space:]]*(@includedir|#includedir)[[:space:]]+/etc/sudoers.d([[:space:]]|$)' /etc/sudoers || {
            echo 'Expected /etc/sudoers to include /etc/sudoers.d.' >&2; exit 1;
        }
    fi
    previous=
    if [[ $relative == etc/sudoers.d/* && -e $target ]]; then
        previous="$staging/previous"
        cp -a -- "$target" "$previous"
    fi
    [[ ! -L $target ]] || { echo "Refusing system file symlink: $target" >&2; exit 1; }
    install -D -o root -g root -m "$mode" -- "$source" "$target"
    if [[ $relative == etc/sudoers.d/* ]] && ! visudo --check; then
        if [[ -n $previous ]]; then
            cp -a --remove-destination -- "$previous" "$target"
        else
            rm -f -- "$target"
        fi
        exit 1
    fi
    [[ -z $previous ]] || rm -f -- "$previous"
done

while IFS= read -r -d '' script; do
    bash "$script" "$user"
done < <(find "$repo_dir/modules" -type f -name postinstall.sh -print0 | sort -z)

