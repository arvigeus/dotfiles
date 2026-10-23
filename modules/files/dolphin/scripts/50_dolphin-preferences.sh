#!/usr/bin/env bash
set -Eeuo pipefail

kwriteconfig6 --file dolphinrc --group General --key BrowseThroughArchives --type bool true
kwriteconfig6 --file dolphinrc --group General --key GlobalViewProps --type bool true
kwriteconfig6 --file kdeglobals --group KDE --key SingleClick --type bool true

view=${XDG_DATA_HOME:-$HOME/.local/share}/dolphin/view_properties/global/.directory
mkdir -p -- "$(dirname -- "$view")"
kwriteconfig6 --file "$view" --group Dolphin --key Version 4
kwriteconfig6 --file "$view" --group Dolphin --key VisibleRoles Icons_size,Compact_size
