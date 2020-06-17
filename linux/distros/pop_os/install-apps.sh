#!/bin/bash

flatpak install com.getpostman.Postman
flatpak install com.obsproject.Studio
flatpak install com.slack.Slack
flatpak install org.gimp.GIMP
flatpak install org.gnome.meld
flatpak install org.qbittorrent.qBittorrent
flatpak install org.videolan.VLC
flatpak install org.inkscape.Inkscape
flatpak install org.audacityteam.Audacity

sudo apt install chromium mpv steam glhack nodejs npm wget youtube-dl lutris winetricks gamemode p7zip-full

# Install Insomnia
# https://support.insomnia.rest/article/23-installation#linux
echo "deb https://dl.bintray.com/getinsomnia/Insomnia /" | sudo tee -a /etc/apt/sources.list.d/insomnia.list
wget --quiet -O - https://insomnia.rest/keys/debian-public.key.asc | sudo apt-key add -
sudo apt-get update
sudo apt-get install insomnia