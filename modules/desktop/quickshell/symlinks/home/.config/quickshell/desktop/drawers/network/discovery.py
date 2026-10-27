#!/usr/bin/env python3
"""Discover reachable devices on a connected private IPv4 network on request."""

import ipaddress
import json
import signal
import subprocess
import sys
import xml.etree.ElementTree as ET

PRIVATE = [
    ipaddress.ip_network(cidr)
    for cidr in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')
]


def scope(interface, addresses):
    for entry in addresses:
        if entry.get('ifname') != interface or entry.get('operstate') not in (
            'UP',
            'UNKNOWN',
        ):
            continue
        for value in entry.get('addr_info', []):
            if value.get('family') != 'inet' or value.get('scope') != 'global':
                continue
            address = ipaddress.ip_interface(f'{value["local"]}/{value["prefixlen"]}')
            if not any(address.ip in network for network in PRIVATE):
                continue
            # A large corporate LAN must not silently become a broad sweep.
            return str(
                ipaddress.ip_network(
                    f'{address.ip}/{max(24, address.network.prefixlen)}', strict=False
                )
            )
    raise ValueError('Connect to a private IPv4 network to discover nearby devices.')


def parse_hosts(document):
    hosts = []
    for host in ET.fromstring(document).findall('host'):
        if host.find('status') is None or host.find('status').get('state') != 'up':
            continue
        address = next(
            (
                a.get('addr')
                for a in host.findall('address')
                if a.get('addrtype') == 'ipv4'
            ),
            None,
        )
        if address:
            device = {'address': str(ipaddress.IPv4Address(address))}
            times = host.find('times')
            response = times.get('srtt', '') if times is not None else ''
            if response.isdecimal():
                device['responseMs'] = int(response) / 1000
            hosts.append(device)
    return sorted(hosts, key=lambda h: ipaddress.IPv4Address(h['address']))


def discover(interface):
    addresses = subprocess.run(
        ['ip', '-json', '-4', 'address', 'show'],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    target = scope(interface, json.loads(addresses.stdout))
    child = subprocess.Popen(
        [
            'nmap',
            '-sn',
            '-n',
            '--unprivileged',
            '--max-retries',
            '1',
            '--host-timeout',
            '2s',
            '-oX',
            '-',
            '--',
            target,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    previous = signal.signal(signal.SIGTERM, lambda *_: child.terminate())
    try:
        output, _ = child.communicate(timeout=75)
        if child.returncode:
            raise ValueError('Device discovery stopped. Try again.')
        return {'subnet': target, 'hosts': parse_hosts(output)}
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate()
        signal.signal(signal.SIGTERM, previous)


if __name__ == '__main__':
    try:
        print(json.dumps({'ok': True, 'data': discover(sys.argv[1])}))
    except (
        ValueError,
        KeyError,
        IndexError,
        OSError,
        subprocess.SubprocessError,
        ET.ParseError,
    ) as error:
        message = (
            str(error)
            if isinstance(error, ValueError)
            else 'Device discovery failed. Check the connection and try again.'
        )
        print(json.dumps({'ok': False, 'error': message}))
