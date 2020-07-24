#!/bin/bash

sudo apt -y dist-upgrade

flatpak install -y com.obsproject.Studio
flatpak install -y com.slack.Slack
flatpak install -y com.discordapp.Discord
flatpak install -y org.gimp.GIMP
flatpak install -y org.gnome.meld
flatpak install -y org.qbittorrent.qBittorrent
flatpak install -y org.videolan.VLC
flatpak install -y org.inkscape.Inkscape
flatpak install -y org.audacityteam.Audacity

sudo apt -y install gnome-tweak-tool chromium code mpv steam glhack nodejs npm wget youtube-dl lutris winetricks gamemode p7zip-full libnotify-bin glhack

# Open with VSCode
wget -qO- https://raw.githubusercontent.com/cra0zy/code-nautilus/master/install.sh | bash

# Install Insomnia
# https://support.insomnia.rest/article/23-installation#linux
echo "deb https://dl.bintray.com/getinsomnia/Insomnia /" | sudo tee -a /etc/apt/sources.list.d/insomnia.list
wget --quiet -O - https://insomnia.rest/keys/debian-public.key.asc | sudo apt-key add -
sudo apt-get -y update
sudo apt-get -y install insomnia

sudo apt -y autoremove
