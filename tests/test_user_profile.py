"""Read-only account lookup and the Spaces profile header/editor action."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_display_drawer as fixtures

SOURCE = fixtures.DESKTOP / 'drawers/spaces/profile.py'
SPEC = importlib.util.spec_from_file_location('desktop_user_profile', SOURCE)
profile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profile)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.account = SimpleNamespace(pw_uid=1234, pw_name='alice', pw_dir=str(self.home),
                                       pw_gecos='Alice Local,Room,Phone')
        lookup = patch.object(profile.pwd, 'getpwuid', return_value=self.account)
        lookup.start(); self.addCleanup(lookup.stop)

    def test_account_service_name_photo_and_photo_refresh(self):
        photo = self.home / 'portrait.svg'; photo.write_text('<svg/>')
        with patch.object(profile, 'account_properties', return_value=dict(RealName='Alice Example', IconFile=str(photo))):
            first = profile.profile()
            self.assertEqual(first['name'], 'Alice Example')
            self.assertEqual(first['username'], 'alice')
            self.assertTrue(first['avatar'].startswith(photo.as_uri()+'?v='))
            stamp = photo.stat().st_mtime_ns+1000000000
            os.utime(photo, ns=(stamp, stamp))
            self.assertNotEqual(first['avatar'], profile.profile()['avatar'])

    def test_unset_photo_and_name_fallback_without_inventing_details(self):
        with patch.object(profile, 'account_properties', return_value={}):
            self.assertEqual(profile.profile()['name'], 'Alice Local')
            self.account.pw_gecos = ''
            self.assertEqual(profile.profile(), dict(name='', username='alice', avatar=''))
            face = self.home / '.face.icon'; face.write_text('<svg/>')
            self.assertTrue(profile.profile()['avatar'].startswith(face.as_uri()))

    def test_missing_account_photo_falls_back_to_home_face(self):
        photo = self.home / '.face'; photo.write_text('<svg/>')
        with patch.object(profile, 'account_properties', return_value=dict(IconFile='/missing/profile-picture')):
            self.assertTrue(profile.profile()['avatar'].startswith(photo.as_uri()))


@unittest.skipUnless(fixtures.QS, 'Quickshell is required')
class ProfileButtonTests(unittest.TestCase):
    run_qml = fixtures.DisplayQmlTests.run_qml

    def test_header_photo_hint_fallback_and_editor_launch(self):
        def setup(root):
            data = dict(name='Alice Example', username='alice',
                        avatar=(root / 'icons/user-round.svg').as_uri()+'?v=1')
            (root / 'drawers/spaces/profile.py').write_text('import json\nprint(json.dumps('+repr(data)+'))\n')
        self.run_qml('''import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtTest
import Quickshell
import "ui"
import "drawers"
ShellRoot {
 id:root
 property int closes:0
 property var launches:[]
 QtObject{id:mock;property var state:({capabilities:{},scheduledShutdown:""});property bool busy:false;property string error:"";function refresh(){}}
 FloatingWindow {
  id:window;implicitWidth:480;implicitHeight:120;visible:true;color:Theme.background
  RowLayout {
   id:header;anchors.fill:parent;anchors.margins:16;spacing:12
   ShellText {Layout.fillWidth:true;text:"Spaces"}
   Loader{id:headerAction;sourceComponent:drawer.headerActions}
   Button{id:close;text:"X";Layout.preferredWidth:34;Layout.preferredHeight:34}
  }
  SpacesDrawer{id:drawer;visible:false;active:true;service:mock;launch:argv=>root.launches.push(argv);onCloseRequested:root.closes++}
 }
 TestCase{id:input;when:false;parent:window.contentItem}
 function check(value,message){if(!value)throw new Error(message);}
 Timer{interval:250;running:true;onTriggered:{try{
  const button=headerAction.item;
  check(button&&button.enabled,"profile header missing");
  check(button.profileHint==="Alice Example\\n@alice","profile hint missing name or username: "+button.profileHint);
  check(button.hasAvatar,"profile photo did not load");
  check(button.mapToItem(header,0,0).x+button.width<=close.x,"profile is not before close");
  button.profile={name:"",username:"alice",avatar:""};
  check(button.profileHint==="@alice","missing full name produced duplicate or empty text");
  input.wait(50);check(!button.hasAvatar,"cleared photo retained image");
  input.mouseClick(button,button.width/2,button.height/2);
  check(root.closes===1&&root.launches.length===1&&JSON.stringify(root.launches[0])==='["/usr/local/bin/mugshot"]',"profile did not dismiss and launch editor");
  drawer.active=false;check(!button.enabled,"dismissed header still accepts clicks");
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:4000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}''', setup)


if __name__ == '__main__':
    unittest.main()
