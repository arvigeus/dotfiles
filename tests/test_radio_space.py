"""Radio runs through the retained fullscreen host and real owned worker."""

import unittest
import support
from test_movies_space import setup as movies_setup
from test_radio import STATION, fake_mpv
import shutil


def setup(root):
    movies_setup(root)
    shutil.copytree(support.DESKTOP / 'integrations', root / 'integrations')
    player = fake_mpv(root)
    path = root / 'spaces/radio/backend.py'
    fixture = """    import time
    fixture_station = STATION_LITERAL
    def fixture_api(path, params=None):
        if path == '/json/countries': return [dict(name="Vietnam",stationcount=110)]
        if path == '/json/tags': return [dict(name="jazz",stationcount=110)]
        if path.startswith('/json/url/'):
            time.sleep(.2)
            return dict(url=fixture_station['url'])
        offset=int((params or {}).get('offset',0))
        return [dict(fixture_station,stationuuid="11111111-1111-1111-1111-"+str(i+1).zfill(12),name="Station "+str(i),homepage="https://station"+str(i)+".example.invalid",url="https://stream"+str(i)+".example.invalid/live",url_resolved="https://stream"+str(i)+".example.invalid/live",bitrate=128 if i%2 else 256) for i in range(offset,min(offset+100,110))]
    api.api_get = fixture_api
    shutil.which = lambda name: PLAYER_LITERAL
""".replace('STATION_LITERAL', repr(STATION)).replace(
        'PLAYER_LITERAL', repr(str(player))
    )
    path.write_text(
        path.read_text().replace(
            '    backend = RadioBackend()\n', fixture + '    backend = RadioBackend()\n'
        )
    )


@unittest.skipUnless(support.QS, 'Quickshell is required')
class RadioSpaceTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_toolbar_list_filters_playback_hide_resume_close_and_races(self):
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
 property int ticks:0
 property var retained:null
 property var radioService:null
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const result=find(child,name);if(result)return result;}return null;}
 function click(item){check(!!item,"missing control");input.mouseClick(item,item.width/2,item.height/2);}
 Timer {id:driver;interval:90;repeat:false;running:true;onTriggered:{try{
  if(root.step===0){SpaceState.open("radio",Quickshell.screens[0]);root.step++;return;}
  const page=host.currentPage;
  if(root.step<8&&(!page||!page.initialized||page.loading||page.favoriteSaving||page.commandPending||page.resolving))return;
  if(root.step===1){
   check(page.rows.length===100,"station catalogue missing: "+page.error);
   const toolbar=find(host.contentItem,"radioToolbar"),hide=find(host.contentItem,"hideSpace");
   check(toolbar.parent===page.toolbarTarget,"toolbar outside shared header");
   check(find(toolbar,"radioStationHeading").parent===toolbar&&find(toolbar,"radioStationCount").text==="100","station heading/count not in top toolbar");
   check(Math.abs(toolbar.mapToItem(host.contentItem,0,0).y+toolbar.height/2-hide.mapToItem(host.contentItem,0,0).y-hide.height/2)<1,"controls not at top beside X");
   check(find(host.contentItem,"radioBackground").color.toString()==="#000000","background is not black");
   check(!find(host.contentItem,"radioDiscover")&&!find(host.contentItem,"radioFavorites"),"browse tabs still visible");
   const list=find(page,"radioStationList");check(list.height>500&&list.count===100,"scrolling list missing");
   const variant=Object.assign({},page.results[0],{stationuuid:"22222222-2222-2222-2222-222222222222",bitrate:64});
   page.results=page.results.concat([variant]);page.displayRows(true);
   check(page.rows.length===100&&page.rows[0].qualityOptions.length===2,"stream variants were not grouped");
   page.chooseQuality(page.rows[0],1);
   check(page.qualities[page.rows[0].groupKey]===variant.stationuuid,"stream quality selection failed");
   Theme.setMode("light");check(find(page,"radioNowPlaying").color.toString()==="#ffffff","light theme broke immersive text");
   page.browse(true);root.step++;return;
  }
  if(root.step===2){
   check(page.rows.length===110&&page.nextOffset<0,"pagination failed");
   page.filtersOpen=true;input.wait(50);click(find(host.contentItem,"radioCountry"));input.wait(40);
   host.escapeHandler();check(host.opened&&page.filtersOpen,"country menu Escape hid Radio");
   host.escapeHandler();check(host.opened&&!page.filtersOpen,"filter Escape hid Radio");
   page.searchOpen=true;find(host.contentItem,"radioSearch").text="Station";
   host.escapeHandler();check(host.opened&&page.searchOpen&&find(host.contentItem,"radioSearch").text==="","search clear priority wrong");
   host.escapeHandler();check(host.opened&&!page.searchOpen,"search close priority wrong");
   page.toggleFavorite(page.rows[1]);root.step++;return;
  }
  if(root.step===3){
   check(page.favorites.length===1,"favorite not saved");
   check(page.rows.length>1&&page.favorite(page.rows[0].groupKey)&&page.rows[0].name==="Station 1","favorite was not pinned above discovery");
   page.play(page.rows[0]);root.step++;return;
  }
  if(root.step===4){
   page.refreshStatus();root.step++;return;
  }
  if(root.step===5){
   if(page.statusPending)return;
   check(page.playback.playing&&page.playback.title==="Fixture artist - Fixture song","metadata missing: "+page.playbackError);
   page.playerCommand("pause");root.step++;return;
  }
  if(root.step===6){
   check(page.playback.paused,"pause failed");page.playerCommand("pause");root.step++;return;
  }
  if(root.step===7){
   check(!page.playback.paused,"resume failed");root.retained=page;
   host.dismiss();check(!page.active&&SpaceState.runningIds.includes("radio"),"hide destroyed Radio");
   check(!Array.from(page.data).find(item=>item.objectName==="radioMetadataTimer").running&&!find(host.contentItem,"radioLoadingIndicator").running,"hidden visual work continued");
   root.step++;return;
  }
  if(root.step===8){
   if(++root.ticks<5)return;
   check(root.retained.playback.playing,"hide stopped playback");
   SpaceState.open("books",Quickshell.screens[0]);root.step++;return;
  }
  if(root.step===9){
   if(!host.currentPage||SpaceState.currentId!=="books")return;
   check(root.retained.playback.playing&&!root.retained.active,"navigation stopped Radio");
   SpaceState.open("radio",Quickshell.screens[0]);check(host.currentPage===root.retained,"restore recreated Radio");
   check(host.currentPage.favorite(host.currentPage.rows[0].groupKey),"favorite pin lost on restore");
   host.currentPage.play(host.currentPage.rows[0]);host.currentPage.playerCommand("stop");root.ticks=0;root.step++;return;
  }
  if(root.step===10){
   if(++root.ticks<8)return;
   check(!host.currentPage.playback.playing&&!host.currentPage.commandPending,"late resolver restarted stopped playback");
   SpaceState.close("radio");input.wait(60);
   check(!find(host.contentItem,"radioToolbar")&&!SpaceState.runningIds.includes("radio"),"close left Radio resources");
   check(SpaceState.runningIds.includes("books"),"close disturbed Books");
   SpaceState.open("radio",Quickshell.screens[0]);root.step++;return;
  }
  if(root.step===11){
   if(!host.currentPage||!host.currentPage.initialized||host.currentPage.loading)return;
   check(host.currentPage!==root.retained&&host.currentPage.favorites.length===1,"fresh instance did not restore favorites");
   check(Object.keys(host.currentPage.qualities).length===1,"fresh instance lost stream quality preferences");
   click(find(host.contentItem,"hideSpace"));check(!host.opened&&SpaceState.runningIds.includes("radio"),"X did not hide");
   SpaceState.open("radio",Quickshell.screens[0]);host.escapeHandler();check(!host.opened,"Escape did not hide Radio");
   SpaceState.close("radio");SpaceState.close("books");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",error.message+" "+error.stack);Qt.quit();}finally{driver.restart();}}}
 Timer {interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout at "+root.step);Qt.quit();}}
}""",
            setup=setup,
        )

    def test_cloud_sync_preserves_hidden_favorites_and_keeps_playback_worker_responsive(
        self,
    ):
        def prepare(root):
            setup(root)
            backend = root / 'spaces/radio/backend.py'
            backend.write_text(
                backend.read_text().replace(
                    'syncConfigured=configured()', 'syncConfigured=True'
                )
            )
            favorite_worker = root / 'spaces/radio/favorites.py'
            fixture = """    import time
    class FixtureCloud:
        account_id = "fixture-account"
        def stations(self):
            time.sleep(.5)
            return [dict(id="1", name="Cloud station", streamUrl="https://cloud-station.example/live")]
        def request(self, *args, **kwargs):
            raise AssertionError("Import must not write to the cloud")
    store = FavoritesStore(client_factory=FixtureCloud)
"""
            favorite_worker.write_text(
                favorite_worker.read_text().replace(
                    '    store = FavoritesStore()\n', fixture
                )
            )

        self.run_qml(
            """import QtQuick
import Quickshell
import "ui"
ShellRoot {
 id:root
 InteractionState {id:interactions}
 SpaceHost {id:host;interactionState:interactions}
 property int step:0
 property bool replied:false
 property var retained:null
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer {interval:60;running:true;repeat:true;onTriggered:{try{
  if(root.step===0){SpaceState.open("radio",Quickshell.screens[0]);root.step++;return;}
  if(root.step===1){
   const page=host.currentPage;if(!page?.syncing)return;
   root.retained=page;
   Array.from(page.data).find(item=>item.objectName==="radioService").request("status",{},()=>{root.replied=true;});
   root.step++;return;
  }
  if(root.step===2){
   if(!root.replied)return;
   check(root.retained.syncing,"cloud request blocked the playback worker");
   check(!find(root.retained,"radioFavorite:0")?.enabled,"favorite changes can race an active sync");
   host.dismiss();
   check(!Array.from(root.retained.data).find(item=>item.objectName==="radioSyncTimer").running,"hidden cloud polling continued");
   root.step++;return;
  }
  if(root.step===3){
   if(root.retained.syncing)return;
   check(!root.retained.syncError&&root.retained.favorites.length===1,"hidden cloud import failed: "+root.retained.syncError);
   SpaceState.open("radio",Quickshell.screens[0]);root.step++;return;
  }
  if(root.step===4){
   const page=host.currentPage;if(page.syncing)return;
   check(page===root.retained&&page.favorites[0].name==="Cloud station","restore lost synced favorite");
   page.results=[Object.assign({},page.favorites[0],{stationuuid:"33333333-3333-3333-3333-333333333333",country:"Vietnam",countrycode:"VN",source:""})];
   page.displayRows(false);
   check(page.rows.length===1,"cloud favorite was duplicated by the discovery catalogue");
   page.hasFilters;page.searchOpen=true;find(host.contentItem,"radioSearch").text="cloud";
   page.displayRows(false);
   check(page.rows.length===1&&page.favorite(page.rows[0].groupKey),"catalogue station did not recognize its cloud favorite");
   SpaceState.close("radio");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",error.message+" "+error.stack);Qt.quit();}}}
 Timer {interval:6000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout at "+root.step);Qt.quit();}}
}""",
            setup=prepare,
        )
