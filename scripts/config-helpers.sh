#!/usr/bin/env bash
# Atomic config writes; HOME is a staging directory during system setup.
file_write() {
    local destination=${1:?Destination required} temporary
    mkdir -p -- "$(dirname -- "$destination")"
    temporary=$(mktemp "$destination.tmp.XXXXXX")
    cat > "$temporary"
    chmod 0644 "$temporary"
    mv -Tf -- "$temporary" "$destination"
}
file_append() {
    local destination=${1:?Destination required}
    { [[ ! -f $destination ]] || cat -- "$destination"; cat; } | file_write "$destination"
}
