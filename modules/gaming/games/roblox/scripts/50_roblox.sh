#!/usr/bin/env bash
## Roblox through Sober
## https://www.roblox.com/
set -Eeuo pipefail
repo_dir=${DOTFILES_REPO:?}

source "$repo_dir/scripts/config-helpers.sh"
source "$repo_dir/scripts/helpers/flatpak.sh"

configure() {
	flatpak_override --device=input org.vinegarhq.Sober
}

configure
