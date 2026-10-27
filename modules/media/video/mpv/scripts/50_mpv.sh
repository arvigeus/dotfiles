#!/usr/bin/env bash
## mpv media player with shaders and plugins
## https://mpv.io/
set -Eeuo pipefail
repo_dir=${DOTFILES_REPO:?}

source "$repo_dir/scripts/config-helpers.sh"

SHADERS_DIR="${MPV_SHADERS_DIR:-/usr/share/mpv-shim-default-shaders/shaders}"
PACK_JSON="${MPV_SHADER_PACK:-/usr/share/mpv-shim-default-shaders/pack-next.json}"
MPV_CONF_DIR="${MPV_CONF_DIR:-$HOME/.config/mpv}"

configure() {
    # Physical GA402RK comparisons found VA-API/OpenGL substantially cheaper
    # than the original Vulkan/software-decoding path for tested H.264 playback.
    # Keep driver and codec discovery automatic.
    if grep -qi ga402rk /sys/class/dmi/id/product_name 2> /dev/null; then
        file_append "${MPV_CONF_DIR}/mpv.conf" << 'EOF'
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
    file_append "${MPV_CONF_DIR}/mpv.conf" << 'HEADER'
# Auto-generated from https://github.com/iwalton3/default-shader-pack/blob/master/pack-next.json
HEADER
    # shellcheck disable=SC2016 # jq owns the variables in its program.
    file_append "${MPV_CONF_DIR}/mpv.conf" jq -r --arg sd "${SHADERS_DIR}" '
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
    "profile=standard",
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
' "${PACK_JSON}"

    # Convenience aliases for long profile names
    file_append "${MPV_CONF_DIR}/mpv.conf" << 'EOF'
[fsr]
profile=AMD FidelityFX Super Resolution

[cas]
profile=AMD FidelityFX Contrast Adaptive Sharpening

EOF

    # Resume global options after the generated profile sections.
    file_append "${MPV_CONF_DIR}/mpv.conf" << 'EOF'

[default]
profile=standard

EOF

    # Generate input.conf menu entries for profiles without manual keybindings
    BOUND_PROFILES="AMD FidelityFX Super Resolution|generic-high|nnedi-very-high|anime4k-high-a|anime4k-high-b|anime4k-high-c|anime4k-high-aa|anime4k-high-bb|anime4k-high-ca"
    # shellcheck disable=SC2016 # jq owns the variables in its program.
    file_append "${MPV_CONF_DIR}/input.conf" jq -r --arg skip "$BOUND_PROFILES" '
    def menu_name:
        if .key == "AMD FidelityFX Contrast Adaptive Sharpening" then "Sharpen"
        elif .key == "nvscaler" then "Other > Nvidia"
        elif .key | startswith("anime4k-") then
            (.key | split("-")[2]) as $mode |
            "Anime > Fast > " + ({a: "Blurry", b: "Ringing", c: "Sharp",
                aa: "Blurry+", bb: "Ringing+", ca: "Sharp+"}[$mode] // $mode)
        elif .key == "generic" then "Neural > FSRCNNX"
        elif .key == "artcnn-sharp" then "Neural > ArtCNN Sharp"
        elif .key == "artcnn-high" then "Neural > ArtCNN High"
        elif .key == "nnedi-high" then "Neural > NNEDI"
        elif .key == "artcnn" then "Neural > ArtCNN"
        else .value.displayname // .key end;
    ($skip | split("|")) as $skip_list |
    .profiles | to_entries[] |
    select((.value.platforms // ["linux"]) | index("linux")) |
    select(.key as $k | $skip_list | index($k) | not) |
    menu_name as $label |
    "# apply-profile \"\(.key)\"; show-text \"\($label | split(" > ") | last)\" #! Profiles > \($label)"
' "${PACK_JSON}"
}

configure
