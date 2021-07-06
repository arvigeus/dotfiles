#!/bin/bash

sudo apt -y dist-upgrade

flatpak install -y org.chromium.Chromium
flatpak install -y com.obsproject.Studio
flatpak install -y com.slack.Slack
flatpak install -y com.discordapp.Discord
flatpak install -y org.gimp.GIMP
flatpak install -y org.gnome.meld
flatpak install -y org.qbittorrent.qBittorrent
flatpak install -y org.videolan.VLC
flatpak install -y org.inkscape.Inkscape
flatpak install -y com.viber.Viber
flatpak install -y com.github.johnfactotum.Foliate
flatpak install -y com.github.tchx84.Flatseal
# flatpak install -y com.microsoft.Edge

# Viber try icon: https://github.com/flathub/com.viber.Viber/issues/4
flatpak override --user --own-name='org.kde.*' com.viber.Viber

sudo apt -y install gnome-tweak-tool code fonts-firacode mpv steam glhack nodejs npm wget youtube-dl lutris winetricks gamemode p7zip-full libnotify-bin glhack

# Open with VSCode
sudo apt -y install python3-nautilus
wget https://raw.githubusercontent.com/vvanloc/Nautilus-OpenInVSCode/master/vscode-nautilus.py -P ~/.local/share/nautilus-python/extensions

# Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
# rustup update

# Install Insomnia
# https://support.insomnia.rest/article/23-installation#linux
echo "deb https://dl.bintray.com/getinsomnia/Insomnia /" | sudo tee -a /etc/apt/sources.list.d/insomnia.list
wget --quiet -O - https://insomnia.rest/keys/debian-public.key.asc | sudo apt-key add -
sudo apt-get -y update
sudo apt-get -y install insomnia

sudo apt -y autoremove
