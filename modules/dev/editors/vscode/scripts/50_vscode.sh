#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir=${DOTFILES_REPO:?}
source "$repo_dir/scripts/config-helpers.sh"

# Extension declarations contribute settings to the user's Code - OSS profile.
# shellcheck disable=SC2016 # jq owns the variables in its program.
file_write "$HOME/.config/Code - OSS/User/settings.json" jq '
    .extra.vscode
    | reduce .extensions[] as $settings (.settings; . * $settings)
' /run/system-configuration.json
