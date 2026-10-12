#!/usr/bin/env bash
## Interactive shell defaults shared across shell environments
set -Eeuo pipefail
repo_dir=${DOTFILES_REPO:?}

source "$repo_dir/scripts/config-helpers.sh"

configure() {
	# List completions on first Tab when ambiguous, instead of beeping and requiring a second Tab.
	sed -i '/^set show-all-if-ambiguous on$/d' /etc/inputrc
	file_append /etc/inputrc <<'EOF'
set show-all-if-ambiguous on
EOF
}

configure
