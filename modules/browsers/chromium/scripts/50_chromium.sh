#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir=${DOTFILES_REPO:?}
source "$repo_dir/scripts/config-helpers.sh"
config=$(jq -c '.extra.browsers.chromium' /run/system-configuration.json)
policies=/etc/chromium/policies/managed
# Extensions are declared as Web Store URLs; the policy takes their IDs.
file_write "$policies/extensions.json" jq '{ExtensionInstallForcelist: [.extensions[]
    | (capture("/detail/[^/]+/(?<id>[a-z]+)/?$").id // error("Unrecognized extension URL: \(.)"))
    + ";https://clients2.google.com/service/update2/crx"]}' <<< "$config"
file_write "$policies/web-apps.json" jq '{WebAppInstallForceList: (.web_apps // [])}' <<< "$config"
