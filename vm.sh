#!/usr/bin/env bash
set -euo pipefail
[[ $# == 0 || ($# == 1 && $1 == boot) ]] || {
    echo 'Usage: ./vm.sh [boot]' >&2
    exit 1
}
mode=${1:-iso}
[[ $EUID != 0 ]] || {
    echo 'Run ./vm.sh as your regular user.' >&2
    exit 1
}
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/dotfiles-vm"
for tool in qemu-system-x86_64 qemu-img; do
    command -v "$tool" > /dev/null || {
        echo "Missing $tool; install qemu-desktop and qemu-img." >&2
        exit 1
    }
done
[[ -r /dev/kvm && -w /dev/kvm ]] || {
    echo 'KVM access is required (/dev/kvm).' >&2
    exit 1
}
firmware_dir=/usr/share/edk2/x64
[[ -r $firmware_dir/OVMF_CODE.4m.fd && -r $firmware_dir/OVMF_VARS.4m.fd ]] || {
    echo 'UEFI firmware is missing; install edk2-ovmf.' >&2
    exit 1
}
if [[ $mode == iso ]]; then
    for tool in bsdtar python3; do
        command -v "$tool" > /dev/null || {
            echo "Missing $tool; install libarchive and python." >&2
            exit 1
        }
    done
    read -r -p 'Arch ISO path: ' iso
    [[ -f $iso && -r $iso ]] || {
        echo "Cannot read ISO: $iso" >&2
        exit 1
    }
    iso=$(realpath -- "$iso")
else
    [[ -f $state_dir/disk.qcow2 && -f $state_dir/OVMF_VARS.fd ]] || {
        echo 'No saved VM disk and firmware; run ./vm.sh first.' >&2
        exit 1
    }
fi
mkdir -p -- "$state_dir"
# Keep the disk and firmware settings across launches. Never recreate an existing disk.
[[ -e $state_dir/disk.qcow2 ]] || qemu-img create -f qcow2 "$state_dir/disk.qcow2" 64G
[[ -e $state_dir/OVMF_VARS.fd ]] || cp -- "$firmware_dir/OVMF_VARS.4m.fd" "$state_dir/OVMF_VARS.fd"
# QEMU uses commas to separate option fields; double literal commas in paths.
qemu_path() { printf '%s' "${1//,/,,}"; }
printf '\nVM disk and firmware: %s\n' "$state_dir"
boot_args=(-boot "order=c,menu=on")
if [[ $mode == iso ]]; then
    scratch=$(mktemp -d)
    server_pid=
    cleanup() {
        if [[ -n $server_pid ]]; then
            kill "$server_pid" 2> /dev/null || true
            wait "$server_pid" 2> /dev/null || true
        fi
        rm -rf -- "$scratch"
    }
    trap cleanup EXIT
    bsdtar -xOf "$iso" arch/boot/x86_64/vmlinuz-linux > "$scratch/linux"
    bsdtar -xOf "$iso" arch/boot/x86_64/initramfs-linux.img > "$scratch/initramfs"
    entry=$(bsdtar -xOf "$iso" loader/entries/01-archiso-linux.conf)
    options=$(sed -n 's/^options[[:space:]]\+//p' <<< "$entry")
    [[ -n $options ]] || {
        echo 'ISO has no supported Arch boot entry.' >&2
        exit 1
    }
    python3 "$repo_dir/scripts/vm-serve.py" "$repo_dir" > "$scratch/port" &
    server_pid=$!
    for ((attempt = 0; attempt < 50; attempt++)); do
        [[ -s $scratch/port ]] && break
        kill -0 "$server_pid" 2> /dev/null || {
            echo 'Startup server failed.' >&2
            exit 1
        }
        sleep 0.1
    done
    port=$(cat "$scratch/port")
    [[ $port =~ ^[0-9]+$ ]] || {
        echo 'Startup server did not become ready.' >&2
        exit 1
    }
    boot_args+=(
        -drive "media=cdrom,readonly=on,file=$(qemu_path "$iso")"
        -kernel "$scratch/linux" -initrd "$scratch/initramfs"
        -append "$options script=http://10.0.2.2:$port/startup.sh"
    )
    printf 'The ISO will mount the checkout automatically at %s.\n' "$repo_dir"
    printf 'It will print the VM generation and installation commands.\n'
    printf 'The share is writable: edits and generated files also change the host checkout.\n\n'
else
    printf 'Booting the installed system from the saved virtual disk.\n\n'
fi
qemu-system-x86_64 \
    -name dotfiles-install-test \
    -machine q35,accel=kvm \
    -cpu host -smp 4 -m 8G \
    -drive "if=pflash,format=raw,readonly=on,file=$(qemu_path "$firmware_dir/OVMF_CODE.4m.fd")" \
    -drive "if=pflash,format=raw,file=$(qemu_path "$state_dir/OVMF_VARS.fd")" \
    -drive "if=virtio,format=qcow2,file=$(qemu_path "$state_dir/disk.qcow2")" \
    "${boot_args[@]}" \
    -nic user,model=virtio-net-pci \
    -virtfs "local,path=$(qemu_path "$repo_dir"),mount_tag=dotfiles,security_model=none" \
    -device virtio-vga -display gtk
