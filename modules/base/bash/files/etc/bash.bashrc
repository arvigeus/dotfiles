# shellcheck shell=bash
#
# /etc/bash.bashrc
#

# If not running interactively, don't do anything
[[ $- != *i* ]] && return
[[ -z ${BASHRCSOURCED:-} ]] || return

# Prevent doublesourcing
if [[ -z "${BASHRCSOURCED}" ]] ; then
  BASHRCSOURCED="Y"
  # the check is bash's default value
  [[ "$PS1" = '\s-\v\$ ' ]] && PS1='[\u@\h \W]\$ '
  case ${TERM} in
    Eterm*|alacritty*|aterm*|foot*|gnome*|konsole*|kterm*|putty*|rxvt*|tmux*|xterm*)
      # shellcheck disable=SC2016 # Expanded when the prompt runs.
      PROMPT_COMMAND+=('printf "\033]0;%s@%s:%s\007" "${USER}" "${HOSTNAME%%.*}" "${PWD/#$HOME/\~}"')
      ;;
    screen*)
      # shellcheck disable=SC2016 # Expanded when the prompt runs.
      PROMPT_COMMAND+=('printf "\033_%s@%s:%s\033\\" "${USER}" "${HOSTNAME%%.*}" "${PWD/#$HOME/\~}"')
      ;;
  esac
fi

# Login shells already read these through /etc/profile.
if ! shopt -q login_shell; then
  # Package-provided profile scripts use /etc/profile's path helper.
  # shellcheck disable=SC2329 # Called by sourced profile scripts.
  append_path() {
    case ":$PATH:" in
      *:"$1":*) ;;
      *) PATH="${PATH:+$PATH:}$1" ;;
    esac
  }
  for profile in /etc/profile.d/*.sh; do
    # shellcheck disable=SC1090
    [[ ! -r $profile ]] || source "$profile"
  done
  unset profile
  unset -f append_path
  export PATH
fi

if [[ -r /usr/share/bash-completion/bash_completion ]]; then
  # shellcheck disable=SC1091
  . /usr/share/bash-completion/bash_completion
fi
