# Networking

This module installs `network-manager-applet` for its connection editor.
`extra.masked_user_services` globally masks the generated
`app-nm\x2dapplet@autostart.service` login unit in `/etc/systemd/user`.
NetworkManager and the connection editor remain available.

The mask applies to all users of UWSM/systemd-managed XDG autostart sessions and
survives package updates without modifying package-owned desktop entries. Desktop
environments that launch XDG entries without systemd do not consult this mask.
Applying it to a running session also requires reloading its user manager and
stopping an already-running applet unit.
