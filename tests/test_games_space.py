"""Games uses production workers and the retained fullscreen host with isolated providers."""

import sys
import unittest

import support
from test_movies_space import setup as movies_setup

sys.path.insert(0, str(support.DESKTOP))
from spaces.games.backend import GamesBackend


def setup(root):
    movies_setup(root)
    (root / 'spaces/movies/Browser.qml').write_text("""pragma Singleton
import QtQuick
QtObject {
 property string lastUrl: ""
 function open(url,moduleId,command,host){lastUrl=String(url);}
}
""")
    image = root / 'game-art.svg'
    image.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#294963"/></svg>'
    )
    (root / 'spaces/movies/torrent_backend.py').write_text(
        'import json,sys\nfor line in sys.stdin:\n'
        ' r=json.loads(line);result=dict(connected=False,canStart=False,error="Fixture offline") if r["op"]=="probe" else [];'
        'print(json.dumps(dict(id=r["id"],result=result)),flush=True)\n'
    )
    backend = GamesBackend(
        root / 'config/quickshell/desktop/spaces/games/games.json',
        root / 'data/quickshell/desktop/spaces/games',
    )
    game = backend._save_game(
        'fixture',
        dict(
            catalogProvider='fixture',
            catalogProviderId='fixture',
            title='Fixture game',
            summary='A saved game',
            cover=None,
            rating=4.3,
            ratingCount=17,
            officialWebsite='https://example.com/game',
            artwork=[],
            screenshots=[dict(url=image.as_uri(), thumbnail=image.as_uri())],
        ),
    )
    backend.set_favorite(dict(gameId=game['id'], favorite=True))
    path = root / 'spaces/games/backend.py'
    source = path.read_text()
    state = dict(
        steam=dict(items=[], ownedIds=[], available=False, ownershipKnown=False),
        epic=dict(items=[], ownedIds=[], available=False, ownershipKnown=False),
        gog=dict(items=[], ownedIds=[], available=True, ownershipKnown=False),
    )
    fixture = (
        '\n'.join(
            [
                '    GamesBackend.libraries = lambda self, force=False: ' + repr(state),
                '    GamesBackend.library_games = lambda self, request: self._favorite_games("", 0)',
                '    GamesBackend.presentation = lambda self, request: {}',
                '    GamesBackend.protondb = lambda self, request: dict(tier="gold",label="Gold",total=42,url="https://www.protondb.com/app/620")',
                '    GamesBackend.howlongtobeat = lambda self, request: dict(main=10, extras=15, complete=20, override="", url="https://howlongtobeat.com/game/1")',
                '    GamesBackend.action = lambda self, request: dict(started=True, handoff=True, message="Fixture launcher handoff")',
            ]
        )
        + '\n'
    )
    path.write_text(
        source.replace(
            '    backend = GamesBackend()\n', fixture + '    backend = GamesBackend()\n'
        )
    )


@unittest.skipUnless(support.QS, 'Quickshell is required')
class GamesSpaceTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_badges_store_actions_tooltip_and_image_strip(self):
        self.run_qml(
            """import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "ui"
import "spaces/movies"
ShellRoot {
 id:root
 InteractionState {id:interactions}
 SpaceHost {id:host;interactionState:interactions}
 TestCase {id:input;when:false;parent:host.contentItem}
 property int step:0
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function click(item){input.mouseClick(item,item.width/2,item.height/2);}
 Timer {id:driver;interval:80;running:true;repeat:false;onTriggered:{try{
  if(root.step===0){SpaceState.open("games",Quickshell.screens[0]);root.step++;return;}
  const page=host.currentPage;if(!page||page.busy)return;
  const beat=find(page,"hltbButton");const proton=find(page,"protonDbButton");
  const tooltip=beat.data.find(item=>item.objectName==="hltbTooltip");
  if(root.step===1){
   if(beat.x<=proton.x||find(page,"gameStore:gog").x<=find(page,"gameStore:epic").x)return;
   check(beat.text==="10 h"&&beat.iconName==="clock","HLTB main time or clock missing");
   check(Math.abs(beat.y-proton.y)<1&&Math.abs(beat.x-proton.x-proton.width-12)<1,"clock not next to ProtonDB: "+[proton.x,proton.y,proton.width,beat.x,beat.y]);
   check(find(page,"protonDbArtwork").source.toString().endsWith("protondb-gold.svg"),"wrong Proton badge");
   check(find(page,"protonDbArtwork").status===Image.Ready,"Proton badge did not load");
   check(find(page,"igdbRating").visible&&find(page,"igdbArtwork").status===Image.Ready,"IGDB badge missing");
   check(tooltip&&tooltip.text.includes("Main story: 10 h")&&tooltip.text.includes("Main + extras: 15 h")&&tooltip.text.includes("Completionist: 20 h"),"HLTB tooltip lacks times");
   input.mouseMove(host.contentItem,0,0);input.wait(20);
   input.mouseMove(beat,beat.width/2,beat.height/2);root.step++;return;
  }
  if(root.step===2){
   if(!tooltip.visible)return;
   click(beat);check(Browser.lastUrl==="https://howlongtobeat.com/game/1","clock and time do not open HLTB");
   click(proton);check(Browser.lastUrl==="https://www.protondb.com/app/620","Proton badge does not open its page");
   check(!find(page,"hltbMatchButton"),"redundant HLTB matching action remains");
   const website=find(page,"gameWebsiteButton");
   check(website.visible&&website.iconName==="link"&&website.parent===beat.parent,"website does not use the facts link button");
   click(website);check(Browser.lastUrl==="https://example.com/game","website link does not open official website");
   const savedTimes=page.beatTimes;page.beatTimes={};input.wait(30);
   check(beat.text==="—"&&tooltip.text.includes("Click to enter"),"unmatched HLTB hint missing");
   click(beat);input.wait(30);
   const matching=Array.from(page.data).find(item=>item.objectName==="gameMatchDialog");
   check(matching.visible&&page.editingStore==="hltb","unmatched clock does not open manual matching");
   const matchInput=find(matching.contentItem,"gameMatchInput");
   matchInput.forceActiveFocus();for(const character of "https://howlongtobeat.com/game/1")input.keyClick(character);
   check(matchInput.text==="https://howlongtobeat.com/game/1","manual HLTB match cannot be typed");
   host.escapeHandler();check(host.opened&&!matching.visible,"HLTB matching Escape hid Games");page.beatTimes=savedTimes;
   const steam=find(page,"gameStore:steam");const epic=find(page,"gameStore:epic");const gog=find(page,"gameStore:gog");
   check(steam.y===epic.y&&epic.y===gog.y&&epic.x>steam.x&&gog.x>epic.x,"store buttons are not side by side");
   check(steam.brandColor.toString()==="#1a9fff"&&epic.brandColor.toString()==="#111111"&&gog.brandColor.toString()==="#86328a","store branding colors missing");
   check(find(page,"gameStoreArtwork:steam").status===Image.Ready&&find(page,"gameStoreArtwork:epic").status===Image.Ready&&find(page,"gameStoreArtwork:gog").status===Image.Ready,"store logos did not load");
   check(find(page,"gameStoreAction:steam").text==="Link","unlinked action wrong");
   const favorite=find(page,"gameFavorite");const refresh=find(page,"gameRefresh");
   check(favorite.parent===gog.parent&&favorite.y===gog.y&&favorite.x>gog.x,"favorite is not beside store buttons");
   check(refresh.parent===epic.parent&&refresh.y===epic.y&&refresh.x>favorite.x,"reload is not beside favorite");
   click(find(page,"gameStoreAction:steam"));input.wait(30);check(page.editingStore==="steam","Link does not edit Steam match");host.escapeHandler();
   click(find(page,"gameStoreAction:gog"));input.wait(30);check(page.editingStore==="gog","Link does not edit GOG match");host.escapeHandler();
   click(find(page,"gameStoreOptions:gog"));input.wait(30);
   check(find(gog.popup.contentItem,"gameStoreManage:gog").visible,"GOG launcher management missing");
   check(!find(gog.popup.contentItem,"gameStoreUninstall:gog").visible,"GOG offers unsupported direct uninstall");host.escapeHandler();
   const stores=page.availability.stores.map(store=>Object.assign({},store,{primaryAction:{id:store.store+":fixture",type:store.store==="steam"?"play":"install",label:store.store==="steam"?"Play":"Install",enabled:true},actions:store.store==="steam"?[{id:"steam:uninstall:620",type:"uninstall",store:"steam"}]:store.actions}));
   page.availability={stores:stores};input.wait(50);
   check(find(page,"gameStoreAction:steam").text==="Play"&&find(page,"gameStoreAction:epic").text==="Install"&&find(page,"gameStoreAction:gog").text==="Install","store action labels did not update");
   const currentSteam=find(page,"gameStore:steam");click(find(page,"gameStoreOptions:steam"));input.wait(30);
   check(currentSteam.popup.visible,"store menu did not open");host.escapeHandler();check(!currentSteam.popup.visible&&host.opened,"store menu Escape hid Games");
   click(find(page,"gameStoreOptions:steam"));input.wait(30);
   click(find(currentSteam.popup.contentItem,"gameStoreUninstall:steam"));input.wait(50);
   const confirmation=Array.from(page.data).find(item=>item.objectName==="gameUninstallConfirmation");
   check(confirmation.visible,"store menu skipped uninstall confirmation");
   host.escapeHandler();check(host.opened&&!confirmation.visible,"uninstall confirmation Escape hid Games");
   const strip=find(page,"gameImageStrip");check(strip.visible&&strip.count===1&&strip.height===116,"movie-style image strip missing");
   check(strip.parent.objectName==="gameOverviewContent"&&strip.y<200,"screenshots are not directly below overview content");
   check(strip.mapToItem(page,0,strip.height).y<=find(page,"gamesRail").y,"image strip overlaps game posters");
   strip.currentIndex=0;strip.forceActiveFocus();input.keyClick(Qt.Key_Return);input.wait(50);
   const gallery=Array.from(page.data).find(item=>item.objectName==="gamesGallery");
   check(gallery.visible&&gallery.currentIndex===0&&gallery.images.length===1,"strip keyboard activation did not open gallery");
   host.escapeHandler();check(host.opened&&!gallery.visible,"gallery Escape hid Games");
   const title=page.selected.id;const pane=find(page,"gameDetailPane");
   click(find(page,"gameFindTab"));input.wait(100);
   check(page.tab==="torrent"&&find(page,"gameFindContent").visible&&!find(page,"gameOverview").visible,"Find is not an inline tab");
   check(pane.visible&&find(page,"gameStore:steam").visible&&beat.visible&&find(page,"gamesRail").visible&&page.selected.id===title,"Find replaced the game detail layout");
   click(find(page,"gameOverviewTab"));input.wait(50);
   check(page.tab==="overview"&&strip.visible&&!find(page,"gameFindContent").visible,"Overview did not restore screenshots");
   click(find(page,"gameStoreOptions:gog"));input.wait(30);
   click(find(find(page,"gameStore:gog").popup.contentItem,"gameStoreManage:gog"));
   root.step++;return;
  }
  if(root.step===3){
   check(!host.opened&&SpaceState.runningIds.includes("games"),"Heroic handoff did not hide and retain Games");
   SpaceState.close("games");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",error);Qt.quit();}finally{driver.restart();}}}
 Timer {interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""",
            setup=setup,
        )

    def test_game_page_hide_restore_close_and_independent_movies(self):
        self.run_qml(
            """import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "ui"
import "drawers"
ShellRoot {
 id:root
 InteractionState {id:interactions}
 SpaceHost {id:host;interactionState:interactions}
 TestCase {id:input;when:false;parent:host.contentItem}
 QtObject {id:session
  property var state:({capabilities:{},scheduledShutdown:""})
  property bool busy:false
  property string error:""
  property bool sleepPaused:false
  property bool lockingPaused:false
  property bool pausesAvailable:false
  function refresh(){}
 }
 FloatingWindow {id:drawerWindow;implicitWidth:480;implicitHeight:900;visible:false
  SpacesDrawer {id:drawer;anchors.fill:parent;active:drawerWindow.visible;screen:Quickshell.screens[0];service:session}
 }
 property int step:0
 property var retained:null
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer {id:driver;interval:80;running:true;repeat:false;onTriggered:{try{
  if(root.step===0){check(SpaceState.open("games",Quickshell.screens[0]),"cannot open Games");root.step++;return;}
  const page=host.currentPage;if(!page||page.busy)return;
  if(root.step===1){
   check(page.titles.length===1&&page.selected.title==="Fixture game","library missing");
   check(page.beatTimes.main===10,"beat times missing");
   check(page.backdropTarget.width===host.width,"backdrop inset");
   check(find(host.contentItem,"gamesToolbar").visible,"toolbar missing");
   check(!page.gridMode,"default layout differs from Movies");
   root.retained=page;page.gridMode=true;
   input.mouseClick(find(host.contentItem,"catalogueLayoutToggle"));
   input.mouseClick(find(host.contentItem,"catalogueLayoutToggle"));
   page.searchOpen=true;host.escapeHandler();check(host.opened&&!page.searchOpen,"search Escape hid Games");
   page.filtersOpen=true;const picker=find(page,"genrePicker");picker.popup.open();input.wait(30);
   host.escapeHandler();check(host.opened&&!picker.popup.visible&&page.filtersOpen,"picker Escape hid Games");
   host.escapeHandler();check(host.opened&&!page.filtersOpen,"filters Escape hid Games");
   input.mouseClick(find(page,"gameFindTab"));input.wait(100);host.escapeHandler();
   check(!host.opened&&page.tab==="torrent","Find tab did not retain selection when hiding");
   SpaceState.open("games",Quickshell.screens[0]);input.wait(30);
   check(host.currentPage===page&&page.tab==="torrent","Find tab lost on restore");
   page.editMatch("hltb","");input.wait(30);host.escapeHandler();
   check(host.opened,"match Escape hid Games");
   const gallery=Array.from(page.data).find(item=>item.objectName==="gamesGallery");gallery.show([],0,"Fixture");input.wait(30);
   input.mouseClick(find(host.contentItem,"hideSpace"));
   check(!host.opened&&!gallery.visible&&SpaceState.runningIds.includes("games"),"hide destroyed Games or gallery blocked X");
   check(!find(host.contentItem,"gamesToolbar").visible,"hidden toolbar active");
   SpaceState.open("movies",Quickshell.screens[0]);root.step++;return;
  }
  if(root.step===2){check(page.selected.title==="Fixture movie","Games disturbed Movies");SpaceState.open("games",Quickshell.screens[0]);root.step++;return;}
  if(root.step===3){
   check(page===root.retained&&page.gridMode&&page.tab==="torrent","restore lost instance, layout or Find tab");
   host.escapeHandler();check(!host.opened,"Escape did not hide");
   drawerWindow.visible=true;input.wait(30);input.mouseClick(find(drawer,"closeSpace:games"));
   check(!host.opened&&!SpaceState.runningIds.includes("games")&&SpaceState.runningIds.includes("movies"),"drawer close affected Movies");
   drawerWindow.visible=false;SpaceState.open("games",Quickshell.screens[0]);root.step++;return;
  }
  if(root.step===4){
   check(page!==root.retained&&page.selected.favorite&&page.gridMode&&page.tab==="overview","fresh instance lost saved state or default tab");
   SpaceState.close("games");SpaceState.close("movies");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",error);Qt.quit();}finally{driver.restart();}}}
 Timer {interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""",
            setup=setup,
        )
