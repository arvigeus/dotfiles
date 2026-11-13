"""Registry discovery, validated installs and cancellable native model search."""

import io
import json
import sys
import unittest
import urllib.parse
from unittest.mock import patch

import support
import test_assistant_drawer as drawer_tests

sys.path.insert(0, str(support.DESKTOP / 'drawers/assistant'))
backend = support.load(
    'assistant_registry', support.DESKTOP / 'drawers/assistant/backend.py'
)


def metadata(**overrides):
    return (
        dict(
            recipe='llamacpp',
            repo_kind='gguf',
            suggested_labels=['chat', 'vision'],
            mmproj_files=['mmproj-f16.gguf'],
            variants=[
                dict(
                    name='Q4_K_M',
                    primary_file='weights/model-Q4_K_M.gguf',
                    size_bytes=4_000_000_000,
                    draft_file='draft.gguf',
                )
            ],
        )
        | overrides
    )


class RegistryBackendTests(unittest.TestCase):
    def setUp(self):
        self.values = dict(
            source='huggingface', repository='owner/Model-GGUF', variant='Q4_K_M'
        )
        self.calls = []
        self.catalogue = []
        self.metadata = metadata()

        def request(url, payload=None, **kwargs):
            self.calls.append((url, payload, kwargs))
            if '/pull/variants?' in url:
                data = self.metadata
            elif '/v1/models?' in url:
                data = dict(data=self.catalogue)
            else:
                data = dict(status='success')
            return io.BytesIO(json.dumps(data).encode())

        for name, replacement in (
            ('service', lambda: ('user', {})),
            ('server_url', lambda _scope: 'http://localhost:13305'),
            ('request', request),
            ('status', lambda: dict(online=True, models=[])),
        ):
            patcher = patch.object(backend, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_search_uses_each_local_registry_route_and_encodes_query(self):
        for source in backend.REGISTRIES:
            with self.subTest(source=source):
                rows = dict(
                    results=[
                        dict(repository_id='owner/Model-GGUF', downloads=12),
                        dict(repository_id='https://other.invalid/repo'),
                        dict(repository_id='../bad'),
                    ]
                )
                with patch.object(
                    backend,
                    'request',
                    return_value=io.BytesIO(json.dumps(rows).encode()),
                ) as request:
                    result = backend.control(
                        'registry_search',
                        dict(source=source, query='  mistral & qwen  '),
                    )
                parsed = urllib.parse.urlsplit(request.call_args.args[0])
                self.assertEqual(parsed.netloc, 'localhost:13305')
                self.assertEqual(parsed.path, '/v1/registry/search')
                self.assertEqual(
                    urllib.parse.parse_qs(parsed.query),
                    dict(
                        source=[source],
                        query=['mistral & qwen'],
                        format=['gguf'],
                        limit=['12'],
                    ),
                )
                self.assertEqual(
                    result['results'],
                    [dict(id='owner/Model-GGUF', downloads=12, likes=0)],
                )
        for values in (
            dict(source='unknown', query='qwen'),
            dict(source='huggingface', query='ab'),
        ):
            with self.assertRaises(ValueError):
                backend.control('registry_search', values)

    def test_install_revalidates_files_and_registers_server_owned_job(self):
        result = backend.control(
            'registry_install',
            self.values | dict(checkpoint='malicious', recipe='cloud'),
        )
        self.assertTrue(
            self.calls[0][0].startswith('http://localhost:13305/v1/pull/variants?')
        )
        url, payload, _ = self.calls[-1]
        self.assertEqual(url, 'http://localhost:13305/v1/pull')
        self.assertEqual(
            payload['checkpoints'],
            dict(
                main='owner/Model-GGUF:weights/model-Q4_K_M.gguf',
                mmproj='owner/Model-GGUF:mmproj-f16.gguf',
                draft='owner/Model-GGUF:draft.gguf',
            ),
        )
        self.assertEqual(payload['recipe'], 'llamacpp')
        self.assertEqual(payload['source'], 'huggingface')
        self.assertEqual(payload['labels'], ['chat', 'vision'])
        self.assertTrue(payload['stream'])
        self.assertFalse(payload['subscribe'])
        self.assertEqual(result['installed_model'], payload['model_name'])
        self.assertTrue(result['installed_model'].startswith('user.Model-GGUF-Q4_K_M-'))
        other = backend.control(
            'registry_install', self.values | dict(source='modelscope')
        )
        self.assertNotEqual(result['installed_model'], other['installed_model'])

    def test_reuses_existing_model_without_overwriting_its_definition(self):
        self.catalogue = [
            dict(
                id='existing',
                recipe='llamacpp',
                labels=['chat'],
                source='huggingface',
                checkpoint='owner/Model-GGUF:Q4_K_M',
                downloaded=False,
            )
        ]
        self.assertEqual(
            backend.control('registry_install', self.values)['installed_model'],
            'existing',
        )
        self.assertEqual(
            self.calls[-1][1], dict(model_name='existing', stream=True, subscribe=False)
        )
        self.calls.clear()
        self.catalogue[0]['downloaded'] = True
        self.assertEqual(
            backend.control('registry_install', self.values)['installed_model'],
            'existing',
        )
        self.assertFalse(any(payload for _, payload, _ in self.calls))

    def test_rejects_incompatible_changed_or_unsafe_repository_before_pull(self):
        for overrides in (
            dict(recipe='cloud'),
            dict(repo_kind='onnx-ryzenai'),
            dict(suggested_labels=['embeddings']),
            dict(mmproj_files=[]),
            dict(variants=[dict(name='Q4_K_M', primary_file='../model.gguf')]),
            dict(variants=[dict(name='Q8_0', primary_file='model.gguf')]),
        ):
            with self.subTest(overrides=overrides):
                self.calls.clear()
                self.metadata = metadata(**overrides)
                with self.assertRaises(ValueError):
                    backend.control('registry_install', self.values)
                self.assertFalse(any(payload for _, payload, _ in self.calls))
        self.metadata = metadata(suggested_labels=['chat'], mmproj_files=[])
        with self.assertRaisesRegex(ValueError, 'vision'):
            backend.control('registry_install', self.values | dict(needs_vision=True))
        for repository in ('../foo', 'a/../b', 'https://host/repo', 'a/repo:variant'):
            with self.assertRaisesRegex(ValueError, 'repository'):
                backend.control(
                    'registry_variants', self.values | dict(repository=repository)
                )

    def test_name_collision_and_pull_failure_do_not_report_install_success(self):
        installed = backend.control('registry_install', self.values)['installed_model']
        self.catalogue = [
            dict(
                id=installed,
                checkpoint='other/repo:Q4',
                recipe='llamacpp',
                source='modelscope',
            )
        ]
        with self.assertRaisesRegex(ValueError, 'different model'):
            backend.control('registry_install', self.values)
        self.catalogue = []
        original = backend.request

        def fail(url, payload=None, **kwargs):
            if url.endswith('/v1/pull'):
                return io.BytesIO(b'{"error":"Disk full"}')
            return original(url, payload, **kwargs)

        with patch.object(backend, 'request', fail):
            with self.assertRaisesRegex(ValueError, 'Disk full'):
                backend.control('registry_install', self.values)

    def test_registration_uses_the_native_catalogue_id_and_checks_bare_collisions(self):
        canonical = backend.control('registry_install', self.values)['installed_model']
        bare = canonical.removeprefix('user.')
        with patch.object(
            backend, 'status', return_value=dict(online=True, models=[dict(id=bare)])
        ):
            self.assertEqual(
                backend.control('registry_install', self.values)['installed_model'],
                bare,
            )
        self.catalogue = [dict(id=bare, checkpoint='another/repo:Q4')]
        with self.assertRaisesRegex(ValueError, 'different model'):
            backend.control('registry_install', self.values)

    def test_vision_install_keeps_an_existing_text_only_definition_intact(self):
        self.catalogue = [
            dict(
                id='text-only',
                recipe='llamacpp',
                labels=['chat'],
                source='huggingface',
                checkpoint='owner/Model-GGUF:Q4_K_M',
                downloaded=True,
            )
        ]
        result = backend.control(
            'registry_install', self.values | dict(needs_vision=True)
        )
        self.assertNotEqual(result['installed_model'], 'text-only')
        self.assertEqual(
            self.calls[-1][1]['checkpoints']['mmproj'],
            'owner/Model-GGUF:mmproj-f16.gguf',
        )


REMOTE_FIXTURE = """
if value['op'].startswith('registry_'):
    import signal
    log=pathlib.Path(os.environ['XDG_STATE_HOME'])/'registry.log'
    log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('a') as out:out.write(json.dumps(value)+'\\n')
    if value['op']=='registry_search':
        query=value['query']
        if query=='first':signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(.8)
        if value['source']=='modelscope' and query=='latest':
            print(json.dumps(dict(type='error',error='ModelScope is unavailable')),flush=True)
        else:
            print(json.dumps(dict(results=[dict(id=query+'/Model-GGUF')],source=value['source'])),flush=True)
        sys.exit(0)
    if value['op']=='registry_variants':
        print(json.dumps(dict(labels=['chat','vision'],variants=[dict(name='Q8_0',size=8e9),dict(name='Q4_K_M',size=4e9)])),flush=True)
        sys.exit(0)
    if value['op']=='registry_install':value['op']='download';value['model']='new'
"""
REMOTE_BACKEND = drawer_tests.FAKE_BACKEND.replace(
    'value=json.loads(sys.stdin.readline())\n',
    'value=json.loads(sys.stdin.readline())\n' + REMOTE_FIXTURE,
    1,
).replace(
    'print(json.dumps(result),flush=True)',
    "if op=='download':result['installed_model']='new'\n    print(json.dumps(result),flush=True)",
)


class RegistryPickerTests(unittest.TestCase):
    def run_qml(self, body, setup=None):
        def prepare(root):
            (root / 'drawers/assistant/backend.py').write_text(REMOTE_BACKEND)
            if setup:
                setup(root)

        return support.run_qml(self, body, prepare, isolate_bus=True)

    def test_collapsing_and_switching_results_restores_row_positions(self):
        def setup(root):
            script = REMOTE_BACKEND.replace(
                "results=[dict(id=query+'/Model-GGUF')]",
                "results=[dict(id=query+'/'+name) for name in ('Model-GGUF','Other-GGUF','Broken-GGUF')]",
            ).replace(
                "if value['op']=='registry_variants':\n",
                """if value['op']=='registry_variants':
        if value['repository'].endswith('Broken-GGUF'):
            print(json.dumps(dict(type='error',error='Unsupported model files')),flush=True)
            sys.exit(0)
        time.sleep(.3)
""",
            )
            (root / 'drawers/assistant/backend.py').write_text(script)

        self.run_qml(
            """import QtQuick
import QtTest
import Quickshell
import "ui"
import "drawers"
import "drawers/assistant"
ShellRoot {
 property int stage:0
 property int tries:0
 property var baseline:null
 property var names:["Model-GGUF","Other-GGUF","Broken-GGUF"]
 FloatingWindow {id:window;implicitWidth:420;implicitHeight:580;visible:true
  AssistantDrawer {id:drawer;anchors.fill:parent;active:true}
 }
 TestCase {id:input;when:false;parent:window.contentItem}
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function item(name){return find(drawer.modelPopup.contentItem,name);}
 function row(index){return item("assistantRepository:huggingface:collapse/"+names[index]);}
 function geometry(){const registry=item("assistantRegistry:huggingface");return [registry.height,item("assistantModelResults").contentHeight,...names.map((name,index)=>row(index).mapToItem(registry,0,0).y)];}
 function collapsed(){const current=geometry();check(current.every((value,index)=>Math.abs(value-baseline[index])<1),"collapsed results retained gaps: "+JSON.stringify({baseline,current}));}
 function click(index){input.mouseClick(row(index),row(index).width/2,row(index).height/2);}
 Timer {interval:100;repeat:true;running:true;onTriggered:{try{
  if(++tries>90)throw new Error("timeout stage "+stage);
  const inspection=item("assistantRegistryInspection:huggingface");
  if(stage===0){
   if(!AssistantService.online||AssistantService.checking)return;
   drawer.modelPopup.open();
  }else if(stage===1){
   if(AssistantService.checking)return;
   item("assistantModelSearch").text="collapse";
  }else if(stage===2){
   if(!row(2)||item("assistantRegistrySearch:huggingface").busy||item("assistantRegistrySearch:modelscope").busy)return;
   baseline=geometry();click(0);
  }else if(stage===3){
   if(inspection.busy)return;
   check(!inspection.error&&item("assistantRegistryQuantization:huggingface").count===2,"model form did not load");
   check(geometry()[0]>baseline[0],"expanded result did not occupy space");click(0);
  }else if(stage===4){
   collapsed();click(1);
  }else if(stage===5){
   check(inspection.busy,"missing loading state");click(1);
  }else if(stage===6){
   collapsed();click(1);
  }else if(stage===7){
   if(inspection.busy)return;
   check(!inspection.error,"second result did not load");click(0);
  }else if(stage===8){
   if(inspection.busy)return;
   check(row(1).parent.height===row(1).height,"switching results left previous row expanded");
   click(0);
  }else if(stage===9){
   collapsed();click(2);
  }else if(stage===10){
   if(inspection.busy)return;
   check(inspection.error==="Unsupported model files","missing inspection failure");
   check(geometry()[0]>baseline[0],"error details did not occupy space");click(2);
  }else if(stage===11){
   collapsed();
   const folder=Quickshell.env("DISPLAY_PREVIEW_DIR");
   if(folder)drawer.modelPopup.contentItem.parent.grabToImage(result=>result.saveToFile(folder+"/assistant-registry-collapsed.png"));
  }else if(stage===12){
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;tries=0;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
}""",
            setup,
        )

    def test_provider_results_variants_download_and_native_controls(self):
        self.run_qml("""import QtQuick
import Quickshell
import Quickshell.Io
import "ui"
import "drawers"
import "drawers/assistant"
ShellRoot {
 property int stage:0
 property int tries:0
 FloatingWindow {id:window;implicitWidth:400;implicitHeight:580;visible:true
  AssistantDrawer {id:drawer;anchors.fill:parent;active:true}
 }
 FileView {id:log;path:Quickshell.env("XDG_STATE_HOME")+"/registry.log";blockLoading:true;printErrors:false}
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function item(name){return find(drawer.modelPopup.contentItem,name);}
 Timer {interval:100;repeat:true;running:true;onTriggered:{try{
  if(++tries>90)throw new Error("timeout stage "+stage+" "+AssistantService.error);
  if(stage===0){
   if(!AssistantService.online||AssistantService.checking)return;
   AssistantService.draft="keep this draft";drawer.modelPopup.open();
  }else if(stage===1){
   if(AssistantService.checking)return;
   item("assistantModelSearch").text="latest";
  }else if(stage===2){
   const row=item("assistantRepository:huggingface:latest/Model-GGUF");
   const ms=item("assistantRegistrySearch:modelscope");
   if(!row||ms.busy)return;
   check(ms.error==="ModelScope is unavailable","provider error hidden");
   check(!AssistantService.busy,"search blocked chat controls");
   check(!AssistantService.error,"provider error overwrote conversation error");
   row.clicked();
  }else if(stage===3){
   const request=item("assistantRegistryInspection:huggingface");
   const choice=item("assistantRegistryQuantization:huggingface");
   if(request.busy||!choice||choice.count!==2)return;
   check(choice.currentIndex===1,"Q4_K_M was not selected by default");
   const button=item("assistantRegistryDownload:huggingface");
   check(button.enabled,"validated download unavailable");
   const folder=Quickshell.env("DISPLAY_PREVIEW_DIR");
   if(folder)drawer.modelPopup.contentItem.parent.grabToImage(result=>result.saveToFile(folder+"/assistant-registry.png"));
   button.clicked();
  }else if(stage===4){
   if(AssistantService.checking)return;
   check(!AssistantService.error&&AssistantService.selectedModel==="new"&&AssistantService.downloading,"native download/selection missing: "+AssistantService.error);
   check(item("assistantModelSearch").text==="","search did not reveal the registered model");
   check(drawer.modelPopup.visible&&AssistantService.draft==="keep this draft","install lost draft or closed picker");
   const action=item("assistantModelAction:new");if(!action)return;
   check(action.visible,"native pause control missing");
   log.reload();log.waitForJob();const calls=log.text().trim().split("\\n").map(JSON.parse);
   const install=calls.find(row=>row.op==="registry_install");
   check(install.source==="huggingface"&&install.repository==="latest/Model-GGUF"&&install.variant==="Q4_K_M","incorrect installation request");
   check(calls.filter(row=>row.op==="registry_variants").length===1,"inspected untouched provider");
   action.clicked();
  }else if(stage===5){
   if(AssistantService.checking)return;
   check(AssistantService.selectedDownload.status==="paused","download cannot pause");
   drawer.active=false;check(!drawer.modelPopup.visible,"closed drawer retained picker");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;tries=0;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
}""")

    def test_search_debounces_ignores_stale_results_and_stops_on_close(self):
        self.run_qml("""import QtQuick
import Quickshell
import Quickshell.Io
import "ui"
import "drawers"
import "drawers/assistant"
ShellRoot {
 property int stage:0
 property int ticks:0
 FloatingWindow {implicitWidth:360;implicitHeight:420;visible:true
  AssistantDrawer {id:drawer;anchors.fill:parent;active:true}
 }
 FileView {id:log;path:Quickshell.env("XDG_STATE_HOME")+"/registry.log";blockLoading:true;printErrors:false}
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function item(name){return find(drawer.modelPopup.contentItem,name);}
 function calls(){log.reload();log.waitForJob();return log.text().trim().split("\\n").filter(Boolean).map(JSON.parse);}
 Timer {interval:100;repeat:true;running:true;onTriggered:{try{
  if(++ticks>100)throw new Error("timeout stage "+stage);
  if(stage===0){
   if(!AssistantService.online||AssistantService.checking)return;
   drawer.modelPopup.open();
  }else if(stage===1){
   if(AssistantService.checking)return;
   item("assistantModelSearch").text="ab";
  }else if(stage===2){
   if(ticks<6)return;
   check(!calls().length,"short query searched online");
   item("assistantModelSearch").text="ignored";
  }else if(stage===3){item("assistantModelSearch").text="first";
  }else if(stage===4){
   if(calls().filter(row=>row.query==="first").length<2)return;
   item("assistantModelSearch").text="latest";
  }else if(stage===5){
   if(item("assistantRegistrySearch:huggingface").busy||item("assistantRegistrySearch:modelscope").busy)return;
   check(!!item("assistantRepository:huggingface:latest/Model-GGUF"),"latest result missing");
   check(!item("assistantRepository:huggingface:first/Model-GGUF"),"stale response replaced results");
   check(!calls().some(row=>row.query==="ignored"),"typing was not debounced");
   item("assistantModelSearch").text="first";
  }else if(stage===6){
   if(calls().filter(row=>row.query==="first").length<4)return;
   drawer.modelPopup.close();
  }else if(stage===7){
   if(ticks<12)return;
   check(!item("assistantRegistrySearch:huggingface").busy&&!item("assistantRegistrySearch:modelscope").busy,"hidden search remained active");
   check(!item("assistantRepository:huggingface:first/Model-GGUF"),"hidden picker accepted results");
   check(calls().length===6,"hidden picker kept searching");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;ticks=0;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
}""")
