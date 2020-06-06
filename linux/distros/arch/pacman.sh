# Base
 wpa_supplicant iw

# KDE
plasma-meta plasma-wayland-session sddm ark dolphin dolphin-plugins filelight gwenview kcalc konsole ksystemlog okular spectacle sweeper packagekit-qt5

# Video
xorg-server
lib32-mesa

# Intel
# https://wiki.archlinux.org/index.php/intel_graphics
xf86-video-intel vulkan-intel libva-intel-driver
lib32-vulkan-intel lib32-libva-intel-driver

# Radeon
# https://wiki.archlinux.org/index.php/AMDGPU
xf86-video-amdgpu vulkan-radeon libva-mesa-driver
lib32-vulkan-radeon lib32-libva-mesa-driver

# Multimedia
vlc mpv gimp gimp-plugin-lqr gimp-refocus

# Networking
chromium nodejs npm yarn wget samba youtube-dl qbittorrent networkmanager-openvpn

# Utils
pacmatic git zip unzip p7zip unrar systemd-kcm ntfs-3g bash-completion

# Office
calligra-meta

# Fonts
ttf-dejavu ttf-liberation wqy-zenhei

# Dev
meld

# Games
steam glhack wine steam-native-runtime

# System
partitionmanager

# Powerpill key
gpg --recv-keys --keyserver hkp://pgp.mit.edu 1D1F0DC78F173680

# AUR
visual-studio-code-bin subtitlecomposer-git gpmdp powerpill

# CSharp extra packages
icu55