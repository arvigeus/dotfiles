#!/usr/bin/env bash
# Install AUR, Cargo, uv and Flatpak packages; pacman owns repository packages.
# Usage: extra-packages.sh CONFIG USER
set -Eeuo pipefail
config=${1:?Configuration required}
user=${2:?User required}
user_home=$(getent passwd "$user" | cut -d: -f6)
run_as_user() {
    runuser -u "$user" -- env HOME="$user_home" \
        XDG_CONFIG_HOME="$user_home/.config" XDG_DATA_HOME="$user_home/.local/share" \
        XDG_STATE_HOME="$user_home/.local/state" XDG_CACHE_HOME="$user_home/.local/cache" \
        bash -lc 'exec "$@"' bash "$@"
}

mapfile -t aur < <(jq -r '.extra.aur_packages[]' "$config")
if ((${#aur[@]})); then
    build_dir=$(mktemp -d)
    sudoers=/etc/sudoers.d/package-build
    [[ ! -e $sudoers && ! -L $sudoers ]] || {
        echo "Build sudoers file already exists: $sudoers" >&2
        exit 1
    }
    trap 'rm -rf -- "$build_dir"; rm -f -- "$sudoers"' EXIT
    # makepkg and paru call sudo pacman; allow only that during the build.
    printf '%s ALL=(root) NOPASSWD: /usr/bin/pacman\n' "$user" > "$build_dir/sudoers"
    visudo --check --quiet --file "$build_dir/sudoers"
    install -o root -g root -m 0440 "$build_dir/sudoers" "$sudoers"
    chown "$user:" "$build_dir"
    if ! run_as_user paru --version > /dev/null 2>&1; then
        run_as_user git clone --depth 1 https://aur.archlinux.org/paru.git "$build_dir/paru"
        # shellcheck disable=SC2016
        run_as_user bash -c 'cd -- "$1" && makepkg --noconfirm --syncdeps --install --clean' bash "$build_dir/paru"
    fi
    # Resolve these exact AUR targets, not a differently named repository
    # provider (for example arkenfox-user.js-git for arkenfox-user.js).
    run_as_user paru --aur --noconfirm --needed -S -- "${aur[@]}"
fi

while IFS= read -r crate; do
    run_as_user env CARGO_HOME="$user_home/.local/share/cargo" cargo install --locked -- "$crate"
done < <(jq -r '.extra.cargo_packages[]?' "$config")

# Manage uv tools declared by selected modules. Keep a small ownership list so
# removing a module uninstalls only tools that this executor previously added.
mapfile -t uv_tools < <(jq -r '.extra.uv_tools[]? | [.name, .source] | @tsv' "$config")
uv_state_dir="$user_home/.local/state/dotfiles"
uv_state="$uv_state_dir/uv-tools"
if ((${#uv_tools[@]})) || [[ -f $uv_state ]]; then
    install -d -o "$user" -g "$(id -gn "$user")" -m 0700 "$uv_state_dir"
    mapfile -t previous_uv_tools < <(cat "$uv_state" 2>/dev/null || true)
    declared_uv_names=()
    managed_uv_names=()
    uv_failures=()
    remember_managed_uv_tool() {
        local candidate
        for candidate in "${managed_uv_names[@]}"; do
            [[ $candidate == "$1" ]] && return
        done
        managed_uv_names+=("$1")
    }
    report_uv_failure() {
        local action=$1 status=$2
        uv_failures+=("$action")
        printf 'Warning: uv tool %s failed (exit %s); continuing apply.\n' \
            "$action" "$status" >&2
    }
    for spec in "${uv_tools[@]}"; do
        IFS=$'\t' read -r name source extra <<< "$spec"
        [[ $name =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ && -n $source && -z $extra &&
            $source != -* && ! $source =~ [[:space:]] ]] || {
            echo "Invalid uv tool declaration: $spec" >&2
            exit 1
        }
        declared_uv_names+=("$name")
        if run_as_user uv tool install --upgrade --from "$source" "$name"; then
            remember_managed_uv_tool "$name"
        else
            status=$?
            report_uv_failure "install/update $name" "$status"
            # Keep managing an existing installation so a later apply can retry
            # the update and removing the declaration can still uninstall it.
            if [[ " ${previous_uv_tools[*]} " == *" $name "* ]]; then
                remember_managed_uv_tool "$name"
            fi
        fi
    done
    for name in "${previous_uv_tools[@]}"; do
        [[ -n $name ]] || continue
        [[ $name =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || {
            echo "Invalid managed uv tool name in $uv_state: $name" >&2
            exit 1
        }
        if [[ " ${declared_uv_names[*]} " != *" $name "* ]]; then
            if run_as_user uv tool uninstall "$name"; then
                :
            else
                status=$?
                report_uv_failure "uninstall $name" "$status"
                # Retain failed removals in the ownership file for the next apply.
                remember_managed_uv_tool "$name"
            fi
        fi
    done
    state_tmp=$(mktemp "$uv_state_dir/.uv-tools.XXXXXX")
    printf '%s\n' "${managed_uv_names[@]}" > "$state_tmp"
    chown "$user:$(id -gn "$user")" "$state_tmp"
    chmod 0600 "$state_tmp"
    mv -f -- "$state_tmp" "$uv_state"
    if ((${#uv_failures[@]})); then
        printf 'Warning: %d uv tool action(s) failed; other apply steps will continue.\n' \
            "${#uv_failures[@]}" >&2
    fi
fi

flatpak_system() (
    # Flatpak writes per-user state even for system operations; keep it out of the real home.
    flatpak_home=$(mktemp -d /home/.flatpak.XXXXXX)
    trap 'rm -rf -- "$flatpak_home"' EXIT
    HOME=$flatpak_home XDG_CONFIG_HOME=$flatpak_home/.config XDG_DATA_HOME=$flatpak_home/.local/share flatpak "$@"
)
while IFS=$'\t' read -r remote url; do
    flatpak_system remote-add --system --if-not-exists "$remote" "$url"
done < <(jq -r '.extra.flatpak.remotes | to_entries[] | [.key, .value] | @tsv' "$config")
while IFS=$'\t' read -r remote app; do
    flatpak_system install --system --noninteractive -y "$remote" "$app"
done < <(jq -r '.extra.flatpak.packages[] | [.remote, .app] | @tsv' "$config")
