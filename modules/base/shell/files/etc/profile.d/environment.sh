# Export the systemd user environment (environment.d) to login shells, so each
# variable is declared once for both shells and user services.
while IFS= read -r assignment; do
    # shellcheck disable=SC2163 # Each line is a NAME=value assignment.
    export "$assignment"
done << END
$(/usr/lib/systemd/user-environment-generators/30-systemd-environment-d-generator)
END
unset assignment
# A login shell may inherit PATH from the user manager or another login shell.
# Keep the declared order without accumulating entries on each invocation.
PATH=$(printf '%s' "$PATH" | awk -v RS=: '!seen[$0]++ { printf "%s%s", separator, $0; separator=":" }')
export PATH
