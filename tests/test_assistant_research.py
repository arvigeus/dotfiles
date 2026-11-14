"""Public text research, verified local lyric matches, and native card handoffs."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import support
from test_assistant_drawer import backend, event_stream
import test_assistant_agent as Agent
from test_assistant_agent import tool_call, tool_stream
import research
from spaces.music import backend as music, local_files

web = research.web


class WebResearchTests(unittest.TestCase):
    def test_native_plot_identification_resolves_catalogue_card(self):
        ref = 'space_' + 'b' * 32
        card = research.Spaces.card(
            'movie', dict(id='tt0133093', title='The Matrix', year='1999')
        )
        card['ref'] = ref
        streams = [
            tool_stream(
                tool_call(
                    'web_search', dict(query='movie hacker discovers simulated reality')
                )
            ),
            tool_stream(
                tool_call(
                    'read_web_page',
                    dict(url='https://example.com/film'),
                    identifier='page',
                )
            ),
            tool_stream(
                tool_call(
                    'search_spaces',
                    dict(
                        kind='movie',
                        query='The Matrix',
                        filters=dict(min_year=1999, max_year=1999),
                        display=False,
                    ),
                    identifier='catalogue',
                )
            ),
            tool_stream(
                tool_call(
                    'present_space_results',
                    dict(selections=[dict(ref=ref)]),
                    identifier='cards',
                )
            ),
            event_stream([dict(choices=[dict(delta={}, finish_reason='stop')])]),
        ]
        original = backend.execute_tool

        def execute(name, args, prepared=None):
            if name == 'web_search':
                return dict(
                    entries=[
                        dict(title='Film evidence', url='https://example.com/film')
                    ]
                )
            if name == 'read_web_page':
                return dict(
                    url=args['url'],
                    content='The Matrix (1999): a hacker discovers simulated reality.',
                )
            if name == 'search_spaces':
                backend.SPACE_RESULTS[ref] = card
                return dict(items=[card], display=False)
            return original(name, args, prepared)

        with (
            Agent.AssistantAgentTests().agent(streams) as (chat, events, sent),
            patch.object(backend, 'execute_tool', side_effect=execute),
            patch.object(backend, 'wait_for_approval') as approve,
        ):
            chat()
        approve.assert_not_called()
        self.assertTrue(events[-1]['cards_answer'])
        self.assertEqual(
            [
                row['activity']['name']
                for row in events
                if row['type'] == 'tool' and row['activity']['state'] == 'completed'
            ],
            ['web_search', 'read_web_page', 'search_spaces', 'present_space_results'],
        )
        self.assertIn('untrusted_tool_result', sent[2]['messages'][-1]['content'])
        backend.SPACE_RESULTS.clear()

    def test_urls_and_mixed_dns_cannot_target_local_networks(self):
        for url in (
            'file:///etc/passwd',
            'http://user:secret@example.com/',
            'http://127.0.0.1/',
            'https://[::1]/',
            'https://host.local/',
            'http://10.0.0.1/',
            'https://example.com/\r\nx',
            'https://example.com\\@localhost/',
        ):
            with self.subTest(url=url), self.assertRaises(web.WebError):
                web.clean_url(url)
        self.assertEqual(
            web.clean_url('https://EXAMPLE.com/#x'), 'https://example.com/'
        )
        with (
            patch.object(
                web.socket,
                'getaddrinfo',
                return_value=[
                    (socket.AF_INET, 1, 6, '', ('93.184.216.34', 443)),
                    (socket.AF_INET, 1, 6, '', ('127.0.0.1', 443)),
                ],
            ),
            self.assertRaises(web.WebError),
        ):
            web.public_addresses('example.com', 443)

    def test_connection_pins_validated_address_and_preserves_tls_hostname(self):
        context = MagicMock()
        with (
            patch.object(web.socket, 'create_connection') as connect,
            patch.object(web.ssl, 'create_default_context', return_value=context),
        ):
            connection = web.Connection('example.com', 443, '93.184.216.34', True)
            connection.connect()
        connect.assert_called_once_with(('93.184.216.34', 443), 10)
        context.wrap_socket.assert_called_once_with(
            connect.return_value, server_hostname='example.com'
        )

    def test_redirects_and_oversized_or_compressed_bodies_are_rejected(self):
        for headers, status in [
            ({'Location': 'http://127.0.0.1/'}, 302),
            ({'Content-Length': str(web.MAX_BODY + 1)}, 200),
            ({'Content-Encoding': 'gzip'}, 200),
        ]:
            connection = MagicMock()
            response = connection.getresponse.return_value
            response.status = status
            response.getheader.side_effect = lambda key, default=None: headers.get(
                key, default
            )
            with (
                patch.object(web, 'public_addresses', return_value=['93.184.216.34']),
                patch.object(web, 'Connection', return_value=connection),
                self.assertRaises(web.WebError),
            ):
                web.fetch('https://example.com/')
            connection.close.assert_called_once()
            response.read.assert_not_called()

    def test_page_extraction_ignores_active_hidden_and_navigation_content(self):
        html = '<html><head><title>A film &amp; music</title><script>fetch("private")</script></head><body><nav>Navigation</nav><main><h1>Evidence</h1><p>A visible sentence.</p><div hidden>Hidden</div><a href="/source">Primary source</a><a href="file:///etc/passwd">Bad link</a><style>secret</style></main></body></html>'
        with patch.object(
            web,
            'fetch',
            return_value=dict(
                text=html, mime='text/html', url='https://example.com/film'
            ),
        ):
            result = web.read_page('https://example.com/film')
        self.assertEqual(result['title'], 'A film & music')
        self.assertEqual(
            result['links'],
            [dict(title='Primary source', url='https://example.com/source')],
        )
        for hidden in ('fetch(', 'Navigation', 'Hidden', 'secret'):
            self.assertNotIn(hidden, result['content'])
        self.assertIn('A visible sentence.', result['content'])

    def test_search_challenge_falls_back_and_parses_only_safe_source_links(self):
        html = '<a class="result-link" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Ffilm">A <b>film</b><br> source</a><td class="result-snippet">Plot evidence</td><a class="result-link" href="http://127.0.0.1/">Private</a>'
        with (
            patch.object(web, 'configuration', return_value=dict(provider='auto')),
            patch.object(
                web,
                'fetch',
                side_effect=[
                    dict(status=202, text='challenge-form'),
                    dict(status=200, text=html),
                ],
            ) as fetch,
        ):
            result = web.search('film plot')
        self.assertIn('lite.duckduckgo.com', fetch.call_args_list[0].args[0])
        self.assertIn('html.duckduckgo.com', fetch.call_args_list[1].args[0])
        self.assertEqual(
            result['entries'],
            [
                dict(
                    title='A film source',
                    url='https://example.com/film',
                    snippet='Plot evidence',
                )
            ],
        )
        self.assertIn('verification', result['warning'])

    def test_no_results_and_failed_provider_are_distinct(self):
        with patch.object(web, 'configuration', return_value=dict(provider='auto')):
            with patch.object(
                web,
                'fetch',
                return_value=dict(status=200, text='<p>No results found</p>'),
            ):
                self.assertEqual(web.search('invented phrase')['entries'], [])
            with (
                patch.object(
                    web, 'fetch', return_value=dict(status=202, text='challenge-form')
                ),
                self.assertRaisesRegex(web.WebError, 'unavailable'),
            ):
                web.search('invented phrase')

    def test_configured_searxng_and_pagination(self):
        with (
            patch.object(
                web,
                'configuration',
                return_value=dict(
                    provider='searxng', url='https://search.example/search'
                ),
            ),
            patch.object(
                web,
                'fetch',
                return_value=dict(
                    text=json.dumps(
                        {
                            'results': [
                                {
                                    'title': 'A song',
                                    'url': 'https://example.com/song',
                                    'content': 'Artist evidence',
                                }
                            ]
                        }
                    )
                ),
            ) as fetch,
        ):
            result = web.search('lyric fragment')
        self.assertIn('format=json', fetch.call_args.args[0])
        self.assertEqual(result['provider'], 'SearXNG')
        text, chunks, offset = '夜の音楽 🎵 ' * 4000, [], 0
        while True:
            result = web.chunk(text, offset, 9000)
            self.assertLessEqual(len(result['content'].encode()), 11000)
            chunks.append(result['content'])
            if not result['has_more']:
                break
            offset = result['next_offset']
        self.assertEqual(''.join(chunks), text)
        small = backend.bound_result(web.chunk(text), 100)
        self.assertEqual(small['next_offset'], len(small['content']))


class LyricsResearchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'account/library.sqlite'
        self.path.parent.mkdir()
        self.folder = self.root / 'Music'
        self.folder.mkdir()
        self.song = dict(
            id='song-1',
            title='Fixture Song',
            artist='Fixture Artist',
            album='Fixture Album',
            source='nextcloud',
            account='account',
            serverPath='/album/song.flac',
            local=True,
        )
        self.lyrics = '[00:01.20]Silver spaceships cross the quiet sky\n[00:04.50]Original invented words for this test'
        self.file = self.folder / 'album/song.flac'
        self.file.parent.mkdir()
        self.file.write_bytes(b'fixture audio identity')
        stat = self.file.stat()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE records(kind,id,payload)')
            db.execute(
                'INSERT INTO records VALUES(?,?,?)',
                ('song', self.song['id'], json.dumps(self.song)),
            )
        with closing(sqlite3.connect(self.path.parent / 'local.sqlite')) as db, db:
            db.execute('CREATE TABLE files(path,signature,payload)')
            db.execute(
                'INSERT INTO files VALUES(?,?,?)',
                (
                    'album/song.flac',
                    json.dumps([stat.st_ino, stat.st_size, stat.st_mtime_ns]),
                    json.dumps(dict(tags={**self.song, 'lyrics': self.lyrics})),
                ),
            )
        for patcher in (
            patch.object(research.Spaces, 'music_path', return_value=self.path),
            patch.object(local_files, 'ROOT', self.folder),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        backend.SPACE_RESULTS.clear()
        self.addCleanup(backend.SPACE_RESULTS.clear)

    def test_fragment_returns_real_local_card_without_sending_fragment_online(self):
        args = research.normalize(
            'search_lyrics', dict(fragment='SPACESHIPS, cross the quiet sky!')
        )
        with patch.object(web, 'search') as search:
            result = research.search_lyrics(args)
        search.assert_not_called()
        self.assertEqual(len(result['items']), 1)
        card = result['items'][0]
        self.assertEqual(card['availability'], 'Local')
        self.assertEqual(card['payload']['item']['id'], 'song-1')
        self.assertNotIn('lyrics', card['payload']['item'])
        self.assertIn('spaceships cross', card['metadata']['lyrics_excerpt'])

    def test_stale_or_symlinked_inventory_never_identifies_a_song(self):
        self.file.write_bytes(b'changed audio identity')
        self.assertEqual(research.local_matches('spaceships cross', 5), [])
        self.file.unlink()
        self.file.symlink_to(self.root / 'outside.flac')
        self.assertEqual(research.local_matches('spaceships cross', 5), [])
        self.assertIsNone(research.local_file('../outside.flac'))
        self.assertIsNone(research.local_file('/absolute.flac'))

    def test_online_fragment_leads_require_catalogue_resolution_and_offline_never_searches(
        self,
    ):
        with patch.object(
            web,
            'search',
            return_value=dict(
                entries=[dict(title='Possible artist', url='https://example.com/song')],
                provider='Fixture',
            ),
        ) as search:
            result = research.search_lyrics(
                dict(fragment='entirely different invented words', limit=5)
            )
        self.assertEqual(result['items'], [])
        self.assertIn('verify title and artist', result['next_step'])
        self.assertIn('"entirely different invented words"', search.call_args.args[0])
        with patch.object(web, 'search') as search:
            result = research.search_lyrics(
                dict(
                    fragment='entirely different invented words', limit=5, online=False
                )
            )
        search.assert_not_called()
        self.assertTrue(result['local_checked'])

    def test_online_catalogue_song_prefers_complete_library_lyrics_over_truncated_payload(
        self,
    ):
        online = dict(
            self.song,
            id='apple-song',
            source='itunes',
            account='',
            lyrics='Truncated stale text',
        )
        with patch.object(
            music,
            'fetch_lyrics',
            side_effect=AssertionError('Embedded lyrics must win'),
        ):
            result = research.get_lyrics(dict(song=online, online=False))
        self.assertEqual(result['content'], self.lyrics)
        self.assertTrue(result['saved'])
        self.assertEqual(result['provider'], 'Song tags')

    def test_account_switch_cannot_read_previous_inventory(self):
        with (
            patch.object(research.Spaces, 'music_path', return_value=None),
            patch.object(
                music, 'fetch_lyrics', return_value=dict(available=False)
            ) as lookup,
        ):
            result = research.get_lyrics(dict(song=self.song, online=False))
            self.assertEqual(research.local_matches('spaceships cross', 5), [])
        self.assertFalse(result['available'])
        self.assertFalse(lookup.call_args.args[0]['online'])

    def test_actual_worker_reads_current_account_inventory_and_complete_lyrics(self):
        account = dict(url='https://cloud.example/', username='fixture')
        digest = hashlib.sha256(
            json.dumps(account, sort_keys=True).encode()
        ).hexdigest()
        config = self.root / 'config/quickshell/desktop/integrations'
        config.mkdir(parents=True)
        (config / 'nextcloud.json').write_text(json.dumps(account))
        cache = self.root / 'cache/quickshell/desktop/spaces/music/nextcloud' / digest
        cache.mkdir(parents=True)
        for filename in ('library.sqlite', 'local.sqlite'):
            shutil.copyfile(self.path.parent / filename, cache / filename)
        with patch.dict(
            os.environ,
            dict(
                XDG_CONFIG_HOME=str(self.root / 'config'),
                XDG_CACHE_HOME=str(self.root / 'cache'),
                XDG_MUSIC_DIR=str(self.folder),
            ),
        ):
            args, _ = backend.normalize_tool(
                'search_lyrics', dict(fragment='spaceships cross', online=False)
            )
            found = backend.execute_tool('search_lyrics', args)
            self.assertEqual(found['items'][0]['payload']['item']['account'], digest)
            lyrics = backend.execute_tool(
                'get_song_lyrics', dict(ref=found['items'][0]['ref'], online=False)
            )
        self.assertEqual(lyrics['content'], self.lyrics)
        self.assertTrue(lyrics['saved'])

    def test_lyrics_tool_refs_survive_followup_and_reject_non_song_refs(self):
        result = research.search_lyrics(
            dict(fragment='spaceships cross', limit=5, online=False)
        )
        with patch.object(
            backend,
            'bounded_process',
            return_value=dict(exit_code=0, stdout=json.dumps(result)),
        ):
            args, _ = backend.normalize_tool(
                'search_lyrics', dict(fragment='spaceships cross', online=False)
            )
            found = backend.execute_tool('search_lyrics', args)
        ref = found['items'][0]['ref']
        call = tool_call('search_lyrics', args)
        message = dict(
            role='tool',
            tool_call_id=call['id'],
            content=json.dumps(dict(untrusted_tool_result=found)),
        )
        backend.restore_space_results(
            [dict(role='assistant', tool_calls=[call]), message]
        )
        selected = backend.execute_tool(
            'present_space_results', dict(selections=[dict(ref=ref)])
        )
        self.assertEqual(selected['items'][0]['title'], self.song['title'])
        with patch.object(
            backend,
            'bounded_process',
            return_value=dict(
                exit_code=0,
                stdout=json.dumps(dict(available=True, content='Full lyrics')),
            ),
        ) as worker:
            backend.execute_tool('get_song_lyrics', dict(ref=ref, online=False))
        request = json.loads(worker.call_args.args[0][-1])
        self.assertEqual(request['arguments']['song']['id'], 'song-1')
        backend.SPACE_RESULTS[ref]['kind'] = 'album'
        with self.assertRaisesRegex(ValueError, 'song ref'):
            backend.execute_tool('get_song_lyrics', dict(ref=ref))

    def test_native_agent_can_identify_lyrics_and_present_card(self):
        found = research.search_lyrics(
            dict(fragment='spaceships cross', limit=5, online=False)
        )
        ref = 'space_' + 'a' * 32
        found['items'][0]['ref'] = ref
        streams = [
            tool_stream(tool_call('search_lyrics', dict(fragment='spaceships cross'))),
            tool_stream(
                tool_call(
                    'present_space_results',
                    dict(
                        selections=[
                            dict(
                                ref=ref,
                                reason='Your embedded lyrics contain the remembered line.',
                            )
                        ]
                    ),
                    identifier='present',
                )
            ),
            event_stream([dict(choices=[dict(delta={}, finish_reason='stop')])]),
        ]
        original = backend.execute_tool

        def execute(name, args, prepared=None):
            if name == 'search_lyrics':
                backend.SPACE_RESULTS[ref] = found['items'][0]
                return found
            return original(name, args, prepared)

        with (
            Agent.AssistantAgentTests().agent(streams) as (chat, events, sent),
            patch.object(backend, 'execute_tool', side_effect=execute),
            patch.object(backend, 'wait_for_approval') as approve,
        ):
            chat()
        approve.assert_not_called()
        self.assertTrue(events[-1]['cards_answer'])
        self.assertIn('untrusted_tool_result', sent[1]['messages'][-1]['content'])
        backend.validate_tool_context(events[-1]['tool_context'])

    def test_validation_rejects_model_authored_song_payloads(self):
        for name, args in [
            ('get_song_lyrics', dict(ref='space_' + 'a' * 32, song=self.song)),
            ('get_song_lyrics', dict(ref='invalid')),
            ('search_lyrics', dict(fragment='a')),
            ('search_lyrics', dict(fragment='a real fragment', online='false')),
            ('read_web_page', dict(url='http://localhost')),
            ('web_search', dict(query='real query', limit=True)),
        ]:
            with self.subTest(name=name, args=args), self.assertRaises(ValueError):
                backend.normalize_tool(name, args)


@unittest.skipUnless(support.QS, 'Quickshell required')
class ResearchUiTests(unittest.TestCase):
    def test_source_buttons_lyrics_provenance_and_cards_render(self):
        support.run_qml(
            self,
            """import QtQuick
import Quickshell
import "ui"
import "drawers/assistant"
ShellRoot {
 FloatingWindow {visible:true;implicitWidth:620;implicitHeight:450
  Column {width:600
   ToolActivity {id:sources;width:600;activity:({id:"web",name:"web_search",arguments:{query:"film plot"},state:"completed",result:{entries:[{title:"Evidence",url:"https://example.com/film",snippet:"Plot evidence"}]}})}
   ToolActivity {id:lyrics;width:600;activity:({id:"lyrics",name:"get_song_lyrics",arguments:{},state:"completed",result:{available:true,title:"Fixture song",provider:"Song tags",saved:true,content:"Invented lyric"}})}
   ToolActivity {id:matches;width:600;activity:({id:"match",name:"search_lyrics",arguments:{fragment:"invented words"},state:"completed",result:{items:[{id:"song:fixture",title:"Fixture song",kind:"song",space:"music",icon:"music",payload:{item:{id:"fixture"}}}]}})}
  }
 }
 Timer {interval:250;running:true;onTriggered:{try{
  const links=sources.children.filter(item=>item.objectName?.startsWith("assistantWebSource:"));
  if(links.length!==1||links[0].text!=="Evidence"||!links[0].enabled)throw Error("source link missing");
  if(!sources.resultText.includes("Plot evidence")||sources.resultText.includes("undefined"))throw Error("web details missing");
  if(!lyrics.resultText.includes("Saved lyrics")||!lyrics.resultText.includes("Invented lyric"))throw Error("lyrics provenance missing");
  if(matches.children.filter(item=>item.result?.id==="song:fixture").length!==1)throw Error("lyric match card missing");
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(e){console.error("DISPLAY_FAIL",e.message);Qt.quit();}}}
}""",
        )
