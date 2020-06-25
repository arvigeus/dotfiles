#
# ~/.bashrc: executed by bash(1) for non-login shells.
# see /usr/share/doc/bash/examples/startup-files (in the package bash-doc)
# for examples
#
# Manually reload bashrc: source ~/.bashrc


# If not running interactively, don't do anything
case $- in
    *i*) ;;
      *) return;;
esac

# don't put duplicate lines or lines starting with space in the history.
# See bash(1) for more options
HISTCONTROL=ignoreboth

# append to the history file, don't overwrite it
shopt -s histappend

# for setting history length see HISTSIZE and HISTFILESIZE in bash(1)
HISTSIZE=1000
HISTFILESIZE=2000

# check the window size after each command and, if necessary,
# update the values of LINES and COLUMNS.
shopt -s checkwinsize

# If set, the pattern "**" used in a pathname expansion context will
# match all files and zero or more directories and subdirectories.
#shopt -s globstar

# make less more friendly for non-text input files, see lesspipe(1)
[ -x /usr/bin/lesspipe ] && eval "$(SHELL=/bin/sh lesspipe)"

# set a fancy prompt (non-color, unless we know we "want" color)
case "$TERM" in
    xterm-color|*-256color) color_prompt=yes;;
esac

# uncomment for a colored prompt, if the terminal has the capability; turned
# off by default to not distract the user: the focus in a terminal window
# should be on the output of commands, not on the prompt
#force_color_prompt=yes

if [ -n "$force_color_prompt" ]; then
    if [ -x /usr/bin/tput ] && tput setaf 1 >&/dev/null; then
	# We have color support; assume it's compliant with Ecma-48
	# (ISO/IEC-6429). (Lack of such support is extremely rare, and such
	# a case would tend to support setf rather than setaf.)
	color_prompt=yes
    else
	color_prompt=
    fi
fi

if [ "$color_prompt" = yes ]; then
    function BG {
        echo -n "48;5;$1"
    }
    function FG {
        echo -n "38;5;$1"
    }
    WHITE=231
    BLACK=0
    GREY=240
    RED=160
    BLUE=32
    GREEN=36
    YELLOW=226

    ARROW=$'\uE0B0'
    BOLD=$'\e[1m'
    RESET=$'\e[0m'

    # All non-printable chars must be wrapped in \\[ and \\].

    if [[ $UID -eq 0 ]]; then
        # Root
        PS1=$'\\[${BOLD}\\033[$(BG $RED);$(FG $WHITE)m\\] \u26a1\u@\h \\[\\033[$(BG $BLUE);$(FG $RED)m\\]${ARROW}'
    else
        # Normal user
        PS1=$'\\[${BOLD}\\033[$(BG $GREY);$(FG $WHITE)m\\] \u@\h \\[\\033[$(BG $BLUE);$(FG $GREY)m\\]${ARROW}'
    fi
    
    PS1+=$'\\[\\033[$(FG $WHITE)m\\] \w '

    git_branch=$(git branch 2>/dev/null | grep "^*" | colrm 1 2)
    if [ -n "${git_branch}" ]; then
        branch_changes=$(git status --porcelain --ignore-submodules)
        if [ -z "${branch_changes}" ]; then
            PS1+=$'\\[\\033[$(BG $GREEN);$(FG $BLUE)m\\]${ARROW}\\[\\033[$(FG $WHITE)m\\] \ue0a0 ${git_branch} \\[${RESET}\\033[$(FG $GREEN)m\\]${ARROW}'
        else
            PS1+=$'\\[\\033[$(BG $YELLOW);$(FG $BLUE)m\\]${ARROW}\\[\\033[$(FG $BLACK)m\\] \ue0a0 ${git_branch}* \\[${RESET}\\033[$(FG $YELLOW)m\\]${ARROW}'
        fi
    else
        PS1+=$'\\[${RESET}\\033[$(FG $BLUE)m\\]${ARROW}'
    fi

    PS1+=$'\\[${RESET}\\]\n\\$ '
else
    PS1='\u@\h:\w \$ '
fi

unset color_prompt force_color_prompt

# Reset colors for print statements
#trap 'printf "\e[0m" "$_"' DEBUG

# enable color support of ls and also add handy aliases
if [ -x /usr/bin/dircolors ]; then
    test -r ~/.dircolors && eval "$(dircolors -b ~/.dircolors)" || eval "$(dircolors -b)"
    alias ls='ls --color=auto'
    #alias dir='dir --color=auto'
    #alias vdir='vdir --color=auto'

    alias grep='grep --color=auto'
    alias fgrep='fgrep --color=auto'
    alias egrep='egrep --color=auto'
fi

# colored GCC warnings and errors
export GCC_COLORS='error=01;31:warning=01;35:note=01;36:caret=01;32:locus=01:quote=01'

# some more ls aliases
alias ll='ls -alF'
alias la='ls -A'
alias l='ls -CF'

# Add an "alert" alias for long running commands.  Use like so:
#   sleep 10; alert
alias alert='notify-send --urgency=low -i "$([ $? = 0 ] && echo terminal || echo error)" "$(history|tail -n1|sed -e '\''s/^\s*[0-9]\+\s*//;s/[;&|]\s*alert$//'\'')"'

# Alias definitions.
# You may want to put all your additions into a separate file like
# ~/.bash_aliases, instead of adding them here directly.
# See /usr/share/doc/bash-doc/examples in the bash-doc package.

if [ -f ~/.bash_aliases ]; then
    . ~/.bash_aliases
fi

# enable programmable completion features (you don't need to enable
# this, if it's already enabled in /etc/bash.bashrc and /etc/profile
# sources /etc/bash.bashrc).
if ! shopt -oq posix; then
  if [ -f /usr/share/bash-completion/bash_completion ]; then
    . /usr/share/bash-completion/bash_completion
  elif [ -f /etc/bash_completion ]; then
    . /etc/bash_completion
  fi
fi

alias mkdir='mkdir -p -v'
alias df='df -h'
alias du='du -c -h'
alias dmesg='dmesg -HL'
alias rm='rm -i'
alias cp='cp -i'
alias mv='mv -i'
alias cls='printf "\033c" && clear && echo -en "\e[3J"'

# Autocomplete: commands which have more than one possible completion cause the matches to be listed
set show-all-if-ambiguous on

function extract {
 if [ -z "$1" ]; then
    # Display usage if no parameters given
    echo "Usage: extract <path/file_name>.<zip|rar|bz2|gz|tar|tbz2|tgz|Z|7z|xz|ex|tar.bz2|tar.gz|tar.xz>"
 else
    if [ -f $1 ] ; then
        # NAME=${1%.*}
        # mkdir $NAME && cd $NAME
        case $1 in
          *.tar.bz2)   tar xvjf ../$1    ;;
          *.tar.gz)    tar xvzf ../$1    ;;
          *.tar.xz)    tar xvJf ../$1    ;;
          *.lzma)      unlzma ../$1      ;;
          *.bz2)       bunzip2 ../$1     ;;
          *.rar)       7z x ../$1 ;;
          *.gz)        gunzip ../$1      ;;
          *.tar)       tar xvf ../$1     ;;
          *.tbz2)      tar xvjf ../$1    ;;
          *.tgz)       tar xvzf ../$1    ;;
          *.zip)       unzip ../$1       ;;
          *.Z)         uncompress ../$1  ;;
          *.7z)        7z x ../$1        ;;
          *.xz)        unxz ../$1        ;;
          *.exe)       cabextract ../$1  ;;
          *)           echo "extract: '$1' - unknown archive method" ;;
        esac
    else
        echo "$1 - file does not exist"
    fi
fi
}

psgrep() {
	if [ ! -z $1 ] ; then
		ps aux | grep $1 | grep -v grep
	else
		echo "No process specified"
	fi
}