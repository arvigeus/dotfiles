#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir=${DOTFILES_REPO:?}

source "$repo_dir/scripts/config-helpers.sh"

configure() {
	install -d -m 0750 /etc/sudoers.d
	# The encrypted boot and lock screen remain the authentication boundaries;
	# interactive sudo is deliberately passwordless for this personal workstation.
	printf '%s ALL=(ALL:ALL) NOPASSWD: ALL\n' "$USERNAME" >"/etc/sudoers.d/10-$USERNAME"
	chmod 0440 "/etc/sudoers.d/10-$USERNAME"
	visudo --check --file "/etc/sudoers.d/10-$USERNAME"

	# "please" — polite alias for sudo
}

configure
