"""Real fixture conversions and tag editing never touch the user's audio library."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / 'modules/media/tools/audio'
LIB = MODULE / 'files/usr/local/lib/audio-tools'
SPEC = importlib.util.spec_from_file_location('audio_tools_core', LIB / 'core.py')
core = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = core
SPEC.loader.exec_module(core)
PRESETS = MODULE / 'files/home/.config/audio-tools/presets.json'


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
class AudioToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "Artist's $(touch UNEXPECTED) song.flac"
        self.run_command(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.3',
                          '-ac', '2', '-metadata', 'title=Original', '-metadata', 'artist=Artist',
                          '-metadata', 'comment=Keep this', str(self.source)])
        self.original = self.source.read_bytes()

    def run_command(self, command):
        return subprocess.run(command, check=True, capture_output=True, timeout=30)

    def info(self, path):
        return core.audio_info(self.run_command(core.probe_command(path)).stdout)

    def complete(self, operation):
        try:
            self.run_command(operation.command)
            operation.finish()
        finally:
            operation.abort()

    def test_all_presets_keep_sources_and_copy_tags(self):
        expected = ['aac', 'mp3', 'mp3', 'flac', 'opus', 'vorbis', 'pcm_s16le']
        for preset, codec in zip(core.read_presets(PRESETS), expected, strict=True):
            with self.subTest(preset=preset['id']):
                operation = core.conversion(self.source, preset)
                self.complete(operation)
                info = self.info(operation.target)
                self.assertEqual(info['audio'][0]['codec_name'], codec)
                self.assertEqual(info['tags']['title'], 'Original')
                self.assertEqual(info['tags']['artist'], 'Artist')
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse((self.root / 'UNEXPECTED').exists())
        self.assertFalse(list(self.root.glob('.audio-tools-*')))

    def test_conversion_collision_never_overwrites(self):
        preset = core.read_presets(PRESETS)[0]
        operation = core.conversion(self.source, preset)
        self.run_command(operation.command)
        operation.target.write_text('arrived while conversion ran')
        with self.assertRaises(FileExistsError):
            operation.finish()
        self.assertEqual(operation.target.read_text(), 'arrived while conversion ran')
        with self.assertRaises(FileExistsError):
            core.conversion(self.source, preset)

    def test_normalized_conversion_uses_configured_output_sample_rate(self):
        operation = core.conversion(self.source, core.read_presets(PRESETS)[0], normalize=True)
        self.complete(operation)
        self.assertEqual(self.info(operation.target)['audio'][0]['sample_rate'], '48000')

    def test_tags_unicode_clear_field_backup_and_audio_are_preserved(self):
        before = self.run_command(['ffmpeg', '-v', 'error', '-i', str(self.source), '-f', 'md5', '-']).stdout
        self.complete(core.tag_edit(self.source, {'title': 'Български · Tiếng Việt', 'artist': ''}))
        info = self.info(self.source)
        self.assertEqual(info['tags']['title'], 'Български · Tiếng Việt')
        self.assertFalse(info['tags'].get('artist'))
        self.assertEqual(info['tags']['comment'], 'Keep this')
        self.assertEqual(Path(str(self.source) + '.tags-backup').read_bytes(), self.original)
        after = self.run_command(['ffmpeg', '-v', 'error', '-i', str(self.source), '-f', 'md5', '-']).stdout
        self.assertEqual(before, after)

    def test_changed_source_and_failed_job_leave_original_safe(self):
        operation = core.tag_edit(self.source, {'title': 'New'}, backup=False)
        self.run_command(operation.command)
        os.utime(self.source, ns=(1, 1))
        with self.assertRaisesRegex(ValueError, 'changed'):
            operation.finish()
        self.assertEqual(self.source.read_bytes(), self.original)
        operation = core.conversion(self.source, core.read_presets(PRESETS)[0])
        operation.temporary.write_text('incomplete')
        operation.abort()
        self.assertFalse(operation.target.exists())
        self.assertFalse(operation.temporary.exists())

    def test_cover_add_remove_and_tags_roundtrip_in_common_containers(self):
        cover = self.root / 'cover.png'
        self.run_command(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=80x80',
                          '-frames:v', '1', str(cover)])
        presets = core.read_presets(PRESETS)
        for preset in [presets[0], presets[1], presets[3]]:
            with self.subTest(preset=preset['id']):
                operation = core.conversion(self.source, preset)
                self.complete(operation)
                source = operation.target
                self.complete(core.tag_edit(source, {'album_artist': 'Artist', 'track': '3/12',
                                                    'composer': 'Composer', 'date': '2026'}, str(cover), False))
                self.assertEqual(self.info(source)['artwork'], 1)
                converted = core.conversion(source, presets[0], self.root)
                self.complete(converted)
                self.assertEqual(self.info(converted.target)['artwork'], 1)
                self.complete(core.tag_edit(source, {'title': 'Edited'}, '', False))
                self.assertEqual(self.info(source)['artwork'], 0)

    def test_invalid_preset_and_hardlinks_are_rejected(self):
        invalid = self.root / 'presets.json'
        data = json.loads(PRESETS.read_text()); data['presets'][0]['extension'] = '../mp3'
        invalid.write_text(json.dumps(data))
        with self.assertRaises(ValueError): core.read_presets(invalid)
        os.link(self.source, self.root / 'hardlink.flac')
        with self.assertRaisesRegex(ValueError, 'hard-linked'):
            core.tag_edit(self.source, {'title': 'No'})

    def test_lyrics_roundtrip_in_mp3_and_flac(self):
        conversion = core.conversion(self.source, core.read_presets(PRESETS)[1])
        self.complete(conversion)
        for source in (self.source, conversion.target):
            with self.subTest(extension=source.suffix):
                text = 'Line one\n千本桜 · Second line'
                self.complete(core.tag_edit(source, {'lyrics': text}, backup=False))
                self.assertEqual(self.info(source)['tags']['lyrics'], text)


if __name__ == '__main__':
    unittest.main()
