# Tips and tricks

## Dual booting

### UEFI

- Copy files from Windows efi partition
- Enable timeout for systemd-boot: `sudo nano /boot/efi/loader.conf`

Add the following text:

```text
default Pop_OS-current
timeout 5

auto-entries 1
```

### Legacy (Grub)

Execute the following script:

```sh
sudo apt install os-prober
sudo os-prober
sudo update-grub
```
