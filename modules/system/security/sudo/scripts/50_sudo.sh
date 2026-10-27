#!/usr/bin/env bash
set -Eeuo pipefail
# The encrypted boot and lock screen remain the authentication boundaries;
# interactive sudo is deliberately passwordless for this personal workstation.
rule=$(mktemp)
trap 'rm -f -- "$rule"' EXIT
printf '%s ALL=(ALL:ALL) NOPASSWD: ALL\n' "${USERNAME:?}" > "$rule"
visudo --check --quiet --file "$rule"
install -D -m 0440 -o root -g root -- "$rule" "${DOTFILES_SYSTEM_STAGE:-}/etc/sudoers.d/10-$USERNAME"
