"""Desktop applications register file and folder workflows."""

from pathlib import Path
import subprocess
import unittest

REPO = Path(__file__).resolve().parents[1]
APPS = {
    'pdf': 'modules/media/tools/pdf',
    'file': 'modules/files/tools/general',
    'encryption': 'modules/files/tools/encryption',
}


class FileAppRegistrationTests(unittest.TestCase):
    def test_file_and_folder_launchers_are_valid_and_executable(self):
        for kind, module in APPS.items():
            desktop = (
                REPO
                / module
                / f'files/usr/local/share/applications/{kind}-tools.desktop'
            )
            text = desktop.read_text()
            self.assertIn(f'Exec=/usr/local/bin/{kind}-tools %F', text)
            self.assertIn('inode/directory;', text)
            self.assertIn('Type=Application', text)
            subprocess.run(
                ['desktop-file-validate', str(desktop)], check=True, capture_output=True
            )
            launcher = REPO / module / f'files/usr/local/bin/{kind}-tools'
            self.assertTrue(launcher.stat().st_mode & 0o111)


if __name__ == '__main__':
    unittest.main()
