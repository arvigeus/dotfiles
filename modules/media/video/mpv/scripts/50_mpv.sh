#!/usr/bin/env bash
## mpv media player with shaders and plugins
## https://mpv.io/
set -Eeuo pipefail
repo_dir=${DOTFILES_REPO:?}

source "$repo_dir/scripts/config-helpers.sh"
source "$repo_dir/scripts/helpers/hardware.sh"

# Configuration
SHADERS_DIR="${MPV_SHADERS_DIR:-/usr/share/mpv-shim-default-shaders/shaders}"
PACK_JSON="${MPV_SHADER_PACK:-/usr/share/mpv-shim-default-shaders/pack-next.json}"
MPV_CONF_DIR="${MPV_CONF_DIR:-$HOME/.config/mpv}"

configure() {
	# Physical GA402RK comparisons found VA-API/OpenGL substantially cheaper
	# than the original Vulkan/software-decoding path for tested H.264 playback.
	# Keep driver and codec discovery automatic.
	if dmi_matches ga402rk; then
		file_append "${MPV_CONF_DIR}/mpv.conf" <<'EOF'
# GA402RK playback renderer preference
gpu-api=opengl
hwdec=auto-safe
include=/etc/mpv/power-profiles.conf

EOF
	fi
	# Package-owned shader and plugin payloads provide pack-next.json before this
	# configuration phase begins.
	[[ -f $PACK_JSON ]] || {
		printf 'MPV extras package did not install %s\n' "$PACK_JSON" >&2
		return 1
	}

	# Generate mpv profile sections from upstream pack-next.json
	file_append "${MPV_CONF_DIR}/mpv.conf" <<'HEADER'
# Auto-generated from https://github.com/iwalton3/default-shader-pack/blob/master/pack-next.json
HEADER
	jq -r --arg sd "${SHADERS_DIR}" '
    .["setting-groups"] as $g |
    .profiles | to_entries[] |
    select((.value.platforms // ["linux"]) | index("linux")) |
    .key as $n | .value as $p |
    ($p["setting-groups"] // []) as $sgs |
    ([($sgs[] | $g[.].shaders // [] | .[])] + ($p.shaders // [])) as $shaders |
    [($sgs[] | $g[.].settings // [] | .[])] as $settings |
    # The shared pack contains Windows-only D3D11 profiles; mpv validates
    # even inactive profiles and reports unsupported options at every launch.
    "[\($n)]",
    ($settings[] |
        "\(.[0] | gsub("_"; "-"))=\(
            if .[1] == true then "yes"
            elif .[1] == false then "no"
            else .[1] | tostring
            end
        )"
    ),
    ($shaders | to_entries[] |
        if .key == 0 then "glsl-shaders=\($sd)/\(.value)"
        else "glsl-shaders-append=\($sd)/\(.value)"
        end
    ),
    ""
' "${PACK_JSON}" | file_append "${MPV_CONF_DIR}/mpv.conf"

	# Convenience aliases for long profile names
	file_append "${MPV_CONF_DIR}/mpv.conf" <<'EOF'
[fsr]
profile=AMD FidelityFX Super Resolution

[cas]
profile=AMD FidelityFX Contrast Adaptive Sharpening

EOF

	# Custom combo profile (not in upstream shader pack)
	file_append "${MPV_CONF_DIR}/mpv.conf" <<EOF
[fsr-cas]
glsl-shaders=${SHADERS_DIR}/FSR.glsl
glsl-shaders-append=${SHADERS_DIR}/CAS-scaled.glsl
EOF

	# The owner selected generic-high as the default; preserve all other profiles.
	jq -e '.profiles | has("generic-high")' "$PACK_JSON" >/dev/null || {
		printf 'Shader pack is missing the requested generic-high profile.\n' >&2
		return 1
	}
	file_append "${MPV_CONF_DIR}/mpv.conf" <<'EOF'

[default]
profile=generic-high

EOF

	# Generate input.conf menu entries for profiles without manual keybindings
	BOUND_PROFILES="fsr-cas generic-high nnedi-very-high anime4k-high-a anime4k-high-b anime4k-high-c anime4k-high-aa anime4k-high-bb anime4k-high-ca"
	jq -r --arg skip "$BOUND_PROFILES" '
    ($skip | split(" ")) as $skip_list |
    .profiles | to_entries[] |
    select((.value.platforms // ["linux"]) | index("linux")) |
    select(.key as $k | $skip_list | index($k) | not) |
    "# apply-profile \"\(.key)\"; show-text \"Profile: \(.value.displayname // .key)\" #! Profiles > \(.value.displayname // .key)"
' "${PACK_JSON}" | file_append "${MPV_CONF_DIR}/input.conf"
}

configure
