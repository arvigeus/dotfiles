#!/usr/bin/env bash
set -Eeuo pipefail
version=1.89
checksum=de090c7b9e40f10f225d9393f2cf73a660ad4edc21f6b333eea3190a8722e005
target=/opt/gravity-mark/GravityMark.run
# Compare the installed payload itself; no version/state manifest is needed.
if [[ -f $target ]] && printf '%s  %s\n' "$checksum" "$target" | sha256sum --check --status; then
    exit 0
fi
temporary=$(mktemp -d)
trap 'rm -rf -- "$temporary"' EXIT
curl --fail --location --silent --show-error --retry 3 \
    --connect-timeout 20 --max-time 600 \
    "https://tellusim.com/download/GravityMark_$version.run" \
    --output "$temporary/GravityMark.run"
printf '%s  %s\n' "$checksum" "$temporary/GravityMark.run" | sha256sum --check --status
install -Dm0755 "$temporary/GravityMark.run" "$target"
