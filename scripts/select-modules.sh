#!/usr/bin/env bash
# Included by generation and apply scripts so both select the same modules.
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
dotfiles_host=${DOTFILES_HOST:-$(cat "$repo_dir/host")}
[[ $dotfiles_host =~ ^[a-zA-Z0-9_-]+$ && -d $repo_dir/modules/hosts/$dotfiles_host ]] || {
    echo "Unknown host: $dotfiles_host" >&2; exit 1;
}
export DOTFILES_HOST="$dotfiles_host"
module_dirs=()
while IFS= read -r -d '' directory; do
    case "$directory" in
        "$repo_dir/modules/hosts/"*)
            [[ $directory == "$repo_dir/modules/hosts/$dotfiles_host" ]] || continue
            ;;
    esac
    if [[ -f $directory/hosts ]] && ! grep -Fxq -- "$dotfiles_host" "$directory/hosts"; then
        continue
    fi
    module_dirs+=("$directory")
done < <(find "$repo_dir/modules" \
    -type d -name files ! -path "$repo_dir/modules/files" -printf '%h\0' -prune -o \
    -type f \( -name '*.json' -o -name '*.jsonc' -o -name config.sh \
        -o -name postinstall.sh -o -name check.sh \) -printf '%h\0' | sort -zu)
