"""Desktop applications register file and folder workflows."""

import json
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
    def test_all_three_apps_register_files_and_folders_without_changing_defaults(self):
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

    def test_checksum_mime_types_are_owned_by_file_tools(self):
        mime = (
            REPO
            / 'modules/files/tools/general/files/usr/local/share/mime/packages/dotfiles-checksums.xml'
        ).read_text()
        for name in ['md5', 'sha1', 'sha256', 'sha512']:
            self.assertIn('text/x-dotfiles-' + name, mime)
        databases = (
            REPO / 'modules/files/dolphin/scripts/50_dolphin-databases.sh'
        ).read_text()
        self.assertIn('update-mime-database', databases)
        self.assertIn('update-desktop-database', databases)

    def test_ocr_and_pdf_conversion_packages_have_separate_owners(self):
        ocr = json.loads((REPO / 'modules/media/tools/ocr/config.json').read_text())
        pdf = json.loads((REPO / 'modules/media/tools/pdf/config.json').read_text())
        self.assertIn('gimagereader-qt', ocr['packages'])
        self.assertNotIn('chaotic-aur/ocrmypdf', ocr['packages'])
        self.assertIn('chaotic-aur/ocrmypdf', pdf['packages'])


if __name__ == '__main__':
    unittest.main()
