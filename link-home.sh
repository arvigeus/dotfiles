#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
backup_dir=
sources=()
declare -A destinations=()

while IFS= read -r -d '' source; do
    relative=${source#*/files/home/}
    if [[ -v destinations[$relative] ]]; then
        echo "Multiple modules provide $relative" >&2
        exit 1
    fi
    destinations[$relative]=$source
    sources+=("$source")
done < <(find "$repo_dir/modules" -type f -path '*/files/home/*' -print0 | sort -z)

for source in "${sources[@]}"; do
    relative=${source#*/files/home/}
    target="$HOME/$relative"
    # A parent link would redirect writes into its source rather than HOME.
    parent=$(dirname -- "$target")
    while [[ $parent != "$HOME" && $parent != / ]]; do
        if [[ -L $parent ]]; then
            echo "Refusing to link through directory symlink: $parent" >&2
            exit 1
        fi
        parent=$(dirname -- "$parent")
    done
    if [[ -L $target && $(readlink -- "$target") == "$source" ]]; then
        continue
    fi
    mkdir -p -- "$(dirname -- "$target")"
    if [[ -e $target || -L $target ]]; then
        if [[ -z $backup_dir ]]; then
            mkdir -p -- "$HOME/.local/state/dotfiles"
            backup_dir=$(mktemp -d "$HOME/.local/state/dotfiles/backup.XXXXXXXX")
        fi
        mkdir -p -- "$backup_dir/$(dirname -- "$relative")"
        mv -- "$target" "$backup_dir/$relative"
    fi
    ln -s -- "$source" "$target"
done

[[ -z $backup_dir ]] || echo "Previous files saved to $backup_dir"
