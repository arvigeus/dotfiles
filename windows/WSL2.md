# How to Install WSL 2 on Windows

Enable [Intel Virtualization Technology](https://www.intel.com/content/www/us/en/virtualization/virtualization-technology/intel-virtualization-technology.html) from BIOS

Then run the following commands:

```sh
# Enable WSL
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart

# Enable ‘Virtual Machine Platform’
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
```

After restart, run

```sh
# Set WSL 2 as default
wsl --set-default-version 2
```

## Install distribution

- Ubuntu: `winget install --id=Canonical.Ubuntu -e`

## Using WSL 2 with Visual Studio Code

[Read more](https://code.visualstudio.com/blogs/2019/09/03/wsl2)

## Open linux shell context menu

`Shift + Right Click`
