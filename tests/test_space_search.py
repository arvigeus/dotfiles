"""Shared discovery ordering, offline boundaries and actual card handoffs."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import support
from test_assistant_drawer import backend as assistant

search = support.load('space_search', support.DESKTOP / 'ui/space_search.py')


class SpaceSearchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = {
            f'XDG_{kind}_HOME': str(self.root / kind.lower())
            for kind in ('CONFIG', 'DATA', 'CACHE')
        }
        self.environment = patch.dict(os.environ, self.env)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def local_movie(self, kind='movie', title='Home', episode=0):
        space = 'movies' if kind == 'movie' else 'series'
        path = self.root / 'data/quickshell/desktop/spaces' / space / 'library.sqlite'
        path.parent.mkdir(parents=True, exist_ok=True)
        video = self.root / (space + '.mkv')
        video.touch()
        item = dict(id='tt001', title=title, kind=kind, plot='A family returns home.')
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                'CREATE TABLE IF NOT EXISTS local_files(kind,title_id,season,episode,path,title_json)'
            )
            db.execute(
                'INSERT INTO local_files VALUES(?,?,?,?,?,?)',
                (kind, item['id'], 1, episode, str(video), json.dumps(item)),
            )
        return item, video

    def test_provider_aliases_share_one_card_and_keep_existing_artwork(self):
        tmdb = dict(
            id='tmdb:movie:42',
            tmdbId=42,
            kind='movie',
            title='Movie',
            poster='https://example.org/poster.jpg',
        )
        imdb = tmdb | dict(id='tt123', imdbId='tt123')
        result = search.merge(
            [
                search.card('movie', imdb, local=True),
                search.card('movie', tmdb, saved=True),
            ],
            12,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['availability'], 'Local')
        self.assertEqual(result[0]['artwork'], tmdb['poster'])
        for field, value in [
            ('cover', {'url': 'https://example.org/game.jpg'}),
            ('thumbnail', 'https://example.org/video.jpg'),
            ('favicon', 'https://example.org/radio.png'),
        ]:
            self.assertTrue(search.artwork_url({field: value}).startswith('https://'))
        self.assertEqual(search.artwork_url({'cover': 'cloud-cover-id'}), '')

    def test_local_first_deduplication_and_provider_failure_keep_metadata(self):
        item, video = self.local_movie()
        remote = search.card('movie', dict(item, title='Home online'))
        other = search.card('movie', dict(item, id='tt002', title='Home again'))
        events = []
        with patch.object(search, 'online_results', return_value=([remote, other], '')):
            result = search.search(dict(kind='movie', query='home'), events.append)
        self.assertFalse(events[0]['complete'])
        self.assertEqual(
            [row['availability'] for row in result['items']], ['Local', 'Online']
        )
        self.assertEqual(result['items'][0]['title'], 'Home')
        self.assertIn('family', result['items'][0]['metadata']['plot'])
        with patch.object(
            search, 'online_results', side_effect=search.MediaError('Offline')
        ):
            result = search.search(dict(kind='movie', query='home'))
        self.assertEqual(len(result['items']), 1)
        self.assertIn('Offline', result['warning'])
        video.unlink()
        self.assertEqual(
            search.search(dict(kind='movie', query='home', online=False))['items'], []
        )

    def test_series_namespace_and_episode_numbers(self):
        self.local_movie('tv', 'Home series', episode=2)
        args = dict(kind='episode', query='home S01E02', online=False)
        result = search.search(args)
        self.assertEqual(len(result['items']), 1)
        row = result['items'][0]
        self.assertEqual(row['space'], 'series')
        self.assertEqual(row['payload']['episode'], dict(season=1, number=2))
        self.assertTrue(row['playable'])
        self.assertEqual(search.search({**args, 'query': 'home 1x3'})['items'], [])
        self.assertEqual(
            search.search(dict(kind='movie', query='home', online=False))['items'], []
        )

    def test_saved_episode_names_and_metadata_remain_searchable_offline(self):
        item, video = self.local_movie('tv', 'Home series', episode=2)
        video.unlink()
        path = self.root / 'data/quickshell/desktop/spaces/series/library.sqlite'
        episode = dict(
            season='1', number=2, title='The premiere', plot='A surprising homecoming.'
        )
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                'CREATE TABLE cache(key TEXT PRIMARY KEY,value TEXT,updated REAL)'
            )
            db.executemany(
                'INSERT INTO cache VALUES(?,?,0)',
                [
                    ('title:' + item['id'], json.dumps(item)),
                    (
                        'episodes:' + json.dumps([item['id'], '1', '']),
                        json.dumps(dict(items=[episode])),
                    ),
                ],
            )
        result = search.search(dict(kind='episode', query='premiere', online=False))
        self.assertEqual(result['items'][0]['availability'], 'Saved')
        self.assertEqual(
            result['items'][0]['metadata']['episode']['plot'], episode['plot']
        )

    def test_deadline_preserves_local_results_and_music_categories_share_the_limit(
        self,
    ):
        self.local_movie()
        with patch.object(search, 'online_results', side_effect=search.SearchDeadline):
            result = search.search(dict(kind='movie', query='home'))
        self.assertEqual(result['items'][0]['title'], 'Home')
        self.assertIn('timed out', result['warning'])
        from spaces.music import backend as music

        def page(args):
            kind = args['category'][:-1]
            if kind == 'artist':
                raise search.MusicError('Artist lookup unavailable')
            return dict(
                items=[dict(id=str(i), kind=kind, title='Home') for i in range(12)]
            )

        with patch.object(music, 'search_page', side_effect=page):
            result = search.search(dict(kind='music', query='home'))
        self.assertEqual(len(result['items']), 12)
        self.assertEqual(
            [row['kind'] for row in result['items'][:4]],
            ['song', 'album', 'song', 'album'],
        )
        self.assertIn('Artist lookup unavailable', result['warning'])

    def test_music_uses_current_account_snapshot_with_local_songs_first(self):
        from integrations import nextcloud
        from spaces.music.cloud_index import CatalogueIndex

        account = dict(url='https://cloud.example/', username='fixture')
        digest = hashlib.sha256(
            json.dumps(account, sort_keys=True).encode()
        ).hexdigest()
        base = self.root / 'cache/quickshell/desktop/spaces/music/nextcloud'
        for owner in (digest, 'old-account'):
            path = base / owner / 'library.sqlite'
            path.parent.mkdir(parents=True)
            index = CatalogueIndex(
                SimpleNamespace(account_id=owner), path.parent, lambda item: item
            )
            with closing(sqlite3.connect(path)) as db, db:
                CatalogueIndex.create(db)
                for i in range(40):
                    audio = self.root / 'song.flac'
                    audio.touch()
                    index.put(
                        db,
                        dict(
                            id=str(i),
                            kind='song',
                            source='nextcloud',
                            account=owner,
                            title='Home ' + str(i).zfill(2),
                            artist='Fixture',
                            local=i == 39,
                            localPath=str(audio),
                        ),
                    )
        with (
            patch.object(nextcloud, 'load_account', return_value=account),
            patch.object(search, 'online_results') as remote,
        ):
            result = search.search(dict(kind='song', query='home', online=False))
        remote.assert_not_called()
        self.assertEqual(result['items'][0]['availability'], 'Local')
        self.assertEqual(result['items'][0]['payload']['item']['id'], '39')
        self.assertTrue(
            all(row['payload']['item']['account'] == digest for row in result['items'])
        )

    def test_television_search_never_refreshes_the_whole_directory(self):
        channel = dict(
            id='home',
            name='Home TV',
            streams=[dict(id='one', url='https://tv.invalid/live')],
        )
        base = self.root / 'cache/quickshell/desktop/spaces/television'
        base.mkdir(parents=True)
        (base / 'catalogue.json').write_text(json.dumps(dict(channels=[channel])))
        from spaces.television.catalogue import Catalogue

        with patch.object(
            Catalogue, 'refresh', side_effect=AssertionError('unexpected refresh')
        ):
            result = search.search(dict(kind='tv', query='home'))
        self.assertEqual(
            result['items'][0]['payload']['item'], channel | {'favorite': False}
        )

    def test_game_local_search_never_logs_in_to_a_store(self):
        from spaces.games.backend import GamesBackend

        config = self.root / 'config/quickshell/desktop/spaces/games/games.json'
        data = self.root / 'data/quickshell/desktop/spaces/games'
        backend = GamesBackend(config=config, data=data)
        state = dict(
            available=True,
            items=[dict(externalId='620', title='Portal 2', installed=True)],
            ownedIds=['620'],
            ownershipKnown=True,
            installationKnown=True,
        )
        backend._cache_put(
            'libraries:v1', dict(steam=state, epic=state, gog=dict(items=[]))
        )
        with (
            patch('spaces.games.backend.GamesBackend', return_value=backend),
            patch.object(backend, '_steam_state', return_value=state),
            patch.object(
                backend,
                '_run_legendary_json',
                side_effect=AssertionError('unexpected login'),
            ),
        ):
            result = search.search(dict(kind='game', query='portal', online=False))
        self.assertEqual(result['items'][0]['availability'], 'Local')
        self.assertTrue(result['items'][0]['playable'])
        # A configured Steam account with no cached ownership must also stay
        # offline. Ordinary Games discovery may refresh this API on cache miss.
        with (
            patch.object(
                backend,
                'config',
                return_value=dict(
                    steam_api_key='fixture', steam_id='12345678901234567'
                ),
            ),
            patch.object(
                backend,
                '_request',
                side_effect=AssertionError('unexpected Steam API request'),
            ),
        ):
            self.assertFalse(backend._steam_owned_state(offline=True)['known'])

    def test_assistant_tool_uses_real_search_without_approval_and_bounds_cards(self):
        self.local_movie()
        events = []
        with (
            patch.object(assistant, 'emit', side_effect=events.append),
            patch.object(assistant, 'wait_for_approval') as approve,
        ):
            result = assistant.call_tool(
                dict(
                    id='search',
                    function=dict(
                        name='search_spaces',
                        arguments=json.dumps(
                            dict(kind='movie', query='home', online=False)
                        ),
                    ),
                ),
                1,
            )
        approve.assert_not_called()
        self.assertEqual(events[-1]['activity']['state'], 'completed')
        self.assertEqual(events[-1]['activity']['result']['items'][0]['title'], 'Home')
        self.assertIn('family', result['content'])
        bounded = assistant.bound_result(dict(items=[dict(title='x' * 500)] * 50), 1700)
        self.assertLess(len(json.dumps(bounded)), 1800)
        self.assertTrue(bounded['truncated'])
        for value in (
            {'kind': 'shell', 'query': 'x'},
            {'kind': 'movie', 'filters': {'language': 'en'}},
            {'kind': 'movie', 'query': 'x', 'online': 'yes'},
            {'kind': 'movie', 'query': 'x', 'play': True},
        ):
            with self.assertRaises(ValueError):
                assistant.normalize_tool('search_spaces', value)

    def test_cancelling_youtube_search_reaps_its_owned_extractor(self):
        binary = self.root / 'yt-dlp'
        pidfile = self.root / 'extractor.pid'
        binary.write_text(f"""#!{sys.executable}
import os,time
from pathlib import Path
Path({str(pidfile)!r}).write_text(str(os.getpid()))
time.sleep(60)
""")
        binary.chmod(0o700)
        process = subprocess.Popen(
            [sys.executable, str(support.DESKTOP / 'ui/space_search.py')],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            env={
                **os.environ,
                'PATH': str(self.root) + os.pathsep + os.environ['PATH'],
            },
        )
        try:
            process.stdin.write(
                json.dumps(dict(kind='youtube', query='fixture')) + '\n'
            )
            process.stdin.flush()
            deadline = time.monotonic() + 5
            while (
                not pidfile.exists()
                and process.poll() is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.02)
            self.assertTrue(pidfile.exists(), 'The fixture extractor never started.')
            pid = int(pidfile.read_text())
            process.terminate()
            stdout, stderr = process.communicate(timeout=4)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertFalse(
                Path(f'/proc/{pid}').exists(),
                'The cancelled search left yt-dlp running.',
            )
            self.assertFalse(json.loads(stdout.splitlines()[0])['complete'])
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


@unittest.skipUnless(support.QS, 'Quickshell required')
class SpaceCardTests(unittest.TestCase):
    def test_play_cards_repeat_and_wait_for_retained_space_commands(self):
        from test_games_space import setup as games
        from test_music_space import setup as music
        from test_radio_space import setup as radio
        from test_television_space import setup as television
        from test_streaming_space import setup as streaming
        from test_radio import STATION
        from test_television import datasets
        from spaces.television.catalogue import normalize
        from test_streaming import RAW
        from spaces.streaming.youtube import record

        cases = [
            (
                'music',
                music,
                'play',
                {
                    'item': dict(
                        id='music-card', kind='song', source='apple', title='Card song'
                    )
                },
                'track',
                'id',
                'music-card',
            ),
            (
                'radio',
                radio,
                'start',
                {'item': STATION},
                'station',
                'stationuuid',
                STATION['stationuuid'],
            ),
            (
                'television',
                television,
                'play',
                {'item': normalize(datasets())['channels'][17]},
                '',
                'channelId',
                'Fixture17.us',
            ),
            (
                'streaming',
                streaming,
                'play',
                {'item': record(RAW)},
                '',
                'videoId',
                RAW['id'],
            ),
            (
                'games',
                games,
                'action',
                {'item': dict(id='linked-game', title='Card game')},
                '',
                'gameId',
                'linked-game',
            ),
        ]
        for space, prepare, operation, payload, parent, field, expected in cases:
            with self.subTest(space=space):

                def setup(root):
                    prepare(root)
                    path = root / f'spaces/{space}/backend.py'
                    source = path.read_text()
                    log = f"\n        if request.get('op') == {operation!r}:\n            import pathlib,os,json\n            p=pathlib.Path(os.environ['XDG_STATE_HOME'])/'card-plays.jsonl'\n            p.parent.mkdir(parents=True,exist_ok=True)\n            with p.open('a') as f:f.write(json.dumps(request)+'\\n')\n"
                    if space == 'music':
                        source = source.replace(
                            '    if op == "play":\n',
                            log.replace('request', 'args')
                            .replace('        ', '    ')
                            .lstrip('\n')
                            + '    if op == "play":\n',
                        )
                    else:
                        if space == 'games':
                            log += "        if request.get('op')=='availability':return dict(stores=[dict(actions=[dict(id='fixture',type='play')])])\n"
                        source = source.replace(
                            '    def handle(self, request):\n',
                            '    def handle(self, request):\n' + log,
                        )
                    path.write_text(source)

                support.run_qml(
                    self,
                    """import QtQuick
import Quickshell
import Quickshell.Io
import "ui"
ShellRoot {
 InteractionState {id:interactions}
 SpaceHost {id:host;interactionState:interactions}
 FileView {id:log;path:Quickshell.env("XDG_STATE_HOME")+"/card-plays.jsonl";blockLoading:true;printErrors:false}
 property int sent:0
 property int ticks:0
 property int held:0
 property var retained:null
 function requests(){log.reload();log.waitForJob();return log.text().trim().split("\\n").filter(Boolean).map(v=>JSON.parse(v));}
 function open(){SpaceState.open(SPACE,Quickshell.screens[0],Object.assign({},PAYLOAD,{play:true}));sent++;ticks=0;}
 Timer {interval:100;repeat:true;running:true;onTriggered:{try{
  if(!sent){open();return;}
  const page=host.currentPage;if(!page)return;
  if(held){if(++held<4)return;page.commandPending=false;held=0;}
  const calls=requests();
  if(calls.length<sent){if(++ticks<70)return;throw Error("Play request lost: "+SPACE+" "+page.detailError+" "+page.playbackError);}
  const call=PARENT?calls[calls.length-1][PARENT]:calls[calls.length-1];
  if(call[FIELD]!==EXPECTED)throw Error("Wrong playback destination: "+JSON.stringify(calls));
  if(retained&&retained!==page)throw Error("Space was recreated");retained=page;
  if(sent===3){SpaceState.close(SPACE);console.log("DISPLAY_PASS");Qt.quit();return;}
  host.dismiss();
  if(SPACE==="streaming"){page.commandPending=true;held=1;}
  open();
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer {interval:10000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""".replace('SPACE', json.dumps(space))
                    .replace('PAYLOAD', json.dumps(payload))
                    .replace('PARENT', json.dumps(parent))
                    .replace('FIELD', json.dumps(field))
                    .replace('EXPECTED', json.dumps(expected)),
                    setup=setup,
                    isolate_bus=True,
                )

    def test_canonical_details_cannot_replace_repeated_card_selection(self):
        def setup(root):
            from test_movies_space import setup as movies

            movies(root)
            (root / 'spaces/movies/backend.py').write_text("""import time
from worker import serve
def handle(r):
 op=r['op']
 if op=='init':return dict(providers=[],episodeProviders=[],animeProviders=[],genres=[])
 if op=='local_titles':return dict(items=[])
 if op in ('browse','snapshot'):
  time.sleep(.2)
  return dict(items=[dict(id='other',kind=r['kind'],title='Other')],next='')
 if op in ('details','artwork'):
  time.sleep(.02)
  t=r['title']
  if t.get('tmdbId')==42:t=t|dict(id='tt042',imdbId='tt042')
  return dict(title=t,warnings=[]) if op=='artwork' else t
 if op=='personal':return dict(favorite=False,note='',url='')
 if op=='local_files':return []
 return {}
serve(handle,workers=8)
""")

        support.run_qml(
            self,
            """import QtQuick
import Quickshell
import "ui"
ShellRoot {
 InteractionState {id:interactions}
 SpaceHost {id:host;interactionState:interactions}
 property int opens:0
 property int ticks:0
 property var retained:null
 function open(){SpaceState.open("movies",Quickshell.screens[0],{title:{id:"tmdb:movie:42",tmdbId:42,kind:"movie",title:"Requested"}});opens++;ticks=0;}
 Timer {interval:0;running:true;onTriggered:open()}
 Timer {interval:60;repeat:true;running:true;onTriggered:{try{
  const page=host.currentPage;if(!page)return;
  if(++ticks<12)return;
  if(page.selected.id!=="tt042")throw Error("canonical details lost the requested movie: "+JSON.stringify(page.selected));
  if(retained&&page!==retained)throw Error("retained page was replaced");retained=page;
  if(opens<3){page.tab="cast";host.dismiss();open();return;}
  if(page.tab!=="overview")throw Error("repeated open kept a stale tab");
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer {interval:6000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""",
            setup=setup,
            isolate_bus=True,
        )

    def test_assistant_card_survives_drawer_destruction_on_retained_movie_open(self):
        def setup(root):
            import re
            from test_assistant_drawer import FAKE_BACKEND
            from test_movies_space import setup as movies

            movies(root)
            path = root / 'ui/DrawerHost.qml'
            path.write_text(
                re.sub(r'^    WlrLayershell\..*\n', '', path.read_text(), flags=re.M)
            )
            (root / 'drawers/assistant/backend.py').write_text(FAKE_BACKEND)

        support.run_qml(
            self,
            """import QtQuick
import QtTest
import Quickshell
import "ui"
import "drawers/assistant"
ShellRoot {
 id:root
 property int stage:0
 property int ticks:0
 property var retained:null
 InteractionState {id:interactions}
 SpaceHost {id:host;interactionState:interactions}
 DrawerHost {id:drawer;interactionState:interactions
  definitions:[DrawerDefinition {key:"assistant";title:"Assistant";source:Qt.resolvedUrl("drawers/AssistantDrawer.qml")}]
 }
 TestCase {id:input;when:false}
 function findCard(item){if(item.result?.space==="movies")return item;for(const child of item.children??[]){const found=findCard(child);if(found)return found;}return null;}
 function check(value,message){if(!value)throw Error(message);}
 Timer {interval:80;repeat:true;running:true;onTriggered:{try{
  if(++ticks>65)throw Error("timeout stage "+stage+" movie="+host.currentPage?.selected.id+" tab="+host.currentPage?.tab+" linked="+host.currentPage?.linkedTitleId);
  if(stage===0){
   const card={space:"movies",title:"Fixture movie",playable:true,payload:{title:{id:"tt001",kind:"movie",title:"Fixture movie"}}};
   const activity={id:"search",name:"search_spaces",state:"completed",arguments:{kind:"movie"},result:{items:[card]}};
   AssistantService.messages.append({speaker:"assistant",body:"",modelName:"local",state:"done",filesJson:"[]",hasImages:false,reasoning:"",reasoningBlocksJson:"[]",toolContextJson:"[]",toolActivitiesJson:JSON.stringify([activity])});
   drawer.openDrawer("assistant",Quickshell.screens[0]);
  }else if(stage===1||stage===3){
   if(!drawer.currentPage||drawer.slideProgress<1)return;
   const card=findCard(drawer.currentPage);if(!card)return;
   input.mouseClick(card,100,24);
  }else if(stage===2){
   const page=host.currentPage;
   if(!page||page.selected.id!=="tt001"||page.busy)return;
   retained=page;
   page.selectTitle({id:"tt002",kind:"movie",title:"Another movie"});page.tab="cast";
   host.dismiss();drawer.openDrawer("assistant",Quickshell.screens[0]);
  }else if(stage===4){
   const page=host.currentPage;
   check(page===retained&&host.opened&&!drawer.opened,"assistant did not reopen retained Movies page");
   if(page.busy)return;
   check(page.selected.id==="tt001"&&page.tab==="overview","assistant card lost requested movie after drawer destruction: "+JSON.stringify(page.selected));
   SpaceState.close("movies");console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;ticks=0;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer {interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout",stage);Qt.quit();}}
}""",
            setup=setup,
            isolate_bus=True,
        )

    def test_movie_card_reopens_retained_page_and_plays_local_or_first_provider(self):
        def setup(root):
            from test_movies_space import setup as movies

            movies(root)
            (
                root / 'spaces/movies/backend.py'
            ).write_text("""import json,os,pathlib,time
from worker import serve
def title(identifier):
 return dict(id=identifier,kind='movie',title=identifier,poster='',backdrop='')
def handle(request):
 op=request['op']
 if op=='init':
  time.sleep(.3)
  return dict(providers=['First provider','Second provider'],episodeProviders=[],animeProviders=[],genres=[])
 if op in ('browse','snapshot','local_titles'):return dict(items=[title('other')],next='')
 if op=='details':return request['title']
 if op=='artwork':return dict(title=request['title'],warnings=[])
 if op=='personal':return dict(favorite=False,note='',url='')
 if op=='local_files':
  time.sleep(.2)
  return [dict(path='/fixture/local.mkv',torrent=False)] if request['title']['id']=='local' else []
 if op=='play':
  path=pathlib.Path(os.environ['XDG_STATE_HOME'])/'plays.jsonl'
  path.parent.mkdir(parents=True,exist_ok=True)
  with path.open('a') as log:log.write(json.dumps(request)+'\\n')
  return dict(type='direct',command=[])
 return {}
serve(handle,workers=8)
""")

        support.run_qml(
            self,
            """import QtQuick
import Quickshell
import Quickshell.Io
import "ui"
ShellRoot {
 id:root
 property int stage:0
 property int ticks:0
 property double hiddenAt:0
 property var retained:null
 InteractionState {id:interactions}
 SpaceHost {id:host;interactionState:interactions}
 FloatingWindow {implicitWidth:600;implicitHeight:120;visible:true
  SpaceResultCard {id:card;width:580;output:Quickshell.screens[0];result:root.result("remote")}
 }
 FileView {id:plays;path:Quickshell.env("XDG_STATE_HOME")+"/plays.jsonl";blockLoading:true;printErrors:false}
 function result(id){return {space:"movies",title:id,playable:true,payload:{title:{id:id,kind:"movie",title:id}}};}
 function check(value,message){if(!value)throw Error(message);}
 function requests(){plays.reload();plays.waitForJob();return plays.text().trim().split("\\n").filter(Boolean).map(line=>JSON.parse(line));}
 Timer {interval:60;repeat:true;running:true;onTriggered:{try{
  if(++ticks>70)throw Error("timeout stage "+stage+" selected="+host.currentPage?.selected.id);
  const page=host.currentPage;
  if(stage===0){card.clicked();}
  else if(stage===1){
   if(!page||page.selected.id!=="remote"||page.busy)return;
   retained=page;check(requests().length===0,"opening card started playback");
   page.openTitle({id:"other",kind:"movie",title:"Other"});
  }else if(stage===2){
   if(page.selected.id!=="other"||page.busy)return;
   page.tab="cast";host.dismiss();card.clicked();
  }else if(stage===3){
   check(page===retained,"card recreated retained page");
   if(page.selected.id!=="remote"||page.busy)return;
   check(requests().length===0,"reopening card started playback");
   page.tab="cast";host.dismiss();card.clicked();
  }else if(stage===4){
   if(page.busy)return;
   check(page.selected.id==="remote"&&page.tab==="overview","reopening the selected movie kept another detail tab");
   page.watchIndex=1;host.dismiss();card.openResult(true);
  }else if(stage===5){
   const calls=requests();if(calls.length<1)return;
   check(calls.length===1&&calls[0].title.id==="remote"&&calls[0].online&&calls[0].provider===0,"remote movie did not use first Watch online provider: "+JSON.stringify(calls));
   host.dismiss();card.result=result("local");card.openResult(true);
  }else if(stage===6){
   const calls=requests();if(calls.length<2)return;
   check(calls.length===2&&calls[1].title.id==="local"&&!calls[1].online&&calls[1].provider===0,"local movie did not prefer its file: "+JSON.stringify(calls));
   host.dismiss();card.result=result("cancelled");card.openResult(true);
  }else if(stage===7){
   if(page.selected.id!=="cancelled")return;
   check(page.filesLoading,"fixture inventory settled before cancellation");
   host.dismiss();hiddenAt=Date.now();
  }else if(stage===8){
   if(Date.now()-hiddenAt<450)return;
   check(requests().length===2,"hidden card request started playback");
   SpaceState.close("movies");card.result=result("remote");card.openResult(true);
  }else if(stage===9){
   const calls=requests();if(calls.length<3)return;
   check(calls.length===3&&calls[2].title.id==="remote"&&calls[2].online&&calls[2].provider===0,"cold card playback did not wait for its default provider: "+JSON.stringify(calls));
   SpaceState.close("movies");console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;ticks=0;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer {interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout",stage);Qt.quit();}}
}""",
            setup=setup,
            isolate_bus=True,
        )

    def test_links_survive_initial_space_loading_and_select_the_requested_entity(self):
        from test_movies_space import setup as movies
        from test_series_space import setup as series
        from test_music_space import setup as music
        from test_radio_space import setup as radio
        from test_television_space import setup as television
        from test_streaming_space import setup as streaming
        from test_games_space import setup as games
        from test_radio import STATION
        from test_streaming import RAW
        from spaces.streaming.youtube import record
        from spaces.television.catalogue import normalize
        from test_television import datasets

        cases = [
            (
                'movies',
                movies,
                {'title': {'id': 'tt001', 'kind': 'movie', 'title': 'Fixture movie'}},
                'page.selected.id==="tt001" && !page.filters.genre && !page.playLoading',
            ),
            (
                'series',
                series,
                {
                    'title': {'id': 'tt101', 'kind': 'tv', 'title': 'Fixture series'},
                    'episode': {'season': 2, 'number': 1},
                },
                'page.selected.id==="tt101" && page.season==="2" && page.tab==="episodes" && !page.playLoading',
            ),
            (
                'music',
                music,
                {
                    'item': {
                        'id': 'cloud1',
                        'kind': 'song',
                        'source': 'nextcloud',
                        'account': 'fixture',
                        'title': 'Saved song',
                    }
                },
                'Array.from(page.data).some(item=>item.objectName==="musicInformation" && item.song?.id==="cloud1" && item.opened)',
            ),
            (
                'music',
                music,
                {
                    'item': {
                        'id': 'b1',
                        'kind': 'album',
                        'source': 'nextcloud',
                        'account': 'fixture',
                        'title': 'Album',
                    }
                },
                'page.entity?.id==="b1" && page.section==="library"',
            ),
            (
                'music',
                music,
                {
                    'item': {
                        'id': 'a1',
                        'kind': 'artist',
                        'source': 'nextcloud',
                        'account': 'fixture',
                        'name': 'Artist',
                    }
                },
                'page.entity?.id==="a1" && page.section==="library"',
            ),
            (
                'radio',
                radio,
                {'item': STATION},
                'page.rows.length===1 && page.rows[0].name==="Fixture radio" && !page.playback.playing',
            ),
            (
                'television',
                television,
                {'item': normalize(datasets())['channels'][17]},
                'page.channels.length===1 && page.channels[0].id==="Fixture17.us" && !page.playback.playing',
            ),
            (
                'streaming',
                streaming,
                {'item': record(RAW)},
                'page.selected?.id==="aqz-KE-bpKQ" && page.videos.length===1 && !page.playback.playing',
            ),
            (
                'games',
                games,
                {'item': {'id': 'linked-game', 'title': 'Linked game'}},
                'page.selected.id==="linked-game"',
            ),
        ]
        for space, setup, payload, condition in cases:
            with self.subTest(space=space, payload=payload):
                support.run_qml(
                    self,
                    """import QtQuick
import Quickshell
import "ui"
ShellRoot {
 InteractionState {id:interactions}
 SpaceHost {id:host;interactionState:interactions}
 property int stage:0
 property int ticks:0
 property int opens:1
 property var retained:null
 function find(obj,name){if(obj.objectName===name)return obj;for(const c of obj.children||[]){const value=find(c,name);if(value)return value;}return null;}
 Timer {interval:100;repeat:true;running:true;onTriggered:{try{
  if(stage===0){SpaceState.open(SPACE,Quickshell.screens[0],PAYLOAD);stage++;return;}
  const page=host.currentPage;
  if(!page || !(CONDITION)){if(++ticks<65)return;throw Error("requested entity not selected");}
  // Keep observing after initialization so late browse/season replies cannot
  // silently replace the linked selection.
  if(stage++<7)return;
  if(retained&&page!==retained)throw Error("repeated open recreated the Space");retained=page;
  if(opens++<3){
   if(SPACE==="movies"||SPACE==="series")page.openTitle({id:"other",kind:SPACE==="movies"?"movie":"tv",title:"Other"});
   if(SPACE==="games")page.selectGame({id:"other",title:"Other"});
   host.dismiss();SpaceState.open(SPACE,Quickshell.screens[0],PAYLOAD);stage=1;ticks=0;return;
  }
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(e){console.error("DISPLAY_FAIL",e.message);Qt.quit();}}}
 Timer {interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""".replace('SPACE', json.dumps(space))
                    .replace('PAYLOAD', json.dumps(payload))
                    .replace('CONDITION', condition),
                    setup=setup,
                )

    def test_card_actions_and_deferred_open_do_not_autoplay(self):
        support.run_qml(
            self,
            """import QtQuick
import QtTest
import Quickshell
import "ui"
import "drawers/assistant"
import "ui/SpaceQuery.js" as Query
ShellRoot {
 id: root
 property var calls: []
 QtObject {
  id: target
  function openOn(output) {}
  function deliver(id, payload) { root.calls = root.calls.concat([{id:id,payload:payload}]); }
 }
 FloatingWindow {
  id: window; visible: true; implicitWidth: 600; implicitHeight: 500
  TestCase { id: input; when: false }
  ToolActivity {
   id: activity; width: 580; output: Quickshell.screens[0]
   activity: ({id:"search",name:"search_spaces",state:"completed",arguments:{kind:"movie",query:"home"},result:{items:[{id:"movies:1",title:"Home",space:"movies",kind:"movie",icon:"film",availability:"Local",playable:true,payload:{title:{id:"1",kind:"movie"}}}]}})
  }
 }
 SpaceOpenRequest { id: pending; active: true; onDelivered: value => root.calls.push({deferred:value}) }
 property int stage: 0
 function find(obj, name) { if(obj.objectName===name)return obj;for(const c of obj.children||[]){const r=find(c,name);if(r)return r;}return null; }
 Timer { interval: 100; repeat: true; running: true; onTriggered: {
  try {
   if(stage===0){
    SpaceState.host=target;
    if(Query.parse("home")!==null || Query.parse(" /movies home ").kind!=="movie" || Query.parse("/yt space").query!=="space" || Query.parse("/").suggestions.length!==11)throw Error("query routing");
    if(root.calls.length)throw Error("rendering opened a space");
    const card=activity.children.find(c=>c.result?.title==="Home");
    if(!card)throw Error("missing shared card");
    input.mouseClick(card,100,24);
    if(root.calls.length!==1 || root.calls[0].payload.play)throw Error("open played");
    input.mouseClick(find(card,"playSpaceResult"));
    if(root.calls.length!==2 || !root.calls[1].payload.play)throw Error("play was not explicit");
    pending.submit({id:1});
   }else if(stage===1){
    if(root.calls.length!==2)throw Error("delivered before ready");pending.ready=true;
   }else if(stage===2){
    if(root.calls.length<3)return;
    if(root.calls.length!==3 || root.calls[2].deferred.id!==1)throw Error("lost pending open");pending.ready=false;pending.submit({id:2});pending.active=false;pending.ready=true;pending.active=true;
   }else{if(root.calls.length!==3)throw Error("hidden request survived");console.log("DISPLAY_PASS");Qt.quit();}
   stage++;
  }catch(e){console.error("DISPLAY_FAIL",e.message);Qt.quit();}
 } }
 Timer {interval:8000;running:true;onTriggered:{console.error("SPACE_CARDS_TIMEOUT");Qt.quit();}}
}""",
        )
