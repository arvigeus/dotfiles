"""Filtered discovery and the assistant's search/select/present workflow."""

from contextlib import closing
import json
import sqlite3
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import support
import test_space_search as shared
from ui import space_filters as filters

search, assistant = shared.search, shared.assistant


class DiscoveryTests(unittest.TestCase):
    setUp = shared.SpaceSearchTests.setUp
    local_movie = shared.SpaceSearchTests.local_movie

    def seed_movies(self):
        self.local_movie()
        path = self.root / 'data/quickshell/desktop/spaces/movies/library.sqlite'
        items = [
            dict(
                id='tt001',
                kind='movie',
                title='Home',
                genres=['Science Fiction'],
                year='2017',
                rating=8.5,
                votes=4000,
                countries=[{'iso_3166_1': 'US'}],
            ),
            dict(
                id='tt002',
                kind='movie',
                title='Space comedy',
                genres=['Comedy'],
                year='2022',
                rating=9.1,
                votes=5000,
            ),
            dict(
                id='tt003',
                kind='movie',
                title='Old space',
                genres=['Science Fiction'],
                year='1990',
                rating=8.7,
                votes=3000,
            ),
            dict(
                id='tt004',
                kind='movie',
                title='New space',
                genres=['Science Fiction'],
                year='2021',
                rating=7.9,
                votes=2000,
            ),
            dict(id='tt005', kind='movie', title='Unknown metadata'),
        ]
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript(
                'CREATE TABLE cache(key TEXT PRIMARY KEY,value TEXT,updated REAL); CREATE TABLE personal(id TEXT PRIMARY KEY,value TEXT); CREATE TABLE aliases(alias TEXT PRIMARY KEY,id TEXT);'
            )
            for item in items:
                db.execute(
                    'INSERT INTO cache VALUES(?,?,0)',
                    ('title:' + item['id'], json.dumps(item)),
                )
            db.execute(
                'INSERT INTO personal VALUES(?,?)',
                ('tt004', json.dumps({'favorite': True})),
            )
        return items

    def test_genre_discovery_enriches_local_metadata_and_keeps_constraints(self):
        self.seed_movies()
        request = dict(
            kind='movie',
            online=False,
            filters=dict(
                genre='sci-fi',
                min_year=2000,
                max_year=2025,
                min_rating=7,
                min_votes=1000,
                sort='rating',
            ),
        )
        result = search.search(request)
        self.assertEqual(
            [item['title'] for item in result['items']], ['Home', 'New space']
        )
        self.assertEqual(result['items'][0]['availability'], 'Local')
        self.assertEqual(result['filters']['genre'], 'Science Fiction')
        self.assertEqual(result['items'][0]['metadata']['rating'], 8.5)
        self.assertEqual(
            search.normalize(dict(kind='series', filters={'genre': 'sci-fi'}))[
                'filters'
            ]['genre'],
            'Sci-Fi & Fantasy',
        )
        self.assertEqual(
            search.normalize(dict(kind='series', filters={'genre': 'fantasy'}))[
                'filters'
            ]['genre'],
            'Sci-Fi & Fantasy',
        )

    def test_library_scope_does_not_mistake_provider_cache_for_owned_media(self):
        self.seed_movies()
        with patch.object(search, 'online_results') as online:
            result = search.search(
                dict(kind='movie', filters=dict(availability='library'))
            )
        online.assert_not_called()
        self.assertEqual(
            [row['title'] for row in result['items']], ['Home', 'New space']
        )
        with patch.object(search, 'online_results') as online:
            result = search.search(dict(kind='movie', filters=dict(favorites=True)))
        online.assert_not_called()
        self.assertEqual([row['title'] for row in result['items']], ['New space'])
        local = search.search(dict(kind='movie', filters=dict(availability='local')))
        self.assertEqual([row['title'] for row in local['items']], ['Home'])

    def test_movie_discovery_uses_real_provider_filters_without_title_text(self):
        from spaces.movies.backend import Backend

        backend = Backend(
            self.root / 'media.json', self.root / 'media', self.root / 'cache'
        )
        raw = {
            'id': 42,
            'title': 'Arrival',
            'genre_ids': [878],
            'release_date': '2016-11-10',
            'vote_average': 8,
            'vote_count': 10000,
        }
        with (
            patch('spaces.movies.backend.Backend', return_value=backend),
            patch.object(backend, 'config', return_value={'tmdb_key': 'fixture'}),
            patch.object(
                backend, 'tmdb', return_value=dict(results=[raw], total_pages=1)
            ) as provider,
        ):
            result = search.online_results(
                search.normalize(
                    dict(
                        kind='movie',
                        filters={
                            'genre': 'sci-fi',
                            'min_year': 2000,
                            'max_year': 2025,
                            'min_rating': 7,
                            'min_votes': 500,
                            'country': 'US',
                            'sort': 'rating',
                        },
                    )
                )
            )
        self.assertEqual(result[0][0]['title'], 'Arrival')
        args, kwargs = provider.call_args
        self.assertEqual(args, ('discover/movie',))
        self.assertEqual(kwargs['with_genres'], 878)
        self.assertEqual(kwargs['with_origin_country'], 'US')
        self.assertEqual(kwargs['primary_release_date.gte'], '2000-01-01')
        self.assertEqual(kwargs['primary_release_date.lte'], '2025-12-31')
        self.assertEqual(kwargs['vote_average.gte'], 7)
        self.assertEqual(kwargs['vote_count.gte'], 500)

    def test_unsupported_and_malformed_filters_fail_before_provider_work(self):
        invalid = [
            dict(kind='movie', filters={'genre': 'not-a-genre'}),
            dict(kind='movie', filters={'language': 'en'}),
            dict(kind='movie', filters={'min_year': 2025, 'max_year': 2000}),
            dict(kind='movie', filters={'min_rating': float('nan')}),
            dict(kind='movie', filters={'min_votes': True}),
            dict(kind='tv', filters={'genre': 'news'}),
            dict(kind='game', filters={'installed': 'yes'}),
            dict(kind='song', filters={'min_duration': 600, 'max_duration': 30}),
            dict(kind='youtube'),
        ]
        with (
            patch.object(search, 'local_results') as local,
            patch.object(search, 'online_results') as online,
        ):
            for args in invalid:
                with self.subTest(args=args), self.assertRaises(ValueError):
                    search.search(args)
        local.assert_not_called()
        online.assert_not_called()

    def test_title_search_hydrates_country_before_filtering(self):
        with patch('spaces.movies.backend.Backend') as constructor:
            backend = constructor.return_value
            backend.browse.return_value = dict(
                items=[dict(id='tt1', kind='movie', title='Home')]
            )
            backend.details.return_value = dict(
                id='tt1',
                kind='movie',
                title='Home',
                countries=[dict(name='United States', iso_3166_1='US')],
            )
            result, _ = search.online_results(
                search.normalize(
                    dict(kind='movie', query='Home', filters=dict(country='us'))
                )
            )
        self.assertEqual([row['title'] for row in result], ['Home'])
        self.assertNotIn('country', backend.browse.call_args[0][0]['filters'])
        backend.details.assert_called_once()

    def test_each_space_applies_its_own_metadata_constraints(self):
        cases = [
            (
                'radio',
                dict(
                    stationuuid='r1',
                    name='Station',
                    tags='jazz,hip-hop',
                    country='Vietnam',
                    countrycode='VN',
                    language='vietnamese,english',
                    bitrate=192,
                    codec='AAC',
                ),
                dict(
                    genre='hip hop',
                    country='VN',
                    language='English',
                    min_bitrate=128,
                    codec='aac',
                ),
            ),
            (
                'tv',
                dict(
                    id='t1',
                    name='News',
                    categories=['news'],
                    categoryNames=['News'],
                    languages=['eng'],
                    languageNames=['English'],
                    country='US',
                ),
                dict(category='news', country='us', language='English'),
            ),
            (
                'game',
                dict(
                    id='g1',
                    title='Game',
                    genres=['Role-playing (RPG)'],
                    platforms=['PC (Microsoft Windows)'],
                    rating=4.4,
                    installedBy=['steam'],
                    ownedBy=['steam'],
                    releaseDate='2022-01-01',
                ),
                dict(
                    genre='rpg',
                    platform='pc',
                    min_rating=8,
                    min_year=2020,
                    installed=True,
                    owned=True,
                ),
            ),
            (
                'song',
                dict(
                    id='s1',
                    title='Song',
                    artist='Daft Punk',
                    album='Discovery',
                    genreNames=['Electronic'],
                    duration=210,
                    releaseDate='2001-01-01',
                ),
                dict(
                    artist='Daft Punk',
                    album='Discovery',
                    genre='electronic',
                    max_duration=300,
                    min_year=2000,
                ),
            ),
            (
                'youtube',
                dict(
                    id='aqz-KE-bpKQ',
                    title='Astronomy',
                    creator='NASA',
                    duration=600,
                    date='2025-01-01',
                    live=False,
                ),
                dict(
                    channel='NASA',
                    min_duration=60,
                    max_duration=1200,
                    min_year=2020,
                    live=False,
                ),
            ),
        ]
        for kind, item, request in cases:
            with self.subTest(kind=kind):
                card = search.card(kind, item, local=True)
                self.assertTrue(filters.accepts(card, filters.normalize(kind, request)))
        unknown = search.card('youtube', {'id': 'aqz-KE-bpKQ', 'duration': 0})
        self.assertFalse(filters.accepts(unknown, {'max_duration': 600}))
        unknown = search.card('movie', {'id': 'unknown'})
        self.assertFalse(filters.accepts(unknown, {'min_rating': 0}))
        artist = search.card('song', {'id': 's1', 'artist': '宇多田ヒカル'})
        self.assertTrue(filters.accepts(artist, {'artist': '宇多田'}))
        self.assertFalse(filters.accepts(artist, {'artist': '坂本'}))
        game = search.card('game', dict(id='unknown', ownedBy=[], installedBy=[]))
        self.assertFalse(filters.accepts(game, {'owned': False}))
        self.assertFalse(filters.accepts(game, {'installed': False}))
        game['payload']['item'].update(ownershipKnown=True, installationKnown=True)
        self.assertTrue(filters.accepts(game, {'owned': False, 'installed': False}))

    def test_music_artist_filter_searches_the_artist_instead_of_default_charts(self):
        from spaces.music import backend

        with (
            patch.object(
                backend,
                'search_page',
                return_value=dict(
                    items=[
                        dict(
                            id='1',
                            kind='song',
                            source='apple',
                            title='One more time',
                            artist='Daft Punk',
                            duration=200,
                        )
                    ]
                ),
            ) as provider,
            patch.object(
                backend, 'charts', side_effect=AssertionError('unexpected chart')
            ),
        ):
            result, _ = search.online_results(
                search.normalize(
                    dict(
                        kind='song',
                        filters={'artist': 'Daft Punk', 'max_duration': 300},
                    )
                )
            )
        self.assertEqual(result[0]['title'], 'One more time')
        self.assertEqual(provider.call_args[0][0]['query'], 'Daft Punk')

    def test_music_genre_discovery_uses_genre_charts_with_metadata(self):
        from spaces.music import backend

        charts = {
            'songs': [
                {
                    'data': [
                        dict(
                            id='1',
                            attributes=dict(
                                name='Jazz song',
                                artistName='Artist',
                                genreNames=['Jazz'],
                                releaseDate='2021-01-01',
                                durationInMillis=180000,
                            ),
                        )
                    ]
                }
            ]
        }
        with (
            patch.object(
                backend, 'load_genres', return_value=[dict(id='11', name='Jazz')]
            ),
            patch.object(backend, 'charts', return_value=charts) as provider,
            patch.object(
                backend,
                'search_page',
                side_effect=AssertionError('unexpected landing playlist'),
            ),
        ):
            result, _ = search.online_results(
                search.normalize(
                    dict(
                        kind='song',
                        filters={
                            'genre': 'jazz',
                            'min_year': 2020,
                            'max_duration': 300,
                        },
                    )
                )
            )
        self.assertEqual(result[0]['title'], 'Jazz song')
        provider.assert_called_once_with('songs', '11')

    def test_library_music_genre_filter_precedes_limits_and_includes_related_artists(
        self,
    ):
        from integrations import nextcloud
        from spaces.music.cloud_index import CatalogueIndex

        account = dict(url='https://cloud.example/', username='fixture')
        digest = hashlib.sha256(
            json.dumps(account, sort_keys=True).encode()
        ).hexdigest()
        base = self.root / 'cache/quickshell/desktop/spaces/music/nextcloud' / digest
        base.mkdir(parents=True)
        index = CatalogueIndex(
            SimpleNamespace(account_id=digest), base, lambda item: item
        )
        with closing(sqlite3.connect(base / 'library.sqlite')) as db, db:
            index.create(db)
            for i in range(50):
                index.put(
                    db,
                    dict(
                        id=str(i),
                        kind='song',
                        source='nextcloud',
                        account=digest,
                        title=f'Song {i:02}',
                        genreNames=['Jazz' if i == 49 else 'Rock'],
                        artistIds=['a1'] if i == 49 else [],
                        albumId='b1' if i == 49 else '',
                    ),
                )
            index.put(
                db,
                dict(
                    id='a1',
                    kind='artist',
                    source='nextcloud',
                    account=digest,
                    name='Jazz artist',
                ),
            )
            index.put(
                db,
                dict(
                    id='b1',
                    kind='album',
                    source='nextcloud',
                    account=digest,
                    title='Jazz album',
                ),
            )
        with (
            patch.object(nextcloud, 'load_account', return_value=account),
            patch.object(
                search,
                'online_results',
                side_effect=AssertionError('unexpected network request'),
            ),
        ):
            song = search.search(
                dict(kind='song', filters=dict(genre='jazz', availability='library'))
            )
            artist = search.search(
                dict(kind='artist', filters=dict(genre='jazz', availability='library'))
            )
            album = search.search(
                dict(kind='album', filters=dict(genre='jazz', availability='library'))
            )
            choices = search.filter_options(dict(kind='song'))
        self.assertEqual([row['title'] for row in song['items']], ['Song 49'])
        self.assertEqual([row['title'] for row in artist['items']], ['Jazz artist'])
        self.assertEqual([row['title'] for row in album['items']], ['Jazz album'])
        self.assertEqual(
            choices['options']['genres'], [dict(name='Jazz'), dict(name='Rock')]
        )

    def test_game_filters_resolve_names_and_ids_and_use_the_correct_rating_scale(self):
        from spaces.games.igdb import normalize

        item = normalize(
            dict(
                id=42,
                name='A game',
                genres=[dict(id=12, name='Role-playing (RPG)')],
                platforms=[dict(id=6, name='PC (Microsoft Windows)')],
                first_release_date=1609459200,
                total_rating=88,
                total_rating_count=100,
            ),
            'game42',
        )
        for genre, platform in (('rpg', 'pc'), ('12', '6')):
            with (
                self.subTest(genre=genre),
                patch('spaces.games.backend.GamesBackend') as constructor,
            ):
                backend = constructor.return_value
                backend._filter_options.return_value = dict(
                    genres=[dict(id=12, name='Role-playing (RPG)')],
                    platforms=[dict(id=6, name='PC (Microsoft Windows)')],
                )
                backend.browse.return_value = dict(items=[item])
                result, _ = search.online_results(
                    search.normalize(
                        dict(
                            kind='game',
                            filters=dict(
                                genre=genre,
                                platform=platform,
                                min_year=2020,
                                min_rating=8,
                                min_votes=50,
                                sort='oldest',
                            ),
                        )
                    )
                )
                self.assertEqual(len(result), 1)
                self.assertEqual(
                    backend.browse.call_args[0][0]['filters'],
                    dict(genre='12', platform='6', fromYear=2020, sort='released'),
                )
                self.assertEqual(result[0]['metadata']['rating_scale'], 5)

    def test_radio_and_television_filter_the_right_sources(self):
        from test_radio import STATION
        from spaces.radio import api

        with patch.object(
            api,
            'browse',
            return_value={
                'items': [STATION | dict(country='Vietnam', tags='jazz', bitrate=192)]
            },
        ) as provider:
            result, _ = search.online_results(
                search.normalize(
                    dict(
                        kind='radio',
                        filters=dict(genre='jazz', country='Vietnam', min_bitrate=128),
                    )
                )
            )
        self.assertEqual(len(result), 1)
        self.assertEqual(
            provider.call_args[0][0], dict(query='', country='Vietnam', tags=['jazz'])
        )
        base = self.root / 'cache/quickshell/desktop/spaces/television'
        base.mkdir(parents=True)
        channel = dict(
            id='c1',
            name='News',
            categories=['news'],
            country='US',
            languages=['eng'],
            languageNames=['English'],
            streams=[],
        )
        (base / 'catalogue.json').write_text(json.dumps(dict(channels=[channel])))
        result = search.search(
            dict(
                kind='tv',
                filters=dict(category='news', language='English', country='us'),
            )
        )
        self.assertEqual([row['title'] for row in result['items']], ['News'])
        self.assertEqual(
            search.search(dict(kind='tv', filters=dict(favorites=True)))['items'], []
        )

    def test_filter_lookup_is_read_only_and_reports_provider_choices(self):
        from spaces.music import backend

        with patch.object(
            backend,
            'load_genres',
            return_value=[dict(id='11', name='Jazz'), dict(id='21', name='Rock')],
        ) as load:
            result = search.filter_options(dict(kind='song', online=True, query='jazz'))
        load.assert_called_once()
        self.assertEqual(result['options']['genres'], [dict(id='11', name='Jazz')])
        with patch.object(
            backend,
            'load_genres',
            side_effect=AssertionError('unexpected online lookup'),
        ):
            self.assertIn('genre', search.filter_options(dict(kind='movie'))['filters'])
            result = search.filter_options(dict(kind='song'))
        self.assertEqual(result['options'], {})

    def test_shortlist_uses_only_returned_refs_and_survives_a_follow_up(self):
        self.seed_movies()
        captured = []
        args, _ = assistant.normalize_tool(
            'search_spaces',
            dict(
                kind='movie', online=False, filters={'genre': 'sci-fi'}, display=False
            ),
        )
        with (
            patch.object(assistant, 'emit', side_effect=captured.append),
            patch.object(assistant, 'wait_for_approval') as approve,
        ):
            call = dict(
                id='search',
                function=dict(name='search_spaces', arguments=json.dumps(args)),
            )
            message = assistant.call_tool(call, 1)
        approve.assert_not_called()
        result = json.loads(message['content'])['untrusted_tool_result']
        self.assertFalse(result['display'])
        refs = [item['ref'] for item in result['items']]
        selections = [
            dict(ref=refs[-1], reason='A newer choice.'),
            dict(ref=refs[0], reason='A highly rated local option.'),
        ]
        normalized, _ = assistant.normalize_tool(
            'present_space_results',
            dict(title='Science fiction picks', selections=selections),
        )
        presented = assistant.execute_tool('present_space_results', normalized)
        self.assertEqual(
            [row['ref'] for row in presented['items']],
            [row['ref'] for row in selections],
        )
        self.assertEqual(presented['items'][1]['reason'], selections[1]['reason'])
        assistant.restore_space_results(
            [dict(role='assistant', tool_calls=[call]), message]
        )
        restored = assistant.execute_tool('present_space_results', normalized)
        self.assertEqual(restored, presented)
        with self.assertRaises(ValueError):
            assistant.execute_tool(
                'present_space_results', {'selections': [{'ref': 'space_' + '0' * 32}]}
            )
        with self.assertRaises(ValueError):
            assistant.normalize_tool(
                'present_space_results',
                {'selections': [{'ref': refs[0], 'payload': {'command': ['false']}}]},
            )
        assistant.restore_space_results(
            [{'role': 'user', 'content': json.dumps(result)}]
        )
        self.assertEqual(assistant.SPACE_RESULTS, {})

    def test_native_tool_rounds_can_discover_and_present_a_curated_recommendation(self):
        from test_assistant_agent import AssistantAgentTests, tool_call, tool_stream
        from test_assistant_drawer import event_stream

        self.seed_movies()

        def responses():
            yield tool_stream(
                tool_call(
                    'search_spaces',
                    {
                        'kind': 'movie',
                        'filters': {'genre': 'sci-fi', 'min_rating': 7},
                        'online': False,
                        'display': False,
                    },
                    identifier='discovery',
                )
            )
            ref = next(iter(assistant.SPACE_RESULTS))
            yield tool_stream(
                tool_call(
                    'present_space_results',
                    {
                        'selections': [
                            {
                                'ref': ref,
                                'reason': 'A highly rated science fiction film from your local library.',
                            }
                        ]
                    },
                    identifier='shortlist',
                )
            )
            yield event_stream(
                [
                    {
                        'choices': [
                            {
                                'delta': {'content': 'Here is my pick.'},
                                'finish_reason': 'stop',
                            }
                        ]
                    }
                ]
            )

        case = AssistantAgentTests()
        with case.agent(responses()) as (chat, emitted, sent):
            chat()
        activities = [
            event['activity']
            for event in emitted
            if event.get('type') == 'tool' and event['activity']['state'] == 'completed'
        ]
        self.assertEqual(
            [row['name'] for row in activities],
            ['search_spaces', 'present_space_results'],
        )
        self.assertFalse(activities[0]['result']['display'])
        self.assertEqual(len(activities[1]['result']['items']), 1)
        self.assertEqual(activities[1]['result']['items'][0]['availability'], 'Local')
        self.assertEqual(len(sent), 3)
        self.assertIn('Current local date:', sent[0]['messages'][0]['content'])

    def test_presented_cards_are_a_valid_answer_without_redundant_final_prose(self):
        from test_assistant_agent import AssistantAgentTests, tool_call, tool_stream
        from test_assistant_drawer import event_stream

        self.seed_movies()

        def responses():
            yield tool_stream(
                tool_call(
                    'search_spaces',
                    dict(kind='movie', query='Home', online=False, display=False),
                    identifier='discovery',
                )
            )
            ref = next(iter(assistant.SPACE_RESULTS))
            yield tool_stream(
                tool_call(
                    'present_space_results',
                    {
                        'selections': [
                            {
                                'ref': ref,
                                'reason': 'Science fiction from your local library.',
                            }
                        ]
                    },
                    identifier='picks',
                )
            )
            yield event_stream([{'choices': [{'delta': {}, 'finish_reason': 'stop'}]}])

        with AssistantAgentTests().agent(responses()) as (chat, emitted, _sent):
            chat()
        self.assertTrue(emitted[-1]['cards_answer'])
        self.assertNotIn('empty_answer', emitted[-1])


@unittest.skipUnless(support.QS, 'Quickshell required')
class DiscoveryUiTests(unittest.TestCase):
    def test_launcher_filter_parser_and_selected_cards_render_without_extra_matches(
        self,
    ):
        support.run_qml(
            self,
            """import QtQuick
import Quickshell
import "ui"
import "drawers/assistant"
import "ui/SpaceQuery.js" as Query
ShellRoot {
 FloatingWindow {
  id: window;visible:true;implicitWidth:620;implicitHeight:400
  ToolActivity {id: hiddenSearch;width:600;activity:({id:"lookup",name:"search_spaces",arguments:{kind:"movie"},state:"completed",result:{display:false,items:[{id:"movies:extra",title:"Unselected match",payload:{}}]}})}
  ToolActivity {id: shortlist;y:50;width:600;activity:({id:"picks",name:"present_space_results",arguments:{},state:"completed",result:{title:"My picks",items:[{id:"movies:chosen",title:"Chosen film",kind:"movie",space:"movies",icon:"film",payload:{title:{id:"chosen"}},reason:"A thoughtful first-contact story."}]}})}
 }
 function check(value,message){if(!value)throw Error(message);}
 Timer {interval:250;running:true;onTriggered:{try{
  const movie=Query.parse('/movie genre:sci-fi year:2000..2025 rating:7 sort:rating');
  check(movie.query===""&&movie.hasCriteria&&!movie.error&&movie.filters.genre==="sci-fi"&&movie.filters.min_year===2000&&movie.filters.max_year===2025&&movie.filters.min_rating===7,"movie filters");
  const song=Query.parse('/song artist:"Daft Punk" duration:2m..5m local:true');
  check(song.filters.artist==="Daft Punk"&&song.filters.min_duration===120&&song.filters.max_duration===300&&song.filters.availability==="local","quoted artist/duration");
  check(Query.parse("/movie Schindler's List").query==="Schindler's List","apostrophe in title");
  check(Query.parse('/youtube https://www.youtube.com/watch?v=aqz-KE-bpKQ duration:..20m').filters.max_duration===1200,"URL and filter");
  check(Query.parse('/movie genre:"science fiction').error,"unfinished quote");
  check(Query.parse('/movie rating:nope').error,"invalid numeric filter");
  check(Query.parse('/movie gnere:sci-fi').error,"unknown filter");
  const hidden=hiddenSearch.children.filter(item=>item.result?.id==="movies:extra");
  check(hidden.length===0,"lookup rendered unselected cards");
  const cards=shortlist.children.filter(item=>item.result?.id==="movies:chosen");
  check(cards.length===1&&cards[0].height>=90&&cards[0].Accessible.description==="A thoughtful first-contact story.","shortlist card/reason missing");
  AssistantService.messages.append({speaker:"assistant",body:"",state:"streaming",reasoning:"",reasoningBlocksJson:"[]",toolActivitiesJson:JSON.stringify([shortlist.activity])});
  AssistantService.error="";
  AssistantService.receive(JSON.stringify({type:"done",cards_answer:true}));
  check(AssistantService.messages.get(0).state==="done"&&!AssistantService.error,"card-only answer was treated as empty");
  AssistantService.messages.clear();
  AssistantService.messages.append({speaker:"assistant",body:"",state:"streaming",reasoning:"",reasoningBlocksJson:"[]",toolActivitiesJson:"[]"});
  AssistantService.receive(JSON.stringify({type:"done",cards_answer:true}));
  check(AssistantService.messages.get(0).state==="error","missing cards bypassed empty-answer check");
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(e){console.error("DISPLAY_FAIL",e.message);Qt.quit();}}}
}""",
        )
