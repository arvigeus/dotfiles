#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir=${DOTFILES_REPO:?}

source "$repo_dir/scripts/config-helpers.sh"

configure() {
	[[ -x /opt/btrustbiss/bin/BISS && -r /usr/lib/pkcs11/libIDPrimePKCS11.so ]]
	# Undo the AUR install hook, also enforced after mutable package upgrades.
	/usr/local/libexec/btrust-maintain
	# Allow this installation's one desktop user to manage only the QES target.
	# Cleanup must still work after the user's session becomes inactive on logout.
	file_write /etc/polkit-1/rules.d/50-btrust.rules <<EOF
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.systemd1.manage-units" &&
        action.lookup("unit") == "btrust.target" &&
        subject.user == "$USERNAME") {
        var verb = action.lookup("verb");
        if (verb == "stop" || verb == "start")
            return polkit.Result.YES;
    }
});
EOF
}

configure
