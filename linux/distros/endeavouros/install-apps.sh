echo "Enabling multilib"
echo "Uncomment the [multilib] section"
read -n 1 -s -r -p "Press any key to continue"
echo ""
sudo nano /etc/pacman.conf
read -n 1 -s -r -p "Press any key to continue"
echo ""
sudo pacman -Suy
echo ""

echo "Installing XWayland"
sudo pacman xorg-xwayland
cat >> ~/.config/electron-flags.conf <<EOL
--enable-features=UseOzonePlatform
--ozone-platform=wayland
EOL
echo ""

echo "Installing Radeon drivers"
yay -S mesa lib32-mesa xf86-video-ati radeontop
echo ""

echo "Installing Vulkan"
sudo yay -S vulkan-icd-loader package lib32-vulkan-icd-loader vulkan-amdgpu-pro vulkan-tools
echo "Verifying Vulkan installation"
ls /usr/share/vulkan/icd.d/
vulkaninfo
echo ""
read -n 1 -s -r -p "Press any key to continue"
echo ""
echo ""

echo "Installing VA-API"
yay -S libva-mesa-driver lib32-libva-mesa-driver libva-utils
echo "Verifying VA-API"
vainfo
echo ""
read -n 1 -s -r -p "Press any key to continue"
echo ""
echo ""

echo "Installing VDPAU"
yay -S mesa-vdpau lib32-mesa-vdpau vdpauinfo
echo "Verifying VDPAU"
vdpauinfo
echo ""
read -n 1 -s -r -p "Press any key to continue"
echo ""
echo ""

echo "Installing Chromium (with Wayland hardware acceleration)"
sudo yay -Suy chromium-wayland-vaapi libva-vdpau-driver-chromium
cat >> ~/.config/chromium-flags.conf <<EOL
# Wayland support
--enable-features=UseOzonePlatform
--ozone-platform=wayland

# Video accelaration
--ignore-gpu-blocklist
--enable-gpu-rasterization
--enable-zero-copy
--disable-gpu-driver-bug-workarounds
--enable-accelerated-video-decode
--enable-features=VaapiVideoDecoder
# broken since mesa 20.1.1
# --enable-native-gpu-memory-buffers

# Cache in tmpfs
--disk-cache-dir="$XDG_RUNTIME_DIR/chromium-cache"

# Enable reader
enable-reader-mode

# Enable dark mode
--force-dark-mode
--enable-features=WebUIDarkMode
EOL
echo "Ensure harware acceleration is enabled"
chromium chrome://gpu
read -n 1 -s -r -p "Press any key to continue"
echo ""
echo ""

echo "Installing Firefox"
sudo pacman -Suy firefox-developer-edition
echo "How to enable hardware acceleration: https://wiki.archlinux.org/title/Firefox#Hardware_video_acceleration"
read -n 1 -s -r -p "Press any key to continue"
echo ""
echo ""

echo "Installing web tools"
sudo pacman -Suy mkcert

echo "Installing dev tools"
sudo yay -Suy visual-studio-code-bin meld insomnia-bin slack-desktop discord
echo ""

echo "Installing NeoVim"
sudo yay -Suy neovim bash-language-server vscode-css-languageserver dockerfile-language-server graphql-lsp vscode-html-languageserver vscode-json-languageserver python-lsp-server rls-git rust-analyzer sql-language-server deno typescript-language-server-bin yaml-language-server lua-language-server
git clone https://github.com/NvChad/NvChad ~/.config/nvim
nvim +'hi NormalFloat guibg=#1e222a' +PackerSync
echo ""

echo "Installing Podman (Docker)"
sudo pacman -Suy podman-docker podman-dnsname
echo "Additional config needed: https://wiki.archlinux.org/title/Podman"
read -n 1 -s -r -p "Press any key to continue"
echo ""
echo ""

echo "Installing Cockpit"
sudo pacman -Suy cockpit cockpit-podman cockpit-machines
echo ""

echo "Installing Node 16"
sudo pacman -Suy nodejs-lts-gallium npm
echo ""

echo "Installing .Net"
sudo pacman -Suy dotnet-runtime dotnet-sdk
echo ""

echo "Installing Rust language"
sudo pacman -Suy rust rust-analyzer
echo ""

echo "Installing Python language"
sudo pacman -Suy python python-pip
echo ""

echo "Installing Go language"
sudo pacman -Suy go
echo ""

echo "Installing Deno language"
sudo pacman -Suy deno
echo ""

echo "Installing MPV (with Wayland hardware acceleration and autosub)"
sudo pacman -Suy mpv
mkdir -p ~/.config/mpv
cat >> ~/.config/mpv/mpv.conf <<EOL
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
wget https://raw.githubusercontent.com/davidde/mpv-autosub/master/autosub.lua -P ~/.config/mpv/scripts/
echo "Enable autosub support: https://github.com/davidde/mpv-autosub"
echo ""

echo "Installing VLC (with chromecast support)"
sudo pacman -Suy vlc libmicrodns protobuf
echo ""

echo "Installing video tools"
sudo pacman -Suy obs-studio mkvtoolnix-gui subtitlecomposer
echo ""

echo "Installing Steam"
sudo pacman -Suy steam ttf-liberation wqy-zenhei systemd-networkd lib32-systemd
echo ""

echo "Installing Lutris"
sudo pacman -Suy lutris
echo ""

echo "Installing Epic"
sudo yay -Suy rare
echo ""

echo "Installing Gamemode"
sudo pacman -Suy gamemode lib32-gamemode
wget https://raw.githubusercontent.com/FeralInteractive/gamemode/master/example/gamemode.ini -P ~/.config/
echo "Setup with Steam: https://wiki.archlinux.org/title/Gamemode#Steam"
echo ""

echo "Installing wine"
sudo yay -Suy wine winetricks dxvk-bin wine-gecko wine-mono
WINEPREFIX=~/.wine setup_dxvk install

echo "Installing extra games"
sudo pacman -Suy glhack
echo ""

echo "Installing GIMP"
sudo pacman -Suy gimp poppler-glib gimp-plugin-gmic gimp-extras gimp-gap gimp-plugin-beautify gimp-plugin-facedetect gimp-plugin-instagram-effects gimp-plugin-lqr gimp-refocus
echo ""

echo "Installing Inkscape"
sudo pacman -Suy inkscape
echo ""

echo "Installing qBittorrent"
sudo pacman -Suy qbittorrent
echo ""

echo "Installing LibreOffice"
sudo yay -Suy libreoffice-fresh libreoffice-extension-texmaths libreoffice-extension-writer2latex libreoffice-extension-languagetool ttf-caladea ttf-carlito ttf-dejavu ttf-gentium-basic ttf-liberation ttf-linux-libertine-g noto-fonts adobe-source-code-pro-fonts adobe-source-sans-fonts adobe-source-serif-fonts
echo "Fix theme if needed: https://wiki.archlinux.org/title/LibreOffice#Theme"
echo ""

echo "Installing YouTube downloader"
sudo pacman -Suy yt-dlp
echo ""

echo "Installing archive tools"
sudo pacman -Suy p7zip
echo ""

echo "Installing fonts"
sudo pacman -Suy ttf-fira-code ttf-nerd-fonts-symbols

echo "Installing proprietary programs"
sudo yay -Suy whatsapp-for-linux viber deezer
echo ""

echo "Installing flatpak tools"
sudo yay -Suy flatseal
echo ""

echo "Installing partition manager"
sudo pacman -Suy partitionmanager
echo ""