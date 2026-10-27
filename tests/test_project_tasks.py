"""Task discovery parses declarations without evaluating project commands."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LIB = (
    Path(__file__).resolve().parents[1]
    / 'modules/dev/tools/projects/files/usr/local/lib/project-tools'
)
sys.path.insert(0, str(LIB))
import project_tasks as tasks


class TaskDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_package_scripts_choose_declared_manager_and_keep_names_distinct(self):
        (self.root / 'package.json').write_text(
            json.dumps(
                {
                    'packageManager': 'pnpm@10',
                    'scripts': {'build': 'touch MUST_NOT_RUN', 'test': 'echo test'},
                }
            )
        )
        (self.root / 'bun.lock').write_text('{}')
        catalog, notes = tasks.discover(
            self.root,
            [{'name': 'build', 'description': 'Mise build', 'source': 'mise.toml'}],
        )
        self.assertEqual(
            {(t['runner'], t['name']) for t in catalog},
            {('mise', 'build'), ('package', 'build'), ('package', 'test')},
        )
        self.assertEqual(notes, [])
        self.assertEqual(
            tasks.command(self.root, 'package', 'test', ['space value', '--watch']),
            ['pnpm', 'run', 'test', 'space value', '--watch'],
        )
        self.assertFalse((self.root / 'MUST_NOT_RUN').exists())
        (self.root / 'package.json').write_text('{"scripts":{"test":"true"}}')
        (self.root / 'bun.lock').unlink()
        self.assertEqual(
            tasks.command(self.root, 'package', 'test', ['--watch']),
            ['npm', 'run', 'test', '--', '--watch'],
        )
        with self.assertRaisesRegex(ValueError, 'no longer available'):
            tasks.command(self.root, 'package', 'removed')

    def test_make_discovery_never_evaluates_shell_or_follows_external_includes(self):
        (self.root / 'Makefile').write_text("""X := $(shell touch MUST_NOT_RUN)
include tasks.mk
include $(shell touch MUST_NOT_RUN)
.PHONY: build test
# Build everything
build test: ## Friendly description
\ttouch MUST_NOT_RUN
%.o: %.c
\ttrue
define macro
fake:
endef
""")
        (self.root / 'tasks.mk').write_text('lint:\n\ttrue\n')
        catalog, _ = tasks.discover(self.root)
        self.assertEqual({t['name'] for t in catalog}, {'build', 'test', 'lint'})
        self.assertEqual(
            next(t for t in catalog if t['name'] == 'build')['description'],
            'Friendly description',
        )
        self.assertEqual(
            tasks.command(self.root, 'make', 'lint'),
            ['make', '--file', str(self.root / 'Makefile'), '--', 'lint'],
        )
        self.assertFalse((self.root / 'MUST_NOT_RUN').exists())

    @unittest.skipUnless(shutil.which('just'), 'Just required')
    def test_just_native_parser_handles_docs_aliases_arguments_and_no_backticks(self):
        (self.root / 'Justfile').write_text("""x := `touch MUST_NOT_RUN`
# Build all the things
build target mode="debug":
    touch MUST_NOT_RUN
[private]
hidden:
    true
alias b := build
""")
        catalog, notes = tasks.discover(self.root)
        self.assertEqual(notes, [])
        self.assertEqual({t['name'] for t in catalog}, {'build', 'b'})
        task = next(t for t in catalog if t['name'] == 'build')
        self.assertEqual(task['description'], 'Build all the things')
        self.assertEqual(task['parameters'], 'target [mode]')
        self.assertFalse((self.root / 'MUST_NOT_RUN').exists())
        command = tasks.command(self.root, 'just', 'build', ['example target'])
        self.assertEqual(command[-3:], ['--', 'build', 'example target'])
        # Actual execution is validated with a harmless recipe, not the hostile fixture.
        (self.root / 'Justfile').write_text(
            'build target:\n    @printf "%s" "{{target}}"\n'
        )
        result = subprocess.run(
            tasks.command(self.root, 'just', 'build', ['example target']),
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stdout, 'example target')
