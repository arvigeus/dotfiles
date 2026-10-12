#!/usr/bin/env bash
# archinstall/pacman own repository packages. These are the remaining app formats.
set -euo pipefail
run_as_user() {
    runuser -u "$user" -- env HOME="$user_home" \
        XDG_CONFIG_HOME="$user_home/.config" XDG_DATA_HOME="$user_home/.local/share" \
        XDG_STATE_HOME="$user_home/.local/state" XDG_CACHE_HOME="$user_home/.local/cache" \
        bash -lc 'exec "$@"' bash "$@"
}
mapfile -t aur < <(jq -r '.extra.aur_packages[]?' "$config")
if ((${#aur[@]})); then
    build_dir=$(mktemp -d)
    sudoers=/etc/sudoers.d/package-build
    [[ ! -e $sudoers && ! -L $sudoers ]] || { echo "Build sudoers file already exists: $sudoers" >&2; exit 1; }
    trap 'rm -rf -- "$build_dir"; rm -f -- "$sudoers"' EXIT
    printf '%s ALL=(root) NOPASSWD: /usr/bin/pacman\n' "$user" > "$build_dir/sudoers"
    chmod 0440 "$build_dir/sudoers"
    visudo --check
    grep -Eq '^[[:space:]]*(@includedir|#includedir)[[:space:]]+/etc/sudoers.d([[:space:]]|$)' /etc/sudoers || {
        echo 'Expected /etc/sudoers to include /etc/sudoers.d.' >&2; exit 1;
    }
    visudo --check --file "$build_dir/sudoers"
    install -o root -g root -m 0440 "$build_dir/sudoers" "$sudoers"
    chown "$user:" "$build_dir"
    build() {
        local directory=$1
        shift
        # shellcheck disable=SC2016
        run_as_user bash -c \
            'cd -- "$1"; shift; makepkg --noconfirm --syncdeps --install --clean "$@"' bash "$directory" "$@"
    }
    if ((${#aur[@]})); then
        if ! run_as_user paru --version >/dev/null 2>&1; then
            run_as_user git clone --depth 1 https://aur.archlinux.org/paru.git "$build_dir/paru"
            build "$build_dir/paru"
        fi
        run_as_user paru --version
        run_as_user paru --noconfirm --needed -S -- "${aur[@]}"
    fi

fi
flatpak_command() (
    flatpak_home=$(mktemp -d /home/.flatpak.XXXXXX)
    trap 'rm -rf -- "$flatpak_home"' EXIT
    HOME="$flatpak_home" XDG_CONFIG_HOME="$flatpak_home/.config" XDG_DATA_HOME="$flatpak_home/.local/share" flatpak "$@"
)
while IFS=$'\t' read -r remote url; do
    flatpak_command remote-add --system --if-not-exists "$remote" "$url"
done < <(jq -r '.extra.flatpak.remotes | to_entries[] | [.key, .value] | @tsv' "$config")
while IFS=$'\t' read -r remote app; do
    flatpak_command install --system --noninteractive -y "$remote" "$app"
done < <(jq -r '.extra.flatpak.packages[] | [.remote, .app] | @tsv' "$config")
