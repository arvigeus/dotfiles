# Tips and Tricks

## HOWTO make Linux run blazing fast (again) on Intel CPUs

Edit GRUB:

```sh
sudo nano /etc/default/grub
```

Add the following text at the end of `GRUB_CMDLINE_LINUX_DEFAULT`:

```sh
mitigations=off
```

Example:

```sh
GRUB_CMDLINE_LINUX_DEFAULT="mitigations=off quiet splash"
