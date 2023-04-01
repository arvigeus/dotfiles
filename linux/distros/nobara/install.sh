#!/bin/bash

# Asus tools
sudo dnf install asusctl
sudo systemctl enable asusd

# System tools
sudo dnf install kernel-tools
sudo dnf copr enable atim/starship
sudo dnf install starship
sudo dnf install rclone

# Browsers
sudo dnf install chromium
flatpak install flathub com.google.Chrome
sudo dnf config-manager --add-repo https://packages.microsoft.com/yumrepos/edge
sudo dnf install microsoft-edge-stable
sudo dnf install -y torbrowser-launcher

# Dev tools
sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc
sudo sh -c 'echo -e "[code]\nname=Visual Studio Code\nbaseurl=https://packages.microsoft.com/yumrepos/vscode\nenabled=1\ngpgcheck=1\ngpgkey=https://packages.microsoft.com/keys/microsoft.asc" > /etc/yum.repos.d/vscode.repo'
dnf check-update
sudo dnf install code-insiders
sudo dnf install dotnet
sudo dnf install nodejs
sudo dnf install rust cargo
sudo dnf install meld

# Media
sudo dnf install python-subliminal
sudo dnf install mpv
sudo dnf install vlc

# Look and feel
sudo dnf install lightly
sudo dnf install fira-code-fonts

# Web
sudo dnf install kget
sudo dnf install qbittorrent
sudo dnf install telegram-desktop
flatpak install flathub com.rtosta.zapzap
flatpak install flathub com.github.IsmaelMartinez.teams_for_linux
sudo dnf install discord

# Gaming
setcap 'CAP_SYS_NICE=eip' $(which gamescope)
sudo setcap 'CAP_SYS_NICE=eip' $(which gamescope)

# Graphics
sudo dnf install gimp gimp-lqr-plugin gimp-paint-studio gimp-resynthesizer gimpfx-foundry gimp-focusblur-plugin

# Other
flatpak install flathub net.ankiweb.Anki

# KDE
python -m pip install konsave
kwriteconfig5 --file kxkbrc --group "Layouts" --key "+bg" "bg"
kwriteconfig5 --file kxkbrc --group "+bg" --key "Variant" "phonetic"
kwriteconfig5 --file kxkbrc --group "Options" --key "grp:alt_shift_toggle" "true"
kwriteconfig5 --file kwinrc --group "Windows" --key "SeparateScreenFocus" "true"
