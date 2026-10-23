"""LAN discovery stays on a connected private subnet and performs host discovery only."""
import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PATH = Path(__file__).resolve().parents[1] / 'modules/desktop/quickshell/symlinks/home/.config/quickshell/desktop/drawers/network/discovery.py'
SPEC = importlib.util.spec_from_file_location('network_discovery', PATH)
discovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(discovery)


def addresses(ip='192.168.7.42', prefix=24, interface='wlan0', state='UP'):
    return [{'ifname': interface, 'operstate': state,
             'addr_info': [{'family': 'inet', 'scope': 'global', 'local': ip, 'prefixlen': prefix}]}]


class NetworkDiscoveryTests(unittest.TestCase):
    def test_scope_is_connected_private_network_and_at_most_256_addresses(self):
        self.assertEqual(discovery.scope('wlan0', addresses()), '192.168.7.0/24')
        self.assertEqual(discovery.scope('wlan0', addresses('10.20.30.40', 8)), '10.20.30.0/24')
        self.assertEqual(discovery.scope('wlan0', addresses(prefix=28)), '192.168.7.32/28')
        for values in [addresses('8.8.8.8'), addresses(state='DOWN'), addresses(interface='eth0')]:
            with self.assertRaises(ValueError):
                discovery.scope('wlan0', values)

    def test_xml_lists_only_reachable_ipv4_hosts_in_address_order(self):
        xml = '<nmaprun><host><status state="up"/><address addr="192.168.7.20" addrtype="ipv4"/></host><host><status state="up"/><address addr="192.168.7.3" addrtype="ipv4"/></host><host><status state="down"/><address addr="192.168.7.4" addrtype="ipv4"/></host></nmaprun>'
        self.assertEqual([h['address'] for h in discovery.parse_hosts(xml)], ['192.168.7.3', '192.168.7.20'])

    def test_scanner_is_unprivileged_host_discovery_and_cancellation_owns_child(self):
        import json
        child = Mock(returncode=0)
        child.communicate.return_value = ('<nmaprun/>', '')
        child.poll.return_value = 0
        with patch.object(discovery.subprocess, 'run', return_value=Mock(stdout=json.dumps(addresses()))), \
                patch.object(discovery.subprocess, 'Popen', return_value=child) as popen, \
                patch.object(discovery.signal, 'signal') as signal:
            result = discovery.discover('wlan0')
            handler = signal.call_args_list[0].args[1]
            handler(None, None)
        command = popen.call_args.args[0]
        self.assertIn('-sn', command)
        self.assertIn('--unprivileged', command)
        self.assertEqual(command[-1], '192.168.7.0/24')
        self.assertEqual(result['hosts'], [])
        child.terminate.assert_called_once()

    def test_response_time_uses_reported_microseconds_and_omits_unknown_values(self):
        xml = '''<nmaprun>
          <host><status state="up"/><address addr="192.168.7.1" addrtype="ipv4"/><times srtt="1250"/></host>
          <host><status state="up"/><address addr="192.168.7.2" addrtype="ipv4"/><times srtt="-1"/></host>
          <host><status state="up"/><address addr="192.168.7.3" addrtype="ipv4"/><times srtt="unknown"/></host>
          <host><status state="up"/><address addr="192.168.7.4" addrtype="ipv4"/></host>
        </nmaprun>'''
        self.assertEqual(discovery.parse_hosts(xml), [
            {'address': '192.168.7.1', 'responseMs': 1.25},
            {'address': '192.168.7.2'}, {'address': '192.168.7.3'}, {'address': '192.168.7.4'}])

    def test_timeout_kills_the_exact_scan_process(self):
        import json
        child = Mock(returncode=None)
        child.communicate.side_effect = [subprocess.TimeoutExpired('nmap', 75), ('', '')]
        child.poll.return_value = None
        with patch.object(discovery.subprocess, 'run', return_value=Mock(stdout=json.dumps(addresses()))), \
                patch.object(discovery.subprocess, 'Popen', return_value=child), \
                patch.object(discovery.signal, 'signal'), \
                self.assertRaises(subprocess.TimeoutExpired):
            discovery.discover('wlan0')
        child.kill.assert_called_once()
