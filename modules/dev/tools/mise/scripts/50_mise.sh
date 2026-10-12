#!/usr/bin/env bash
## mise — per-project runtime version manager
## https://mise.jdx.dev/
set -Eeuo pipefail
repo_dir=${DOTFILES_REPO:?}


configure() {
	# Pin mise state to XDG locations so it never lands in $HOME root.
	install -d -m 0755 "$HOME/.local/share/mise" "${XDG_CACHE_HOME:-$HOME/.local/cache}/mise" "$HOME/.config/mise"
}

configure
