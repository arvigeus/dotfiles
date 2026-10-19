# UFW and temporary development ports

Provisioning configures a persistent default-deny input / allow-output baseline.
`ufw-rules.service` applies feature-owned scripts serially after UFW starts.

## Desktop port service

`desktop-ports` serves `org.dotfiles.Ports1` on the system bus, activated on demand
by `desktop-ports.service`. The same executable is the unprivileged JSON-lines
client used by Quickshell. The unit is not enabled at boot. It owns NetworkManager
subscriptions after activation; its five-second reconciliation timer makes no
kernel queries while no ports are open.

Request accepts only status, open and close, plus an interface and integer port
1–65535. D-Bus supplies caller identity. Mutations check the exact
`org.dotfiles.ports.manage` polkit action using the caller's unique system-bus
name; only active local wheel sessions are authorized. Status lists only that
UID's openings; closing cannot remove another UID's rules. Each UID may open up
to sixteen ports. No arbitrary command, address, protocol, rule or file is accepted.

The service derives the connected physical Wi-Fi/Ethernet interface, active
connection path, local IPv4 and subnet from libnm. VPN and virtual devices, missing
addresses, unspecified/loopback/multicast addresses and /0 or /32 subnets are
rejected. An allowance matches incoming interface, source subnet, destination host
address and TCP destination port. It is inserted into the active `ufw-user-input`
chain using iptables argv with its shared xtables lock. UFW must already be
enabled; the service never enables, disables or reloads it.

Rules exist only in the kernel. No UFW configuration file is changed, so reboot
and UFW reload discard them. They have no timer. NetworkManager events revoke
allowances when the connection path, address or subnet changes or the device
disconnects. Drawer/shell dismissal and reload leave the system service running.
The five-second check detects externally removed rules without restoring them.
Closing removes the allowance for new connections; UFW's established-connection
policy may keep an existing connection alive.

Every allowance has an unguessable `desktop-ports:<uid>:<uuid>` comment. Resolve
that tag against current iptables output before deleting the complete rule
specification: iptables canonicalizes address/module ordering, and numbered
deletion can target an unrelated rule after concurrent edits. Existing saved
UFW rules are never removed. A service restart removes orphaned owned tags
before accepting requests; normal shutdown also cleans them. Failed removal
retains ownership for retry. An uncertain insertion is rolled back, including
when a command times out after the kernel accepted the rule.

## Validation

`tests/test_network_ports.py` exercises a fake kernel, canonicalized rules,
authentication boundaries, per-user ownership, invalid inputs, network-change
races, failed operations and restart cleanup. QML tests use fake services and
lookup workers; they do not mutate the host firewall or contact public-IP services.
