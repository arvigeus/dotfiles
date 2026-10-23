"""Tokei supplies detection; the dashboard adapts native file reports to byte shares."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

LIB = Path(__file__).resolve().parents[1] / 'modules/dev/tools/projects/files/usr/local/lib/project-tools'
sys.path.insert(0, str(LIB))
import project_inspector as inspector

SCANNER = shutil.which('tokei') or str(Path(os.environ.get('CARGO_HOME', Path.home() / '.local/share/cargo')) / 'bin/tokei')


class LanguageReportTests(unittest.TestCase):
    def test_shell_dialects_share_one_language_percentage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'a.bash').write_text('echo a\n')
            (root / 'b.sh').write_text('echo b\n')
            report = inspector.language_report(root, {
                'BASH': dict(reports=[{'name': 'a.bash'}]),
                'Shell': dict(reports=[{'name': 'b.sh'}]),
            })
            self.assertEqual(len(report['languages']), 1)
            self.assertEqual(report['languages'][0]['name'], 'Shell')
            self.assertEqual(report['languages'][0]['files'], 2)
            self.assertEqual(report['languages'][0]['percentage'], 100)

    def test_reports_count_each_internal_file_once_and_mark_disappeared_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'root'; root.mkdir()
            source = root / 'page.html'; source.write_text('<p>Hello</p>')
            outside = Path(directory) / 'outside.rs'; outside.write_text('fn main() {}')
            (root / 'link.rs').symlink_to(outside)
            report = inspector.language_report(root, {
                'Html': dict(reports=[{'name': 'page.html'}], children={'JavaScript': [{'name': 'page.html'}]}),
                'Rust': dict(reports=[{'name': str(outside)}, {'name': 'link.rs'}, {'name': 'gone.rs'}]),
                'Total': dict(reports=[]),
            })
            self.assertTrue(report['partial'])
            self.assertEqual(report['scanned_files'], 1)
            self.assertEqual(report['total_bytes'], source.stat().st_size)
            self.assertEqual([(l['name'], l['percentage']) for l in report['languages']], [('HTML', 100)])

    def test_missing_tool_bad_output_and_timeout_do_not_break_the_dashboard(self):
        for error in [FileNotFoundError(), subprocess.TimeoutExpired('tokei', 15)]:
            with patch.object(inspector.subprocess, 'run', side_effect=error):
                report, notes = inspector.language_summary(Path('/tmp'))
                self.assertEqual(report['languages'], [])
                self.assertTrue(notes)
        with patch.object(inspector.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '{"Rust":{"reports":[{}]}}')):
            self.assertTrue(inspector.language_summary(Path('/tmp'))[1])


@unittest.skipUnless(Path(SCANNER).is_file(), 'Install Tokei first')
class LanguageScanTests(unittest.TestCase):
    def test_byte_percentages_ignore_vendor_gitignore_and_external_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'project'; root.mkdir()
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / 'main.rs').write_text('fn main() {}\n//' + ' ' * 85)
            (root / 'app.ts').write_text('export const x = true;\n//' + ' ' * 275)
            (root / 'ignored.py').write_text('x' * 5000)
            (root / '.gitignore').write_text('ignored.py\n')
            for directory in ['node_modules', 'vendor', 'target']:
                (root / directory).mkdir(); (root / directory / 'big.js').write_text('x' * 5000)
            outside = Path(folder) / 'outside.py'; outside.write_text('x' * 5000)
            (root / 'link.py').symlink_to(outside)
            report, notes = inspector.language_summary(root)
            self.assertFalse(notes)
            self.assertFalse(report['partial'])
            self.assertEqual(report['total_bytes'], 400)
            self.assertEqual([(l['name'], l['percentage']) for l in report['languages']], [('TypeScript', 75.0), ('Rust', 25.0)])
            self.assertEqual(report['languages'][0]['files'], 1)

    def test_empty_folder_is_a_valid_zero_language_report(self):
        with tempfile.TemporaryDirectory() as folder:
            report, notes = inspector.language_summary(Path(folder))
            self.assertEqual(report['languages'], [])
            self.assertFalse(notes)


if __name__ == '__main__': unittest.main()
