#!/usr/bin/env bash
set -Eeuo pipefail

kwriteconfig6 --file kwalletrc --group KSecretD --key Enabled --type bool false
kwriteconfig6 --file kwalletrc --group Wallet --key Enabled --type bool true
kwriteconfig6 --file kwalletrc --group Migration --key MigrateTo3rdParty --type bool false
systemctl --global enable gnome-keyring-daemon.service secret-service-unlock.service
