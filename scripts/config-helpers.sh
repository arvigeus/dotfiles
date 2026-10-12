#!/usr/bin/env bash
# Atomic config writes; HOME is a staging directory during system setup.
file_write() {
    local mode=0644 destination temporary
    if [[ ${1:-} == -m ]]; then mode=$2; shift 2; fi
    destination=${1:?Destination required}
    mkdir -p -- "$(dirname -- "$destination")"
    temporary=$(mktemp "${destination}.tmp.XXXXXX")
    cat > "$temporary"
    chmod "$mode" "$temporary"
    mv -Tf -- "$temporary" "$destination"

}
file_append() {
    local destination=${1:?Destination required}
    { [[ ! -f $destination ]] || cat -- "$destination"; cat; } | file_write "$destination"
}
home_link() {
    mkdir -p -- "$(dirname -- "$2")"
    ln -sfnT -- "$1" "$2"
}
