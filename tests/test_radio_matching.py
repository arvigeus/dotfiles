"""URL/UUID matching produces real station metadata without guessing by alias."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import support
from test_radio import STATION
from test_radio_sync import Cloud, remote
from spaces.radio import api
from spaces.radio.favorites import FavoritesStore
from spaces.radio.matching import RadioMatcher
from spaces.radio.storage import read_json


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.matcher=RadioMatcher(self.root/'cache')
    def test_exact_url_loads_metadata_quality_options_and_caches_results(self):
        base=dict(STATION,homepage='https://station.example',lastcheckok=1,clickcount=100)
        alternative=dict(base,stationuuid='22222222-2222-2222-2222-222222222222',name=base['name']+' (AAC 256)',codec='AAC',bitrate=256,url='https://stream.example.invalid/high',url_resolved='https://stream.example.invalid/high')
        unrelated=dict(base,stationuuid='33333333-3333-3333-3333-333333333333',countrycode='US',bitrate=320)
        def lookup(path,args):return [base] if path.endswith('byurl') else [base,alternative,unrelated]
        with patch.object(api,'api_get',side_effect=lookup) as network:
            result=self.matcher.match(remote())
            self.assertEqual(result['name'],STATION['name']);self.assertEqual(result['country'],'Vietnam')
            self.assertEqual(len(result['variants']),2);self.assertEqual(result['bitrate'],256)
            count=network.call_count
            self.assertEqual(self.matcher.match(remote()),result)
            self.assertEqual(network.call_count,count)
    def test_scheme_alias_is_verified_and_unrelated_url_results_are_rejected(self):
        base=dict(STATION,url='http://stream.example.invalid/live',url_resolved='http://stream.example.invalid/live',lastcheckok=1)
        with patch.object(api,'api_get',side_effect=[[],[base],[base]]):
            self.assertEqual(self.matcher.match(remote())['stationuuid'],STATION['stationuuid'])
        with patch.object(api,'api_get',return_value=[dict(base,url='https://wrong.example/live',url_resolved='https://wrong.example/live')]):
            self.assertIsNone(self.matcher.match(remote(streamUrl='https://different.example/live')))
    def test_private_auth_streams_are_not_sent_to_the_public_catalogue(self):
        for url in ('https://alice:secret@private.example/live','https://private.example/live?token=private'):
            with patch.object(api,'api_get') as network:
                self.assertIsNone(self.matcher.match(remote(streamUrl=url)))
            network.assert_not_called()
    def test_verified_identity_can_correct_an_old_relay_and_sync_updates_ids_safely(self):
        cloud=Cloud([remote(name='My alias',streamUrl='https://old-relay.example/live')])
        store=FavoritesStore(self.root/'data',client_factory=lambda:cloud)
        imported=store.sync()['favorites'][0]
        canonical=dict(STATION,homepage='https://station.example',variants=[dict(STATION,homepage='https://station.example')])
        class Matcher:
            calls=[]
            def match(self,row,preferred=None):
                self.calls.append(preferred)
                return copy.deepcopy(canonical)
        matcher=Matcher();store.matcher=matcher
        result=store.sync()['favorites'][0]
        self.assertEqual(result['stationuuid'],STATION['stationuuid']);self.assertNotEqual(result['stationuuid'],imported['stationuuid'])
        self.assertEqual(cloud.rows[0]['id'],'1');self.assertEqual(cloud.rows[0]['name'],STATION['name'])
        self.assertEqual(cloud.rows[0]['streamUrl'],STATION['url_resolved'])
        state=read_json(store.state_path,{})
        self.assertEqual(state['links']['1'],STATION['stationuuid']);self.assertEqual(state['matches']['1']['uuid'],STATION['stationuuid'])
        store.sync();self.assertEqual(matcher.calls[-1],STATION['stationuuid'])
        self.assertEqual([op for op,_ in cloud.calls],['updateInternetRadioStation'])
        store.save([]);store.sync()
        self.assertEqual(cloud.rows,[]);self.assertEqual(store.read(),[])
    def test_unmatched_or_temporarily_unavailable_catalogue_keeps_custom_favorites(self):
        cloud=Cloud([remote()]);store=FavoritesStore(self.root/'data',client_factory=lambda:cloud)
        class Matcher:
            def match(self,*args):raise api.RadioError('Unavailable')
        store.matcher=Matcher()
        result=store.sync()
        self.assertEqual(result['favorites'][0]['source'],'nextcloud');self.assertTrue(result['warning'])
        self.assertEqual(cloud.calls,[])
    def test_preferred_uuid_uses_catalogue_record_instead_of_a_renamed_alias(self):
        base=dict(STATION,lastcheckok=1)
        with patch.object(api,'api_get',return_value=[base]) as network:
            result=self.matcher.match(remote(name='My label',streamUrl='https://old.example/relay'),STATION['stationuuid'])
        self.assertEqual(network.call_args_list[0].args,('/json/stations/byuuid',{'uuids':STATION['stationuuid']}))
        self.assertEqual(result['name'],STATION['name'])

    def test_broken_catalogue_stream_enriches_identity_without_replacing_saved_stream(self):
        base=dict(STATION,lastcheckok=0,url='https://broken.example/live',url_resolved='https://broken.example/live')
        saved=remote(streamUrl='https://saved.example/live')
        with patch.object(api,'api_get',return_value=[base]):
            result=self.matcher.match(saved,STATION['stationuuid'])
        self.assertEqual(result['stationuuid'],STATION['stationuuid'])
        self.assertEqual(result['variants'][0]['url'],saved['streamUrl'])
        self.assertEqual(result['source'],'nextcloud')
