# This is not meant to be automated script yet

# Installing XWayland
## https://wiki.archlinux.org/title/Wayland
sudo pacman -S plasma-wayland-session
cat >> ~/.config/electron-flags.conf <<EOL
--enable-features=UseOzonePlatform
--ozone-platform=wayland
EOL

# Installing Radeon drivers
yay -S lib32-mesa radeontop

# Installing Vulkan
sudo yay -S vulkan-amdgpu-pro
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
## https://wiki.archlinux.org/title/Fish
## https://github.com/jorgebucaran/fisher
### TODO: Hook for updating fish plugins
# sudo pacman -S fish fisher

# Install Fish shell
## https://wiki.archlinux.org/title/Alacritty
## https://github.com/alacritty/alacritty
sudo pacman -S alacritty

# Installing flatpak
sudo pacman -S flatpak
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo

# Installing Chromium (with Wayland)
# VAAPI seems to not be working: https://github.com/flathub/org.chromium.Chromium/issues/103
flatpak install flathub org.chromium.Chromium
cat >> ~/.var/app/org.chromium.Chromium/config/chromium-flags.conf <<EOL
# Wayland support
--enable-features=UseOzonePlatform
--ozone-platform=wayland

# Enable reader
--enable-reader-mode

# Enable dark mode
--force-dark-mode
--enable-features=WebUIDarkMode
EOL
# Ensure harware acceleration is enabled
chromium chrome://gpu

# Installing Firefox
sudo pacman -S firefox-developer-edition
mkdir -p ~/.config/environment.d/
cat >> ~/.var/app/org.chromium.Chromium/config/chromium-flags.conf <<EOL
MOZ_ENABLE_WAYLAND=1
EOL
# How to enable hardware acceleration: https://wiki.archlinux.org/title/Firefox#Hardware_video_acceleration

# Installing Tor
flatpak install flathub com.github.micahflee.torbrowser-launcher

# Installing web tools
sudo pacman -S mkcert

# Installing Node 16
sudo pacman -S nodejs-lts-gallium npm
flatpak install flathub org.freedesktop.Sdk.Extension.node16

# Installing .Net
sudo pacman -S dotnet-runtime dotnet-sdk
flatpak install flathub org.freedesktop.Sdk.Extension.dotnet6

# Installing Rust language
sudo pacman -S rust rust-analyzer
flatpak install flathub org.freedesktop.Sdk.Extension.rust-nightly

# Installing Python language
sudo pacman -S python python-pip

# Installing Go language
sudo pacman -S go
flatpak install flathub org.freedesktop.Sdk.Extension.golang

# Installing Deno language
sudo pacman -S deno

# Installing dev tools
flatpak install flathub visual-studio-code-insiders-bin
sudo pacman -S  expect
## Alt to Insomnia: Hoppscotch
flatpak install flathub rest.insomnia.Insomnia
flatpak install flathub com.slack.Slack
flatpak install flathub com.discordapp.Discord
flatpak install flathub com.microsoft.Teams
flatpak install flathub com.skype.Client

# Installing NeoVim
# flatpak install flathub io.neovim.nvim
sudo yay -S neovim bash-language-server vscode-css-languageserver dockerfile-language-server graphql-lsp vscode-html-languageserver vscode-json-languageserver python-lsp-server rls-git rust-analyzer sql-language-server deno typescript-language-server-bin yaml-language-server lua-language-server
git clone https://github.com/NvChad/NvChad ~/.config/nvim
nvim +'hi NormalFloat guibg=#1e222a' +PackerSync

# Installing Podman (Docker)
sudo pacman -S podman-docker podman-dnsname
# Additional config needed: https://wiki.archlinux.org/title/Podman

# Installing Cockpit
sudo pacman -S cockpit cockpit-podman cockpit-machines

# Installing mpz media player
yay -S mpz

# Installing MPV (with Wayland hardware acceleration and autosub)
sudo pacman -S mpv
mkdir -p ~/.config/mpv/
cat >> ~/.config/mpv/mpv.conf <<EOL
# High quality config
profile=gpu-hq
scale=ewa_lanczossharp
cscale=ewa_lanczossharp
video-sync=display-resample
interpolation
tscale=oversample

# Hardware acceleration
vo=gpu
hwdec=vaapi

# Wayland
gpu-context=wayland
x11-bypass-compositor=no
EOL
yay -S subliminal
mkdir ~/.var/app/io.mpv.Mpv/config/mpv/scripts/
wget https://raw.githubusercontent.com/davidde/mpv-autosub/master/autosub.lua -P ~/.var/app/io.mpv.Mpv/config/mpv/scripts/
# Enable autosub support: https://github.com/davidde/mpv-autosub

# Installing video tools
flatpak install flathub org.kde.subtitlecomposer
flatpak install flathub org.bunkus.mkvtoolnix-gui
flatpak install flathub com.obsproject.Studio
flatpak install flathub io.github.seadve.Kooha

# Installing Steam
sudo pacman -S steam ttf-liberation wqy-zenhei

# Installing Lutris
sudo pacman -S lutris

# Installing Epic
yay -S rare

# Installing Gamemode
sudo pacman -S gamemode lib32-gamemode
wget https://raw.githubusercontent.com/FeralInteractive/gamemode/master/example/gamemode.ini -P ~/.config/
## Setup with Steam: https://wiki.archlinux.org/title/Gamemode#Steam

# Installing wine
sudo pacman -S wine winetricks wine-gecko wine-mono
yay -S dxvk-bin
WINEPREFIX=~/.wine setup_dxvk install

# Installing extra games
sudo pacman -S glhack

# Installing GIMP
## https://www.linuxadictos.com/en/como-instalar-plug-ins-a-la-version-flatpak-de-gimp-y-poder-usar-resynthesizer-y-bimp-entre-otros.html
flatpak install org.gimp.GIMP org.gimp.GIMP.Plugin.Resynthesizer org.gimp.GIMP.Plugin.LiquidRescale org.gimp.GIMP.Plugin.Lensfun org.gimp.GIMP.Plugin.GMic org.gimp.GIMP.Plugin.Fourier org.gimp.GIMP.Plugin.FocusBlur org.gimp.GIMP.Plugin.BIMP


# Installing Inkscape
flatpak install flathub org.inkscape.Inkscape

# Installing qBittorrent
flatpak install flathub org.qbittorrent.qBittorrent

# Installing LibreOffice
flatpak install flathub org.libreoffice.LibreOffice
## Fix theme if needed: https://wiki.archlinux.org/title/LibreOffice#Theme

# Installing YouTube downloader
sudo pacman -S yt-dlp
flatpak install flathub com.github.unrud.VideoDownloader

# Installing fonts
sudo pacman -S ttf-fira-code ttf-nerd-fonts-symbols

# Installing proprietary programs
yay -S deezer
## WhatsApp
flatpak install flathub com.rtosta.zapzap
## Viber
# flatpak install -y com.viber.Viber
# Viber try icon: https://github.com/flathub/com.viber.Viber/issues/4
# flatpak override --user --own-name='org.kde.*' com.viber.Viber

# Installing flatpak tools
yay -S flatseal

# Installing partition manager
sudo pacman -S partitionmanager

# Installing plasma addons
sudo pacman -S kdeplasma-addons

# Installing web account tools
sudo pacman -S kio-gdrive

# Installing theming
# sudo yay -S kvantum-qt5 latte-dock tela-icon-theme-git layan-kde-git
# kwriteconfig5 --file ~/.config/kwinrc --group ModifierOnlyShortcuts --key Meta "org.kde.kglobalaccel,/component/kwin,org.kde.kglobalaccel.Component,invokeShortcut,Expose"
