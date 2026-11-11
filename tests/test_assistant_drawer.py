"""Local assistant service boundaries, SSE failures and the compact drawer."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import support

sys.path.insert(0, str(support.DESKTOP / 'drawers/assistant'))
backend = support.load(
    'desktop_assistant', support.DESKTOP / 'drawers/assistant/backend.py'
)


def model(name='local', **values):
    return dict(id=name, downloaded=True, labels=['chat'], recipe='llamacpp', **values)


class AssistantBackendTests(unittest.TestCase):
    def test_plain_chat_and_alias_use_only_the_reply_length_instruction(self):
        sent, _ = self.chat(b'data: [DONE]\n\n', _model='daily', length='balanced')
        self.assertEqual(sent[0][1]['model'], 'daily')
        self.assertEqual(
            sent[0][1]['messages'][0],
            dict(role='system', content=backend.LENGTHS['balanced']),
        )

    def test_alias_metadata_matches_concrete_models_and_excludes_cloud_targets(self):
        rows = [
            model(),
            model('daily'),
            model('chain'),
            model('remote') | dict(recipe='cloud'),
        ]
        catalogue = backend.chat_models(
            dict(data=rows),
            aliases=dict(daily='builtin.local', chain='daily', remote='cloud.model'),
        )
        self.assertEqual([row['id'] for row in catalogue], ['chain', 'daily', 'local'])
        self.assertEqual([row['target'] for row in catalogue], ['local'] * 3)
        self.assertTrue(catalogue[0]['alias'])
        self.assertFalse(catalogue[-1]['alias'])

    def test_unavailable_alias_metadata_does_not_block_public_model_listing(self):
        with patch.object(
            backend,
            'get_json',
            side_effect=backend.urllib.error.HTTPError(
                'local', 403, 'Forbidden', {}, None
            ),
        ):
            self.assertEqual(backend.model_aliases('http://localhost:13305'), {})

    def test_only_downloaded_local_chat_models_are_offered(self):
        rows = [
            model(),
            model('code'),
            model('cloud') | dict(recipe='cloud'),
            model('router') | dict(recipe='collection.router'),
            model('missing') | dict(downloaded=False),
            model('embed') | dict(labels=['embeddings']),
            model('audio') | dict(labels=['transcription']),
        ]
        self.assertEqual(
            [row['id'] for row in backend.chat_models(dict(data=rows))],
            ['code', 'local'],
        )

    def test_running_system_service_wins_over_disabled_user_service(self):
        with patch.object(
            backend,
            'unit_state',
            side_effect=[
                dict(LoadState='loaded', ActiveState='inactive'),
                dict(LoadState='loaded', ActiveState='active'),
            ],
        ):
            self.assertEqual(backend.service()[0], 'system')

    def test_explicit_start_uses_user_unit_without_enabling_it(self):
        with (
            patch.object(
                backend, 'service', return_value=('user', dict(ActiveState='inactive'))
            ),
            patch.object(
                backend, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')
            ) as run,
            patch.object(
                backend, 'status', return_value=dict(online=True, state='active')
            ),
        ):
            self.assertTrue(backend.control('start')['online'])
        run.assert_called_once_with(
            ['systemctl', '--user', 'start', 'lemond.service'], timeout=45
        )

    def test_stop_uses_the_running_service_scope(self):
        with (
            patch.object(
                backend, 'service', return_value=('system', dict(ActiveState='active'))
            ),
            patch.object(
                backend, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')
            ) as run,
            patch.object(backend, 'status', return_value=dict(online=False)),
        ):
            self.assertFalse(backend.control('stop')['online'])
        run.assert_called_once_with(['systemctl', 'stop', 'lemond.service'], timeout=45)

    def test_user_port_is_read_without_honoring_a_remote_host(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, XDG_CONFIG_HOME=directory),
        ):
            config = Path(directory) / 'lemonade'
            config.mkdir()
            (config / 'config.json').write_text(
                json.dumps(dict(port=12345, host='remote.example'))
            )
            self.assertEqual(backend.server_url('user'), 'http://localhost:12345')

    def chat(self, stream, **values):
        sent, replies = [], []
        labels = values.pop('_labels', ['chat', 'reasoning', 'vision'])
        identifier = values.pop('_model', 'local')
        downloaded = values.pop('_downloaded', True)

        def request(url, payload=None, **kwargs):
            sent.append((url, payload))
            return io.BytesIO(stream)

        with (
            patch.object(backend, 'service', return_value=('user', {})),
            patch.object(backend, 'server_url', return_value='http://localhost:13305'),
            patch.object(
                backend,
                'get_json',
                return_value=dict(
                    data=[
                        model(identifier) | dict(labels=labels, downloaded=downloaded)
                    ]
                ),
            ),
            patch.object(backend, 'request', side_effect=request),
            patch.object(backend, 'emit', side_effect=replies.append),
        ):
            backend.chat(
                dict(
                    model=identifier,
                    **dict(messages=[dict(role='user', content='hello')]) | values,
                )
            )
        return sent, replies

    def test_thinking_style_and_multimodal_messages_reach_lemonade(self):
        document = dict(name='notes.txt', kind='text', text='Frozen reference')
        image = dict(
            name='image.png', kind='image', data='data:image/png;base64,aGVsbG8='
        )
        sent, _ = self.chat(
            b'data: [DONE]\n\n',
            thinking='off',
            style='precise',
            messages=[dict(role='user', content='Look', attachments=[document, image])],
        )
        request = sent[0][1]
        self.assertIs(request['enable_thinking'], False)
        self.assertEqual(request['temperature'], 0.2)
        self.assertEqual(request['messages'][1]['content'][2]['type'], 'image_url')
        self.assertIn('Frozen reference', request['messages'][1]['content'][1]['text'])
        sent, _ = self.chat(b'data: [DONE]\n\n')
        self.assertNotIn('enable_thinking', sent[0][1])
        self.assertNotIn('temperature', sent[0][1])

    def test_thinking_override_does_not_require_a_reasoning_catalogue_label(self):
        sent, _ = self.chat(
            b'data: [DONE]\n\n', thinking='off', _labels=['chat', 'vision']
        )
        self.assertIs(sent[0][1]['enable_thinking'], False)
        sent, _ = self.chat(b'data: [DONE]\n\n', thinking='on', _labels=['chat'])
        self.assertIs(sent[0][1]['enable_thinking'], True)
        with self.assertRaisesRegex(ValueError, 'vision'):
            self.chat(
                b'data: [DONE]\n\n',
                _labels=['chat'],
                messages=[
                    dict(
                        role='user',
                        content='Look',
                        attachments=[
                            dict(
                                name='image',
                                kind='image',
                                data='data:image/png;base64,aGVsbG8=',
                            )
                        ],
                    )
                ],
            )

    def test_stream_unicode_reasoning_and_finish(self):
        def event(delta, finish=None):
            return (
                'data: '
                + json.dumps(dict(choices=[dict(delta=delta, finish_reason=finish)]))
                + '\r\n\r\n'
            )

        stream = ': ping\r\n\r\n' + event(dict(reasoning_content='private thought'))
        stream += (
            event(dict(content='Xin chào 👋'))
            + event({}, 'length')
            + 'data: [DONE]\r\n\r\n'
        )
        sent, replies = self.chat(stream.encode(), length='brief')
        self.assertEqual(''.join(row.get('text', '') for row in replies), 'Xin chào 👋')
        self.assertTrue(any(row.get('thinking') for row in replies))
        self.assertEqual(replies[-1], dict(type='done', limited=True))
        self.assertEqual(
            ''.join(row.get('reasoning', '') for row in replies), 'private thought'
        )
        self.assertEqual(sent[0][1]['messages'][-1], dict(role='user', content='hello'))
        self.assertEqual(sent[0][1]['messages'][0]['content'], backend.LENGTHS['brief'])

    def test_reply_verbosity_does_not_cap_the_combined_thinking_and_answer(self):
        for length in backend.LENGTHS:
            with self.subTest(length=length):
                sent, _ = self.chat(b'data: [DONE]\n\n', length=length)
                payload = sent[0][1]
                self.assertNotIn('max_tokens', payload)
                self.assertNotIn('max_completion_tokens', payload)
                self.assertEqual(
                    payload['messages'][0]['content'], backend.LENGTHS[length]
                )

    def test_first_message_uses_lemonade_native_download_and_load(self):
        sent, _ = self.chat(b'data: [DONE]\n\n', _model='new', _downloaded=False)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], 'http://localhost:13305/v1/chat/completions')
        self.assertEqual(sent[0][1]['model'], 'new')

    def test_incomplete_stream_and_server_errors_remain_failures(self):
        with self.assertRaisesRegex(ValueError, 'disconnected'):
            self.chat(b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')
        with self.assertRaisesRegex(ValueError, 'out of memory'):
            self.chat(b'data: {"error":{"message":"out of memory"}}\n\n')

    def test_send_rejects_models_missing_from_the_catalogue_before_native_load(self):
        with (
            patch.object(backend, 'service', return_value=('user', {})),
            patch.object(backend, 'server_url', return_value='http://localhost:13305'),
            patch.object(backend, 'get_json', return_value=dict(data=[])),
            patch.object(backend, 'request') as request,
        ):
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                backend.chat(dict(model='missing'))
        request.assert_not_called()

    def test_catalogue_keeps_download_sizes_and_omits_cloud_models(self):
        rows = [
            model(),
            model('missing', size=2.5) | dict(downloaded=False),
            model('cloud') | dict(recipe='cloud'),
        ]
        catalogue = backend.chat_models(dict(data=rows), catalogue=True)
        self.assertEqual([row['id'] for row in catalogue], ['local', 'missing'])
        self.assertEqual(catalogue[1]['size'], 2.5)
        self.assertFalse(catalogue[1]['downloaded'])

    def test_unchanged_catalogue_polls_health_aliases_and_downloads(self):
        calls = []

        def get(url):
            calls.append(url)
            if url.endswith('/health'):
                return dict(
                    models_generation=4,
                    all_models_loaded=[
                        dict(model_name='local', is_busy=True, pinned=False)
                    ],
                )
            if url.endswith('/internal/aliases'):
                return dict(aliases=[])
            if url.endswith('/downloads'):
                return [dict(type='model', model_name='local', status='paused')]
            raise AssertionError(url)

        with (
            patch.object(
                backend, 'service', return_value=('user', dict(ActiveState='active'))
            ),
            patch.object(backend, 'server_url', return_value='http://localhost:13305'),
            patch.object(backend, 'get_json', side_effect=get),
        ):
            result = backend.status(4, {})
        self.assertNotIn('models', result)
        self.assertTrue(result['loaded'][0]['busy'])
        self.assertEqual(result['downloads'][0]['status'], 'paused')
        self.assertEqual(len(calls), 3)

    def test_alias_retarget_refreshes_catalogue_without_model_generation_change(self):
        def get(url):
            if url.endswith('/health'):
                return dict(models_generation=4)
            if url.endswith('/internal/aliases'):
                return dict(aliases=[dict(alias='daily', target='code')])
            if '/models?' in url:
                return dict(data=[model('code'), model('daily')])
            if url.endswith('/downloads'):
                return []
            raise AssertionError(url)

        with (
            patch.object(backend, 'service', return_value=('user', {})),
            patch.object(backend, 'server_url', return_value='http://localhost:13305'),
            patch.object(backend, 'get_json', side_effect=get),
        ):
            result = backend.status(4, dict(daily='local'))
        self.assertEqual(result['aliases'], dict(daily='code'))
        self.assertEqual(result['models'][0]['id'], 'daily')
        self.assertEqual(result['models'][0]['target'], 'code')

    def test_connect_reuses_a_running_server(self):
        with (
            patch.object(
                backend, 'status', return_value=dict(online=True, installed=True)
            ),
            patch.object(backend, 'run') as run,
        ):
            self.assertTrue(backend.control('connect')['online'])
        run.assert_not_called()

    def test_download_creates_a_server_owned_job_and_pause_uses_its_id(self):
        with (
            patch.object(backend, 'service', return_value=('user', {})),
            patch.object(backend, 'server_url', return_value='http://localhost:13305'),
            patch.object(
                backend,
                'get_json',
                return_value=dict(data=[model() | dict(downloaded=False)]),
            ),
            patch.object(
                backend, 'request', side_effect=lambda *a, **kw: io.BytesIO(b'{}')
            ) as request,
            patch.object(backend, 'status', return_value=dict(online=True)),
        ):
            backend.control('download', dict(model='local'))
            backend.control('pause', dict(model='local'))
        self.assertEqual(
            request.call_args_list[0].args,
            (
                'http://localhost:13305/v1/pull',
                dict(model_name='local', stream=True, subscribe=False),
            ),
        )
        self.assertEqual(
            request.call_args_list[1].args,
            (
                'http://localhost:13305/v1/downloads/control',
                dict(id='model:local', action='pause'),
            ),
        )

    def test_unload_is_scoped_and_refuses_busy_or_pinned_models(self):
        for flags in ({}, dict(is_busy=True), dict(pinned=True)):
            with (
                self.subTest(flags=flags),
                patch.object(backend, 'service', return_value=('user', {})),
                patch.object(
                    backend, 'server_url', return_value='http://localhost:13305'
                ),
                patch.object(
                    backend,
                    'get_json',
                    side_effect=[
                        dict(data=[model()]),
                        dict(aliases=[]),
                        dict(all_models_loaded=[dict(model_name='local', **flags)]),
                    ],
                ),
                patch.object(
                    backend, 'request', return_value=io.BytesIO(b'{}')
                ) as request,
                patch.object(backend, 'status', return_value=dict(online=True)),
            ):
                if flags:
                    with self.assertRaisesRegex(ValueError, 'in use or pinned'):
                        backend.control('unload', dict(model='local'))
                    request.assert_not_called()
                else:
                    backend.control('unload', dict(model='local'))
                    request.assert_called_once_with(
                        'http://localhost:13305/v1/unload',
                        dict(model_name='local'),
                        timeout=30,
                    )

    def test_alias_controls_use_the_concrete_download_and_loaded_model(self):
        for operation, downloaded in [
            ('download', False),
            ('pause', False),
            ('unload', True),
            ('delete', True),
        ]:

            def get(url):
                if url.endswith('/internal/aliases'):
                    return dict(aliases=[dict(alias='daily', target='builtin.local')])
                if '/models?' in url:
                    return dict(
                        data=[
                            model() | dict(downloaded=downloaded),
                            model('daily') | dict(downloaded=downloaded),
                        ]
                    )
                if url.endswith('/health'):
                    return dict(all_models_loaded=[dict(model_name='local')])
                if url.endswith('/downloads'):
                    return []
                raise AssertionError(url)

            with (
                self.subTest(operation=operation),
                patch.object(backend, 'service', return_value=('user', {})),
                patch.object(
                    backend, 'server_url', return_value='http://localhost:13305'
                ),
                patch.object(backend, 'get_json', side_effect=get),
                patch.object(
                    backend, 'request', return_value=io.BytesIO(b'{}')
                ) as request,
                patch.object(backend, 'status', return_value=dict(online=True)),
            ):
                backend.control(operation, dict(model='daily'))
            sent = request.call_args.args[1]
            self.assertEqual(
                sent.get('model_name', sent.get('id')),
                'model:local' if operation == 'pause' else 'local',
            )

    def test_delete_rechecks_model_use_and_downloads_before_native_removal(self):
        cases = [
            ({}, [], True, ''),
            (None, [], True, ''),
            (dict(is_busy=True), [], True, 'in use or pinned'),
            (dict(is_streaming=True), [], True, 'in use or pinned'),
            (dict(pinned=True), [], True, 'in use or pinned'),
            ({}, [dict(model_name='local', running=True)], True, 'downloading'),
            ({}, [], False, 'not downloaded'),
        ]
        for flags, downloads, downloaded, error in cases:

            def get(url):
                if '/models?' in url:
                    return dict(data=[model() | dict(downloaded=downloaded)])
                if url.endswith('/internal/aliases'):
                    return dict(aliases=[])
                if url.endswith('/health'):
                    return dict(
                        all_models_loaded=[]
                        if flags is None
                        else [dict(model_name='local', **flags)]
                    )
                if url.endswith('/downloads'):
                    return downloads
                raise AssertionError(url)

            with (
                self.subTest(flags=flags, downloads=downloads, downloaded=downloaded),
                patch.object(backend, 'service', return_value=('user', {})),
                patch.object(
                    backend, 'server_url', return_value='http://localhost:13305'
                ),
                patch.object(backend, 'get_json', side_effect=get),
                patch.object(
                    backend, 'request', return_value=io.BytesIO(b'{}')
                ) as request,
                patch.object(
                    backend, 'status', return_value=dict(online=True)
                ) as status,
            ):
                if error:
                    with self.assertRaisesRegex(ValueError, error):
                        backend.control('delete', dict(model='local'))
                    request.assert_not_called()
                    status.assert_not_called()
                else:
                    self.assertTrue(backend.control('delete', dict(model='local')))
                    request.assert_called_once_with(
                        'http://localhost:13305/v1/delete',
                        dict(model_name='local'),
                        timeout=60,
                    )
                    status.assert_called_once_with()


FAKE_BACKEND = """import json,sys,time,os,pathlib
value=json.loads(sys.stdin.readline())
if value['op'] in ('attach','paste'):
    if value['op']=='attach':
        import attachments
        print(json.dumps(attachments.prepare(value['urls'])),flush=True)
    else:
        path=pathlib.Path(os.environ['XDG_STATE_HOME'])/'clipboard.json'
        print(path.read_text(),flush=True)
    sys.exit(0)
if value['op']=='chat':
    log=pathlib.Path(os.environ['XDG_STATE_HOME'])/'request.json'
    log.parent.mkdir(parents=True,exist_ok=True);log.write_text(json.dumps(value))
    path=log.with_name('fixture.json');state=json.loads(path.read_text())
    target=state.get('aliases',{}).get(value['model'],value['model'])
    if target=='new' and not state['new']:
        # Native auto-load fetches directly; it does not publish a /downloads job.
        if not state.get('nativeDownloading'):
            state['nativeDownloading']=True
            temporary=path.with_suffix('.chat');temporary.write_text(json.dumps(state));temporary.replace(path)
        deadline=time.monotonic()+12
        while not json.loads(path.read_text())['new']:
            if time.monotonic()>deadline:raise RuntimeError('Native download fixture timed out')
            time.sleep(.05)
    print(json.dumps(dict(type='delta',text='',reasoning='A short model thought.',thinking=True)),flush=True)
    limited=value['messages'][-1]['content']=='reasoning only' and value.get('thinking')!='off'
    if not limited:print(json.dumps(dict(type='delta',text='A compact **answer**.\\n\\n```python\\nprint("hello")\\n```')),flush=True)
    if value['messages'][-1]['content']=='wait': time.sleep(8)
    print(json.dumps(dict(type='done',limited=limited)),flush=True)
else:
    path=pathlib.Path(os.environ['XDG_STATE_HOME'])/'fixture.json'
    state=json.loads(path.read_text()) if path.exists() else dict(online=True,loaded=True,new=False,downloads=[])
    op=value['op']
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.with_name('operations.log').open('a') as log:log.write(op+'\\n')
    if op=='status':
        with path.with_name('polls.log').open('a') as log:log.write('status\\n')
    if op in ('connect','start'):
        if state.get('connectError'):
            print(json.dumps(dict(type='error',error=state['connectError'])),flush=True);sys.exit(0)
        state['online']=True
    if op=='stop':state['online']=False
    if op=='unload':state['loaded']=False
    if op=='delete':
        if state.get('deleteError'):
            print(json.dumps(dict(type='error',error=state['deleteError'])),flush=True);sys.exit(0)
        target=state.get('aliases',{}).get(value['model'],value['model'])
        state['deleted']=state.get('deleted',[])+[target]
        if target=='local':state['loaded']=False
    if op=='pause':state['downloads'][0].update(status='paused',running=False)
    if op=='download':
        state['manualDownloads']=state.get('manualDownloads',0)+1
        if state['downloads']:
            state['new']=True;state['downloads']=[]
        else:
            state['downloads']=[dict(id='model:new',type='model',model_name='new',status='downloading',running=True,total_download_size=100,cumulative_bytes_downloaded=25)]
    if op!='status' or not path.exists():
        path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix('.control');temporary.write_text(json.dumps(state));temporary.replace(path)
    models=[dict(id='local',label='Local model',downloaded=True,size=0.5,labels=['chat','vision','reasoning']),dict(id='code',label='Code model',downloaded=True,size=2,labels=['chat']),dict(id='new',label='New model',downloaded=state['new'],size=2.5,labels=['chat'],suggested=True)]
    for row in models:
        if row['id'] in state.get('deleted',[]):row['downloaded']=False
    for row in models:row.update(alias=False,target=row['id'])
    for alias,target in state.get('aliases',{}).items():
        base=next((row for row in models if row['id']==target),None)
        if base:models.append(dict(base,id=alias,label=alias,alias=True,target=target))
    models.sort(key=lambda row:(not row['downloaded'],not row['alias'],row['id']))
    result=dict(online=state['online'],installed=True,scope='user',state='active' if state['online'] else 'inactive',loaded=[dict(id='local',busy=False,pinned=False)] if state['loaded'] and state['online'] else [],downloads=state['downloads'] if state['online'] else [],error='')
    if state['online']:result.update(models=models,generation=2 if state['new'] else 1,aliases=state.get('aliases',{}))
    print(json.dumps(result),flush=True)
"""


@unittest.skipUnless(support.QS, 'Quickshell is required')
class AssistantDrawerTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_opening_drawer_is_passive_and_model_picker_starts_on_demand(self):
        def setup(root):
            (root / 'drawers/assistant/backend.py').write_text(FAKE_BACKEND)
            (root / 'state').mkdir()
            (root / 'state/fixture.json').write_text(
                json.dumps(dict(online=False, loaded=False, new=False, downloads=[]))
            )

        self.run_qml(
            """import QtQuick
import Quickshell
import Quickshell.Io
import "ui"
import "drawers"
import "drawers/assistant"
ShellRoot {
 property int stage:0
 property int tries:0
 FloatingWindow {implicitWidth:480;implicitHeight:760;visible:true;color:Theme.background
  AssistantDrawer {id:drawer;x:16;y:16;width:448;height:728;active:true}
 }
 FileView {id:operations;path:Quickshell.env("XDG_STATE_HOME")+"/operations.log";blockLoading:true;printErrors:false}
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer {interval:100;repeat:true;running:true;onTriggered:{try{
  if(++tries>90)throw new Error("timeout "+stage+" "+AssistantService.error);
  if(stage===0){
   if(!AssistantService.checked||AssistantService.checking)return;
   check(!AssistantService.online&&!AssistantService.models.length,"opening drawer started the engine");
   check(find(drawer,"assistantModel").enabled,"cold model picker is disabled");
   AssistantService.draft="keep this draft";drawer.active=false;
  }else if(stage===1){
   drawer.active=true;
  }else if(stage===2){
   if(AssistantService.checking)return;
   operations.reload();operations.waitForJob();
   check(operations.text().trim().split("\\n").every(op=>op==="status")&&!AssistantService.online,"reopening drawer starts the engine");
   find(drawer,"assistantModel").clicked();
  }else if(stage===3){
   if(AssistantService.checking||!AssistantService.online)return;
   check(drawer.modelPopup.visible&&drawer.modelPopup.rows.length===3,"picker did not start and fetch catalogue");
   find(drawer.modelPopup.contentItem,"assistantModelRow:code").clicked();
   check(AssistantService.selectedModel==="code"&&AssistantService.canSend,"cold picker cannot select a model");
   drawer.active=false;
  }else if(stage===4){
   operations.reload();operations.waitForJob();
   const log=operations.text().trim().split("\\n");
   check(log.filter(op=>op==="connect").length===1&&!log.includes("stop"),"drawer made unsolicited lifecycle calls");
   check(AssistantService.online&&AssistantService.draft==="keep this draft"&&!AssistantService.messages.count,"closing idle drawer stopped shared server or lost draft");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;tries=0;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
}""",
            setup,
        )

    def test_cold_send_and_retry_validate_saved_choice_without_persisted_catalogue(
        self,
    ):
        for saved, start_error in [
            ('local', ''),
            ('missing', ''),
            ('local', 'Cannot start Lemonade'),
        ]:
            with self.subTest(saved=saved, start_error=start_error):

                def setup(root):
                    (root / 'drawers/assistant/backend.py').write_text(FAKE_BACKEND)
                    (root / 'state').mkdir()
                    (root / 'state/fixture.json').write_text(
                        json.dumps(
                            dict(
                                online=False,
                                loaded=False,
                                new=False,
                                downloads=[],
                                connectError=start_error,
                            )
                        )
                    )
                    (root / 'config/quickshell/desktop/assistant.json').write_text(
                        json.dumps(dict(model=saved, thinking={saved: 'off'}))
                    )
                    (root / 'context.txt').write_text('Frozen context')

                self.run_qml(
                    """import QtQuick
import Quickshell
import Quickshell.Io
import "ui"
import "drawers"
import "drawers/assistant"
ShellRoot {
 property int stage:0
 property int tries:0
 readonly property string saved:SAVED_CHOICE
 readonly property bool fails:EXPECTED_FAILURE
 FloatingWindow {implicitWidth:480;implicitHeight:760;visible:true;color:Theme.background
  AssistantDrawer {id:drawer;x:16;y:16;width:448;height:728;active:true}
 }
 FileView {id:payload;path:Quickshell.env("XDG_STATE_HOME")+"/request.json";blockLoading:true;printErrors:false}
 function check(value,message){if(!value)throw new Error(message);}
 Timer {interval:100;repeat:true;running:true;onTriggered:{try{
  if(++tries>90)throw new Error("timeout "+stage+" "+AssistantService.error);
  if(stage===0){
   if(!AssistantService.checked||AssistantService.checking)return;
   check(!AssistantService.online&&!AssistantService.selectedEntry&&AssistantService.selectedModel===saved,"cold saved choice unavailable or opening started the engine");
   AssistantService.draft="hello";AssistantService.attachUrls([Qt.resolvedUrl("context.txt")]);
  }else if(stage===1){
   if(AssistantService.preparing)return;
   check(AssistantService.canSend&&AssistantService.send(),"cold Send cannot start Lemonade");
   if(!fails)AssistantService.draft="next draft";
   drawer.active=false;
  }else if(stage===2){
   if(AssistantService.checking||AssistantService.generating)return;
   if(fails){
    check(!!AssistantService.error&&!AssistantService.messages.count&&AssistantService.draft==="hello"&&AssistantService.attachments.length===1,"startup failure or missing saved model lost the frozen draft or submitted another model");
    console.log("DISPLAY_PASS");Qt.quit();return;
   }
   check(AssistantService.online&&AssistantService.messages.count===2&&AssistantService.draft==="next draft","first cold reply failed or lost next typing");
   payload.reload();payload.waitForJob();const sent=JSON.parse(payload.text());
   check(sent.model===saved&&sent.thinking==="off"&&sent.messages[0].content==="hello"&&sent.messages[0].attachments[0].text==="Frozen context","cold send lost settings, prompt or frozen files");
   AssistantService.setServer(false);
  }else if(stage===3){
   if(AssistantService.checking)return;
   check(!AssistantService.online,"explicit Stop failed");
   AssistantService.retry();
  }else if(stage===4){
   if(AssistantService.checking||AssistantService.generating)return;
   check(AssistantService.online&&!AssistantService.error&&AssistantService.messages.count===2&&AssistantService.messages.get(1).state==="done"&&AssistantService.draft==="next draft","offline retry did not start on demand or lost the conversation");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;tries=0;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
}""".replace('SAVED_CHOICE', json.dumps(saved)).replace(
                        'EXPECTED_FAILURE',
                        json.dumps(bool(start_error or saved == 'missing')),
                    ),
                    setup,
                )

    def test_unified_rows_tooltips_selection_and_native_delete_are_independent(self):
        def setup(root):
            (root / 'drawers/assistant/backend.py').write_text(FAKE_BACKEND)
            (root / 'state').mkdir()
            (root / 'state/fixture.json').write_text(
                json.dumps(
                    dict(
                        online=True,
                        loaded=True,
                        new=False,
                        downloads=[],
                        deleteError='Disk is read-only',
                    )
                )
            )

        self.run_qml(
            """import QtQuick
import QtTest
import Quickshell
import Quickshell.Io
import "ui"
import "drawers"
import "drawers/assistant"
ShellRoot {
 property int stage:0
 property int tries:0
 FloatingWindow {id:window;implicitWidth:360;implicitHeight:500;visible:true;color:Theme.background
  AssistantDrawer {id:drawer;x:16;y:16;width:328;height:468;active:true}
 }
 TestCase {id:input;name:"Model picker";when:false;parent:window.contentItem}
 FileView {id:fixture;path:Quickshell.env("XDG_STATE_HOME")+"/fixture.json";blockLoading:true;printErrors:false}
 Process {id:allowDelete
  command:["python3","-c","import pathlib,json,sys;p=pathlib.Path(sys.argv[1]);v=json.loads(p.read_text());v.pop('deleteError');t=p.with_suffix('.allow');t.write_text(json.dumps(v));t.replace(p)",Quickshell.env("XDG_STATE_HOME")+"/fixture.json"]
 }
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function model(name){return find(drawer.modelPopup.contentItem,"assistantModelRow:"+name);}
 function action(name){return find(drawer.modelPopup.contentItem,"assistantModelAction:"+name);}
 function tip(name){return model(name).data.find(item=>item.objectName==="assistantModelToolTip:"+name);}
 Timer {interval:100;repeat:true;running:true;onTriggered:{try{
  if(++tries>90)throw new Error("timeout "+stage+" "+AssistantService.error);
  if(stage===0){
   if(!AssistantService.online||AssistantService.checking)return;
   AssistantService.draft="hello";check(AssistantService.send(),"send refused");
  }else if(stage===1){
   if(AssistantService.generating)return;
   AssistantService.draft="keep this draft";drawer.modelPopup.open();
  }else if(stage===2){
   check(drawer.modelPopup.rows.map(row=>row.id).join(",")==="code,local,new"&&!find(drawer.modelPopup.contentItem,"assistantModelFilter"),"downloaded and available models are not in one ordered list");
   check(action("code").iconName==="trash"&&action("local").iconName==="trash"&&!action("new").visible,"delete action replaces selection button incorrectly");
   input.mouseClick(model("code"),2,model("code").height-2);
  }else if(stage===3){
   check(AssistantService.selectedModel==="code"&&!drawer.modelPopup.visible,"row padding cannot select model");
   drawer.modelPopup.open();
  }else if(stage===4){
   check(tip("local")?.target===model("local")&&tip("local").text.includes("500 MB"),"metadata tooltip is not attached to whole row: "+tip("local")?.text);
   input.mouseMove(model("local"),2,model("local").height-2);
  }else if(stage===5){
   if(!tip("local").requested)return;
   const idle=AssistantService.loaded;
   for(const flags of [{busy:true},{pinned:true}]){
    AssistantService.loaded=[Object.assign({id:"local",busy:false,pinned:false},flags)];
    check(!AssistantService.canDeleteModel("local")&&!action("local").enabled,"busy or pinned model is deletable");
    AssistantService.deleteModel("local");check(!AssistantService.working,"guard sent unsafe deletion");
   }
   AssistantService.loaded=idle;
   input.mouseClick(action("local"));
  }else if(stage===6){
   if(AssistantService.checking)return;
   check(AssistantService.error==="Disk is read-only"&&find(drawer.modelPopup.contentItem,"assistantModelError").text===AssistantService.error&&AssistantService.models.find(row=>row.id==="local").downloaded,"failed delete changed model state or hid error");
   check(drawer.modelPopup.visible&&AssistantService.selectedModel==="code","delete click selected row or closed picker");
   allowDelete.running=true;
  }else if(stage===7){
   if(allowDelete.running)return;
   input.mouseClick(action("local"));
  }else if(stage===8){
   if(AssistantService.checking)return;
   check(!AssistantService.error&&!AssistantService.models.find(row=>row.id==="local").downloaded&&!AssistantService.selectedLoaded,"native deletion did not refresh installed/loaded state");
   check(drawer.modelPopup.visible&&AssistantService.selectedModel==="code"&&AssistantService.messages.count===2&&AssistantService.draft==="keep this draft","deletion changed selection, conversation or draft");
   fixture.reload();fixture.waitForJob();const state=JSON.parse(fixture.text());check(state.deleted.join(",")==="local"&&!state.loaded,"delete did not unload and target exactly one model");
   check(action("local").visible===false&&find(drawer.modelPopup.contentItem,"assistantModelIndicator:local").visible,"deleted model still has a delete action");
  }else if(stage===9){
   input.mouseClick(find(drawer.modelPopup.contentItem,"assistantModelIndicator:local"));
  }else if(stage===10){
   check(AssistantService.selectedModel==="local"&&!AssistantService.modelAvailable&&AssistantService.canSend&&!drawer.modelPopup.visible,"deleted catalogue model cannot be selected again: "+JSON.stringify({model:AssistantService.selectedModel,available:AssistantService.modelAvailable,canSend:AssistantService.canSend,busy:AssistantService.busy,popup:drawer.modelPopup.visible,button:model("local")?.mapToItem(window.contentItem,0,0),height:model("local")?.height,width:model("local")?.width}));
   drawer.modelPopup.open();
  }else if(stage===11){
   check(drawer.modelPopup.rows[0].id==="code"&&drawer.modelPopup.rows.slice(1).every(row=>!row.downloaded),"deletion did not retain downloaded-first ordering");
   const folder=Quickshell.env("DISPLAY_PREVIEW_DIR");
   if(folder)drawer.modelPopup.contentItem.parent.grabToImage(result=>result.saveToFile(folder+"/assistant-models-unified.png"));
  }else if(stage===12){
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;tries=0;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
}""",
            setup,
        )

    def test_first_send_downloads_natively_with_context_and_survives_stop_retry(self):
        def setup(root):
            (root / 'drawers/assistant/backend.py').write_text(FAKE_BACKEND)
            (root / 'reference.txt').write_text('Frozen first-use context')

        self.run_qml(
            """import QtQuick
import Quickshell
import Quickshell.Io
import "ui"
import "drawers"
import "drawers/assistant"
ShellRoot {
 property int stage:0
 property int tries:0
 FloatingWindow {implicitWidth:480;implicitHeight:760;visible:true;color:Theme.background
  AssistantDrawer {id:drawer;x:16;y:16;width:448;height:728;active:true}
 }
 FileView {id:payload;path:Quickshell.env("XDG_STATE_HOME")+"/request.json";blockLoading:true;printErrors:false}
 FileView {id:fixture;path:Quickshell.env("XDG_STATE_HOME")+"/fixture.json";blockLoading:true;printErrors:false}
 FileView {id:polls;path:Quickshell.env("XDG_STATE_HOME")+"/polls.log";blockLoading:true;printErrors:false}
 Process {id:completeDownload
  command:["python3","-c","import pathlib,json,sys;p=pathlib.Path(sys.argv[1]);v=json.loads(p.read_text());v.update(new=True,nativeDownloading=False);t=p.with_suffix('.complete');t.write_text(json.dumps(v));t.replace(p)",Quickshell.env("XDG_STATE_HOME")+"/fixture.json"]
 }
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer {interval:100;repeat:true;running:true;onTriggered:{try{
  if(++tries>100)throw new Error("timeout "+stage+" "+AssistantService.error);
  if(stage===0){
   if(!AssistantService.online||AssistantService.checking)return;
   AssistantService.draft="first request";
   drawer.modelPopup.open();
  }else if(stage===1){
   const action=find(drawer.modelPopup.contentItem,"assistantModelRow:new");if(!action)return;
   action.clicked();
   check(AssistantService.selectedModel==="new"&&!AssistantService.modelAvailable&&AssistantService.canSend,"undownloaded selection cannot send");
   check(!AssistantService.downloading&&!AssistantService.generating,"selection started a download");
   AssistantService.chooseThinking("off");
   AssistantService.attachUrls([Qt.resolvedUrl("reference.txt")]);
  }else if(stage===2){
   if(AssistantService.preparing)return;
   check(AssistantService.attachments.length===1,"context import failed");
   check(AssistantService.send(),"first send refused");
   AssistantService.draft="next draft";drawer.active=false;
  }else if(stage===3){
   fixture.reload();fixture.waitForJob();polls.reload();polls.waitForJob();
   if(!JSON.parse(fixture.text()).nativeDownloading||polls.text().trim().split("\\n").length<2||AssistantService.checking)return;
   check(AssistantService.generating&&!AssistantService.observed&&!AssistantService.modelAvailable,"download request did not survive closing drawer");
   payload.reload();payload.waitForJob();const sent=JSON.parse(payload.text());
   check(sent.model==="new"&&sent.thinking==="off"&&sent.messages.length===1,"native first-use request lost settings or context");
   check(sent.messages[0].content==="first request"&&sent.messages[0].attachments[0].text==="Frozen first-use context","request lost frozen draft or attachment");
   check(!AssistantService.selectedDownload&&find(drawer,"assistantStatus").text.includes("Downloading"),"native wait invents a managed job or has no status");
   AssistantService.cancel();
  }else if(stage===4){
   if(AssistantService.generating||AssistantService.checking)return;
   check(AssistantService.messages.get(1).state==="stopped"&&!AssistantService.error,"download wait could not be stopped");
   fixture.reload();fixture.waitForJob();
   check(JSON.parse(fixture.text()).nativeDownloading&&!AssistantService.modelAvailable,"client interfered with Lemonade's download");
   AssistantService.retry();check(AssistantService.messages.get(1).state==="streaming","undownloaded model cannot retry");
  }else if(stage===5){
   if(!AssistantService.generating)return;
   completeDownload.running=true;
  }else if(stage===6){
   if(completeDownload.running||AssistantService.generating)return;
   drawer.active=true;
  }else if(stage===7){
   if(AssistantService.checking||!AssistantService.modelAvailable)return;
   check(!AssistantService.error&&!AssistantService.downloading,"native download did not become ready");
   check(AssistantService.messages.count===2&&AssistantService.messages.get(1).state==="done"&&AssistantService.messages.get(1).body.includes("answer"),"first message did not answer exactly once");
   check(AssistantService.draft==="next draft"&&!AssistantService.attachments.length,"download lost new typing or retained submitted attachments");
   fixture.reload();fixture.waitForJob();check(!JSON.parse(fixture.text()).manualDownloads,"client issued a separate Pull transaction");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;tries=0;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
}""",
            setup,
        )

    def test_thinking_only_cutoff_guidance_and_off_for_an_unlabelled_model(self):
        def setup(root):
            (root / 'drawers/assistant/backend.py').write_text(FAKE_BACKEND)

        self.run_qml(
            """import QtQuick
import Quickshell
import Quickshell.Io
import "ui"
import "drawers"
import "drawers/assistant"
ShellRoot {
 property int stage:0
 property int tries:0
 FloatingWindow {implicitWidth:480;implicitHeight:760;visible:true;color:Theme.background
  AssistantDrawer {id:drawer;x:16;y:16;width:448;height:728;active:true}
 }
 FileView {id:payload;path:Quickshell.env("XDG_STATE_HOME")+"/request.json";blockLoading:true;printErrors:false}
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer {interval:100;repeat:true;running:true;onTriggered:{try{
  if(++tries>90)throw new Error("timeout "+stage+" "+AssistantService.error);
  if(stage===0){
   if(!AssistantService.online||AssistantService.checking)return;
   AssistantService.chooseModel("code");
   check(!AssistantService.selectedEntry.labels.includes("reasoning"),"fixture has reasoning label");
   AssistantService.draft="reasoning only";check(AssistantService.send(),"send refused");
  }else if(stage===1){
   if(AssistantService.generating)return;
   check(AssistantService.messages.get(1).state==="limited"&&!AssistantService.messages.get(1).body&&!!AssistantService.messages.get(1).reasoning,"cutoff hid reasoning or invented an answer");
   check(AssistantService.error.includes("output limit")&&AssistantService.error.includes("Thinking → Off"),"thinking-only cutoff has no useful guidance");
   drawer.optionsPopup.open();
  }else if(stage===2){
   const choice=find(drawer.optionsPopup.contentItem,"assistantThinking");
   check(choice.visible,"thinking control hidden without catalogue label");
   choice.activated(2);check(AssistantService.thinkingMode==="off","cannot disable thinking");
   drawer.optionsPopup.close();
   find(drawer,"assistantRetry:1").clicked();
  }else if(stage===3){
   if(AssistantService.generating)return;
   check(!AssistantService.error&&AssistantService.messages.count===2&&AssistantService.messages.get(1).state==="done"&&AssistantService.messages.get(1).body.includes("answer"),"retry after disabling thinking failed");
   payload.reload();payload.waitForJob();const sent=JSON.parse(payload.text());
   check(sent.thinking==="off"&&sent.messages.length===1&&sent.messages[0].content==="reasoning only","retry resent thinking or lost native control");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;tries=0;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
}""",
            setup,
        )

    def test_native_alias_picker_preferences_retargeting_and_download_state(self):
        def setup(root):
            (root / 'drawers/assistant/backend.py').write_text(FAKE_BACKEND)
            (root / 'state').mkdir()
            (root / 'state/fixture.json').write_text(
                json.dumps(
                    dict(
                        online=True,
                        loaded=True,
                        new=False,
                        downloads=[],
                        aliases={'daily': 'local', 'download-alias': 'new'},
                    )
                )
            )
            (root / 'config/quickshell/desktop/assistant.json').write_text(
                json.dumps(dict(model='daily', length='balanced'))
            )

        self.run_qml(
            """import QtQuick
import Quickshell
import Quickshell.Io
import "ui"
import "drawers"
import "drawers/assistant"
ShellRoot {
 property int stage:0
 property int tries:0
 FloatingWindow {implicitWidth:480;implicitHeight:760;visible:true;color:Theme.background
  AssistantDrawer {id:drawer;x:16;y:16;width:448;height:728;active:true}
 }
 FileView {id:payload;path:Quickshell.env("XDG_STATE_HOME")+"/request.json";blockLoading:true;printErrors:false}
 FileView {id:preferences;path:Quickshell.env("XDG_CONFIG_HOME")+"/quickshell/desktop/assistant.json";blockLoading:true;printErrors:false}
 Process {id:writer
  command:["python3","-c","import pathlib,json,sys;p=pathlib.Path(sys.argv[1]);v=json.loads(p.read_text());v['aliases']['daily']='code';p.write_text(json.dumps(v))",Quickshell.env("XDG_STATE_HOME")+"/fixture.json"]
  onExited:AssistantService.refresh()
 }
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer {interval:100;repeat:true;running:true;onTriggered:{try{
  if(++tries>90)throw new Error("timeout "+stage+" "+AssistantService.error);
  if(stage===0){
   if(!AssistantService.online||AssistantService.checking)return;
   check(AssistantService.selectedModel==="daily"&&AssistantService.responseLength==="balanced","saved native choice missing");
   check(AssistantService.selectedLoaded.id==="local"&&AssistantService.canRelease,"alias does not share concrete loaded state");
   check(!find(drawer,"assistantTask"),"task selector remains");
   drawer.modelPopup.open();
  }else if(stage===1){
   check(drawer.modelPopup.rows.length===5&&drawer.modelPopup.rows.map(row=>row.id).join(",")==="daily,code,local,download-alias,new","downloaded models and aliases are not ordered first");
   const separator=find(drawer.modelPopup.contentItem,"assistantModelSeparator");
   check(separator&&separator.visible&&separator.width>100,"alias/model separator missing");
   find(drawer.modelPopup.contentItem,"assistantModelSearch").text="local";
   check(drawer.modelPopup.rows.length===2&&drawer.modelPopup.rows[0].id==="daily","search does not include alias target");
   find(drawer.modelPopup.contentItem,"assistantModelRow:daily").clicked();
   AssistantService.draft="hello";check(AssistantService.send(),"alias send refused");
  }else if(stage===2){
   if(AssistantService.generating)return;
   payload.reload();payload.waitForJob();const sent=JSON.parse(payload.text());
   check(sent.model==="daily"&&!("task" in sent)&&!("systemPrompt" in sent),"client task behavior remains or alias was resolved before inference");
   AssistantService.draft="keep my draft";writer.running=true;
  }else if(stage===3){
   if(writer.running||AssistantService.checking||AssistantService.selectedEntry.target!=="code")return;
   check(AssistantService.catalogueGeneration===1&&AssistantService.selectedModel==="daily","alias retarget lost selection");
   check(!AssistantService.supportsVision&&!AssistantService.selectedLoaded,"retarget retained stale capabilities or loaded state");
   check(AssistantService.messages.count===2&&AssistantService.draft==="keep my draft","refresh lost conversation or draft");
   AssistantService.chooseModel("code");drawer.width=308;drawer.height=408;drawer.modelPopup.open();
   find(drawer.modelPopup.contentItem,"assistantModelSearch").text="code";
  }else if(stage===4){
   preferences.reload();preferences.waitForJob();const saved=JSON.parse(preferences.text());
   check(saved.model==="code"&&!("task" in saved)&&!("models" in saved),"task preferences remain: "+JSON.stringify({saved,selected:AssistantService.selectedModel,preferred:AssistantService.preferredModel,error:AssistantService.saveError,ready:AssistantService.preferencesReady}));
   check(drawer.modelPopup.rows.length===2&&drawer.modelPopup.rows[0].id==="daily","retargeted alias search failed");
   check(drawer.modelPopup.width<=drawer.width,"narrow alias picker overflow");
   find(drawer.modelPopup.contentItem,"assistantModelSearch").text="new";
   AssistantService.downloadModel("download-alias");
  }else if(stage===5){
   if(AssistantService.checking)return;
   check(AssistantService.selectedModel==="download-alias"&&!AssistantService.modelAvailable,"alias download selection missing");
   check(AssistantService.selectedDownload.model_name==="new"&&drawer.modelPopup.progress(AssistantService.selectedDownload)===0.25,"alias download progress does not match target");
   const action=find(drawer.modelPopup.contentItem,"assistantModelAction:download-alias");
   if(!action)return;
   check(action.iconName==="pause","alias download cannot pause");action.clicked();
  }else if(stage===6){
   if(AssistantService.checking)return;
   check(AssistantService.selectedDownload.status==="paused"&&!AssistantService.downloading,"alias pause state missing");
   check(AssistantService.draft==="keep my draft","alias controls lost draft");
   drawer.active=false;check(!drawer.modelPopup.visible,"dismissal retained alias picker");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;tries=0;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
}""",
            setup,
        )

    def test_markdown_for_both_speakers_and_full_width_multiline_composer(self):
        source = (
            '    indented code\n\n# Notes\nFirst **bold** line\nSecond *italic* line\n\n'
            '- first item\n- second item\n\n'
            '| Left | Right |\n| --- | --- |\n| a | b |\n\n'
            '> quoted first\n> quoted second\n\n'
            '```python\nprint("hello")\n\nprint("goodbye")\n```\n\n'
            'Inline `literal **code**` stays literal.\n'
            'Multiline ``code\nspan`` ends here.\n'
            'Unclosed `backtick\nkeeps a newline.\n\n'
            '~~~text\nfenced\nlines\n~~~\n\n'
            '![Image label](https://example.invalid/no-fetch.png)\n'
            '<img src="https://example.invalid/no-fetch.png">'
        )

        def setup(root):
            (root / 'drawers/assistant/backend.py').write_text(FAKE_BACKEND)

        self.run_qml(
            r"""import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "ui"
import "drawers"
import "drawers/assistant"
ShellRoot {
 id:root
 property int stage:0
 property int tries:0
 readonly property string source: MARKDOWN_SOURCE
 FloatingWindow {id:window;implicitWidth:480;implicitHeight:760;visible:true;color:Theme.background
  AssistantDrawer {id:drawer;x:16;y:16;width:448;height:728;active:true}
 }
 TestCase {id:input;name:"Assistant input";when:false;parent:window.contentItem}
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function plain(item){return item.getText(0,item.length).replace(/[\u2028\u2029]/g,"\n");}
 Timer {interval:100;repeat:true;running:true;onTriggered:{try{
  if(++tries>80)throw new Error("timeout "+stage+" "+AssistantService.error);
  const composer=find(drawer,"assistantComposer");
  if(stage===0){
   if(!AssistantService.online||AssistantService.checking)return;
   AssistantService.draft=root.source;
   composer.forceActiveFocus();
  }else if(stage===1){
   check(composer.text===root.source&&composer.textFormat===TextEdit.PlainText,"draft Markdown was transformed");
   check(composer.width>drawer.width-32,"buttons still narrow the editor");
   const attach=find(drawer,"assistantAttach"),send=find(drawer,"assistantSend");
   const editor=find(drawer,"assistantEditor");
   check(attach.mapToItem(drawer,0,0).y>=editor.mapToItem(drawer,0,0).y+editor.height,"actions overlap editor");
   check(attach.y===send.y&&send.width>=32,"actions have inconsistent placement");
   check(find(drawer,"assistantInput").height<190,"long draft has unbounded height");
   composer.cursorPosition=composer.length;input.keyClick(Qt.Key_Return,Qt.ShiftModifier);
   check(AssistantService.messages.count===0&&AssistantService.draft===root.source+"\n","Shift+Enter submitted or lost source");
   input.keyClick(Qt.Key_Return);
  }else if(stage===2){
   if(AssistantService.generating||AssistantService.messages.count!==2)return;
   check(AssistantService.messages.get(0).body===root.source+"\n"&&!AssistantService.draft,"send modified Markdown source or retained draft");
   const user=find(drawer,"assistantMessage:0"),answer=find(drawer,"assistantMessage:1");
   if(!user||!answer)return;
   const rendered=plain(user);
   check(rendered.includes("First bold line\nSecond italic line"),"Markdown or typed newlines not rendered: "+JSON.stringify(rendered));
   check(!rendered.includes("**bold**")&&!rendered.includes("*italic*")&&!rendered.includes("```")&&!rendered.includes("~~~"),"Markdown delimiters visible");
   check(rendered.includes('literal **code**'),"inline code was altered");
   check(rendered.includes("code span")&&rendered.includes("Unclosed `backtick\nkeeps a newline."),"inline code broke chat newlines");
   check(rendered.includes('print("hello")\n\nprint("goodbye")'),"fenced code changed: "+JSON.stringify({rendered,source:root.source,text:user.text}));
   check(rendered.includes("fenced\nlines")&&rendered.includes("quoted first\nquoted second"),"fences or quote breaks lost");
   check(rendered.includes("first item")&&rendered.includes("Left")&&rendered.includes("Image label"),"list/table/image labels missing");
   check(!user.text.includes('![')&&!user.text.includes('<img'),"inline media still enabled");
   check(plain(answer).includes("A compact answer.")&&!plain(answer).includes("**"),"assistant Markdown not rendered");
   AssistantService.messages.setProperty(1,"body","Streaming **bold**\nnext line\n\n```text\npartial");
  }else if(stage===3){
   const answer=find(drawer,"assistantMessage:1");
   check(plain(answer).includes("Streaming bold\nnext line")&&plain(answer).includes("partial"),"partial Markdown cannot render");
   AssistantService.messages.setProperty(1,"body",AssistantService.messages.get(1).body+"\nfinished\n```");
   AssistantService.draft="";check(AssistantService.editLast(),"cannot restore Markdown for editing");
   drawer.width=308;drawer.height=408;
  }else if(stage===4){
   check(AssistantService.draft===root.source+"\n"&&composer.text===root.source+"\n","edit lost raw Markdown");
   check(composer.width>drawer.width-32,"narrow editor is not full width");
   const folder=Quickshell.env("DISPLAY_PREVIEW_DIR");
   if(folder)drawer.grabToImage(result=>result.saveToFile(folder+"/assistant-composer.png"));
  }else if(stage===5){
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;tries=0;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
}""".replace('MARKDOWN_SOURCE', json.dumps(source)),
            setup,
        )

    def test_files_thinking_previews_paste_and_last_message_edit(self):
        def setup(root):
            from test_assistant_attachments import png

            (root / 'drawers/assistant/backend.py').write_text(FAKE_BACKEND)
            (root / 'image.png').write_bytes(png())
            (root / 'notes.txt').write_text('Frozen reference text')
            (root / 'state').mkdir()
            (root / 'state/clipboard.json').write_text(
                json.dumps(dict(items=[], text='XYZ', error=''))
            )

        self.run_qml(
            """import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import Quickshell
import Quickshell.Io
import "ui"
import "drawers"
import "drawers/assistant"
ShellRoot {
 id:root
 property int stage:0
 property int tries:0
 property var image:null
 FloatingWindow {implicitWidth:480;implicitHeight:760;visible:true;color:Theme.background
  AssistantDrawer {id:drawer;x:16;y:16;width:448;height:728;active:true}
 }
 FileView {id:request;path:Quickshell.env("XDG_STATE_HOME")+"/request.json";blockLoading:true;printErrors:false}
 Process {id:mutate;command:["python3","-c","import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('Changed original')",Quickshell.shellPath("notes.txt")]}
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer {interval:100;repeat:true;running:true;onTriggered:{try{
  if(++tries>100)throw new Error("timeout "+stage+" "+AssistantService.error+" "+AssistantService.attachmentError);
  if(stage===0){
   if(!AssistantService.online||AssistantService.checking)return;
   AssistantService.chooseModel("code");AssistantService.attachUrls([Quickshell.shellPath("image.png"),Quickshell.shellPath("notes.txt")]);
  }else if(stage===1){
   if(AssistantService.preparing)return;
   check(AssistantService.attachments.length===2&&!AssistantService.canSend&&!!AssistantService.attachmentHint,"image capability was not enforced");
   image=AssistantService.attachments.find(item=>item.kind==="image");
   check(find(drawer,"assistantDraftAttachments").visible,"no attachment chips");
   drawer.modelPopup.open();check(drawer.modelPopup.rows.length===1&&drawer.modelPopup.rows[0].id==="local","non-vision models still offered for images");drawer.modelPopup.close();
   drawer.attachmentPreview.file=image;drawer.attachmentPreview.open();mutate.running=true;
  }else if(stage===2){
   if(mutate.running)return;
   check(drawer.attachmentPreview.visible&&find(drawer.attachmentPreview.contentItem,"assistantImagePreview").status===Image.Ready,"image preview missing");drawer.escapeHandler();check(!drawer.attachmentPreview.visible,"Escape did not close preview");
   drawer.attachmentDialog.currentFolder=Qt.resolvedUrl(".");drawer.attachmentDialog.open();
  }else if(stage===3){
   check(drawer.attachmentDialog.visible&&drawer.attachmentDialog.popupType===Popup.Item&&(drawer.attachmentDialog.options&FileDialog.DontUseNativeDialog)!==0,"file picker escaped shell layer");
   drawer.active=false;check(!drawer.attachmentDialog.visible&&AssistantService.attachments.length===2,"dismissal lost pending attachments or picker");drawer.active=true;
  }else if(stage===4){
   if(AssistantService.checking)return;
   AssistantService.chooseModel("local");AssistantService.chooseThinking("off");AssistantService.chooseStyle("precise");
   check(AssistantService.thinkingMode==="off","thinking choice missing");
   AssistantService.draft="Describe the files";check(AssistantService.send(),"multimodal send refused");
  }else if(stage===5){
   if(AssistantService.generating)return;
   check(AssistantService.messages.count===2&&AssistantService.attachments.length===0&&AssistantService.needsVision,"sent attachments or image context lost");
   request.reload();const sent=JSON.parse(request.text());
   check(sent.thinking==="off"&&sent.style==="precise"&&sent.messages[0].attachments.find(item=>item.kind==="text").text==="Frozen reference text","request options or frozen file content lost");
   check(AssistantService.messages.get(1).reasoning==="A short model thought.","thinking not retained separately");
   const folder=Quickshell.env("DISPLAY_PREVIEW_DIR");if(folder)drawer.grabToImage(result=>result.saveToFile(folder+"/assistant-attachments.png"));
  }else if(stage===6){
   AssistantService.chooseModel("code");AssistantService.draft="Follow up";check(!AssistantService.canSend,"model switch silently dropped images");
   AssistantService.draft="";check(AssistantService.editLast(),"last message cannot edit");
  }else if(stage===7){
   check(AssistantService.messages.count===0&&AssistantService.attachments.length===2,"editing failed to restore snapshots");
   AssistantService.removeAttachment(image.id);check(!AssistantService.needsVision&&AssistantService.canSend,"document unnecessarily requires vision");
   AssistantService.draft="ab";AssistantService.paste(1,1);
  }else if(stage===8){
   if(AssistantService.preparing)return;
   check(AssistantService.draft==="aXYZb"&&AssistantService.attachments.length===1,"clipboard text replaced draft or attachments: "+JSON.stringify({draft:AssistantService.draft,files:AssistantService.attachments.length,error:AssistantService.attachmentError}));
   AssistantService.chooseModel("code");check(AssistantService.attachments.length===1,"model switch lost draft attachments");
   drawer.width=308;drawer.height=408;drawer.optionsPopup.open();
  }else if(stage===9){
   check(find(drawer,"assistantAttach").width>20&&find(drawer,"assistantComposer").width>80,"narrow composer overflow");
   check(find(drawer.optionsPopup.contentItem,"assistantThinking").visible,"thinking control hidden by incomplete catalogue labels");
   drawer.active=false;check(!drawer.optionsPopup.visible,"dismissal retained options");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;tries=0;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
}""",
            setup,
            isolate_bus=True,
        )

    def test_open_app_connects_then_launches_independently_of_a_drawer(self):
        def setup(root):
            (root / 'drawers/assistant/backend.py').write_text(FAKE_BACKEND)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / 'launched.json'
            launcher = root / 'uwsm'
            launcher.write_text(
                '#!/usr/bin/env python3\nimport json,sys,pathlib\n'
                f'pathlib.Path({str(log)!r}).write_text(json.dumps(sys.argv[1:]))\n'
            )
            launcher.chmod(0o755)
            with patch.dict(
                os.environ, PATH=directory + os.pathsep + os.environ['PATH']
            ):
                self.run_qml(
                    """import QtQuick
import Quickshell
import "drawers/assistant"
ShellRoot {
 property int opened:0
 property int ticks:0
 Connections {target:AssistantService;function onAppOpened(){opened++;}}
 Component.onCompleted: AssistantService.openApp()
 Timer {interval:100;repeat:true;running:true;onTriggered:{
  if(opened&&++ticks>=3){
   if(!AssistantService.online||opened!==1)console.error("DISPLAY_FAIL open before connection or duplicate launch");
   else console.log("DISPLAY_PASS");Qt.quit();
  }
 }}
 Timer {interval:4000;running:true;onTriggered:{console.error("DISPLAY_FAIL app timeout",AssistantService.error);Qt.quit();}}
}""",
                    setup,
                )
            self.assertEqual(
                json.loads(log.read_text()),
                ['app', '-t', 'service', '--', 'lemonade-web-app'],
            )

    def test_catalogue_download_pause_resume_and_scoped_memory_release(self):
        def setup(root):
            (root / 'drawers/assistant/backend.py').write_text(FAKE_BACKEND)

        self.run_qml(
            """import QtQuick
import Quickshell
import "ui"
import "drawers"
import "drawers/assistant"
ShellRoot {
 property int stage:0
 property int tries:0
 FloatingWindow {implicitWidth:480;implicitHeight:760;visible:true;color:Theme.background
  AssistantDrawer {id:drawer;x:16;y:16;width:448;height:728;active:true}
 }
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function action(){return find(drawer.modelPopup.contentItem,"assistantModelAction:new");}
 Timer {interval:100;repeat:true;running:true;onTriggered:{try{
  if(++tries>100)throw new Error("timeout "+stage+" "+AssistantService.error);
  if(stage===0){
   if(!AssistantService.online||AssistantService.checking)return;
   AssistantService.draft="keep this draft";AssistantService.chooseModel("code");
   check(AssistantService.draft==="keep this draft","switching model lost draft");
   drawer.modelPopup.open();
  }else if(stage===1){
   check(!find(drawer.modelPopup.contentItem,"assistantModelFilter")&&drawer.modelPopup.rows.map(row=>row.id).join(",")==="code,local,new","picker did not merge and order downloaded models first");
  }else if(stage===2){
   const model=find(drawer.modelPopup.contentItem,"assistantModelRow:new");if(!model)return;
   check(!action().visible&&!!find(drawer.modelPopup.contentItem,"assistantModelIndicator:new"),"undownloaded indicator is an action");
   model.clicked();
   check(AssistantService.selectedModel==="new"&&!AssistantService.downloading&&AssistantService.canSend,"selection downloaded prematurely or disabled first send");
   AssistantService.downloadModel("new");
  }else if(stage===3){
   if(AssistantService.checking)return;
   check(AssistantService.selectedModel==="new"&&AssistantService.downloading&&!AssistantService.modelAvailable,"download selection missing");
   check(drawer.modelPopup.progress(AssistantService.selectedDownload)===0.25,"wrong total download progress");
   drawer.active=false;
   check(AssistantService.downloading&&!drawer.modelPopup.visible,"closing drawer cancelled server download");
   drawer.active=true;
  }else if(stage===4){
   if(AssistantService.checking)return;
   check(AssistantService.downloading,"reconnect lost download");
   drawer.modelPopup.open();
  }else if(stage===5){
   if(!action())return;
   check(action().iconName==="pause","download cannot pause");action().clicked();
  }else if(stage===6){
   if(AssistantService.checking)return;
   check(!AssistantService.downloading&&AssistantService.selectedDownload.status==="paused","pause not reflected");
   const folder=Quickshell.env("DISPLAY_PREVIEW_DIR");
   if(folder)drawer.modelPopup.contentItem.parent.grabToImage(result=>result.saveToFile(folder+"/assistant-models.png"));
   action().clicked();
  }else if(stage===7){
   if(AssistantService.checking)return;
   check(AssistantService.modelAvailable&&!AssistantService.downloading,"resumed download did not become ready");
   check(AssistantService.draft==="keep this draft","download lost draft");
  }else if(stage===8){
   const model=find(drawer.modelPopup.contentItem,"assistantModelRow:new");if(!model)return;
   model.clicked();
   check(!drawer.modelPopup.visible&&AssistantService.selectedModel==="new","installed selection failed");
   AssistantService.chooseModel("local");
   check(AssistantService.canRelease,"loaded idle model cannot release memory");
   AssistantService.releaseModel();
  }else if(stage===9){
   if(AssistantService.checking)return;
   check(!AssistantService.selectedLoaded&&!AssistantService.canRelease,"release did not follow Lemonade state");
   drawer.width=308;drawer.height=408;drawer.modelPopup.open();
  }else if(stage===10){
   check(drawer.modelPopup.width<=drawer.width,"picker exceeds narrow drawer");
   drawer.active=false;
   check(!drawer.modelPopup.visible,"dismissal retained picker");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;tries=0;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
}""",
            setup,
        )

    def test_chat_survives_page_and_cancels_retry_preferences_and_server_controls(self):
        def setup(root):
            (root / 'drawers/assistant/backend.py').write_text(FAKE_BACKEND)

        self.run_qml(
            """import QtQuick
import Quickshell
import "ui"
import "drawers"
import "drawers/assistant"
ShellRoot {
 id:root
 property int stage:0
 property int tries:0
 FloatingWindow {id:window;implicitWidth:480;implicitHeight:720;visible:true;color:Theme.background
  Loader {id:page;x:16;y:16;width:448;height:688;sourceComponent:AssistantDrawer{active:true}}
  Loader {id:header;x:16;y:0;sourceComponent:page.item?.headerActions??null}
 }
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer {interval:100;repeat:true;running:true;onTriggered:{try{
  if(++tries>90)throw new Error("timeout stage "+stage+" "+AssistantService.error);
  if(stage===0){
   if(!AssistantService.checked||AssistantService.checking)return;
   check(AssistantService.online&&AssistantService.models.length===3,"existing server status missing");
   check(find(header.item,"assistantEdit").enabled&&find(header.item,"assistantServer").text==="Stop Lemonade","header service control missing");
   check(!find(page.item.optionsPopup.contentItem,"assistantServer"),"options duplicates service control");
   check(!find(page.item,"assistantStart")&&!find(page.item,"assistantManageModels"),"duplicate empty-state actions");
   check(AssistantService.selectedModel==="local","loaded model not selected");
   AssistantService.chooseModel("code");AssistantService.chooseLength("balanced");
   check(AssistantService.selectedModel==="code","model selection was not remembered");
   AssistantService.draft="wait";check(AssistantService.send(),"send refused");
  }else if(stage===1){
   if(!AssistantService.messages.get(1).body)return;
   check(AssistantService.generating,"not streaming");
   page.active=false;
   check(AssistantService.generating&&!AssistantService.observed,"page destruction stopped generation");
   page.active=true;
  }else if(stage===2){
   check(AssistantService.messages.count===2&&AssistantService.generating,"reopen lost chat");
   check(find(page.item,"assistantSend").text==="Stop reply","no stop control");
   AssistantService.cancel();
  }else if(stage===3){
   if(AssistantService.generating)return;
   check(AssistantService.messages.get(1).state==="stopped"&&!!AssistantService.messages.get(1).body,"cancel lost partial answer");
   AssistantService.messages.setProperty(0,"body","hello");AssistantService.retry();
  }else if(stage===4){
   if(AssistantService.generating)return;
   check(!AssistantService.error&&AssistantService.messages.count===2&&AssistantService.messages.get(1).state==="done","retry failed "+AssistantService.error);
   check(find(page.item,"assistantMessage:1").text.includes("answer"),"answer not rendered");
   const folder=Quickshell.env("DISPLAY_PREVIEW_DIR");
   if(folder)page.item.grabToImage(result=>result.saveToFile(folder+"/assistant-chat.png"));
   find(page.item,"assistantOptions").clicked();
  }else if(stage===5){
   check(page.item.optionsPopup.visible,"options missing");
   page.item.active=false;
   check(!page.item.optionsPopup.visible,"dismissal retained options");
   AssistantService.newChat();
   find(header.item,"assistantServer").clicked();
  }else if(stage===6){
   if(AssistantService.checking)return;
   check(!AssistantService.online&&find(page.item,"assistantComposer").enabled,"stopping disabled draft entry");
   const folder=Quickshell.env("DISPLAY_PREVIEW_DIR");
   if(folder)page.item.grabToImage(result=>result.saveToFile(folder+"/assistant-offline.png"));
   AssistantService.draft="hello";check(AssistantService.send(),"send did not reconnect");AssistantService.draft="next prompt";
  }else if(stage===7){
   if(AssistantService.checking||AssistantService.generating)return;
   check(AssistantService.online&&AssistantService.messages.count===2,"send did not reconnect and answer");
   check(AssistantService.messages.get(0).body==="hello"&&AssistantService.draft==="next prompt","startup lost the frozen prompt or new draft");
   page.item.active=true;
   page.width=308;page.height=408;
  }else if(stage===8){
   check(find(page.item,"assistantModel").width>50&&find(page.item,"assistantComposer").height>20,"narrow drawer overflow");
   const folder=Quickshell.env("DISPLAY_PREVIEW_DIR");
   if(folder)page.item.grabToImage(result=>result.saveToFile(folder+"/assistant-narrow.png"));
  }else if(stage===9){
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;tries=0;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
}""",
            setup,
        )
