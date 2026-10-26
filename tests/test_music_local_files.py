"""Passive local cache and explicit single-song publishing/renaming fixtures."""
from contextlib import ExitStack
from datetime import datetime,timezone
import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import sys
import support
sys.path.insert(0,str(support.DESKTOP))
from spaces.music import local_files as files


class MusicLocalFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.local=self.root/'Music';self.remote=self.root/'server/Music';self.history=self.root/'history'
        self.local.mkdir();self.remote.mkdir(parents=True)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(files,'ROOT',self.local));self.stack.enter_context(patch.object(files,'DATA',self.root/'data'))
        self.stack.enter_context(patch.object(files,'account_id',return_value='fixture'))
        self.stack.enter_context(patch.object(files,'metadata',side_effect=self.meta))
        case=self
        class Transport:
            def upload(self,path,rel,expected,history):
                current=case.meta(rel)
                if (current and current['ETag']!=expected) or (not current and expected):
                    raise files.nextcloud.NextcloudError('The item changed on Nextcloud. Refresh and try again.')
                target=case.remote/rel;target.parent.mkdir(parents=True,exist_ok=True)
                if current:
                    backup=case.history/history/rel;backup.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,backup)
                shutil.copy2(path,target)
                return case.meta(rel)['ETag']
        self.transport=Transport()
        self.stack.enter_context(patch.object(files,'RemoteFiles',return_value=self.transport))
        self.realrun=files.run;self.commands=[]
        self.stack.enter_context(patch.object(files,'run',side_effect=self.run_command))
    def meta(self,rel):
        path=self.remote/rel
        return dict(Size=path.stat().st_size,ModTime=datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat().replace('+00:00','Z'),Hashes={},ETag='"'+hashlib.sha256(path.read_bytes()).hexdigest()+'"') if path.exists() else None
    def run_command(self,command,timeout=1800):
        if command[0]!='rclone':return self.realrun(command,timeout)
        self.commands.append(command)
        self.assertIn(command[1],('copyto','hashsum'))
        self.assertTrue(all(value not in ('sync','move','delete','purge','bisync') for value in command))
        mapped=[str(self.remote/value.removeprefix('nextcloud:Music/')) if value.startswith('nextcloud:Music/') else str(self.history/value.removeprefix('nextcloud:Music-history/')) if value.startswith('nextcloud:Music-history/') else value for value in command]
        return self.realrun(mapped,timeout)
    def seed(self,rel,content=b'original music'):
        remote=self.remote/rel;local=self.local/rel;remote.parent.mkdir(parents=True,exist_ok=True);local.parent.mkdir(parents=True,exist_ok=True)
        remote.write_bytes(content);shutil.copy2(remote,local)
        files.remember('fixture',rel,local,self.meta(rel))
        return local,remote
    def test_delete_cached_file_nested_directory_and_entire_music_folder_never_touches_server(self):
        one,remoteone=self.seed('one.flac');two,remotetwo=self.seed('album/two.mp3')
        (self.remote/'server-only.flac').write_bytes(b'not cached')
        before={str(p.relative_to(self.remote)):p.read_bytes() for p in self.remote.rglob('*') if p.is_file()}
        one.unlink();shutil.rmtree(self.local/'album')
        self.assertEqual(files.states([]),[]);self.assertEqual(self.commands,[])
        shutil.rmtree(self.local)
        self.assertEqual(files.states([]),[]);self.assertEqual(self.commands,[])
        self.assertEqual(before,{str(p.relative_to(self.remote)):p.read_bytes() for p in self.remote.rglob('*') if p.is_file()})
    def test_browsing_new_local_files_has_no_server_side_effect(self):
        (self.local/'new.mp3').write_bytes(b'new local song')
        result=files.scan()
        self.assertEqual(len(result['items']),1);self.assertEqual(self.commands,[])
        self.assertFalse((self.remote/'new.mp3').exists())

    def test_cached_state_retains_the_row_identity_and_never_uploads(self):
        path,remote=self.seed('song.flac')
        song=dict(id='one',kind='song',source='nextcloud',account='fixture',serverPath='/song.flac')
        state=files.states([song])[0]
        self.assertEqual(tuple(state[key] for key in ('source','kind','id')),tuple(song[key] for key in ('source','kind','id')))
        self.assertTrue(state['local']);self.assertFalse(state['pendingUpload'])
        path.unlink()
        self.assertFalse(files.states([song])[0]['local'])
        self.assertTrue(remote.exists());self.assertEqual(self.commands,[])

    def test_existing_identical_copy_is_adopted_without_upload_or_replacement(self):
        local=self.local/'song.flac';remote=self.remote/'song.flac'
        local.write_bytes(b'matching bytes');remote.write_bytes(b'matching bytes')
        self.assertTrue(files.publish(local)['synced'])
        self.assertEqual([command[1] for command in self.commands],['hashsum'])
        self.commands.clear();files.publish(local);self.assertEqual(self.commands,[])

    def test_info_captures_server_version_before_saving_an_untracked_local_edit(self):
        local=self.local/'song.flac';remote=self.remote/'song.flac'
        local.write_bytes(b'local draft');remote.write_bytes(b'server song')
        song=dict(id='1',source='nextcloud',account='fixture',serverPath='/song.flac')
        files.file_job(dict(action='editor',song=song))
        self.assertEqual(remote.read_bytes(),b'server song')
        self.assertEqual([command[1] for command in self.commands],['hashsum'])
        local.write_bytes(b'explicitly saved tags')
        self.assertTrue(files.publish(local)['synced'])
        self.assertEqual(remote.read_bytes(),b'explicitly saved tags')

    def test_only_edited_and_new_files_upload_and_previous_versions_survive(self):
        local,remote=self.seed('album/song.flac');old=remote.read_bytes()
        local.write_bytes(b'edited local tags and music')
        (self.local/'new.mp3').write_bytes(b'new song')
        result=files.publish(local);self.assertTrue(result['synced']);self.assertFalse((self.remote/'new.mp3').exists());files.publish(self.local/'new.mp3',create=True)
        self.assertEqual(remote.read_bytes(),local.read_bytes());self.assertEqual((self.remote/'new.mp3').read_bytes(),b'new song')
        self.assertTrue(any(path.read_bytes()==old for path in self.history.rglob('*') if path.is_file()))
        self.commands.clear();files.publish(local);self.assertEqual(self.commands,[])

    def test_publish_rejects_a_server_edit_after_metadata_validation(self):
        local,remote=self.seed('race.flac');local.write_bytes(b'local edit')
        upload=self.transport.upload
        def race(path,rel,expected,history):
            remote.write_bytes(b'concurrent server edit')
            return upload(path,rel,expected,history)
        with patch.object(self.transport,'upload',side_effect=race):
            with self.assertRaisesRegex(files.nextcloud.NextcloudError,'changed'):files.publish(local)
        self.assertEqual(remote.read_bytes(),b'concurrent server edit')
        self.assertEqual(local.read_bytes(),b'local edit')

    def test_retry_adopts_a_committed_upload_when_the_response_was_lost(self):
        local,remote=self.seed('retry.flac');local.write_bytes(b'saved local edit')
        upload=self.transport.upload
        def lost_response(*args):
            upload(*args)
            raise files.nextcloud.NextcloudError('Connection lost after upload')
        with patch.object(self.transport,'upload',side_effect=lost_response):
            with self.assertRaises(files.nextcloud.NextcloudError):files.publish(local)
        with patch.object(self.transport,'upload',side_effect=AssertionError('An identical committed file must not upload twice')):
            self.assertTrue(files.publish(local)['synced'])
        self.assertEqual(remote.read_bytes(),local.read_bytes())

    def test_cancel_after_server_commit_still_reports_and_remembers_success(self):
        import time
        from spaces.books.jobs import Jobs,current_job
        local,remote=self.seed('committed.flac');local.write_bytes(b'committed local edit')
        upload=self.transport.upload
        def commit_then_cancel(*args):
            result=upload(*args);current_job().cancelled.set();return result
        jobs=Jobs(errors=(files.MusicError,ValueError));self.addCleanup(jobs.stop)
        with patch.object(self.transport,'upload',side_effect=commit_then_cancel):
            jobs.start('Save fixture',lambda:files.publish(local))
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                job=jobs.snapshots()['jobs'][0]
                if job['state'] not in ('queued','running'):break
                time.sleep(.01)
        self.assertEqual(job['state'],'finished');self.assertTrue(job['result']['synced'])
        self.assertEqual(files.baseline('fixture','committed.flac')['remote'],self.meta('committed.flac'))

    def test_missing_unuploaded_local_song_cannot_download_a_colliding_server_file(self):
        (self.remote/'missing.flac').write_bytes(b'unrelated server song')
        song=dict(id='local:missing.flac',kind='song',source='music-local',account='fixture',serverPath='/missing.flac',notUploaded=True)
        with self.assertRaisesRegex(files.MusicError,'no longer available'):files.download(song)
        self.assertFalse((self.local/'missing.flac').exists());self.assertEqual(self.commands,[])

    def test_uncached_server_move_never_downloads_the_audio(self):
        from urllib.parse import unquote
        remote=self.remote/'old.mp3';remote.write_bytes(b'server-only audio');case=self
        class DAV:
            home='https://cloud.example/dav/Music/'
            def request(self,method,url,body=None,headers=None):
                if method=='PROPFIND':return b'<d:multistatus xmlns:d="DAV:"><d:getetag>"etag"</d:getetag></d:multistatus>',{}
                (case.remote/unquote(url.split('/Music/',1)[1])).rename(case.remote/unquote(headers['Destination'].split('/Music/',1)[1]))
                return b'',{}
        song=dict(id='server-id',kind='song',source='nextcloud',account='fixture',serverPath='/old.mp3')
        with patch.object(files.nextcloud,'load_account',return_value={'url':'https://cloud.example/','username':'fixture'}),patch.object(files.nextcloud,'DAVClient',return_value=DAV()):
            result=files.file_job(dict(action='move',song=song,relativePath='new.mp3'))
        self.assertTrue(result['synced']);self.assertFalse(result['local']);self.assertEqual(self.commands,[])
        self.assertEqual((self.remote/'new.mp3').read_bytes(),b'server-only audio')
        self.assertFalse((self.local/'new.mp3').exists())
        self.assertEqual(files.pending_path('fixture',song),'new.mp3')
    def test_unchanged_cache_does_not_resurrect_server_delete_and_conflicts_keep_both(self):
        local,remote=self.seed('song.flac');remote.unlink()
        self.assertFalse(files.publish(local)['synced']);self.assertFalse(remote.exists());self.commands.clear()
        remote.write_bytes(b'new server version');local.write_bytes(b'new local version')
        with self.assertRaises(files.MusicError):files.publish(local)
        self.assertTrue(all(command[1]=='hashsum' for command in self.commands))
        self.assertEqual(remote.read_bytes(),b'new server version');self.assertEqual(local.read_bytes(),b'new local version')
    def test_download_keeps_relative_path_and_existing_local_edits_and_plays_cache(self):
        path=self.remote/'artist/album/song.flac';path.parent.mkdir(parents=True);path.write_bytes(b'file bytes')
        song=dict(id='1',kind='song',source='nextcloud',account='fixture',serverPath='/artist/album/song.flac')
        cached=files.download(song);self.assertEqual(cached,self.local/'artist/album/song.flac');self.assertEqual(cached.read_bytes(),path.read_bytes())
        self.assertEqual(files.cached(song),cached)
        self.assertEqual(files.file_job(dict(action='editor',song=song)),dict(action='editor',path=str(cached)))
        cached.write_bytes(b'local edit');self.commands.clear()
        self.assertEqual(files.download(song).read_bytes(),b'local edit');self.assertEqual(self.commands,[])
        self.assertTrue(files.states([song])[0]['pendingUpload'])
    def test_explicit_rename_updates_both_paths_without_overwriting(self):
        from urllib.parse import unquote
        local,remote=self.seed('old.mp3');calls=[];remote_root=self.remote
        class DAV:
            home='https://cloud.example/dav/Music/'
            def request(self,method,url,body=None,headers=None):
                calls.append((method,headers))
                if method=='PROPFIND':return b'<d:multistatus xmlns:d="DAV:"><d:getetag>"etag"</d:getetag></d:multistatus>',{}
                self_path=remote_root/unquote(url.split('/Music/',1)[1])
                target=remote_root/unquote(headers['Destination'].split('/Music/',1)[1]);self_path.rename(target)
                return b'',{}
        with patch.object(files.nextcloud,'load_account',return_value={'url':'https://cloud.example/','username':'fixture'}),patch.object(files.nextcloud,'DAVClient',return_value=DAV()):
            result=files.rename(local,'new.mp3')
        self.assertEqual(result['path'],str(self.local/'new.mp3'));self.assertTrue(result['synced'])
        self.assertFalse(local.exists());self.assertFalse(remote.exists())
        self.assertEqual((self.remote/'new.mp3').read_bytes(),b'original music')
        self.assertEqual(calls[-1][1]['Overwrite'],'F');self.assertEqual(calls[-1][1]['If-Match'],'"etag"')
        (self.local/'taken.mp3').write_bytes(b'keep')
        with self.assertRaises(files.MusicError):files.rename(self.local/'new.mp3','taken.mp3')
        self.assertEqual((self.local/'taken.mp3').read_bytes(),b'keep')

    def test_symlinks_and_path_traversal_are_rejected(self):
        for value in ('/../outside.mp3','/a/../../outside.mp3'):
            with self.assertRaises(files.MusicError):files.local_path(files.relative({'serverPath':value}))
        (self.local/'linked').symlink_to(self.remote,target_is_directory=True)
        with self.assertRaises(files.MusicError):files.local_path('linked/song.flac')
    def test_lyrics_explicit_save_updates_local_and_server_song(self):
        local=self.local/'song.flac'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','anullsrc','-t','0.1',str(local)],check=True)
        shutil.copy2(local,self.remote/'song.flac');files.remember('fixture','song.flac',local,self.meta('song.flac'))
        song=dict(id='1',source='nextcloud',account='fixture',serverPath='/song.flac')
        files.file_job(dict(action='lyrics',song=song,lyrics='Original fixture lyrics'))
        self.assertFalse(files.states([song])[0]['pendingUpload'])
        probe=subprocess.run(['ffprobe','-v','error','-show_format','-of','json',str(local)],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(probe.stdout)['format']['tags']['lyrics'],'Original fixture lyrics')
        self.assertEqual((self.remote/'song.flac').read_bytes(),local.read_bytes())

    def test_server_save_failure_keeps_edited_tags_and_retry_does_not_reencode(self):
        from spaces.music import tags
        local=self.local/'song.flac'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','anullsrc','-t','0.1',str(local)],check=True)
        shutil.copy2(local,self.remote/'song.flac');files.remember('fixture','song.flac',local,self.meta('song.flac'))
        song=dict(id='1',source='nextcloud',account='fixture',serverPath='/song.flac')
        with patch.object(files,'publish',side_effect=files.MusicError('Server unavailable')):
            result=files.file_job(dict(action='save',song=song,tags={'title':'Edited title'}))
        self.assertTrue(result['localSaved']);self.assertIn('Server unavailable',result['error'])
        self.assertEqual(tags.read(local,files.run)['tags']['title'],'Edited title')
        with patch.object(tags,'write',side_effect=AssertionError('Retry must preserve saved bytes')):
            result=files.file_job(dict(action='save',song=song,tags={}))
        self.assertTrue(result['synced']);self.assertEqual(local.read_bytes(),(self.remote/'song.flac').read_bytes())
