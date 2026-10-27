import base64
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
import sys
import support

sys.path.insert(0, str(support.DESKTOP))
from unittest.mock import patch

from spaces.movies import anime_sources

spec = importlib.util.spec_from_file_location(
    'media_backend', support.DESKTOP / 'spaces/movies/backend.py'
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.backend = m.Backend(
            root / 'config/media.json', root / 'data', root / 'cache'
        )
        self.movie = dict(id='tt123', imdbId='tt123', kind='movie', title='Movie')

    def configure(self, value):
        self.backend.config_path.write_text(json.dumps(value))

    def test_person_resolves_imdb_identity_through_tmdb_and_sorts_newest_first(self):
        self.configure({'tmdb_key': 'test'})
        responses = [
            {'person_results': [{'id': 10}]},
            {
                'name': 'Actor',
                'combined_credits': {
                    'cast': [
                        {
                            'id': 2,
                            'media_type': 'movie',
                            'title': 'Later',
                            'release_date': '2020-01-01',
                        },
                        {
                            'id': 1,
                            'media_type': 'movie',
                            'title': 'First',
                            'release_date': '1990-01-01',
                            'poster_path': '/poster.jpg',
                        },
                    ]
                },
            },
        ]
        with patch.object(self.backend, 'tmdb', side_effect=responses) as api:
            result = self.backend.person({'person': {'id': 'nm1'}})
        self.assertEqual([t['title'] for t in result['credits']], ['Later', 'First'])
        self.assertEqual(
            result['credits'][1]['poster'], 'https://image.tmdb.org/t/p/w500/poster.jpg'
        )
        self.assertEqual(api.call_args_list[0].args, ('find/nm1',))
        self.assertEqual(api.call_args_list[0].kwargs, {'external_source': 'imdb_id'})

    def test_person_combines_cast_and_crew_roles_without_duplicate_titles(self):
        data = {
            'name': 'Person',
            'combined_credits': {
                'cast': [
                    {
                        'id': 1,
                        'media_type': 'movie',
                        'title': 'Both roles',
                        'release_date': '2024-01-01',
                    }
                ],
                'crew': [
                    {
                        'id': 1,
                        'media_type': 'movie',
                        'title': 'Both roles',
                        'release_date': '2024-01-01',
                        'job': 'Director',
                    },
                    {
                        'id': 2,
                        'media_type': 'movie',
                        'title': 'Crew only',
                        'release_date': '2025-01-01',
                        'job': 'Executive Producer',
                    },
                ],
            },
        }
        with patch.object(self.backend, 'tmdb', return_value=data):
            result = self.backend.person({'person': {'id': 'tmdb:10'}})
        self.assertEqual(
            [t['title'] for t in result['credits']], ['Crew only', 'Both roles']
        )
        self.assertEqual(result['credits'][1]['roles'], ['Actor', 'Director'])
        self.assertEqual(result['credits'][0]['roles'], ['Producer'])

    def test_separate_kinds_and_pagination(self):
        self.configure({'tmdb_key': 'test'})
        with patch.object(
            m,
            'http',
            return_value={'results': [{'id': 12, 'title': 'Film'}], 'total_pages': 2},
        ) as api:
            result = self.backend.browse(dict(kind='movie'))
            self.assertEqual([t['id'] for t in result['items']], ['tmdb:movie:12'])
            self.assertEqual(result['next'], 'tmdb:2')
            self.assertTrue(api.call_args.args[0].endswith('/discover/movie'))

    def test_tmdb_genres_match_each_media_type_in_discovery_and_search(self):
        self.configure({'tmdb_key': 'test'})
        movies = self.backend.handle({'op': 'init', 'kind': 'movie'})['genres']
        series = self.backend.handle({'op': 'init', 'kind': 'tv'})['genres']
        self.assertIn('TV Movie', movies)
        self.assertIn('Science Fiction', movies)
        self.assertIn('Action & Adventure', series)
        self.assertIn('Sci-Fi & Fantasy', series)
        for invalid in ('Biography', 'Sport'):
            self.assertNotIn(invalid, movies)
            self.assertNotIn(invalid, series)
        calls = []

        def api(url, params):
            calls.append((url, params))
            if url.endswith('/search/tv'):
                return {
                    'results': [
                        {'id': 1, 'name': 'Example series', 'genre_ids': [10759, 10765]}
                    ],
                    'total_pages': 1,
                }
            if url.endswith('/discover/tv'):
                return {
                    'results': [
                        {'id': 2, 'name': 'Another series', 'genre_ids': [10765]}
                    ],
                    'total_pages': 1,
                }
            return {
                'results': [{'id': 3, 'title': 'Example movie', 'genre_ids': [10770]}],
                'total_pages': 1,
            }

        with patch.object(m, 'http', side_effect=api):
            found = self.backend.browse(
                {
                    'kind': 'tv',
                    'query': 'Example',
                    'filters': {'genre': 'Action & Adventure'},
                }
            )
            series_result = self.backend.browse(
                {'kind': 'tv', 'filters': {'genre': 'Sci-Fi & Fantasy'}}
            )
            movie_result = self.backend.browse(
                {'kind': 'movie', 'filters': {'genre': 'TV Movie'}}
            )
        self.assertEqual(
            found['items'][0]['genres'], ['Action & Adventure', 'Sci-Fi & Fantasy']
        )
        self.assertEqual(series_result['items'][0]['genres'], ['Sci-Fi & Fantasy'])
        self.assertEqual(movie_result['items'][0]['genres'], ['TV Movie'])
        self.assertEqual(calls[1][1]['with_genres'], 10765)
        self.assertEqual(calls[2][1]['with_genres'], 10770)

    def test_anime_filter_switches_catalogue_and_search_without_affecting_other_genres(
        self,
    ):
        self.configure({'tmdb_key': 'test', 'omdb_key': 'test'})
        calls = []

        def api(url, params):
            calls.append((url, params))
            return {'results': [{'id': 2, 'name': 'Example series'}], 'total_pages': 1}

        anime_row = {
            'idMal': 1,
            'title': {'english': 'Example anime', 'romaji': 'Example anime'},
            'format': 'TV',
            'coverImage': {'large': 'https://example.org/poster.jpg'},
            'startDate': {'year': 2020},
            'genres': ['Action'],
            'episodes': 12,
        }
        with (
            patch.object(m, 'http', side_effect=api),
            patch.object(
                m,
                'anilist',
                return_value={
                    'Page': {'media': [anime_row], 'pageInfo': {'hasNextPage': True}}
                },
            ) as anime_api,
        ):
            anime = self.backend.browse(
                {
                    'kind': 'tv',
                    'query': 'example',
                    'filters': {'genre': 'Anime', 'sort': 'rating'},
                }
            )
            self.assertEqual(anime['items'][0]['id'], 'mal:1')
            self.assertEqual(anime['items'][0]['ratings'], [])
            self.assertEqual(anime['next'], 'anilist:2')
            self.assertEqual(anime_api.call_args.args[1]['search'], 'example')
            self.assertEqual(anime_api.call_args.args[1]['format'], 'TV')
            self.assertEqual(anime_api.call_args.args[1]['sort'], ['SCORE_DESC'])
            self.backend.browse(
                {
                    'kind': 'tv',
                    'query': 'example',
                    'filters': {'genre': 'Anime', 'sort': 'rating'},
                    'page': anime['next'],
                }
            )
            self.assertEqual(anime_api.call_args.args[1]['page'], 2)
            ordinary = self.backend.browse(
                {'kind': 'tv', 'filters': {'genre': 'Animation'}}
            )
            self.assertEqual(ordinary['items'][0]['id'], 'tmdb:tv:2')
            self.assertTrue(calls[-1][0].endswith('/discover/tv'))
            self.assertEqual(calls[-1][1]['with_genres'], 16)

    def test_official_mal_client_supplies_anime_search_ranking_and_details(self):
        self.configure({'mal_client_id': 'private-client-id'})
        series = {
            'id': 1,
            'title': 'Original title',
            'media_type': 'tv',
            'mean': 8.75,
            'num_scoring_users': 120,
            'start_date': '1998-04-03',
            'num_episodes': 26,
            'alternative_titles': {
                'en': 'English title',
                'ja': 'Japanese title',
                'synonyms': [],
            },
            'main_picture': {'large': 'https://example.org/poster.jpg'},
            'genres': [{'name': 'Action'}],
            'studios': [{'name': 'Example studio'}],
        }
        movie = series | {'id': 2, 'media_type': 'movie'}
        calls = []

        def official(url, client_id, params=None):
            calls.append((url, client_id, params))
            if url.endswith('/anime/1'):
                return series | {'synopsis': 'Official synopsis'}
            if params.get('offset') == 100:
                return {'data': [], 'paging': {}}
            return {
                'data': [{'node': series}, {'node': movie}],
                'paging': {
                    'next': 'https://api.myanimelist.net/v2/anime?offset=100&limit=100'
                },
            }

        with (
            patch.object(m, 'official_anime', side_effect=official),
            patch.object(
                m,
                'anilist',
                return_value={
                    'Media': {
                        'idMal': 1,
                        'title': {'english': 'English title'},
                        'bannerImage': 'https://example.org/backdrop.jpg',
                    }
                },
            ) as anime_request,
            patch.object(self.backend, 'anime_episode_metadata', return_value={}),
        ):
            ranked = self.backend.browse({'kind': 'tv', 'filters': {'genre': 'Anime'}})
            next_page = self.backend.browse(
                {'kind': 'tv', 'filters': {'genre': 'Anime'}, 'page': ranked['next']}
            )
            search = self.backend.browse(
                {'kind': 'tv', 'query': 'English', 'filters': {'genre': 'Anime'}}
            )
            detail = self.backend.details({'title': search['items'][0]})
            snapshot = self.backend.handle(
                {
                    'op': 'snapshot',
                    'kind': 'tv',
                    'query': 'English',
                    'filters': {'genre': 'Anime'},
                }
            )
            movies = self.backend.browse(
                {'kind': 'movie', 'filters': {'genre': 'Anime', 'sort': 'rating'}}
            )
        self.assertEqual([row['id'] for row in ranked['items']], ['mal:1'])
        self.assertEqual(ranked['next'], 'malapi:100')
        self.assertEqual(next_page['items'], [])
        self.assertEqual(search['items'][0]['title'], 'English title')
        self.assertEqual(detail['plot'], 'Official synopsis')
        self.assertEqual(detail['ratings'][0]['value'], 8.75)
        self.assertEqual(detail['backdrop'], 'https://example.org/backdrop.jpg')
        self.assertEqual(anime_request.call_count, 1)
        self.assertNotIn('related_anime', calls[3][2]['fields'])
        self.assertEqual(detail['episodesCount'], 26)
        self.assertEqual(snapshot['items'][0]['id'], 'mal:1')
        self.assertEqual([row['id'] for row in movies['items']], ['mal:2'])
        self.assertEqual(calls[0][2]['ranking_type'], 'bypopularity')
        self.assertEqual(calls[1][2]['offset'], 100)
        self.assertEqual(calls[2][2]['q'], 'English')
        self.assertEqual(calls[-1][2]['ranking_type'], 'movie')
        self.assertTrue(all(call[1] == 'private-client-id' for call in calls))
        self.assertNotIn(
            'private-client-id',
            json.dumps(self.backend.handle({'op': 'init', 'kind': 'tv'})),
        )

    def test_anime_movie_popularity_uses_movie_catalogue(self):
        self.configure({'mal_client_id': 'private-client-id'})
        row = {
            'idMal': 2,
            'title': {'english': 'Anime movie'},
            'format': 'MOVIE',
            'episodes': 1,
        }
        with (
            patch.object(
                m,
                'official_anime',
                side_effect=AssertionError(
                    'Mixed MAL rankings cannot provide movie popularity'
                ),
            ),
            patch.object(
                m,
                'anilist',
                return_value={
                    'Page': {'media': [row], 'pageInfo': {'hasNextPage': False}}
                },
            ) as api,
        ):
            movies = self.backend.browse(
                {'kind': 'movie', 'filters': {'genre': 'Anime', 'sort': 'popular'}}
            )
        self.assertEqual([item['id'] for item in movies['items']], ['mal:2'])
        self.assertEqual(api.call_args.args[1]['format'], 'MOVIE')

    def test_official_mal_client_id_is_sent_only_in_request_header(self):
        with patch.object(
            m.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"data":[]}')
        ) as send:
            result = m.official_anime(
                m.MAL + '/anime', 'private-client-id', {'q': 'Cowboy Bebop'}
            )
        request = send.call_args.args[0]
        self.assertEqual(result, {'data': []})
        self.assertEqual(request.get_header('X-mal-client-id'), 'private-client-id')
        self.assertNotIn('private-client-id', request.full_url)
        self.assertIn('q=Cowboy+Bebop', request.full_url)

    def test_anilist_request_omits_null_filters(self):
        with patch.object(
            m.urllib.request,
            'urlopen',
            return_value=io.BytesIO(b'{"data":{"Page":{}}}'),
        ) as send:
            result = m.anilist(
                m.ANILIST_BROWSE,
                {'page': 1, 'format': 'TV', 'search': None, 'genre': None},
            )
        request = send.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(result, {'Page': {}})
        self.assertEqual(body['variables'], {'page': 1, 'format': 'TV'})
        self.assertEqual(request.get_header('Content-type'), 'application/json')

    def test_anilist_data_does_not_reuse_stale_mal_score(self):
        self.backend.save_title(
            {
                'id': 'mal:1',
                'malId': 1,
                'kind': 'tv',
                'title': 'Old title',
                'rating': 8.8,
                'ratings': [{'source': 'MyAnimeList', 'value': 8.8}],
            }
        )
        row = {
            'idMal': 1,
            'title': {'english': 'New title'},
            'format': 'TV',
            'episodes': 12,
        }
        updated = self.backend.save_title(m.anilist_title(row, 'tv'))
        self.assertEqual(updated['title'], 'New title')
        self.assertIsNone(updated['rating'])
        self.assertEqual(updated['ratings'], [])

    def test_official_mal_uses_anilist_for_advanced_filters_and_as_fallback(self):
        self.configure({'mal_client_id': 'private-client-id'})
        row = {
            'idMal': 1,
            'title': {'english': 'Anime'},
            'format': 'TV',
            'startDate': {'year': 2020},
            'episodes': 2,
        }

        def anilist_api(query, variables=None):
            if 'Page(' in query:
                return {'Page': {'media': [row], 'pageInfo': {'hasNextPage': False}}}
            return {'Media': row}

        with (
            patch.object(
                m, 'official_anime', side_effect=m.MediaError('MAL unavailable')
            ) as official,
            patch.object(m, 'anilist', side_effect=anilist_api) as anime_request,
        ):
            plain = self.backend.browse(
                {'kind': 'tv', 'query': 'Anime', 'filters': {'genre': 'Anime'}}
            )
            filtered = self.backend.browse(
                {
                    'kind': 'tv',
                    'query': 'Anime',
                    'filters': {
                        'genre': 'Anime',
                        'animeGenre': 'Action',
                        'minYear': '2020',
                        'maxYear': '2024',
                        'rating': '8.0',
                        'sort': 'rating',
                    },
                }
            )
            detail = self.backend.details({'title': plain['items'][0]})
        self.assertEqual(plain['items'][0]['id'], 'mal:1')
        self.assertEqual(filtered['items'][0]['id'], 'mal:1')
        self.assertEqual(detail['ratings'], [])
        self.assertEqual(
            official.call_count, 2
        )  # Search and title details; filtered browse used AniList.
        filters = anime_request.call_args_list[1].args[1]
        self.assertEqual(filters['genre'], 'Action')
        self.assertEqual(filters['after'], 20191231)
        self.assertEqual(filters['before'], 20250101)
        self.assertEqual(filters['minScore'], 79)
        self.assertEqual(filters['sort'], ['SCORE_DESC'])

    def test_anime_favorite_details_and_episodes_keep_mal_identity(self):
        self.configure({'tmdb_key': 'test'})
        title = {'id': 'mal:1', 'malId': 1, 'kind': 'tv', 'title': 'Example anime'}
        self.backend.handle(
            {'op': 'save', 'title': title, 'values': {'favorite': True}}
        )
        row = {
            'idMal': 1,
            'title': {'english': 'English title'},
            'format': 'TV',
            'episodes': 2,
            'genres': ['Action'],
        }
        with (
            patch.object(m, 'anilist', return_value={'Media': row}),
            patch.object(self.backend, 'anime_episode_metadata', return_value={}),
        ):
            detailed = self.backend.details({'title': title})
            seasons = self.backend.episodes({'title': detailed})
            episodes = self.backend.episodes({'title': detailed, 'season': '1'})
        self.assertEqual(detailed['id'], 'mal:1')
        self.assertEqual(detailed['title'], 'English title')
        self.assertEqual(seasons['seasons'], ['1'])
        self.assertEqual([row['number'] for row in episodes['items']], [1, 2])
        self.assertTrue(self.backend.personal('mal:1')['favorite'])
        self.assertEqual(
            len(
                self.backend.browse(
                    {'kind': 'tv', 'filters': {'genre': 'Anime'}, 'favorites': True}
                )['items']
            ),
            1,
        )
        self.assertEqual(
            self.backend.browse({'kind': 'tv', 'favorites': True})['items'], []
        )

    def test_anime_selected_title_combines_mal_detail_fields_and_anilist_gaps(self):
        self.configure({'mal_client_id': 'private-client-id'})
        official = {
            'id': 1,
            'title': 'Original',
            'alternative_titles': {'en': 'English title'},
            'mean': 8.75,
            'num_episodes': 26,
            'source': 'manga',
            'rating': 'pg_13',
            'start_season': {'season': 'spring', 'year': 1998},
            'background': 'Production notes.',
            'related_anime': [
                {
                    'node': {'id': 2, 'title': 'Sequel'},
                    'relation_type_formatted': 'Sequel',
                }
            ],
            'recommendations': [{'node': {'id': 3, 'title': 'Another anime'}}],
        }
        enrichment = {
            'idMal': 1,
            'title': {'english': 'Different AniList title'},
            'bannerImage': 'https://example.org/backdrop.jpg',
            'trailer': {'id': 'abcdefghijk', 'site': 'youtube'},
            'relations': {
                'edges': [
                    {
                        'relationType': 'SIDE_STORY',
                        'node': {'idMal': 4, 'title': {'english': 'Side story'}},
                    }
                ]
            },
            'characters': {
                'edges': [
                    {
                        'node': {'name': {'full': 'Character'}},
                        'voiceActors': [
                            {
                                'id': 12,
                                'name': {'full': 'Voice Actor'},
                                'image': {'medium': 'https://example.org/actor.jpg'},
                            }
                        ],
                    }
                ]
            },
            'staff': {
                'edges': [
                    {
                        'role': 'Director',
                        'node': {
                            'id': 15,
                            'name': {'full': 'Director'},
                            'image': {'medium': 'https://example.org/director.jpg'},
                        },
                    }
                ]
            },
        }
        with (
            patch.object(m, 'official_anime', return_value=official) as mal,
            patch.object(m, 'anilist', return_value={'Media': enrichment}) as anilist,
        ):
            title = self.backend.details(
                {'title': {'id': 'mal:1', 'malId': 1, 'kind': 'tv', 'title': 'Old'}}
            )
            cached = self.backend.details({'title': title})
            collections = self.backend.collections({'title': title})
            cached_collections = self.backend.collections({'title': title})
        self.assertEqual(title['id'], 'mal:1')
        self.assertEqual(title['title'], 'English title')
        self.assertEqual(
            title['ratings'],
            [
                {
                    'source': 'MyAnimeList',
                    'value': 8.75,
                    'url': 'https://myanimelist.net/anime/1',
                }
            ],
        )
        self.assertEqual(title['backdrop'], 'https://example.org/backdrop.jpg')
        self.assertEqual(
            title['trailers'][0]['url'], 'https://www.youtube.com/watch?v=abcdefghijk'
        )
        self.assertEqual(
            (title['premiere'], title['sourceMaterial'], title['ageRating']),
            ('Spring 1998', 'Manga', 'PG-13'),
        )
        self.assertEqual(title['background'], 'Production notes.')
        self.assertNotIn('relatedAnime', title)
        self.assertEqual(
            [row['malId'] for row in collections['sections'][0]['items']], [2, 4]
        )
        self.assertEqual(
            [row['malId'] for row in collections['sections'][1]['items']], [3]
        )
        self.assertEqual(cached_collections, collections)
        self.assertEqual(
            [row['name'] for row in title['cast']], ['Voice Actor', 'Director']
        )
        self.assertTrue(
            all(
                row['url'].startswith('https://anilist.co/staff/')
                for row in title['cast']
            )
        )
        self.assertEqual(cached, title)
        self.assertEqual(mal.call_count, 2)
        self.assertEqual(anilist.call_count, 2)
        self.assertEqual(anilist.call_args.args[1], {'malId': 1})
        self.assertNotIn('related_anime', mal.call_args_list[0].args[2]['fields'])
        self.assertEqual(
            mal.call_args_list[1].args[2]['fields'], 'related_anime,recommendations'
        )

    def test_anilist_only_title_keeps_its_score_distinct_and_adds_related_data(self):
        self.configure({})
        row = {
            'idMal': 1,
            'title': {'english': 'Anime'},
            'season': 'SPRING',
            'seasonYear': 2020,
            'source': 'LIGHT_NOVEL',
            'relations': {
                'edges': [
                    {
                        'relationType': 'SIDE_STORY',
                        'node': {'idMal': 2, 'title': {'english': 'Side story'}},
                    }
                ]
            },
            'recommendations': {
                'nodes': [
                    {
                        'mediaRecommendation': {
                            'idMal': 3,
                            'title': {'english': 'Suggestion'},
                        }
                    }
                ]
            },
        }
        with patch.object(m, 'anilist', return_value={'Media': row}):
            title = self.backend.details(
                {'title': {'id': 'mal:1', 'malId': 1, 'kind': 'tv', 'title': 'Anime'}}
            )
            collections = self.backend.collections({'title': title})
        self.assertEqual(title['ratings'], [])
        self.assertEqual(title['premiere'], 'Spring 2020')
        self.assertEqual(title['sourceMaterial'], 'Light Novel')
        self.assertNotIn('recommendations', title)
        self.assertEqual(
            [row['malId'] for row in collections['sections'][0]['items']], [2]
        )
        self.assertEqual(
            [row['malId'] for row in collections['sections'][1]['items']], [3]
        )

    def test_related_anime_entry_resolves_movie_kind_and_reuses_cached_identity(self):
        self.configure({'mal_client_id': 'private-client-id'})
        row = {'id': 2, 'title': 'Related film', 'media_type': 'movie'}
        with (
            patch.object(m, 'official_anime', return_value=row) as mal,
            patch.object(
                m,
                'anilist',
                side_effect=AssertionError('Official MAL supplied the entry'),
            ),
        ):
            first = self.backend.handle({'op': 'anime_entry', 'malId': 2})
            second = self.backend.handle({'op': 'anime_entry', 'malId': 2})
        self.assertEqual((first['id'], first['kind']), ('mal:2', 'movie'))
        self.assertEqual(second, first)
        self.assertEqual(mal.call_count, 1)

    def test_related_anime_entry_falls_back_to_anilist_for_series(self):
        self.configure({'mal_client_id': 'private-client-id'})
        row = {
            'idMal': 3,
            'title': {'english': 'Related series'},
            'format': 'TV',
            'episodes': 12,
        }
        with (
            patch.object(
                m, 'official_anime', side_effect=m.MediaError('MAL unavailable')
            ),
            patch.object(m, 'anilist', return_value={'Media': row}) as api,
        ):
            title = self.backend.handle({'op': 'anime_entry', 'malId': 3})
        self.assertEqual(
            (title['id'], title['kind'], title['episodesCount']), ('mal:3', 'tv', 12)
        )
        self.assertIn('Media(idMal:$malId', api.call_args.args[0])
        self.assertEqual(api.call_args.args[1], {'malId': 3})

    def test_movie_collections_load_franchise_and_recommendations_on_request(self):
        self.configure({'tmdb_key': 'test'})
        movie = {
            'id': 'tmdb:movie:10',
            'tmdbId': 10,
            'kind': 'movie',
            'title': 'First film',
        }

        def api(path, **params):
            if path == 'movie/10':
                return {'belongs_to_collection': {'id': 7}}
            if path == 'collection/7':
                return {
                    'name': 'Film collection',
                    'parts': [
                        {
                            'id': 11,
                            'title': 'Second film',
                            'release_date': '2024-01-01',
                            'poster_path': '/two.jpg',
                        },
                        {
                            'id': 10,
                            'title': 'First film',
                            'release_date': '2020-01-01',
                            'poster_path': '/one.jpg',
                        },
                    ],
                }
            if path == 'movie/10/recommendations':
                return {
                    'results': [
                        {
                            'id': 12,
                            'title': 'Suggested film',
                            'poster_path': '/suggested.jpg',
                        }
                    ]
                }
            raise AssertionError(path)

        with patch.object(self.backend, 'tmdb', side_effect=api) as tmdb:
            first = self.backend.handle({'op': 'collections', 'title': movie})
            second = self.backend.handle({'op': 'collections', 'title': movie})
        self.assertEqual(first, second)
        self.assertEqual(
            [section['label'] for section in first['sections']],
            ['Film collection', 'Recommended'],
        )
        self.assertEqual(
            [item['title'] for item in first['sections'][0]['items']],
            ['First film', 'Second film'],
        )
        self.assertEqual(
            first['sections'][0]['items'][0]['poster'],
            'https://image.tmdb.org/t/p/w500/one.jpg',
        )
        self.assertEqual(first['sections'][1]['items'][0]['kind'], 'movie')
        self.assertEqual(tmdb.call_count, 3)

    def test_tv_collections_load_recommendations_without_movie_collection_lookup(self):
        self.configure({'tmdb_key': 'test'})
        series = {
            'id': 'tmdb:tv:20',
            'tmdbId': 20,
            'kind': 'tv',
            'title': 'Original show',
        }
        with patch.object(
            self.backend,
            'tmdb',
            return_value={
                'results': [
                    {
                        'id': 21,
                        'name': 'Recommended show',
                        'first_air_date': '2022-01-01',
                    }
                ]
            },
        ) as tmdb:
            result = self.backend.handle({'op': 'collections', 'title': series})
        self.assertEqual(result['sections'][0]['label'], 'Recommended')
        self.assertEqual(result['sections'][0]['items'][0]['kind'], 'tv')
        self.assertEqual(tmdb.call_args.args, ('tv/20/recommendations',))

    def test_anime_episode_details_load_only_for_episode_tab_and_are_cached(self):
        title = {
            'id': 'mal:1',
            'malId': 1,
            'kind': 'tv',
            'title': 'Anime',
            'episodesCount': 26,
        }

        def api(url, params=None, *, timeout=15):
            if url.endswith('/map/mal/1'):
                return {
                    'sources': [
                        'https://myanimelist.net/anime/1',
                        'https://kitsu.app/anime/9',
                    ]
                }
            if url.endswith('/kitsu/9/episodes'):
                return {
                    'episodes': [
                        {
                            'number': 1,
                            'title_en_us': 'Opening episode',
                            'description': 'The story begins.',
                            'airdate': '2020-01-01',
                            'thumbnail': 'https://example.org/episode.jpg',
                        },
                        {'number': 2, 'canonical_title': 'Second episode'},
                    ]
                }
            raise AssertionError('Unexpected metadata request')

        with patch.object(m, 'http', side_effect=api) as requests:
            seasons = self.backend.episodes({'title': title})
            self.assertEqual(requests.call_count, 0)
            first = self.backend.episodes({'title': title, 'season': '1'})
            second = self.backend.episodes(
                {'title': title, 'season': '1', 'page': first['next']}
            )
        self.assertEqual(seasons, {'seasons': ['1']})
        self.assertEqual(requests.call_count, 2)
        self.assertEqual(first['next'], 'anime:2')
        self.assertEqual(first['items'][0]['title'], 'Opening episode')
        self.assertEqual(first['items'][0]['plot'], 'The story begins.')
        self.assertEqual(first['items'][0]['date'], '2020-01-01')
        self.assertEqual(first['items'][0]['image'], 'https://example.org/episode.jpg')
        self.assertEqual(first['items'][1]['title'], 'Second episode')
        self.assertEqual(second['items'][0]['number'], 25)
        self.assertEqual(second['next'], '')

    def test_anime_episode_details_fall_back_when_mapping_is_ambiguous(self):
        title = {
            'id': 'mal:1',
            'malId': 1,
            'kind': 'tv',
            'title': 'Anime',
            'episodesCount': 2,
        }
        mapping = {
            'sources': [
                'https://myanimelist.net/anime/1',
                'https://kitsu.app/anime/9',
                'https://kitsu.app/anime/10',
            ]
        }
        with patch.object(m, 'http', return_value=mapping) as requests:
            first = self.backend.episodes({'title': title, 'season': '1'})
            again = self.backend.episodes({'title': title, 'season': '1'})
        self.assertEqual(requests.call_count, 1)
        self.assertEqual(
            [row['title'] for row in first['items']], ['Episode 1', 'Episode 2']
        )
        self.assertEqual(again, first)

    def test_anime_episode_details_do_not_override_missing_or_duplicate_titles(self):
        title = {
            'id': 'mal:1',
            'malId': 1,
            'kind': 'tv',
            'title': 'Anime',
            'episodesCount': 3,
        }
        responses = [
            {
                'sources': [
                    'https://myanimelist.net/anime/1',
                    'https://kitsu.app/anime/9',
                ]
            },
            {
                'episodes': [
                    {'number': 1, 'title_en_us': ''},
                    {'number': 2, 'title_en_us': 'One numbering'},
                    {'number': 2, 'title_en_us': 'Another numbering'},
                    {'number': 3, 'title_en_us': 'Third episode'},
                ]
            },
        ]
        with patch.object(m, 'http', side_effect=responses):
            result = self.backend.episodes({'title': title, 'season': '1'})
        self.assertEqual(
            [row['title'] for row in result['items']],
            ['Episode 1', 'Episode 2', 'Third episode'],
        )

    def test_without_mal_client_id_uses_anilist_without_faking_mal_score(self):
        self.configure({})
        with (
            patch.object(
                m, 'anilist', side_effect=m.MediaError('AniList unavailable')
            ) as request,
            patch.object(
                m,
                'official_anime',
                side_effect=AssertionError('Official MAL should not be used'),
            ),
        ):
            self.assertEqual(self.backend.anime_genres(), [])
            with self.assertRaises(m.MediaError) as failure:
                self.backend.browse(
                    {'kind': 'tv', 'query': 'example', 'filters': {'genre': 'Anime'}}
                )
        self.assertIn('Anime catalogue unavailable', str(failure.exception))
        self.assertEqual(request.call_count, 2)

    def test_configured_anime_source_resolves_stream_without_exposing_config(self):
        key = b'fixture-key'
        blob = base64.b64encode(
            bytes(
                value ^ key[index % len(key)]
                for index, value in enumerate(
                    json.dumps(
                        {'src': 'https://example.org/video.m3u8', 'subtitles': []}
                    ).encode()
                )
            )
        ).decode()
        source = {
            'name': 'Fixture source',
            'strategy': 'mal_embed',
            'embed_url': 'https://example.org/{malId}/{episode}/{mode}',
            'blob_pattern': r'blob="([^"]+)"',
            'xor_key': key.decode(),
        }
        self.configure({'player': ['mpv'], 'anime_sources': [source]})
        with (
            patch.object(
                anime_sources, '_get', return_value='blob="' + blob + '"'
            ) as source_page,
            patch.object(m.shutil, 'which', return_value='/usr/bin/mpv'),
        ):
            result = self.backend.handle(
                {
                    'op': 'play',
                    'title': {
                        'id': 'mal:1',
                        'malId': 1,
                        'kind': 'tv',
                        'title': 'Anime',
                    },
                    'episode': 2,
                    'mode': 'sub',
                    'provider': 0,
                }
            )
            first = self.backend.handle(
                {
                    'op': 'play',
                    'title': {
                        'id': 'mal:1',
                        'malId': 1,
                        'kind': 'tv',
                        'title': 'Anime',
                    },
                    'mode': 'sub',
                    'provider': 0,
                    'online': True,
                }
            )
        self.assertEqual(result['type'], 'direct')
        self.assertIn('--referrer=https://example.org/', result['command'])
        self.assertEqual(result['command'][-1], 'https://example.org/video.m3u8')
        self.assertEqual(first['type'], 'direct')
        self.assertEqual(source_page.call_args.args[0], 'https://example.org/1/1/sub')
        init = self.backend.handle({'op': 'init', 'kind': 'tv'})
        self.assertEqual(init['animeProviders'], ['Fixture source'])
        self.assertNotIn('fixture-key', json.dumps(init))

    def test_anime_audio_is_owned_by_the_selected_provider(self):
        source = {'name': 'Example (Dub)', 'strategy': 'mal_embed', 'audio_mode': 'dub'}
        self.configure({'player': ['mpv'], 'anime_sources': [source]})
        with (
            patch.object(
                anime_sources,
                'resolve',
                return_value={
                    'url': 'https://example.org/stream',
                    'referer': 'https://example.org/',
                    'subtitle': '',
                },
            ) as resolve,
            patch.object(m.shutil, 'which', return_value='/usr/bin/mpv'),
        ):
            self.backend.handle(
                {
                    'op': 'play',
                    'title': {'id': 'mal:1', 'malId': 1, 'kind': 'movie'},
                    'provider': 0,
                    'mode': 'sub',
                }
            )
        self.assertEqual(resolve.call_args.args[-1], 'dub')
        self.assertEqual(
            self.backend.handle({'op': 'init', 'kind': 'movie'})['animeProviders'],
            ['Example (Dub)'],
        )
        self.configure({'anime_sources': [dict(source, audio_mode='invalid')]})
        with self.assertRaises(m.MediaError):
            self.backend.handle({'op': 'init', 'kind': 'movie'})

    def test_tmdb_pagination_continues_same_provider(self):
        self.configure({'tmdb_key': 'test-secret'})

        def api(url, params):
            return {'results': [{'id': 12, 'title': 'Fallback'}], 'total_pages': 3}

        with patch.object(m, 'http', side_effect=api) as request:
            first = self.backend.browse({'kind': 'movie'})
            self.assertEqual(first['next'], 'tmdb:2')
            self.backend.browse({'kind': 'movie', 'page': 'tmdb:2'})
            self.assertEqual(request.call_args.args[1]['page'], 2)

    def test_favorites_and_notes_survive_identity_merge_and_refresh(self):
        t = dict(id='tmdb:movie:12', tmdbId=12, kind='movie', title='Film')
        self.backend.handle(
            dict(
                op='save',
                title=t,
                values={
                    'favorite': True,
                    'note': 'Keep',
                    'url': 'https://example.org/play',
                },
            )
        )
        canonical = self.backend.save_title(t | {'imdbId': 'tt123'})
        self.assertEqual(canonical['id'], 'tt123')
        self.assertEqual(self.backend.personal('tt123')['note'], 'Keep')
        self.assertEqual(
            self.backend.personal(t['id'])['url'], 'https://example.org/play'
        )
        self.backend.save_title(canonical | {'plot': 'Refreshed'})
        self.assertTrue(self.backend.personal('tt123')['favorite'])
        self.assertEqual(
            len(self.backend.browse({'kind': 'movie', 'favorites': True})['items']), 1
        )
        self.assertEqual(
            self.backend.browse({'kind': 'tv', 'favorites': True})['items'], []
        )

    def test_identity_merge_keeps_personal_data_from_both_ids(self):
        alias = dict(id='tmdb:movie:12', tmdbId=12, kind='movie', title='Film')
        self.backend.handle(
            dict(op='save', title=alias, values={'favorite': True, 'note': 'Old'})
        )
        self.backend.handle(
            dict(op='save', title=self.movie, values={'url': 'https://e.org/x'})
        )
        self.backend.save_title(alias | {'imdbId': 'tt123'})
        self.assertEqual(
            self.backend.personal('tt123'),
            {'favorite': True, 'note': 'Old', 'url': 'https://e.org/x'},
        )

    def test_local_poster_enrichment_keeps_local_file(self):
        with patch.dict(
            os.environ, {'XDG_VIDEOS_DIR': str(self.backend.data / 'Videos')}
        ):
            source = self.backend.data / 'source.mkv'
            source.write_bytes(b'video')
            path = self.backend.local.add(self.movie, source)
            self.assertFalse(
                self.backend.handle({'op': 'local_titles', 'kind': 'movie'})['items'][
                    0
                ].get('poster')
            )
            with patch.object(
                self.backend,
                'details',
                return_value=self.movie | {'poster': 'https://example.org/poster'},
            ):
                posters = self.backend.handle({'op': 'local_posters', 'kind': 'movie'})
            self.assertEqual(
                posters, [{'id': 'tt123', 'poster': 'https://example.org/poster'}]
            )
            self.backend.save_title(self.movie | {'poster': posters[0]['poster']})
            local = self.backend.handle({'op': 'local_titles', 'kind': 'movie'})[
                'items'
            ][0]
            self.assertEqual(local['poster'], posters[0]['poster'])
            self.assertEqual(local['localPath'], path)

    def test_optional_enrichment_failure_preserves_details(self):
        self.configure({'tmdb_key': 'test'})
        self.backend.save_title(
            self.movie | {'plot': 'Hydrated plot', 'cast': [{'name': 'Actor'}]}
        )
        with patch.object(m, 'http', side_effect=m.MediaError('offline')):
            result = self.backend.artwork({'title': self.movie})
        self.assertEqual(result['title']['plot'], 'Hydrated plot')
        self.assertTrue(result['warnings'])

    def test_episode_template_and_invalid_input(self):
        title = self.movie | {'kind': 'tv', 'tmdbId': 42}
        self.assertEqual(
            m.template_url(
                'https://example.org/{kind:film|show}/{tmdbId}/{season}/{episode}',
                title,
                2,
                3,
            ),
            'https://example.org/show/42/2/3',
        )
        for template in (
            'https://example.org/{unknown}',
            'javascript:bad',
            'https://example.org/{episode}',
        ):
            with self.assertRaises(m.MediaError):
                m.template_url(template, title)
        with self.assertRaises(m.MediaError):
            self.backend.episodes({'title': self.movie})

    def test_custom_url_is_used_verbatim(self):
        self.backend.handle(
            dict(
                op='save',
                title=self.movie,
                values={'url': 'https://example.org/watch?id=42'},
            )
        )
        result = self.backend.handle(dict(op='play', title=self.movie))
        self.assertEqual(result['url'], 'https://example.org/watch?id=42')

    def test_config_secrets_do_not_cross_ui_boundary(self):
        self.configure(
            {
                'tmdb_key': 'secret',
                'providers': [
                    {
                        'name': 'Example',
                        'movie_url': 'https://example.org/{imdbId}?secret=private',
                    }
                ],
            }
        )
        output = json.dumps(self.backend.handle({'op': 'init'}))
        self.assertNotIn('secret', output)
        self.assertNotIn('private', output)

    def test_error_redacts_credentials(self):
        from urllib.error import HTTPError

        with patch.object(
            m.urllib.request,
            'urlopen',
            side_effect=HTTPError(
                'https://example.org/?api_key=secret', 403, 'secret', {}, None
            ),
        ):
            with self.assertRaises(m.MediaError) as raised:
                m.http('https://example.org/', {'api_key': 'secret'})
        self.assertNotIn('secret', str(raised.exception))

    def test_direct_stream_player_arguments_are_not_shell_code(self):
        self.configure({'player': ['mpv', '--fullscreen']})
        with patch.object(m.shutil, 'which', return_value='/usr/bin/mpv'):
            target = self.backend.launch_target(
                'https://example.org/stream.m3u8?token=$(echo secret)'
            )
        self.assertEqual(target['type'], 'direct')
        self.assertEqual(
            target['command'],
            [
                'mpv',
                '--fullscreen',
                '--',
                'https://example.org/stream.m3u8?token=$(echo secret)',
            ],
        )
        self.assertEqual(
            self.backend.launch_target('https://example.org/watch/123')['type'], 'web'
        )

    def test_provider_config_requires_documented_objects(self):
        self.configure({'providers': ['https://example.org/{imdbId}']})
        with self.assertRaisesRegex(m.MediaError, 'name and movie_url'):
            self.backend.config()
        self.configure(
            {'providers': [{'name': 'Example', 'url': 'https://example.org/{imdbId}'}]}
        )
        with self.assertRaisesRegex(m.MediaError, 'name and movie_url'):
            self.backend.config()

    def test_separate_movie_and_series_provider_urls(self):
        self.configure(
            {
                'providers': [
                    {
                        'name': 'Movies only',
                        'movie_url': 'https://example.org/film/{imdbId}',
                    },
                    {
                        'name': 'Both',
                        'movie_url': 'https://example.net/movie/{tmdbId}',
                        'series_url': 'https://example.net/show/{imdbId}/{season}/{episode}',
                    },
                ]
            }
        )
        self.assertEqual(
            self.backend.handle({'op': 'init', 'kind': 'movie'})['providers'],
            ['Movies only', 'Both'],
        )
        series = self.backend.handle({'op': 'init', 'kind': 'tv'})
        self.assertEqual(series['providers'], ['Both'])
        self.assertEqual(series['episodeProviders'], [True])
        result = self.backend.handle(
            {
                'op': 'play',
                'online': True,
                'provider': 0,
                'title': self.movie | {'kind': 'tv'},
                'season': 2,
                'episode': 7,
            }
        )
        self.assertEqual(result['url'], 'https://example.net/show/tt123/2/7')
        result = self.backend.handle(
            {
                'op': 'play',
                'online': True,
                'provider': 1,
                'title': self.movie | {'tmdbId': 42},
            }
        )
        self.assertEqual(result['url'], 'https://example.net/movie/42')
        with self.assertRaisesRegex(m.MediaError, 'provider is unavailable'):
            self.backend.handle(
                {'op': 'play', 'online': True, 'provider': -1, 'title': self.movie}
            )
        with self.assertRaisesRegex(m.MediaError, 'season is unavailable'):
            self.backend.handle(
                {
                    'op': 'play',
                    'online': True,
                    'provider': 0,
                    'title': self.movie | {'kind': 'tv'},
                }
            )

    def test_artwork_uses_tmdb_cast_and_backdrop(self):
        self.configure({'tmdb_key': 'test'})
        data = {
            'images': {'backdrops': [{'file_path': '/backdrop.jpg'}]},
            'credits': {'cast': [{'id': 1, 'name': 'Actor', 'character': 'Lead'}]},
        }
        with patch.object(self.backend, 'tmdb', return_value=data) as api:
            result = self.backend.artwork({'title': self.movie | {'tmdbId': 42}})
        self.assertEqual(api.call_count, 1)
        self.assertEqual(result['title']['cast'][0]['name'], 'Actor')
        self.assertTrue(result['title']['backdrop'].endswith('/backdrop.jpg'))

    def test_tmdb_details_keep_existing_imdb_identity(self):
        self.configure({'tmdb_key': 'test'})
        with patch.object(
            self.backend,
            'tmdb',
            return_value={'id': 42, 'title': 'Movie', 'overview': 'New plot'},
        ):
            result = self.backend.details({'title': self.movie | {'tmdbId': 42}})
        self.assertEqual(result['id'], 'tt123')
        self.assertEqual(result['imdbId'], 'tt123')
        self.assertEqual(result['tmdbId'], 42)
        self.assertEqual(result['plot'], 'New plot')

    def test_tmdb_episodes_load_seasons_and_episode_artwork(self):
        self.configure({'tmdb_key': 'test'})
        title = self.movie | {'kind': 'tv', 'tmdbId': 42}

        def api(path, **params):
            if path == 'tv/42':
                return {'seasons': [{'season_number': 1}]}
            self.assertEqual(path, 'tv/42/season/1')
            return {
                'episodes': [
                    {'episode_number': 1, 'name': 'Pilot', 'still_path': '/still.jpg'}
                ]
            }

        with patch.object(self.backend, 'tmdb', side_effect=api):
            self.assertEqual(self.backend.episodes({'title': title})['seasons'], ['1'])
            result = self.backend.episodes({'title': title, 'season': '1'})
        self.assertEqual(result['items'][0]['number'], 1)
        self.assertEqual(
            result['items'][0]['image'], 'https://image.tmdb.org/t/p/w300/still.jpg'
        )

    def test_omdb_search_when_tmdb_fails_and_pagination(self):
        self.configure({'tmdb_key': 'tmdb-secret', 'omdb_key': 'omdb-secret'})

        def api(url, params):
            if url != m.OMDB:
                raise m.MediaError('offline')
            self.assertEqual(params['type'], 'series')
            return {
                'Response': 'True',
                'Search': [
                    {
                        'imdbID': 'tt456',
                        'Title': 'Series',
                        'Type': 'series',
                        'Year': '2019–2023',
                        'Poster': 'N/A',
                    }
                ],
                'totalResults': '22',
            }

        with patch.object(m, 'http', side_effect=api) as request:
            result = self.backend.browse({'kind': 'tv', 'query': 'Series'})
            self.assertEqual(result['next'], 'omdb:2')
            self.assertEqual(result['items'][0]['kind'], 'tv')
            self.assertEqual(result['items'][0].get('poster', ''), '')
            result = self.backend.browse(
                {'kind': 'tv', 'query': 'Series', 'page': result['next']}
            )
            self.assertEqual(request.call_args.args[1]['page'], 2)
            self.assertEqual(result['next'], 'omdb:3')

    def test_omdb_details_fallback_preserves_personal_data(self):
        self.configure({'omdb_key': 'test'})
        self.backend.handle(
            dict(
                op='save',
                title=self.movie,
                values={'favorite': True, 'note': 'Keep this'},
            )
        )

        def api(url, params):
            self.assertEqual(url, m.OMDB)
            self.assertEqual(params['i'], 'tt123')
            return {
                'imdbID': 'tt123',
                'Type': 'movie',
                'Title': 'Movie',
                'Plot': 'Full plot',
                'Year': '2024',
                'Runtime': '112 min',
                'imdbRating': '8.2',
                'imdbVotes': '123,456',
                'Actors': 'A, B',
                'Ratings': [{'Source': 'Internet Movie Database', 'Value': '8.2/10'}],
            }

        with patch.object(m, 'http', side_effect=api):
            result = self.backend.details({'title': self.movie, 'refresh': True})
        self.assertEqual(result['plot'], 'Full plot')
        self.assertEqual(result['runtime'], 112)
        self.assertEqual(result['votes'], 123456)
        self.assertEqual(self.backend.personal('tt123')['note'], 'Keep this')

    def test_omdb_seasons_and_episodes(self):
        self.configure({'omdb_key': 'test'})
        title = self.movie | {'kind': 'tv'}

        def api(url, params):
            self.assertEqual(url, m.OMDB)
            if 'Season' not in params:
                return {'totalSeasons': '2'}
            return {
                'Episodes': [
                    {
                        'Episode': '1',
                        'Title': 'Pilot',
                        'Released': '2020-01-01',
                        'imdbRating': 'N/A',
                    }
                ]
            }

        with patch.object(m, 'http', side_effect=api):
            self.assertEqual(
                self.backend.episodes({'title': title})['seasons'], ['1', '2']
            )
            result = self.backend.episodes({'title': title, 'season': '1'})
        self.assertEqual(result['items'][0]['number'], 1)
        self.assertIsNone(result['items'][0]['rating'])

    def test_omdb_discovery_explains_search_instead_of_fake_results(self):
        self.configure({'omdb_key': 'test'})
        with patch.object(m, 'http', side_effect=m.MediaError('offline')):
            with self.assertRaisesRegex(m.MediaError, 'discovery requires a TMDB key'):
                self.backend.browse({'kind': 'movie'})

    def test_omdb_rejections_do_not_echo_upstream_secrets(self):
        self.configure({'omdb_key': 'private-value'})
        with patch.object(
            m,
            'http',
            return_value={
                'Response': 'False',
                'Error': 'Invalid API key private-value',
            },
        ):
            with self.assertRaises(m.MediaError) as error:
                self.backend.omdb(i='tt123')
        self.assertNotIn('private-value', str(error.exception))

    def test_omdb_no_results_is_a_successful_empty_page(self):
        self.configure({'omdb_key': 'test'})

        def api(url, params):
            self.assertEqual(url, m.OMDB)
            return {'Response': 'False', 'Error': 'Movie not found!'}

        with patch.object(m, 'http', side_effect=api):
            self.assertEqual(
                self.backend.browse({'kind': 'movie', 'query': 'no matches'}),
                {'items': [], 'next': ''},
            )

    def test_stale_catalogue_survives_tmdb_outage(self):
        self.configure({'tmdb_key': 'test'})
        key = 'browse:' + json.dumps(['movie', '', {}, ''], sort_keys=True)
        self.backend.put(key, dict(items=[self.movie], next=''))
        with self.backend.db() as db:
            db.execute('UPDATE cache SET updated=0')
        with patch.object(m, 'http', side_effect=m.MediaError('offline')):
            result = self.backend.browse({'kind': 'movie'})
        self.assertEqual(result['items'][0]['id'], 'tt123')
        self.assertIn('Offline', result['warning'])

    def test_trailers_exclude_promotional_clips_and_deduplicate(self):
        videos = [
            dict(
                key='clip', site='YouTube', type='Featurette', name='Behind the scenes'
            ),
            dict(
                key='trailer',
                site='YouTube',
                type='Trailer',
                name='Official trailer',
                official=True,
            ),
            dict(
                key='trailer',
                site='YouTube',
                type='Trailer',
                name='Official trailer',
                official=True,
            ),
        ]
        trailers = m.tmdb_trailers({'videos': {'results': videos}})
        self.assertEqual(len(trailers), 1)
        self.assertTrue(trailers[0]['url'].endswith('trailer'))

    def test_full_cast_includes_all_crew_jobs_and_actors(self):
        actors = [dict(id=i, name=str(i), character='Character') for i in range(45)]
        crew = [
            dict(id=90, name='Director', job='Director', department='Directing'),
            dict(id=91, name='Editor', job='Editor', department='Editing'),
        ]
        credits = m.tmdb_credits({'credits': {'cast': actors, 'crew': crew}})
        self.assertEqual(len(credits), 47)
        self.assertEqual(credits[-1]['job'], 'Editor')
        self.assertEqual(credits[0]['department'], 'Acting')

    def test_spoiler_cleanup_preserves_story_and_cleans_cached_heading(self):
        self.assertEqual(
            m.clean_spoiler('Plot[edit]\nA story about the Plot family.'),
            'A story about the Plot family.',
        )
        self.backend.put(
            'spoiler:tt123',
            {
                'text': 'Plot[edit]\nThe story.',
                'url': 'https://en.wikipedia.org/wiki/Example',
            },
        )
        self.assertEqual(
            self.backend.spoilers({'title': self.movie})['text'], 'The story.'
        )

    def test_anime_spoilers_find_matching_wikipedia_plot_without_imdb(self):
        anime = {
            'id': 'mal:7',
            'kind': 'tv',
            'title': 'Example Anime',
            'aliases': ['Example Anime'],
        }
        calls = []

        def wiki(url, params):
            calls.append(params)
            if params.get('list') == 'search':
                return {
                    'query': {
                        'search': [
                            {'title': 'Example Anime episodes'},
                            {'title': 'Example Anime (TV series)'},
                        ]
                    }
                }
            if params.get('prop') == 'sections':
                return {'parse': {'sections': [{'line': 'Plot', 'index': '2'}]}}
            return {'parse': {'text': '<p>The ending is revealed.</p>'}}

        with patch.object(m, 'http', side_effect=wiki) as api:
            result = self.backend.spoilers({'title': anime})
            self.assertEqual(self.backend.spoilers({'title': anime}), result)
        self.assertEqual(result['text'], 'The ending is revealed.')
        self.assertEqual(
            result['url'], 'https://en.wikipedia.org/wiki/Example_Anime_%28TV_series%29'
        )
        self.assertEqual(calls[1]['page'], 'Example Anime (TV series)')
        self.assertEqual(api.call_count, 3)

    def test_offline_catalogue(self):
        key = 'browse:' + json.dumps(['movie', '', {}, ''], sort_keys=True)
        self.backend.put(key, dict(items=[self.movie], next=''))
        with self.backend.db() as db:
            db.execute('UPDATE cache SET updated=0')
        with patch.object(m, 'http', side_effect=m.MediaError('offline')):
            result = self.backend.browse({'kind': 'movie'})
        self.assertEqual(result['items'][0]['id'], 'tt123')
        self.assertIn('Offline', result['warning'])


if __name__ == '__main__':
    unittest.main()
