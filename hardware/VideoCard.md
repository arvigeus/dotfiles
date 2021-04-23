# Video card

## Radeon HD 7850 *(Southern Islands)*

```shell
$ lspci -v

01:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Baffin [Radeon RX 550 640SP / RX 560/560X] (rev cf) (prog-if 00 [VGA controller])
	Subsystem: ASUSTeK Computer Inc. Radeon RX 560
	Flags: bus master, fast devsel, latency 0, IRQ 129
	Memory at e0000000 (64-bit, prefetchable) [size=256M]
	Memory at f0000000 (64-bit, prefetchable) [size=2M]
	I/O ports at e000 [size=256]
	Memory at f7d00000 (32-bit, non-prefetchable) [size=256K]
	Expansion ROM at 000c0000 [disabled] [size=128K]
	Capabilities: <access denied>
	Kernel driver in use: amdgpu
	Kernel modules: amdgpu
```

### Install Vulkan

```sh
sudo apt install libvulkan1 mesa-vulkan-drivers vulkan-utils
```

Confirm that Vulkan is working:

```sh
vulkaninfo
```

If it says `VK_ERROR_INITIALIZATION_FAILED`, then something went wrong.

### Enable gamemode

To enable Gamemode for a steam game, click on the Properties of a game, navigate to SET LAUNCH OPTIONS and type in `gamemoderun %command%`.

To enable Gamemode for all lutris games, navigate to Preferences (the **` ⋮ `** icon) -> System options -> Command prefix and type in `gamemoderun`, then click Save.

### Custom Proton version

[Read more](https://github.com/GloriousEggroll/proton-ge-custom)
