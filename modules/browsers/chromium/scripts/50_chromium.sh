#!/usr/bin/env bash
## Chromium and Chrome-compatible browser setup
## https://www.chromium.org/Home/
## https://www.google.com/chrome/
set -Eeuo pipefail
repo_dir=${DOTFILES_REPO:?}

source "$repo_dir/scripts/config-helpers.sh"
chromium_install_extensions() {
	local browsers_config=$1 url extension_id
	local entries=()

	while IFS= read -r url; do
		[[ -n $url ]] || continue
		if [[ $url =~ /detail/[^/]+/([a-zA-Z]+)/?$ ]]; then
			extension_id=${BASH_REMATCH[1]}
		else
			printf 'Could not extract Chromium extension ID from %s\n' "$url" >&2
			return 1
		fi
		entries+=("$extension_id;https://clients2.google.com/service/update2/crx")
	done < <(jq -r '.extensions[]' <<<"$browsers_config")

	printf '%s\n' "${entries[@]}" |
		jq -R -s '{ExtensionInstallForcelist: (split("\n") | map(select(length > 0)))}' |
		file_write /etc/chromium/policies/managed/ported-extensions.json
}



configure() {
	BROWSERS_CONFIG=$(jq -c '.extra.browsers.chromium' /run/system-configuration.json)

	chromium_install_extensions "$BROWSERS_CONFIG"
    jq '{WebAppInstallForceList: (.web_apps // [])}' <<<"$BROWSERS_CONFIG" |
        file_write /etc/chromium/policies/managed/web-apps.json
	# Keep Chrome clean (no extensions)
}

configure
