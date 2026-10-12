export MISE_DATA_DIR="$HOME/.local/share/mise"
export MISE_CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.local/cache}/mise"
export MISE_CONFIG_DIR="$HOME/.config/mise"
if command -v mise >/dev/null 2>&1; then
	if [ -n "${BASH_VERSION:-}" ]; then
		eval "$(mise activate bash)"
	elif [ -n "${ZSH_VERSION:-}" ]; then
		eval "$(mise activate zsh)"
	fi
fi
