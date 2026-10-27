#!/usr/bin/env bash
# Pass a producer command as arguments so failed generation never publishes
# partial output. With no command, read stdin (for literal here-documents).
_file_publish() (
    local operation=$1 destination=${2:?Destination required} temporary
    shift 2
    if [[ -n ${DOTFILES_SYSTEM_STAGE:-} && $destination == /* && $destination != "$HOME/"* ]]; then
        destination=$DOTFILES_SYSTEM_STAGE$destination
    fi
    (($#)) || set -- cat
    mkdir -p -- "$(dirname -- "$destination")" || exit
    temporary=$(mktemp "$destination.tmp.XXXXXX") || exit
    trap 'rm -f -- "$temporary"' EXIT
    if [[ $operation == append && -f $destination ]]; then
        cat -- "$destination" > "$temporary" || exit
    fi
    "$@" >> "$temporary" || exit
    chmod 0644 "$temporary" && mv -Tf -- "$temporary" "$destination"
)
file_write() { _file_publish write "$@"; }
file_append() { _file_publish append "$@"; }
