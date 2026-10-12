#!/usr/bin/env bash
## Python development with uv, Ruff and ty; pip for compatibility
## https://www.python.org/ https://docs.astral.sh/uv/
set -Eeuo pipefail
repo_dir=${DOTFILES_REPO:?}

source "$repo_dir/scripts/config-helpers.sh"

configure() {
	# Keep the REPL history out of $HOME root, in the XDG state location
	# (honored by Python 3.13+; ignored by older versions).
	# Pin the pip cache to its XDG-default location so an unset XDG_*
	# var cannot push it elsewhere. Values stay unexpanded until login.
	install -d -m 0755 "$HOME/.local/state/python" "${XDG_CACHE_HOME:-$HOME/.local/cache}/pip"
}

configure
