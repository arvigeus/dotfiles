import importlib.util
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    'qbit_configure', Path(__file__).resolve().parents[1]
    / 'modules/internet/qbittorrent/configure.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class QbittorrentConfigurationTests(unittest.TestCase):
    def test_merge_preserves_qt_values_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'live.conf'
            output = Path(directory) / 'stage/qBittorrent.conf'
            opaque = r'Geometry=@ByteArray(\0\xff\x1\0)' + '\n'
            source.write_text('[GUI]\n; comment\n' + opaque
                              + '[WebUI]\nAddress=*\nLocalHostAuth=true\nUsername=keep\n'
                              + 'Password_PBKDF2=@ByteArray(existing:hash)\n'
                              + '[Preferences]\nSearch\\SearchEnabled=false\nOther=keep')
            module.configure(source, output)
            result = output.read_text()
            self.assertIn(opaque, result)
            self.assertIn('; comment\n', result)
            self.assertIn('Username=keep\n', result)
            self.assertIn('Password_PBKDF2=@ByteArray(existing:hash)\n', result)
            self.assertIn('Other=keep\n', result)
            self.assertNotIn('Address=*', result)
            self.assertIn('Address=127.0.0.1\n', result)
            self.assertEqual(result.count('Search\\SearchEnabled=true\n'), 1)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            module.configure(output, output)
            self.assertEqual(output.read_text(), result)

    def test_fresh_configuration_has_current_webui_section(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'qBittorrent.conf'
            module.configure(path, path)
            content = path.read_text()
            self.assertIn('[WebUI]\nEnabled=true\nAddress=127.0.0.1\n', content)
            self.assertIn('LocalHostAuth=false\n', content)
            self.assertIn('HTTPS\\Enabled=false\n', content)
            self.assertIn('Username=admin\nPassword_PBKDF2=@ByteArray(', content)
            module.configure(path, path)
            self.assertEqual(path.read_text(), content)
