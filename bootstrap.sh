#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

command -v archinstall >/dev/null || {
    echo 'archinstall is required; run this from the Arch Linux ISO.' >&2
    exit 1
}
for command in jq tar base64; do
    command -v "$command" >/dev/null || { echo "$command is required." >&2; exit 1; }
done

read -r -p 'Username to create in archinstall and configure: ' dotfiles_user
[[ $dotfiles_user =~ ^[a-z_][a-z0-9_-]*\$?$ ]] || { echo 'Invalid username.' >&2; exit 1; }

"$repo_dir/generate-config.py"
runtime_dir=$(mktemp -d)
trap 'rm -rf -- "$runtime_dir"' EXIT

# Carry this exact checkout into the target through archinstall's chroot hook.
tar -czf "$runtime_dir/repo.tar.gz" -C "$repo_dir" \
    --exclude='./.agents' --exclude='./.aws' --exclude='./.codex' \
    --exclude='./__pycache__' .
base64 -w0 "$runtime_dir/repo.tar.gz" > "$runtime_dir/payload"
printf -v quoted_user '%q' "$dotfiles_user"
cat > "$runtime_dir/postinstall" <<EOF
set -euo pipefail
staging=\$(mktemp -d)
trap 'rm -rf -- "\$staging"' EXIT
printf '%s' '$(cat "$runtime_dir/payload")' | base64 -d | tar -xz -C "\$staging"
bash "\$staging/postinstall.sh" $quoted_user
EOF
printf -v postinstall_command 'bash -euo pipefail -c %q' "$(cat "$runtime_dir/postinstall")"
printf '%s' "$postinstall_command" > "$runtime_dir/command"
jq --rawfile command "$runtime_dir/command" \
    '.custom_commands = [$command] + (.custom_commands // [])' \
    "$repo_dir/user-configuration.json" > "$runtime_dir/user-configuration.json"
archinstall --config "$runtime_dir/user-configuration.json" "$@"
