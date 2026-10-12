#!/usr/bin/env bash
set -Eeuo pipefail
# CODEX_HOME must exist before starting Codex.
entry=$(getent passwd "${1:?User required}")
IFS=: read -r _ _ uid gid _ home _ <<< "$entry"
install -d -o "$uid" -g "$gid" -m 0700 "$home/.local/share/codex"
