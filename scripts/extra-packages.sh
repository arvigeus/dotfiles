#!/usr/bin/env bash
# Install AUR, Cargo and Flatpak packages; archinstall/pacman own repository packages.
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
    [[ ! -e $sudoers && ! -L $sudoers ]] || { echo "Build sudoers file already exists: $sudoers" >&2; exit 1; }
    trap 'rm -rf -- "$build_dir"; rm -f -- "$sudoers"' EXIT
    # makepkg and paru call sudo pacman; allow only that during the build.
    printf '%s ALL=(root) NOPASSWD: /usr/bin/pacman\n' "$user" > "$build_dir/sudoers"
    visudo --check --quiet --file "$build_dir/sudoers"
    install -o root -g root -m 0440 "$build_dir/sudoers" "$sudoers"
    chown "$user:" "$build_dir"
    if ! run_as_user paru --version >/dev/null 2>&1; then
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
