# shellcheck shell=sh
# Start the desktop from the TTY1 autologin shell. The supervisor replaces the
# shell, so no prompt appears. Sorted last to inherit every profile.d export.
if [ "${XDG_VTNR-}" = 1 ] && uwsm check may-start; then
    exec session-mode run
fi
