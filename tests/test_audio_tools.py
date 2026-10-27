"""Real fixture conversions and tag editing never touch the user's audio library."""
import importlib.util
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mutagen.flac import Picture
from mutagen.oggopus import OggOpus

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

    def opus_with_cover(self):
        operation = core.conversion(self.source, core.read_presets(PRESETS)[4])
        self.complete(operation)
        cover = self.root / 'cover.png'
        self.run_command(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=80x80',
                          '-frames:v', '1', str(cover)])
        picture = Picture()
        picture.type = 3; picture.mime = 'image/png'; picture.width = picture.height = 80
        picture.data = cover.read_bytes()
        audio = OggOpus(operation.target)
        audio['metadata_block_picture'] = [base64.b64encode(picture.write()).decode('ascii')]
        audio['custom-field'] = ['Keep this too']
        audio['tracknumber'] = ['1/5']
        audio['discnumber'] = ['1/1']
        audio['year'] = ['2020']
        audio.save()
        return operation.target

    def packets(self, path):
        probe = json.loads(self.run_command(['ffprobe', '-v', 'error', '-select_streams', 'a:0',
            '-show_packets', '-show_entries', 'packet=data_hash', '-show_data_hash', 'sha256', '-of', 'json', str(path)]).stdout)
        return [packet['data_hash'] for packet in probe['packets']]

    def test_opus_tags_preserve_cover_packets_aliases_and_large_lyrics(self):
        source = self.opus_with_cover()
        original = source.read_bytes()
        before = self.packets(source)
        cover = OggOpus(source)['metadata_block_picture']
        changes = {'title': 'Smile · 千本桜', 'artist': '', 'album_artist': 'Glen Hansard',
                   'track': '3/12', 'disc': '1/2', 'date': '2013-06-13',
                   'lyrics': 'A line of lyrics\n' * 12000}
        self.assertEqual(self.info(source)['tags']['track'], '1/5')
        self.complete(core.tag_edit(source, changes))
        info = self.info(source)
        for key, value in changes.items():
            self.assertEqual(info['tags'].get(key, ''), value)
        audio = OggOpus(source)
        self.assertNotIn('artist', audio)
        self.assertNotIn('year', audio)
        self.assertEqual(audio['custom-field'], ['Keep this too'])
        self.assertEqual(audio['metadata_block_picture'], cover)
        self.assertEqual(info['artwork'], 1)
        self.assertTrue(before)
        self.assertEqual(self.packets(source), before)
        self.assertEqual(Path(str(source) + '.tags-backup').read_bytes(), original)
        self.assertFalse(list(self.root.glob('.audio-tools-*')))
        # Blank edits must not revive values through Vorbis aliases.
        self.complete(core.tag_edit(source, {'album_artist': '', 'track': '', 'disc': '', 'date': ''}, backup=False))
        self.assertTrue(all(not self.info(source)['tags'][key] for key in ('album_artist', 'track', 'disc', 'date')))
        self.assertEqual(self.packets(source), before)

    def test_opus_abort_and_source_conflict_clean_the_private_job_payload(self):
        source = self.opus_with_cover()
        original = source.read_bytes()
        operation = core.tag_edit(source, {'title': 'Draft'}, backup=False)
        self.assertEqual(operation.payload.stat().st_mode & 0o777, 0o600)
        operation.abort()
        self.assertEqual(source.read_bytes(), original)
        self.assertFalse(list(self.root.glob('.audio-tools-*')))
        operation = core.tag_edit(source, {'title': 'Draft'}, backup=False)
        self.run_command(operation.command)
        os.utime(source, ns=(1, 1))
        with self.assertRaisesRegex(ValueError, 'changed'):
            operation.finish()
        self.assertEqual(source.read_bytes(), original)
        self.assertFalse(list(self.root.glob('.audio-tools-*')))


if __name__ == '__main__':
    unittest.main()
