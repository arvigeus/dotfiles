# Firewall

firewalld rejects unsolicited inbound traffic. Modules allow only their own
services: KDE Connect from private and link-local addresses, SSH when the SSH
server module is selected, and DNS/DHCP for libvirt guests.

NetworkManager connections use the default `public` zone unless assigned another.
Other stock zones keep firewalld's defaults; `home` and `work`, for example, allow
SSH.

```sh
firewall-cmd --get-active-zones
firewall-cmd --zone=public --list-all
nmcli connection modify <name> connection.zone home
firewall-cmd --zone=public --add-port=8080/tcp   # until reload or reboot
```

Wheel members in the active local session can change zones without a password,
including with `--permanent`. Applying the configuration overwrites the managed
zone and policy files, so keep permanent access in module assets. See
[ARCHITECTURE.md](ARCHITECTURE.md).
