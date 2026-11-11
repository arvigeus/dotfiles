"""Dolphin selections use the shell's IPC without shell interpolation or inference."""

import json
import os
from pathlib import Path
import runpy
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import support

LAUNCHER = (
    support.REPO
    / 'modules/desktop/quickshell/symlinks/home/.local/bin/desktop-assistant-context'
)
helper = runpy.run_path(str(LAUNCHER))
SHARE = LAUNCHER.parent.parent / 'share/kpackage/Purpose/desktop-assistant-context'


class AssistantContextTests(unittest.TestCase):
    def test_multiple_paths_are_encoded_as_one_ipc_argument_without_a_shell(self):
        paths = ['/tmp/$(touch nope) "notes".md', '/tmp/Việt #100%\nsecond.txt']
        with (
            patch.dict(os.environ, XDG_CONFIG_HOME='/tmp/context-config'),
            patch.object(
                subprocess,
                'run',
                return_value=subprocess.CompletedProcess([], 0, '\n', ''),
            ) as run,
        ):
            helper['add_files'](paths)
        args = run.call_args.args[0]
        self.assertEqual(
            args[:7],
            [
                'qs',
                'ipc',
                '--path',
                '/tmp/context-config/quickshell/desktop/shell.qml',
                'call',
                'assistant',
                'addFiles',
            ],
        )
        self.assertEqual(
            json.loads(args[7]), dict(files=[Path(path).as_uri() for path in paths])
        )
        self.assertNotIn('shell', run.call_args.kwargs)
        self.assertEqual(run.call_args.kwargs['timeout'], 5)

    def test_invalid_selection_shell_failure_and_queue_rejection_are_visible(self):
        for paths in ([], ['/tmp/file'] * 7, ['/tmp/' + 'a' * 100000]):
            with self.subTest(paths=len(paths)), patch.object(subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    helper['add_files'](paths)
                run.assert_not_called()
        for result in (
            subprocess.CompletedProcess([], 1, '', 'no instance'),
            subprocess.CompletedProcess(
                [], 0, 'Wait for the current files to finish preparing.\n', ''
            ),
        ):
            with (
                self.subTest(result=result),
                patch.object(subprocess, 'run', return_value=result),
            ):
                with self.assertRaises(ValueError):
                    helper['add_files'](['/tmp/file'])
        with patch.object(
            subprocess, 'run', side_effect=subprocess.TimeoutExpired('qs', 5)
        ):
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                helper['add_files'](['/tmp/file'])

    def test_notification_escapes_file_names_and_bounds_its_wait(self):
        with patch.object(subprocess, 'run') as run:
            helper['notify']('Cannot read <notes> & files')
        self.assertEqual(
            run.call_args.args[0][-1], 'Cannot read &lt;notes&gt; &amp; files'
        )
        self.assertEqual(run.call_args.kwargs['timeout'], 3)

    def test_share_protocol_rejects_nonlocal_and_invalid_selections(self):
        from PySide6.QtCore import QCborValue

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'notes #100%.txt'
            path.write_text('context')
            for urls, error in (
                ([path.as_uri()], ''),
                ([], 'six local files'),
                ([path.as_uri()] * 7, 'six local files'),
                (['https://example.invalid/file'], 'Only local files'),
                (['file://remote/tmp/file'], 'Only local files'),
                ([root.as_uri()], 'Select files'),
                ([None], 'Only local files'),
            ):
                responses = []
                with self.subTest(urls=urls), socket.socket(socket.AF_UNIX) as server:
                    address = str(root / 'share.socket')
                    Path(address).unlink(missing_ok=True)
                    server.bind(address)
                    server.listen(1)
                    server.settimeout(3)

                    def serve():
                        with server.accept()[0] as channel:
                            payload = bytes(
                                QCborValue.fromVariant(dict(urls=urls)).toCbor()
                            )
                            channel.sendall(str(len(payload)).encode() + b'\n')
                            channel.sendall(payload)
                            responses.append(channel.makefile('rb').readline())

                    thread = threading.Thread(target=serve, daemon=True)
                    thread.start()
                    with patch.dict(
                        helper['share'].__globals__, add_files=lambda paths: None
                    ):
                        self.assertEqual(helper['share'](address), 0)
                    thread.join(3)
                    self.assertFalse(thread.is_alive())
                    response = json.loads(responses[0])
                    if error:
                        self.assertEqual(response['error'], 1)
                        self.assertIn(error, response['errorText'])
                    else:
                        self.assertEqual(response, dict(output={}))

    @unittest.skipUnless(
        shutil.which('g++')
        and shutil.which('dbus-run-session')
        and Path('/usr/include/KF6/PurposeWidgets').exists(),
        'KDE Purpose/KIO development files and g++ are required',
    )
    def test_native_dolphin_share_menu_discovers_and_executes_the_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'bin'
            binary.mkdir()
            (root / 'runtime').mkdir(mode=0o700)
            shutil.copytree(
                SHARE, root / 'data/kpackage/Purpose/desktop-assistant-context'
            )
            (binary / 'desktop-assistant-context').symlink_to(LAUNCHER)
            logger = binary / 'qs'
            logger.write_text(
                '#!/usr/bin/env python3\nimport json,os,pathlib,sys\n'
                'pathlib.Path(os.environ["SHARE_TEST_LOG"]).write_text(json.dumps(sys.argv[1:]))\n'
            )
            logger.chmod(0o755)
            executable = root / 'share-test'
            qt = subprocess.check_output(
                ['pkg-config', '--cflags', '--libs', 'Qt6Widgets', 'Qt6Qml'], text=True
            ).split()
            compiled = subprocess.run(
                [
                    'g++',
                    '-fPIC',
                    '-std=c++17',
                    str(support.REPO / 'tests/fixtures/assistant-share.cpp'),
                    '-o',
                    str(executable),
                    *[
                        '-I/usr/include/KF6/' + part
                        for part in (
                            'Purpose',
                            'PurposeWidgets',
                            'KIO',
                            'KIOWidgets',
                            'KIOCore',
                            'KCoreAddons',
                            'KService',
                        )
                    ],
                    '-lKF6PurposeWidgets',
                    '-lKF6Purpose',
                    '-lKF6KIOWidgets',
                    '-lKF6KIOCore',
                    *qt,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            paths = [root / '$(touch nope) #100%.txt', root / 'Việt\nmore.txt']
            for path in paths:
                path.write_text('context')
            result = subprocess.run(
                [*support.private_bus(root), str(executable), *map(str, paths)],
                env={
                    **os.environ,
                    'PATH': str(binary) + os.pathsep + os.environ['PATH'],
                    'QT_QPA_PLATFORM': 'offscreen',
                    'XDG_DATA_HOME': str(root / 'data'),
                    'XDG_CONFIG_HOME': str(root / 'config'),
                    'XDG_CACHE_HOME': str(root / 'cache'),
                    'XDG_RUNTIME_DIR': str(root / 'runtime'),
                    'SHARE_TEST_LOG': str(root / 'request.json'),
                },
                capture_output=True,
                text=True,
                timeout=12,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            request = json.loads((root / 'request.json').read_text())
            self.assertEqual(request[:2], ['ipc', '--path'])
            self.assertEqual(
                json.loads(request[-1]), dict(files=[path.as_uri() for path in paths])
            )


@unittest.skipUnless(support.QS, 'Quickshell is required')
class AssistantContextIpcTests(unittest.TestCase):
    def test_files_accumulate_while_closed_and_show_in_the_drawer_without_sending(self):
        def setup(root):
            from test_assistant_attachments import png
            from test_assistant_drawer import FAKE_BACKEND

            (root / 'drawers/assistant/backend.py').write_text(FAKE_BACKEND)
            (root / 'context-helper').write_bytes(LAUNCHER.read_bytes())
            (root / '$(touch nope) notes.md').write_text('Original frozen text ✓')
            (root / 'image #100%.png').write_bytes(png())
            (root / 'Việt\nmore.txt').write_text('More context')
            (root / 'unsupported.bin').write_bytes(b'\x00\xff\x01')
            for index in range(4):
                (root / f'extra-{index}.txt').write_text(f'Extra {index}')
            binary = root / 'bin'
            binary.mkdir()
            notifier = binary / 'notify-send'
            notifier.write_text(
                '#!/usr/bin/env python3\nimport json,os,pathlib,sys\n'
                'p=pathlib.Path(os.environ["XDG_STATE_HOME"]);p.mkdir(exist_ok=True)\n'
                'with (p/"notices.jsonl").open("a") as f:f.write(json.dumps(sys.argv[1:])+"\\n")\n'
            )
            notifier.chmod(0o755)

        # Prefix only the fixture notifier. Real qs IPC connects to the private
        # offscreen shell, using the same config path as the installed helper.
        body = r"""import QtQuick
import Quickshell
import Quickshell.Io
import "ui"
import "drawers"
import "drawers/assistant"
ShellRoot {
 id:root
 property int stage:0
 property int tries:0
 PersistentProperties {id:run;reloadableId:"contextRun";property bool reloaded:false}
 AssistantInbox {id:inbox}
 FloatingWindow {implicitWidth:480;implicitHeight:760;visible:true
  Loader {id:page;width:448;height:728;active:false;sourceComponent:AssistantDrawer{active:true}}
 }
 Process {id:helper
  property var paths:[]
  property int result:-1
  command:["python3",Quickshell.shellPath("context-helper"),...paths]
  environment:({PATH:Quickshell.shellPath("bin")+":"+Quickshell.env("PATH")})
  onExited: (code,status) => {result=code;}
  stdout:StdioCollector{}
  stderr:StdioCollector{}
 }
 Process {id:mutate
  command:["python3","-c","import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('Changed after adding')",Quickshell.shellPath("$(touch nope) notes.md")]
 }
 FileView {id:notices;path:Quickshell.env("XDG_STATE_HOME")+"/notices.jsonl";printErrors:false;blockLoading:true}
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function invoke(names){helper.result=-1;helper.paths=names.map(name=>Quickshell.shellPath(name));helper.running=true;}
 Timer {interval:100;repeat:true;running:true;onTriggered:{try{
  if(++tries>100)throw new Error("timeout "+stage+" "+AssistantService.attachmentError+" "+helper.stderr.text);
  if(stage===0){
   if(run.reloaded){
    check(AssistantService.attachments.length===0&&!AssistantService.checked&&!page.active,"restart retained pending context or started inference");
    console.log("DISPLAY_PASS");Qt.quit();return;
   }
   check(inbox.addFiles("not json").length>0&&inbox.addFiles('{"files":["https://example.invalid/file"]}').length>0,"malformed/remote IPC accepted");
   check(inbox.addFiles('{"files":[]}').length>0&&inbox.addFiles('{"files":[null]}').length>0,"invalid selection accepted");
   AssistantService.draft="Keep this draft";
   invoke(["$(touch nope) notes.md","image #100%.png"]);
  }else if(stage===1){
   if(helper.running||helper.result<0||AssistantService.preparing)return;
   check(helper.result===0,"IPC helper failed: "+helper.stderr.text);
   check(AssistantService.attachments.length===2&&!AssistantService.checked&&!page.active,"closed drawer did not accept files or started Lemonade");
   check(AssistantService.messages.count===0&&AssistantService.draft==="Keep this draft","files submitted or changed draft");
   mutate.running=true;invoke(["image #100%.png","Việt\nmore.txt"]);
  }else if(stage===2){
   if(helper.running||helper.result<0||AssistantService.preparing||mutate.running)return;
   check(helper.result===0&&AssistantService.attachments.length===3,"second selection did not accumulate or deduplicate");
   check(AssistantService.attachments.find(file=>file.name.includes("notes.md")).text==="Original frozen text ✓","file was not snapshotted on add");
   invoke(["unsupported.bin"]);
  }else if(stage===3){
   if(helper.running||helper.result<0||AssistantService.preparing)return;
   check(helper.result===0&&AssistantService.attachments.length===3&&AssistantService.attachmentError.length>0,"unsupported file silently accepted");
   invoke(["extra-0.txt","extra-1.txt","extra-2.txt","extra-3.txt"]);
  }else if(stage===4){
   if(helper.running||helper.result<0||AssistantService.preparing)return;
   check(AssistantService.attachments.length===6&&AssistantService.attachmentError.includes("limit"),"combined selections bypass attachment limit");
   check(AssistantService.messages.count===0&&!AssistantService.checked&&!page.active,"background action opened UI or generated a reply");
   notices.reload();notices.waitForJob();
   const log=notices.text();if(log.trim().split("\n").length<4)return;
   check(log.includes("2 files added")&&log.includes("File added")&&log.includes("unsupported.bin")&&log.includes("limit"),"success/partial/error feedback missing: "+log);
   page.active=true;
  }else if(stage===5){
   if(!page.item||AssistantService.checking)return;
   check(find(page.item,"assistantDraftAttachments").files.length===6,"queued files do not appear when opening drawer");
   check(AssistantService.messages.count===0&&AssistantService.draft==="Keep this draft","opening drawer sent context or lost draft");
   page.active=false;run.reloaded=true;Quickshell.reload(false);return;
  }
  stage++;tries=0;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
}"""

        # The service's detached notifications use its inherited PATH as well.
        def with_path(root):
            setup(root)
            source = root / 'drawers/assistant/AssistantService.qml'
            source.write_text(
                source.read_text().replace(
                    '["notify-send",', '[Quickshell.shellPath("bin/notify-send"),'
                )
            )
            config = root / 'config/quickshell/desktop'
            for path in root.iterdir():
                if path.name not in ('config', 'runtime'):
                    (config / path.name).symlink_to(path)

        support.run_qml(
            self,
            body,
            with_path,
            isolate_bus=True,
            entrypoint='config/quickshell/desktop/shell.qml',
        )


if __name__ == '__main__':
    unittest.main()
