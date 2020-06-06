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

sudo apt install chromium mpv steam glhack nodejs npm wget youtube-dl lutris winetricks gamemode

# Install chrome
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install ./google-chrome-stable_current_amd64.deb
rm ./google-chrome-stable_current_amd64.deb