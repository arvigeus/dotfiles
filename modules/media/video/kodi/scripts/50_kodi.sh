#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir=${DOTFILES_REPO:?}

source "$repo_dir/scripts/config-helpers.sh"

# Zephyrus provides its own media interface on Hyprland.

# playercorefactory.xml launches host mpv.

KODI_APP_ID="tv.kodi.Kodi"
KODI_RELEASE="omega"

configure() {

    KODI_TMP_ROOT=$(mktemp -d)
    trap 'rm -rf -- "$KODI_TMP_ROOT"' EXIT

    KODI_DATA_DIR="${HOME}/.var/app/${KODI_APP_ID}/data"
    KODI_USERDATA_DIR="${KODI_DATA_DIR}/userdata"
    KODI_ADDONS_DIR="${KODI_DATA_DIR}/addons"
    KODI_GUISETTINGS="${KODI_USERDATA_DIR}/guisettings.xml"
    KODI_OFFICIAL_ADDON_REPO_BASE="https://mirrors.kodi.tv/addons/${KODI_RELEASE}"

    # Kodi/Arctic Fuse ratings and metadata
    # KODI_OMDB_API_KEY=
    # KODI_MDBLIST_API_KEY=
    # KODI_TRAKT_TOKEN=

    # Add-on source values are classified automatically:
    # - repository base URL: resolve latest <addon-id>-<version>.zip
    # - addons.xml URL: resolve add-on and same-repository dependencies
    # - zip URL: install directly
    declare -A KODI_ADDONS=(
        # Program add-ons
        ["plugin.video.mms"]="${KODI_OFFICIAL_ADDON_REPO_BASE}"
        ["script.metadata.editor"]="${KODI_OFFICIAL_ADDON_REPO_BASE}"

        # Skins
        ["skin.bingie"]="https://raw.githubusercontent.com/matke-84/repository.bingie/main/${KODI_RELEASE}/addons.xml"
        ["skin.arctic.fuse.3"]="https://raw.githubusercontent.com/jurialmunkey/repository.jurialmunkey/master/${KODI_RELEASE}/zips/addons.xml"

        # Subtitles
        ["service.subtitles.a4ksubtitles"]="https://github.com/a4k-openproject/a4kSubtitles/archive/refs/heads/master.zip"

        # Universal Movie Scraper is intentionally not installed: the wiki recommends
        # metadata.universal.python, but the Omega mirror currently exposes only the
        # broken legacy metadata.universal add-on.
    )

    declare -A KODI_GUI_SETTINGS=(
        ["musiclibrary.updateonstartup"]=true
        ["musiclibrary.backgroundupdate"]=true
        ["videolibrary.updateonstartup"]=true
        ["videolibrary.backgroundupdate"]=true
    )

    KODI_ADDON_ZIPS=()
    KODI_INSTALLED_ADDONS=()
    declare -A KODI_SCHEDULED_ADDONS=()
    declare -A KODI_UNRESOLVED_DEPENDENCIES=()

    mkdir -p "${KODI_USERDATA_DIR}" "${KODI_ADDONS_DIR}"

    die() {
        printf '[kodi] ERROR: %s\n' "$*" >&2
        exit 1
    }

    schedule_addon_zip() {
        local addon_id="$1" zip_url="$2"

        [[ -z "${KODI_SCHEDULED_ADDONS[$addon_id]+x}" ]] || return 0
        KODI_SCHEDULED_ADDONS["$addon_id"]=1
        KODI_ADDON_ZIPS+=("$zip_url")
    }

    latest_addon_zip_url() {
        local addon_id="$1" repo_base="$2"
        local index_url="${repo_base%/}/${addon_id}/"
        local index_file pattern latest_zip

        index_file=$(mktemp "$KODI_TMP_ROOT/index.XXXXXX")
        if ! curl -fsSL --connect-timeout 20 --max-time 120 \
            --retry 3 --retry-all-errors "$index_url" > "$index_file"; then
            rm -f "$index_file"
            return 1
        fi
        pattern="${addon_id}"'-[0-9][^"/]*[.]zip'
        latest_zip=$(
            grep -Eo "$pattern" "$index_file" |
                sort -V |
                tail -1
        )
        rm -f "$index_file"
        [[ -n "$latest_zip" ]] || return 1
        printf '%s\n' "${index_url}${latest_zip}"
    }

    install_latest_addons() {
        local addon_id="$1" repo_base="$2" zip_url

        zip_url=$(latest_addon_zip_url "$addon_id" "$repo_base") ||
            die "could not find latest zip for ${addon_id} at ${repo_base%/}/${addon_id}/"
        schedule_addon_zip "$addon_id" "$zip_url"
    }

    schedule_official_dependency() {
        local addon_id="$1"
        local zip_url

        [[ -z "${KODI_SCHEDULED_ADDONS[$addon_id]+x}" ]] || return 0
        [[ -z "${KODI_UNRESOLVED_DEPENDENCIES[$addon_id]+x}" ]] || return 0
        if zip_url=$(latest_addon_zip_url "$addon_id" "$KODI_OFFICIAL_ADDON_REPO_BASE" 2> /dev/null); then
            printf '[kodi] Resolved official dependency %s: %s\n' "$addon_id" "$zip_url"
            schedule_addon_zip "$addon_id" "$zip_url"
        else
            KODI_UNRESOLVED_DEPENDENCIES["$addon_id"]=1
            printf '[kodi] Could not resolve dependency %s from the official Kodi repo; Kodi must resolve it from enabled repositories\n' "$addon_id"
        fi
    }

    repository_datadir() {
        local addons_xml="$1" addons_xml_url="$2"
        local datadir

        datadir=$(xmlstarlet sel -t -v "(/addons/addon/extension[@point='xbmc.addon.repository']/dir/datadir)[1]" "$addons_xml")
        if [[ -z "$datadir" ]]; then
            datadir="${addons_xml_url%/*}"
        fi
        printf '%s\n' "$datadir"
    }

    repository_addon_zip_url() {
        local addons_xml="$1" addons_xml_url="$2" addon_id="$3"
        local datadir version

        datadir=$(repository_datadir "$addons_xml" "$addons_xml_url")
        version=$(xmlstarlet sel -t -v "/addons/addon[@id='${addon_id}']/@version" "$addons_xml")
        [[ -n "$version" ]] || die "could not find ${addon_id} in ${addons_xml_url}"
        printf '%s\n' "${datadir%/}/${addon_id}/${addon_id}-${version}.zip"
    }

    repository_addon_dependencies() {
        local addons_xml="$1" addon_id="$2"
        xmlstarlet sel -t \
            -m "/addons/addon[@id='${addon_id}']/requires/import[not(@optional='true')]/@addon" \
            -v . -n \
            "$addons_xml" |
            grep -Ev '^(xbmc|kodi)[.]' || true
    }

    addon_file_dependencies() {
        local addon_xml="$1"
        xmlstarlet sel -t \
            -m "/addon/requires/import[not(@optional='true')]/@addon" \
            -v . -n \
            "$addon_xml" |
            grep -Ev '^(xbmc|kodi)[.]' || true
    }

    repository_has_addon() {
        local addons_xml="$1" addon_id="$2"
        [[ "$(xmlstarlet sel -t -v "count(/addons/addon[@id='${addon_id}'])" "$addons_xml")" != "0" ]]
    }

    install_repository_addon_tree() {
        local addons_xml="$1" addons_xml_url="$2" addon_id="$3"
        local dependency zip_url

        [[ -z "${_KODI_REPOSITORY_ADDON_SEEN[$addon_id]+x}" ]] || return 0
        _KODI_REPOSITORY_ADDON_SEEN["$addon_id"]=1

        while IFS= read -r dependency; do
            [[ -n "$dependency" ]] || continue
            if repository_has_addon "$addons_xml" "$dependency"; then
                install_repository_addon_tree "$addons_xml" "$addons_xml_url" "$dependency"
            elif [[ -n "${KODI_SCHEDULED_ADDONS[$dependency]+x}" ]]; then
                continue
            else
                schedule_official_dependency "$dependency"
            fi
        done < <(repository_addon_dependencies "$addons_xml" "$addon_id")

        zip_url=$(repository_addon_zip_url "$addons_xml" "$addons_xml_url" "$addon_id")
        schedule_addon_zip "$addon_id" "$zip_url"
    }

    install_addon_zips() {
        ((${#KODI_ADDON_ZIPS[@]} > 0)) || return 0

        local zip_ref tmpdir zip addon_xml addon_src addon_id dependency i
        for ((i = 0; i < ${#KODI_ADDON_ZIPS[@]}; i++)); do
            zip_ref="${KODI_ADDON_ZIPS[$i]}"
            tmpdir=$(mktemp -d "$KODI_TMP_ROOT/addon.XXXXXX")
            zip="${tmpdir}/addon.zip"
            curl -fsSL --connect-timeout 20 --max-time 300 \
                --retry 3 --retry-all-errors "$zip_ref" -o "$zip"
            unzip -q "$zip" -d "$tmpdir/unpacked"
            addon_xml=$(find "$tmpdir/unpacked" -mindepth 2 -maxdepth 2 -type f -name addon.xml | head -1)
            [[ -n "$addon_xml" ]] || die "zip does not contain an add-on addon.xml: ${zip_ref}"
            addon_src=$(dirname "$addon_xml")
            addon_id=$(xmlstarlet sel -t -v '/addon/@id' "$addon_xml")
            [[ -n "$addon_id" ]] || die "could not read add-on id from ${addon_xml}"
            while IFS= read -r dependency; do
                [[ -n "$dependency" ]] || continue
                [[ -n "${KODI_SCHEDULED_ADDONS[$dependency]+x}" ]] && continue
                schedule_official_dependency "$dependency"
            done < <(addon_file_dependencies "$addon_xml")
            rm -rf "${KODI_ADDONS_DIR:?}/${addon_id}"
            cp -a "$addon_src" "${KODI_ADDONS_DIR}/${addon_id}"
            KODI_INSTALLED_ADDONS+=("$addon_id")
            rm -rf "$tmpdir"
        done
    }

    install_configured_addons() {
        ((${#KODI_ADDONS[@]} > 0)) || return 0

        declare -A _KODI_REPOSITORY_ADDON_SEEN=()
        local addon_id source addons_xml

        for addon_id in "${!KODI_ADDONS[@]}"; do
            source="${KODI_ADDONS[$addon_id]}"
            case "$source" in
                *addons.xml*)
                    addons_xml=$(mktemp "$KODI_TMP_ROOT/repository.XXXXXX")
                    curl -fsSL --connect-timeout 20 --max-time 120 \
                        --retry 3 --retry-all-errors "$source" -o "$addons_xml"
                    install_repository_addon_tree "$addons_xml" "$source" "$addon_id"
                    rm -f "$addons_xml"
                    ;;
                *.zip | *.zip\?*)
                    schedule_addon_zip "$addon_id" "$source"
                    ;;
                *)
                    install_latest_addons "$addon_id" "$source"
                    ;;
            esac
        done
    }

    ensure_guisettings_xml() {
        if [[ -s "$KODI_GUISETTINGS" ]]; then
            xmlstarlet val -q "$KODI_GUISETTINGS" ||
                die "invalid XML in ${KODI_GUISETTINGS}"
            return 0
        fi

        file_write "$KODI_GUISETTINGS" << 'GUISETTINGS'
<settings version="2">
</settings>
GUISETTINGS
    }

    set_guisetting() {
        local setting_id="$1" value="$2"
        local setting_xpath="/settings/setting[@id='${setting_id}']"

        if [[ "$(xmlstarlet sel -t -v "count(${setting_xpath})" "$KODI_GUISETTINGS")" == "0" ]]; then
            xmlstarlet ed -L \
                -s /settings -t elem -n setting -v "$value" \
                -i "/settings/setting[last()]" -t attr -n id -v "$setting_id" \
                "$KODI_GUISETTINGS"
        else
            xmlstarlet ed -L -u "$setting_xpath" -v "$value" "$KODI_GUISETTINGS"
        fi
    }

    apply_guisettings() {
        ((${#KODI_GUI_SETTINGS[@]} > 0)) || return 0

        local setting_id
        ensure_guisettings_xml
        for setting_id in "${!KODI_GUI_SETTINGS[@]}"; do
            set_guisetting "$setting_id" "${KODI_GUI_SETTINGS[$setting_id]}"
        done
    }

    install_configured_addons
    install_addon_zips
    apply_guisettings

    # Allow playercorefactory.xml to launch host mpv through flatpak-spawn.

    # SMPlayer: <args>--host /usr/bin/flatpak run --branch=stable --arch=x86_64 --command=smplayer --file-forwarding info.smplayer.SMPlayer "{1}"</args>

}

configure
