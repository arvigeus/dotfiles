#!/usr/bin/env bash
## Uncomplicated firewall — persistent default-deny baseline
set -Eeuo pipefail
repo_dir=${DOTFILES_REPO:?}

source "$repo_dir/scripts/config-helpers.sh"

# Do not invoke ufw against the build host's kernel. The packaged defaults are
# edited offline; feature-owned rules are applied serially during boot.
configure() {
	sed -i 's/^DEFAULT_INPUT_POLICY=.*/DEFAULT_INPUT_POLICY="DROP"/' /etc/default/ufw
	sed -i 's/^DEFAULT_OUTPUT_POLICY=.*/DEFAULT_OUTPUT_POLICY="ACCEPT"/' /etc/default/ufw

}

configure
