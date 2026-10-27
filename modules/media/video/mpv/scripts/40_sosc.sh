#!/usr/bin/env bash
set -Eeuo pipefail
commit=5491dbdd9286d3a6da4bb6976d914a7f82dc0727
checksum=986857997e1739960b35a6c8161b6ce2b6f221ee341e95e1948c39a32821533e
temporary=$(mktemp -d)
trap 'rm -rf -- "$temporary"' EXIT
curl --fail --location --silent --show-error --retry 3 \
    --connect-timeout 20 --max-time 120 \
    "https://github.com/christoph-heinrich/sosc/archive/$commit.tar.gz" \
    --output "$temporary/sosc.tar.gz"
printf '%s  %s\n' "$checksum" "$temporary/sosc.tar.gz" | sha256sum --check --status
tar -xzf "$temporary/sosc.tar.gz" -C "$temporary"
install -Dm0644 "$temporary/sosc-$commit/osc.lua" "${DOTFILES_SYSTEM_STAGE:-}/etc/mpv/scripts/osc.lua"
install -Dm0644 "$temporary/sosc-$commit/LICENSE" "${DOTFILES_SYSTEM_STAGE:-}/usr/share/licenses/mpv-sosc/LICENSE"
