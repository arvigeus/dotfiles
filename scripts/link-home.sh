#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source "$repo_dir/scripts/select-modules.sh"
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
done < <(find "${module_dirs[@]}" -type f -path '*/files/home/*' -print0 | sort -zu)

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
    ln -sfnT -- "$source" "$target"
done
