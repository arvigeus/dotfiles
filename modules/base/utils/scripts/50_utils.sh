#!/usr/bin/env bash
## Small baseline command-line utilities
set -Eeuo pipefail
repo_dir=${DOTFILES_REPO:?}

source "$repo_dir/scripts/config-helpers.sh"

configure() {
	# Keep less history out of $HOME root, in the XDG state location.
	install -d -m 0755 "$HOME/.local/state/less"
}

configure
