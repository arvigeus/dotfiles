# shellcheck shell=bash
# Start only on the local graphical login console, never in a terminal, SSH,
# or UWSM's environment preloader. The supervisor replaces the login shell.
if shopt -q login_shell && [[ $- == *i* && $EUID != 0 && ${XDG_VTNR:-} == 1 && -z ${SSH_CONNECTION:-} &&
      -z ${WAYLAND_DISPLAY:-} && -z ${DISPLAY:-} &&
      ${IN_UWSM_ENV_PRELOADER:-false} != true ]]; then
    exec session-mode run
fi
