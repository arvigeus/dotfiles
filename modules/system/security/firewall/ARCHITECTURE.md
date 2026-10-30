# Firewall

archinstall's native firewall handler installs and enables firewalld. Permanent
configuration is declarative XML; firewalld loads it at start, so no boot-time
rule service or unit ordering is needed.

`/etc/firewalld/zones/public.xml` overrides the stock default zone, which also
accepts SSH, to accept only DHCPv6 replies. NetworkManager binds each connection
to its configured zone, or the default one.

Feature modules ship `/etc/firewalld/policies/<feature>.xml` policies from `ANY`
to `HOST` instead of editing a shared zone file: KDE Connect and mDNS from private
and link-local source ranges, SSH only from the SSH server module. libvirt ships
its own zones and policies. Its network driver adds bridges to them and enables IPv4
forwarding when it starts a NAT or routed network, so no sysctl is declared.

KDE Connect needs both the `kdeconnect` service (TCP/UDP 1714–1764) and `mdns`
for discovery. The stock `mdns` service limits UDP 5353 to the multicast
destinations `224.0.0.251` and `ff02::fb`; the module's rich rules also restrict
source addresses to the same private and link-local ranges as its pairing ports.
No per-SSID zone assignment is needed.

## Desktop ports

`/usr/local/libexec/firewall-ports` is the unprivileged client behind the
Quickshell Ports controls. It reads one JSON request (`status`, or `open`/`close`
with an interface and port 1–65535) and prints one JSON response. It runs `ip`
with an argv list and calls firewalld's runtime zone interface
(`org.fedoraproject.FirewallD1.zone`: `getActiveZones`, `getRichRules`,
`addRichRule` with no timeout, `removeRichRule`) through Gio, never the permanent
configuration. These are the methods and polkit actions `firewall-cmd` uses, but
a status read takes about a quarter of the time without its Python client per
query. Calls never activate a stopped firewalld. python-gobject comes with
firewalld. Error replies map to fixed drawer messages; firewalld's text is not
forwarded.

An opening is a runtime rich rule in the zone of the interface:

```
rule family="ipv4" source address="<subnet>" destination address="<address>" port port="<port>" protocol="tcp" accept
```

The interface's first usable IPv4 address supplies both values. firewalld
reload/restart and reboot discard the rule. Status lists rules of exactly this
shape in active zones and reports each one for the zone interfaces that currently
have that address and subnet. After a network change, rules stay inert and hidden
until that address and subnet return in the same zone. Openings are not owned per
user, and closing does not end established connections.

firewalld's polkit check carries no method details: runtime and permanent zone
changes share `org.fedoraproject.FirewallD1.config`, and reading rich rules needs
`.config.info`. `50-firewall.rules` grants both to active local wheel sessions so
no authentication dialog competes with the drawer's keyboard focus. Direct,
policy and `.all` actions keep the packaged authentication defaults.

## Validation

`tests/test_network_ports.py` replaces firewalld's zone methods and `ip` with an
in-memory host. It covers rule shape, zone lookup, read-only status, input
validation, D-Bus call shape, error mapping, the polkit rule and the zone and
policy assets.
