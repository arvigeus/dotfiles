# This is not meant to be automated script yet

# Enabling multilib
## https://wiki.archlinux.org/title/Official_repositories#multilib
## Uncomment the [multilib] section
sudo nano /etc/pacman.conf
## Update deps
sudo pacman -Suy

# Installing XWayland
## https://wiki.archlinux.org/title/Wayland
sudo pacman xorg-xwayland
cat >> ~/.config/electron-flags.conf <<EOL
--enable-features=UseOzonePlatform
--ozone-platform=wayland
EOL

# Installing Radeon drivers
yay -S mesa lib32-mesa xf86-video-ati radeontop

# Installing Vulkan
sudo yay -S vulkan-icd-loader package lib32-vulkan-icd-loader vulkan-amdgpu-pro vulkan-tools
# Verifying Vulkan installation
ls /usr/share/vulkan/icd.d/
vulkaninfo

# Installing VA-API
yay -S libva-mesa-driver lib32-libva-mesa-driver libva-utils
# Verifying VA-API
vainfo

# Installing VDPAU
yay -S mesa-vdpau lib32-mesa-vdpau vdpauinfo
# Verifying VDPAU
vdpauinfo

# Install Alacritty terminal emulator
## https://wiki.archlinux.org/title/Alacritty
## https://github.com/alacritty/alacritty
sudo pacman -S alacritty

# Installing Chromium (with Wayland)
# VAAPI seems to not be working: https://github.com/flathub/org.chromium.Chromium/issues/103
flatpak install flathub org.chromium.Chromium
cat >> ~/.var/app/org.chromium.Chromium/config/chromium-flags.conf <<EOL
# Wayland support
--enable-features=UseOzonePlatform
--ozone-platform=wayland

# Enable reader
enable-reader-mode

# Enable dark mode
--force-dark-mode
--enable-features=WebUIDarkMode
EOL
# Ensure harware acceleration is enabled
chromium chrome://gpu

# Installing Firefox
sudo pacman -Suy firefox-developer-edition
# How to enable hardware acceleration: https://wiki.archlinux.org/title/Firefox#Hardware_video_acceleration

# Installing Tor
flatpak install flathub com.github.micahflee.torbrowser-launcher

# Installing web tools
sudo pacman -Suy mkcert

# Installing Node 16
sudo pacman -Suy nodejs-lts-gallium npm
flatpak install flathub org.freedesktop.Sdk.Extension.node16

# Installing .Net
sudo pacman -Suy dotnet-runtime dotnet-sdk
flatpak install flathub org.freedesktop.Sdk.Extension.dotnet6

# Installing Rust language
sudo pacman -Suy rust rust-analyzer
flatpak install flathub org.freedesktop.Sdk.Extension.rust-nightly

# Installing Python language
sudo pacman -Suy python python-pip

# Installing Go language
sudo pacman -Suy go
flatpak install flathub org.freedesktop.Sdk.Extension.golang

# Installing Deno language
sudo pacman -Suy deno
flatpak install flathub org.freedesktop.Sdk.Extension.dotnet6

# Installing dev tools
flatpak install flathub com.vscodium.codium
## Alt to Insomnia: Hoppscotch
flatpak install flathub rest.insomnia.Insomnia
flatpak install flathub org.gnome.meld
flatpak install flathub com.slack.Slack
flatpak install flathub com.discordapp.Discord
flatpak install flathub com.microsoft.Teams
flatpak install flathub com.skype.Client

# Installing NeoVim
# flatpak install flathub io.neovim.nvim
sudo yay -Suy neovim bash-language-server vscode-css-languageserver dockerfile-language-server graphql-lsp vscode-html-languageserver vscode-json-languageserver python-lsp-server rls-git rust-analyzer sql-language-server deno typescript-language-server-bin yaml-language-server lua-language-server
git clone https://github.com/NvChad/NvChad ~/.config/nvim
nvim +'hi NormalFloat guibg=#1e222a' +PackerSync

# Installing Podman (Docker)
sudo pacman -Suy podman-docker podman-dnsname
# Additional config needed: https://wiki.archlinux.org/title/Podman

# Installing Cockpit
sudo pacman -Suy cockpit cockpit-podman cockpit-machines

# Installing MPV (with Wayland hardware acceleration and autosub)
flatpak install flathub io.mpv.Mpv
cat >> ~/.var/app/io.mpv.Mpv/config/mpv/mpv.conf <<EOL
# High quality config
profile=gpu-hq
scale=ewa_lanczossharp
cscale=ewa_lanczossharp
video-suync=display-resample
interpolation
tscale=oversample

# Hardware acceleration
vo=gpu
hwdec=vaapi

# Wayland
gpu-context=wayland
x11-bypass-compositor=no
EOL
sudo yay -Suy subliminal wget
mkdir ~/.config/mpv/scripts
wget https://raw.githubusercontent.com/davidde/mpv-autosub/master/autosub.lua -P ~/.var/app/io.mpv.Mpv/config/mpv/scripts/
# Enable autosub support: https://github.com/davidde/mpv-autosub

# Installing VLC
flatpak install flathub org.videolan.VLC

# Installing video tools
flatpak install flathub org.kde.subtitlecomposer
flatpak install flathub org.bunkus.mkvtoolnix-gui
flatpak install flathub com.obsproject.Studio
https://flathub.org/apps/details/io.github.seadve.Kooha

# Installing Steam
sudo pacman -Suy steam ttf-liberation wqy-zenhei systemd-networkd lib32-systemd

# Installing Lutris
sudo pacman -Suy lutris

# Installing Epic
sudo yay -Suy rare

# Installing Gamemode
sudo pacman -Suy gamemode lib32-gamemode
wget https://raw.githubusercontent.com/FeralInteractive/gamemode/master/example/gamemode.ini -P ~/.config/
## Setup with Steam: https://wiki.archlinux.org/title/Gamemode#Steam

# Installing wine
sudo yay -Suy wine winetricks dxvk-bin wine-gecko wine-mono
WINEPREFIX=~/.wine setup_dxvk install

# Installing extra games
sudo pacman -Suy glhack

# Installing GIMP
## https://www.linuxadictos.com/en/como-instalar-plug-ins-a-la-version-flatpak-de-gimp-y-poder-usar-resynthesizer-y-bimp-entre-otros.html
flatpak install org.gimp.GIMP org.gimp.GIMP.Plugin.Resynthesizer org.gimp.GIMP.Plugin.LiquidRescale org.gimp.GIMP.Plugin.Lensfun org.gimp.GIMP.Plugin.GMic org.gimp.GIMP.Plugin.Fourier org.gimp.GIMP.Plugin.FocusBlur org.gimp.GIMP.Plugin.BIMP


# Installing Inkscape
flatpak install flathub org.inkscape.Inkscape

# Installing qBittorrent
flatpak install flathub org.qbittorrent.qBittorrent

# Installing LibreOffice
flatpak install flathub org.libreoffice.LibreOffice
## Fix theme if needed: https://wiki.archlinux.org/title/LibreOffice#Theme"

# Installing YouTube downloader
sudo pacman -Suy yt-dlp
flatpak install flathub com.github.unrud.VideoDownloader

# Installing archive tools
sudo pacman -Suy p7zip

# Installing fonts
sudo pacman -Suy ttf-fira-code ttf-nerd-fonts-symbols

# Installing proprietary programs
sudo yay -Suy whatsapp-for-linux deezer
## Viber
flatpak install -y com.viber.Viber
# Viber try icon: https://github.com/flathub/com.viber.Viber/issues/4
flatpak override --user --own-name='org.kde.*' com.viber.Viber

# Installing flatpak tools
sudo yay -Suy flatseal

# Installing partition manager
sudo pacman -Suy partitionmanager

# Installing web account tools
sudo pacman -S kio-gdrive

# Installing theming
sudo yay -S kvantum-qt5 latte-dock tela-icon-theme-git layan-kde-git
kwriteconfig5 --file ~/.config/kwinrc --group ModifierOnlyShortcuts --key Meta "org.kde.kglobalaccel,/component/kwin,org.kde.kglobalaccel.Component,invokeShortcut,Expose"
