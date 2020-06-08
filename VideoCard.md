# Video card

## Radeon HD 7850 *(Southern Islands)*

```shell
$ lspci -v

01:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Pitcairn PRO [Radeon HD 7850 / R7 265 / R9 270 1024SP] (prog-if 00 [VGA controller])
        Subsystem: PC Partner Limited / Sapphire Technology Pitcairn PRO [Radeon HD 7850 / R7 265 / R9 270 1024SP]
        Flags: bus master, fast devsel, latency 0, IRQ 128
        Memory at e0000000 (64-bit, prefetchable) [size=256M]
        Memory at f7d00000 (64-bit, non-prefetchable) [size=256K]
        I/O ports at e000 [size=256]
        Expansion ROM at 000c0000 [disabled] [size=128K]
        Capabilities: <access denied>
        Kernel driver in use: amdgpu
        Kernel modules: radeon, amdgpu
```

### Install Vulkan

```sh
sudo apt install libvulkan1 mesa-vulkan-drivers vulkan-utils
```

Southern Islands cards support is considered *experimental*, so it needs boot parameters to be added.

Edit GRUB:

```sh
sudo nano /etc/default/grub
```

Add the following text at the end of `GRUB_CMDLINE_LINUX_DEFAULT`:

```sh
radeon.si_support=0 amdgpu.si_support=1
```

Example:

```sh
GRUB_CMDLINE_LINUX_DEFAULT="mitigations=off quiet splash radeon.si_support=0 amdgpu.si_support=1"
```

Confirm that Vulkan is working:

```sh
vulkaninfo
```

If it says `VK_ERROR_INITIALIZATION_FAILED`, then something went wrong.

### Enable gamemode

To enable Gamemode for a steam game, click on the Properties of a game, navigate to SET LAUNCH OPTIONS and type in `gamemoderun %command%`.

To enable Gamemode for all lutris games, navigate to Preferences (the **` ⋮ `** icon) -> System options -> Command prefix and type in `gamemoderun`, then click Save.
