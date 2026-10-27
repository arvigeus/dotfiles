"""Television uses the shared host, a list without a playback heading, and native mpv handoff."""

import unittest
import support
from test_movies_space import setup as movies_setup
from test_radio import fake_mpv
from test_television import datasets


def setup(root):
    movies_setup(root)
    player = fake_mpv(root)
    path = root / 'spaces/television/backend.py'
    fixture = """    import time
    import spaces.television.player as player_module
    player_module.shutil.which = lambda name: PLAYER
    fixture_data = FIXTURE
    def fetch(name):
        time.sleep(.1)
        return fixture_data[name]
    backend = TelevisionBackend(fetch=fetch)
""".replace('PLAYER', repr(str(player))).replace('FIXTURE', repr(datasets()))
    path.write_text(
        path.read_text().replace('    backend = TelevisionBackend()\n', fixture)
    )


@unittest.skipUnless(support.QS, 'Quickshell is required')
class TelevisionSpaceTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_list_toolbar_filters_favorites_player_handoff_and_retained_lifecycle(self):
        self.run_qml(
            """import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "ui"
ShellRoot {
 id:root
 InteractionState {id:interactions}
 SpaceHost {id:host;interactionState:interactions}
 TestCase {id:input;when:false;parent:host.contentItem}
 property int step:0
 property var retained:null
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function click(item){check(!!item,"control missing");input.mouseClick(item,item.width/2,item.height/2);}
 Timer {id:driver;interval:90;repeat:false;running:true;onTriggered:{try{
  if(root.step===0){check(SpaceState.open("television",Quickshell.screens[0]),"Space missing");root.step++;return;}
  const page=host.currentPage;
  if(root.step<5&&(!page||!page.initialized||page.loading||page.refreshing||page.saving||page.commandPending))return;
  if(root.step===1){
   check(page.total===110&&page.channels.length===100,"catalogue failed: "+page.error);
   check(find(host.contentItem,"televisionBackground").color.toString()==="#000000","background is not black");
   const toolbar=find(host.contentItem,"televisionToolbar"),hide=find(host.contentItem,"hideSpace");
   check(toolbar.parent===page.toolbarTarget&&Math.abs(toolbar.mapToItem(host.contentItem,0,0).y+toolbar.height/2-hide.mapToItem(host.contentItem,0,0).y-hide.height/2)<1,"toolbar not in top row");
   check(find(toolbar,"televisionChannelHeading").parent===toolbar&&find(toolbar,"televisionChannelCount").text==="110","channel heading/count not in top toolbar");
   check(!find(page,"radioNowPlaying")&&!find(page,"televisionNowPlaying"),"Radio playback heading carried over");
   const list=find(page,"televisionChannelList");check(list.height>650&&list.count===100,"list did not use space freed by heading");
   const first=find(page,"televisionStream:0"),second=find(page,"televisionStream:1");
   check(Math.abs(first.mapToItem(page,0,0).x-second.mapToItem(page,0,0).x)<1,"missing website shifts stream selector");
   check(!find(host.contentItem,"televisionDiscover")&&!find(host.contentItem,"televisionFavorites"),"browse tabs still visible");
   Theme.setMode("light");input.wait(30);check(list.currentItem.children.length>0,"light theme broke channel list");
   page.browse(true);root.step++;return;
  }
  if(root.step===2){
   check(page.channels.length===110&&page.nextOffset<0,"paging failed");
   page.filtersOpen=true;input.wait(40);click(find(host.contentItem,"televisionCountry"));input.wait(40);
   host.escapeHandler();check(host.opened&&page.filtersOpen,"menu Escape hid Television");
   host.escapeHandler();check(host.opened&&!page.filtersOpen,"filter Escape hid Television");
   page.searchOpen=true;find(host.contentItem,"televisionSearch").text="test";
   host.escapeHandler();check(page.searchOpen&&find(host.contentItem,"televisionSearch").text==="","search clear priority wrong");
   host.escapeHandler();check(!page.searchOpen&&host.opened,"search close priority wrong");
   page.toggleFavorite(page.channels[0]);root.step++;return;
  }
  if(root.step===3){
   check(page.favorites.length===1,"favorite was not saved");
   check(page.channels.length===100&&page.isFavorite(page.channels[0]),"favorite was not pinned above discovery");root.step++;return;
  }
  if(root.step===4){
   check(page.channels[0].streams.length===2,"favorite lost stream variants");
   page.chooseStream(page.channels[0],1);root.retained=page;page.play(page.channels[0]);root.step++;return;
  }
  if(root.step===5){
   if(root.retained.commandPending)return;
   check(!host.opened&&root.retained.playback.playing&&SpaceState.runningIds.includes("television"),"mpv handoff did not hide and retain Television");
   check(!Array.from(root.retained.data).find(item=>item.objectName==="televisionStatusTimer").running,"hidden polling continued");
   check(!find(host.contentItem,"televisionLoadingIndicator").running,"hidden spinner continued");
   SpaceState.open("television",Quickshell.screens[0]);root.step++;return;
  }
  if(root.step===6){
   if(root.retained.statusPending)return;
   check(host.currentPage===root.retained&&host.currentPage.isFavorite(host.currentPage.channels[0]),"restore lost browse state");
   host.currentPage.playerCommand("pause");root.step++;return;
  }
  if(root.step===7){
   if(root.retained.commandPending)return;
   check(root.retained.playback.paused,"player pause failed");
   root.retained.playerCommand("stop");root.step++;return;
  }
  if(root.step===8){
   if(root.retained.commandPending)return;
   check(!root.retained.playback.playing,"stop failed");
   SpaceState.open("movies",Quickshell.screens[0]);root.step++;return;
  }
  if(root.step===9){
   if(!host.currentPage||SpaceState.currentId!=="movies")return;
   const movies=host.currentPage;SpaceState.close("television");input.wait(40);
   check(host.opened&&host.currentPage===movies&&!find(host.contentItem,"televisionToolbar"),"Television close disturbed Movies or retained controls");
   SpaceState.open("television",Quickshell.screens[0]);root.step++;return;
  }
  if(root.step===10){
   const fresh=host.currentPage;if(!fresh||!fresh.initialized||fresh.loading||fresh.refreshing)return;
   check(fresh!==root.retained&&fresh.favorites.length===1&&Object.keys(fresh.streamChoices).length===1,"fresh instance failed private restore");
   click(find(host.contentItem,"hideSpace"));check(!host.opened&&SpaceState.runningIds.includes("television"),"X did not hide");
   SpaceState.open("television",Quickshell.screens[0]);host.escapeHandler();check(!host.opened,"Escape did not hide Television");
   SpaceState.close("television");SpaceState.close("movies");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",error.message+" "+error.stack);Qt.quit();}finally{driver.restart();}}}
 Timer {interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout at "+root.step);Qt.quit();}}
}""",
            setup=setup,
        )
