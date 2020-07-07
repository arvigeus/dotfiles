# Tips and Tricks

## HOWTO make Linux run blazing fast (again) on Intel CPUs

### Via kernelstub

```sh
sudo kernelstub -a mitigations=off
```

### Via Grub

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
```

## Dark themes

- Audacity: *Edit -> Preferences -> Interface -> Theme -> Dark*
