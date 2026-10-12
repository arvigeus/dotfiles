#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir=${DOTFILES_REPO:?}

source "$repo_dir/scripts/config-helpers.sh"


configure() {
	# Keep history out of $HOME root, in the XDG state location.
	install -d -m 0755 "$HOME/.local/state/bash"
}

configure
