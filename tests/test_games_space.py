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
                '    GamesBackend.libraries = lambda self, *args, **kwargs: '
                + repr(state),
                '    GamesBackend.library_games = lambda self, request: self._favorite_games("", 0)',
                '    GamesBackend.presentation = lambda self, request: {}',
                '    GamesBackend.protondb = lambda self, request: dict(tier="gold",label="Gold",total=42,url="https://www.protondb.com/app/620")',
                '    GamesBackend.howlongtobeat = lambda self, request: dict(main=10, extras=15, complete=20, override="", url="https://howlongtobeat.com/game/1")',
                '    GamesBackend.action = lambda self, request: dict(started=True, handoff=True, message="Fixture launcher handoff")',
                # Never read the host's Steam client or contact a storefront.
                '    GamesBackend._steam_roots = lambda self: []',
                '    def fixture_offline(self, *args, **kwargs):',
                "        raise GamesError('Fixture offline')",
                '    GamesBackend._http_json = fixture_offline',
            ]
        )
        + '\n'
    )
    path.write_text(
        source.replace(
            '    backend = GamesBackend()\n', fixture + '    backend = GamesBackend()\n'
        )
    )


def setup_install(root):
    setup(root)
    launcher = root / 'legendary-fixture'
    launcher.write_text(
        f'#!{sys.executable}\nimport time\n'
        'time.sleep(0.5)\n'
        'print("= Progress: 25.00% (1/4), Running for 00:00:01, ETA: 00:00:03", flush=True)\n'
        'print("+ Download\\t- 8.50 MiB/s (raw)", flush=True)\n'
        'time.sleep(3)\n'
    )
    launcher.chmod(0o700)
    path = root / 'spaces/games/backend.py'
    path.write_text(
        path.read_text().replace(
            '    backend = GamesBackend()\n',
            f"""
    def fixture_availability(self, request):
        completed = any(job['state'] == 'completed' for job in self.install_jobs({{}}))
        kind = 'play' if completed else 'install'
        return dict(stores=[dict(store='epic', label='Epic', externalId='Fixture',
            primaryAction=dict(id='epic:' + kind + ':Fixture', type=kind, store='epic',
                               label=kind.title(), enabled=True), actions=[])])
    GamesBackend.availability = fixture_availability
    GamesBackend._which = lambda self, name: None
    GamesBackend.action = lambda self, request: self._install_epic(self._catalog_id(request['gameId'])[1], {str(launcher)!r}, 'Fixture')
    backend = GamesBackend()
""",
        )
    )


def setup_content(root):
    setup(root)
    worker = GamesBackend(
        root / 'config/quickshell/desktop/spaces/games/games.json',
        root / 'data/quickshell/desktop/spaces/games',
    )
    for identifier, title in [
        ('456', 'Explicit game'),
        ('457', 'Ordinary game'),
        ('458', 'Unchecked game'),
        ('459', 'Untagged game'),
    ]:
        game = worker._save_game(
            'content-' + identifier,
            dict(
                catalogProvider='fixture',
                catalogProviderId='content-' + identifier,
                title=title,
                storeReferences=[dict(store='gog', externalId=identifier)],
                cover=dict(url=(root / 'game-art.svg').as_uri()),
            ),
        )
        worker.set_favorite(dict(gameId=game['id'], favorite=True))
    path = root / 'spaces/games/backend.py'
    path.write_text(
        path.read_text().replace(
            '    backend = GamesBackend()\n',
            """
    def fixture_content_request(self, url, *args):
        # One pass over GOG's NSFW-tagged catalogue classifies every game.
        assert url.startswith('https://catalog.gog.com/v1/catalog?')
        time.sleep(0.5)
        return dict(pages=1, products=[dict(id=identifier, tags=[dict(slug='nsfw')])
                                       for identifier in ('456', '458')])
    GamesBackend._http_json = fixture_content_request
    backend = GamesBackend()
""",
        )
    )


def setup_selection(root):
    setup(root)
    worker = GamesBackend(
        root / 'config/quickshell/desktop/spaces/games/games.json',
        root / 'data/quickshell/desktop/spaces/games',
    )
    game = worker._save_game(
        'second',
        dict(
            catalogProvider='fixture', catalogProviderId='second', title='Second game'
        ),
    )
    worker.set_favorite(dict(gameId=game['id'], favorite=True))
    path = root / 'spaces/games/backend.py'
    path.write_text(
        path.read_text().replace(
            '    backend = GamesBackend()\n',
            """
    def fixture_availability(self, request):
        # An older, slower hydration of the same game must not win.
        if not request.get('refresh'):
            time.sleep(0.6)
        label = 'Fresh' if request.get('refresh') else 'Stale'
        return dict(stores=[dict(store='steam', label='Steam', externalId='620',
            primaryAction=dict(type='disabled', label=label, enabled=False), actions=[])])
    GamesBackend.availability = fixture_availability
    backend = GamesBackend()
""",
        )
    )


def setup_uninstall(root):
    setup(root)
    path = root / 'spaces/games/backend.py'
    path.write_text(
        path.read_text().replace(
            '    backend = GamesBackend()\n',
            """
    def fixture_removed(self):
        return (self.data_root / 'uninstalled').exists()
    def fixture_availability(self, request):
        installed = not fixture_removed(self)
        kind = 'play' if installed else 'install'
        return dict(stores=[dict(store='epic', label='Epic', externalId='Fixture', installed=installed,
            primaryAction=dict(id='epic:' + kind + ':Fixture', type=kind, store='epic',
                               label=kind.title(), enabled=True), actions=[])])
    def fixture_uninstall(self, request):
        (self.data_root / 'uninstalled').write_text('')
        return dict(started=True, message='Epic uninstall started in Legendary.')
    GamesBackend.availability = fixture_availability
    GamesBackend.action = fixture_uninstall
    backend = GamesBackend()
""",
        )
    )


@unittest.skipUnless(support.QS, 'Quickshell is required')
class GamesSpaceTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_scrolling_the_library_makes_no_per_game_requests(self):
        def setup_large(root):
            setup(root)
            worker = GamesBackend(
                root / 'config/quickshell/desktop/spaces/games/games.json',
                root / 'data/quickshell/desktop/spaces/games',
            )
            for index in range(119):
                game = worker._save_game(
                    f'bulk-{index}',
                    dict(
                        catalogProvider='library',
                        catalogProviderId=f'bulk-{index}',
                        title=f'Game {index:03}',
                        storeReferences=[
                            dict(store='steam', externalId=str(1000 + index))
                        ],
                    ),
                )
                worker.set_favorite(dict(gameId=game['id'], favorite=True))
            path = root / 'spaces/games/backend.py'
            path.write_text(
                path.read_text().replace(
                    '    backend = GamesBackend()\n',
                    """
    GamesBackend.library_games = lambda self, request: self._favorite_games('', int(request.get('offset') or 0))
    original_handle = GamesBackend.handle
    def fixture_handle(self, request):
        counts = self.__dict__.setdefault('fixture_ops', {})
        if request.get('op') == 'fixture_ops':
            return dict(counts)
        counts[request['op']] = counts.get(request['op'], 0) + 1
        return original_handle(self, request)
    GamesBackend.handle = fixture_handle
    backend = GamesBackend()
""",
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
 property var ops:null
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer {id:driver;interval:60;running:true;repeat:false;onTriggered:{try{
  if(root.step===0){SpaceState.open("games",Quickshell.screens[0]);root.step++;return;}
  const page=host.currentPage;if(!page||page.initializing)return;
  const service=find(page,"gamesService");const rail=find(page,"gamesRail");
  if(root.step===1){
   if(page.nextOffset||page.loading){rail.positionViewAtEnd();return;}
   if(page.titles.length!==120||service.pendingCount)return;
   service.request("fixture_ops",{},result=>{root.ops=result;});root.step++;return;
  }
  if(root.step===2){
   if(!root.ops)return;
   check(root.ops.library_games===3,"paging did not load three pages: "+JSON.stringify(root.ops));
   check(root.ops.details===1,"scrolling requested details for unselected games: "+JSON.stringify(root.ops));
   check((root.ops.content_rating||0)<=6,"classification was not batched: "+JSON.stringify(root.ops));
   check(!root.ops.library_metadata,"background metadata hydration returned");
   SpaceState.close("games");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",error);Qt.quit();}finally{driver.restart();}}}
 Timer {interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout",root.step,host.currentPage?.titles.length,JSON.stringify(root.ops));Qt.quit();}}
}""",
            setup=setup_large,
        )

    def test_header_nsfw_filter_hides_labelled_and_unclassified_games_and_persists(
        self,
    ):
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
 property bool classifying:false
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer {id:driver;interval:30;running:true;repeat:false;onTriggered:{try{
  if(root.step===0){SpaceState.open("games",Quickshell.screens[0]);root.step++;return;}
  const page=host.currentPage;if(!page||page.allTitles.length!==5)return;
  const toolbar=find(page.toolbarTarget,"gamesToolbar");
  const toggle=find(toolbar,"gameContentFilter");
  const filters=find(toolbar,"gameFiltersButton");
  const status=toggle.data.find(item=>item.objectName==="gameContentStatus");
  if(root.step===1){
   check(page.hideNsfw&&!toggle.highlighted&&toggle.Accessible.checked===false,"NSFW must default to hidden");
   check(!find(page,"gameContentFilter")&&!find(page,"gameContentStatus"),"NSFW filter is outside the header");
   check(!page.filtersOpen&&!toggle.visible,"NSFW control shown outside collapsed filters");
   check(find(page.backdropTarget,"gamesBackdrop").retainPreviousFor===1000,"backdrop does not retain the previous image during selection");
   if(page.contentBusy||page.contentQueue.length){
    root.classifying=true;
    check(page.titles.length===1&&page.titles[0].title==='Fixture game',"unclassified artwork reached catalogue");
    return;
   }
   check(root.classifying,"classification was not observed");
   check(page.contentHidden===2&&page.contentAwaiting===0&&page.contentUnlabelled===0,"native results not applied: "+[page.contentHidden,page.contentAwaiting,page.contentUnlabelled]);
   check(page.titles.length===3&&['Fixture game','Ordinary game','Untagged game'].every(title=>page.titles.some(game=>game.title===title)),"untagged games stayed hidden");
   check(status.text.includes("2 hidden by store labels")&&!status.text.includes("without store labels"),"NSFW tooltip lacks counts: "+status.text);
   check(filters.enabled,"library content filter requires catalogue credentials");
   input.mouseClick(filters);
   input.wait(40);
   const header=toolbar.mapToItem(host.contentItem,0,0);const placed=toggle.mapToItem(host.contentItem,0,0);
   check(toggle.visible&&toggle.text==='NSFW'&&placed.y>=header.y&&placed.y+toggle.height<=header.y+toolbar.height+1,"NSFW toggle is not inline in the header");
   check(!find(toolbar,"genrePicker").visible,"catalogue controls shown in library filters");
   input.mouseClick(toggle);
   check(toggle.highlighted&&!page.hideNsfw&&page.titles.length===5,"including NSFW lost hidden games");
   page.selectGame(page.titles.find(game=>game.title==='Explicit game'));
   check(page.selected.title==='Explicit game',"explicit selection unavailable with filter off");
   input.mouseClick(toggle);
   check(!toggle.highlighted&&page.hideNsfw&&page.titles.length===3&&page.selected.title!=='Explicit game',"hiding NSFW retained explicit details");
   page.showMode("favorites");root.step++;return;
  }
  if(root.step===2){
   if(page.loading)return;
   check(page.titles.length===3,"Favorites bypassed content filter");
   check(!toggle.visible&&!page.filtersOpen,"view change left Filters open");
   input.mouseClick(filters);
   input.wait(40);
   input.mouseClick(toggle);
   SpaceState.close("games");SpaceState.open("games",Quickshell.screens[0]);root.step++;return;
  }
  if(root.step===3){
   if(page.loading)return;
   check(toggle.highlighted&&!page.hideNsfw&&page.titles.length===5,"NSFW preference lost on reopening");
   check(!toggle.visible&&!page.filtersOpen,"reopening exposed NSFW control");
   input.mouseClick(filters);
   input.wait(40);
   input.mouseClick(toggle);
   SpaceState.close("games");SpaceState.open("games",Quickshell.screens[0]);root.step++;return;
  }
  if(root.step===4){
   if(page.loading)return;
   check(!toggle.highlighted&&page.hideNsfw&&page.titles.length===3,"hidden preference or saved labels lost on reopening");
   SpaceState.close("games");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",error);Qt.quit();}finally{driver.restart();}}}
 Timer {interval:10000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout at step",root.step);Qt.quit();}}
}""",
            setup=setup_content,
        )

    def test_rehydration_order_match_edits_row_patches_and_idle_polling(self):
        self.run_qml(
            """import QtQuick
import Quickshell
import "ui"
ShellRoot {
 id:root
 InteractionState {id:interactions}
 SpaceHost {id:host;interactionState:interactions}
 property int step:0
 property int serial:0
 property double since:0
 property string chosen:""
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer {id:driver;interval:40;running:true;repeat:false;onTriggered:{try{
  if(root.step===0){SpaceState.open("games",Quickshell.screens[0]);root.step++;return;}
  const page=host.currentPage;if(!page||page.titles.length!==2)return;
  const service=find(page,"gamesService");const rail=find(page,"gamesRail");
  if(root.step===1){
   if(page.busy)return;
   page.selectGame(page.titles[1]);root.chosen=page.selected.id;root.step++;return;
  }
  if(root.step===2){
   if(page.busy)return;
   // The slower, older hydration is already running when the refresh starts.
   page.hydrateSelection(false);root.since=Date.now();root.step++;return;
  }
  if(root.step===3){
   if(Date.now()-root.since<150)return;
   page.hydrateSelection(true);root.step++;return;
  }
  if(root.step===4){
   if(service.pendingCount)return;
   check(page.availability.stores[0].primaryAction.label==="Fresh","an older hydration replaced newer store state");
   check(!page.detailError.includes("superseded"),"overlapping hydration reported: "+page.detailError);
   const matching=Array.from(page.data).find(item=>item.objectName==="gameMatchDialog");
   page.editMatch("steam","");find(matching.contentItem,"gameMatchInput").text="620";page.saveMatch();root.step++;return;
  }
  if(root.step===5){
   if(service.pendingCount||page.busy)return;
   check(page.selected.id===root.chosen,"saving a store link changed the selection");
   const edited=page.titles.find(game=>game.id===root.chosen);
   check(edited&&edited.content.supported&&edited.content.nsfw===null&&!edited.content.awaiting,"the new Steam link was not classified: "+JSON.stringify(edited&&edited.content));
   const index=page.titles.findIndex(game=>game.id===root.chosen);
   page.patchGame({id:root.chosen,title:"Renamed game"});
   check(rail.itemAtIndex(index).text==="Renamed game"&&page.titles[index].title==="Renamed game","row patch did not reach the poster");
   page.patchGame({id:root.chosen,content:{supported:true,nsfw:true,pending:false,awaiting:false}});
   check(page.titles.length===1&&page.selected.id!==root.chosen,"an NSFW patch kept the game visible");
   page.patchGame({id:root.chosen,content:{supported:true,nsfw:false,pending:false,awaiting:false}});
   check(page.titles.length===2&&page.titles.some(game=>game.id===root.chosen),"a cleared label did not restore the game");
   root.since=Date.now();root.step++;return;
  }
  if(root.step===6){
   // Let the reselection's hydration settle before measuring idle traffic.
   if(Date.now()-root.since<300||service.pendingCount)return;
   root.serial=service.serial;root.since=Date.now();root.step++;return;
  }
  if(root.step===7){
   if(Date.now()-root.since<1800)return;
   check(service.serial===root.serial,"idle Games kept polling the worker");
   SpaceState.close("games");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",error);Qt.quit();}finally{driver.restart();}}}
 Timer {interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout at step",root.step);Qt.quit();}}
}""",
            setup=setup_selection,
        )

    def test_uninstall_rechecks_the_launcher_until_the_game_is_removed(self):
        self.run_qml(
            """import QtQuick
import Quickshell
import "ui"
ShellRoot {
 id:root
 InteractionState {id:interactions}
 SpaceHost {id:host;interactionState:interactions}
 property int step:0
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer {id:driver;interval:40;running:true;repeat:false;onTriggered:{try{
  if(root.step===0){SpaceState.open("games",Quickshell.screens[0]);root.step++;return;}
  const page=host.currentPage;if(!page||page.busy)return;
  const button=find(page,"gameStoreAction:epic");
  if(root.step===1){
   if(!button||button.text!=="Play")return;
   page.availabilityRecheckDelays=[150,400];
   page.execute({id:"epic:uninstall:Fixture",type:"uninstall",store:"epic"});root.step++;return;
  }
  if(root.step===2){
   if(button.text!=="Install")return;
   check(host.opened,"uninstall hid Games");
   check(!page.availabilityChecks.length,"rechecks continued after the launcher changed");
   SpaceState.close("games");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",error);Qt.quit();}finally{driver.restart();}}}
 Timer {interval:8000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout at step",root.step);Qt.quit();}}
}""",
            setup=setup_uninstall,
        )

    def test_epic_install_progress_download_panel_and_reopen(self):
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
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer {id:driver;interval:60;running:true;repeat:false;onTriggered:{try{
  if(root.step===0){SpaceState.open("games",Quickshell.screens[0]);root.step++;return;}
  const page=host.currentPage;if(!page)return;
  const button=find(page,"gameStoreAction:epic");
  if(root.step===1){
   if(!button||button.text!=="Install"||page.busy)return;
   input.mouseClick(button);root.step++;return;
  }
  if(root.step===2){
   if(!page.installing)return;
   check(!button.enabled,"Install remained enabled during download");
   check(button.text==="Preparing…"||button.text.includes("Installing"),"no immediate install feedback");
   const job=page.installJobs[0];if(job.progress!==0.25||job.speed!==8.5)return;
   check(button.text==="Installing · 25%","percentage missing from Epic button");
   const status=find(page,"gameInstallStatus");
   check(status.visible&&status.text.includes("8.5 MiB/s")&&status.text.includes("ETA 00:00:03"),"speed/ETA missing");
   const activity=find(page.toolbarTarget,"spaceActivityIndicator");
   check(activity.tooltipText.includes("25%"),"install missing from the activity indicator");
   input.mouseClick(find(page.toolbarTarget,"gameDownloads"));input.wait(40);
   const downloads=find(page,"gameFindContent");
   const panel=Array.from(downloads.data).find(item=>item.objectName==="downloadJobsPanel");
   check(panel.visible&&downloads.extraJobs.length===1,"Downloads omits Epic install");
   host.escapeHandler();check(host.opened&&!panel.visible,"download panel Escape hid Games");
   SpaceState.close("games");SpaceState.open("games",Quickshell.screens[0]);root.step++;return;
  }
  if(root.step===3){
   if(!button||!page.installJobs.length)return;
   check(page.installJobs[0].progress>=0.25,"reopen lost download telemetry");
   if(page.installJobs[0].state!=="completed"||button.text!=="Play")return;
   check(button.enabled,"completed installation did not enable Play");
   check(find(page,"gameInstallStatus").text.includes("Installed"),"completion missing");
   SpaceState.close("games");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",error);Qt.quit();}finally{driver.restart();}}}
 Timer {interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout at step",root.step);Qt.quit();}}
}""",
            setup=setup_install,
        )

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
   const rating=page.compatibility;page.compatibility=Object.assign({},rating,{native:true});
   check(find(page,"protonDbArtwork").source.toString().endsWith("protondb-native.svg")&&page.protonDbTooltip.includes("Native Linux")&&page.protonDbTooltip.includes("Gold"),"native Linux badge missing");
   page.compatibility=rating;
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
   page.filtersOpen=true;const picker=find(page.toolbarTarget,"genrePicker");picker.popup.open();input.wait(30);
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

    def test_catalogue_warnings_are_inline_and_store_messages_stay_on_stores(self):
        def setup_warnings(root):
            setup(root)
            worker = root / 'spaces/games/backend.py'
            fixture = """    original_library = GamesBackend.library_games
    GamesBackend.library_games = lambda self, request: dict(original_library(self, request), warning="Steam: Fixture store message.")
    GamesBackend.browse = lambda self, request: dict(items=[], next=None, setupRequired=False, warning="Fixture catalogue is offline. Showing saved results.")
"""
            source = worker.read_text()
            marker = '    backend = GamesBackend()\n'
            self.assertEqual(source.count(marker), 1)
            worker.write_text(source.replace(marker, fixture + marker))

        self.run_qml(
            """import QtQuick
import QtTest
import Quickshell
import "ui"
ShellRoot {
 id:root
 InteractionState {id:interactions}
 SpaceHost {id:host;interactionState:interactions}
 TestCase {id:input;when:false;parent:host.contentItem}
 property int step:0
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer {id:driver;interval:80;running:true;repeat:false;onTriggered:{try{
  if(root.step===0){check(SpaceState.open("games",Quickshell.screens[0]),"cannot open Games");root.step++;return;}
  const page=host.currentPage;if(!page||page.loading||page.initializing)return;
  if(root.step===1){
   if(!page.titles.length)return;
   check(page.mode==="library"&&page.error==="","store message took a content row");
   input.mouseClick(find(host.contentItem,"discoverTab"));root.step++;return;
  }
  if(root.step===2){
   if(page.mode!=="discover")return;
   check(page.error.includes("Showing saved results"),"offline catalogue was not flagged: "+page.error);
   SpaceState.close("games");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",error.message);Qt.quit();}finally{driver.restart();}}}
 Timer {interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout",root.step);Qt.quit();}}
}
""",
            setup=setup_warnings,
        )
