"""Pictures uses the real fullscreen host and owned workers without network access."""

import unittest
import support
from test_movies_space import setup as host_setup


def setup(root):
    host_setup(root)
    (root / 'art.svg').write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450"><rect width="800" height="450" fill="#78a078"/></svg>'
    )
    (root / 'spaces/pictures/backend.py').write_text(
        """import sys,time
sys.path.insert(0,%r)
from spaces.pictures.backend import run,clean_item,PROVIDERS
from spaces.movies.worker import serve
item=clean_item({'provider':'wallhaven','id':'abc123','path':'https://w.wallhaven.cc/full/ab/wallhaven-abc123.jpg'})
item.update(title='Mountain lake',preview=%r,path=%r,resolution='3840 × 2160')
def handle(r):
 if r['op']=='providers':return {'providers':[PROVIDERS['wallhaven']],'currentProvider':'wallhaven'}
 if r['op']=='browse' and not r.get('favorites'):return {'items':[item],'next':0}
 if r['op']=='favorite':return {'favorite':True}
 if r['op']=='random':time.sleep(.2);return {'wallpaper':dict(item,id='def456')}
 if r['op']=='set':time.sleep(.25);return {'message':'Wallpaper and lock updated'}
 return run(r)
serve(handle,controls=('set','favorite','savePreferences'))
"""
        % (
            str(support.DESKTOP),
            (root / 'art.svg').as_uri(),
            (root / 'art.svg').as_uri(),
        )
    )


@unittest.skipUnless(support.QS, 'Quickshell is required')
class PicturesSpaceTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_lifecycle_filters_gallery_favorites_and_apply(self):
        self.run_qml(
            """import QtQuick
import QtQuick.Controls
import Quickshell
import "ui"
ShellRoot {
 id: root
 InteractionState {id:interactions}
 SpaceHost {id:host;interactionState:interactions}
 property var original:null
 property int step:0
 function check(v,m){if(!v)throw new Error(m);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer {interval:50;running:true;repeat:true;onTriggered:{try{
  if(root.step===0){SpaceState.open("pictures",Quickshell.screens[0]);root.step++;return;}
  const page=host.currentPage;
  if(!page || page.loading || !page.selected.id)return;
  if(root.step===1){
   const preview=find(page,"selectedWallpaperImage");
   if(preview.loading || !preview.hasImage || preview.transitioning)return;
   check(page.active,"Pictures not active");root.original=page;
   check(find(host.contentItem,"setWallpaperButton").enabled,"Apply is missing");
   const detail=find(page,"pictureDetails"),content=find(page,"picturesContent"),rail=find(page,"wallpaperRail");
   check(detail.x===16 && detail.width<=1000,"rail detail layout differs from Movies");
   check(Math.abs(rail.y+rail.height-content.height)<2,"rail is not bottom aligned");
   check(find(host.contentItem,"picturesToolbar") && !find(host.contentItem,"picturesSearch").visible,"search is not in the compact toolbar");
   check(find(host.contentItem,"picturesBackdrop").visible,"selected wallpaper backdrop is missing");
   find(host.contentItem,"pictureFullImage").clicked();
   check(page.dismissTransient(),"gallery did not take Escape");
   page.gridMode=true;
   check(Math.abs(detail.x-content.width*.55)<2 && Math.abs(detail.width-content.width*.45)<2,"grid detail proportions differ from Movies");
   page.filtersOpen=true;
   check(page.dismissTransient() && !page.filtersOpen,"filters did not dismiss");
   find(host.contentItem,"picturesSearch").text="lake";
   check(page.dismissTransient() && !find(host.contentItem,"picturesSearch").text,"search did not dismiss");
   page.chooseRandom();page.browse(false);
   find(host.contentItem,"favoriteWallpaperButton").clicked();root.step++;return;
  }
  if(root.step===2){if(page.favoriteSaving || page.randomLoading)return;check(page.selected.id==="abc123","late random response replaced a newer catalogue");check(page.isFavorite(page.selected),"favorite did not save");page.setDesktopWallpaper();SpaceState.hide();check(!page.active && SpaceState.runningIds.includes("pictures"),"hide discarded Pictures");root.step++;return;}
  if(root.step===3){if(page.settingWallpaper)return;SpaceState.open("pictures",Quickshell.screens[0]);check(host.currentPage===root.original && page.gridMode,"restore lost retained state");check(page.actionMessage==="Wallpaper and lock updated","background apply was lost");SpaceState.open("movies",Quickshell.screens[0]);root.step++;return;}
  if(root.step===4){if(SpaceState.currentId!=="movies")return;check(SpaceState.runningIds.includes("pictures"),"switch destroyed Pictures");SpaceState.close("pictures");check(SpaceState.runningIds.includes("movies"),"close disturbed Movies");SpaceState.open("pictures",Quickshell.screens[0]);root.step++;return;}
  if(root.step===5){check(page!==root.original,"close did not destroy Pictures");check(page.gridMode,"layout preference did not persist");SpaceState.close("movies");SpaceState.close("pictures");console.log("DISPLAY_PASS");Qt.quit();}
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:11000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""",
            setup=setup,
        )

    def test_drawer_random_uses_shared_service_without_starting_space(self):
        def action_setup(root):
            setup(root)
            (root / 'spaces/pictures/backend.py').write_text(
                """import sys,time
sys.path.insert(0,%r)
from spaces.movies.worker import serve
def handle(r):
 if r['op']!='randomSet':raise ValueError('Unexpected action')
 time.sleep(.25)
 return {'message':'Wallpaper and lock screen updated'}
serve(handle)
"""
                % str(support.DESKTOP)
            )

        self.run_qml(
            """import QtQuick
import Quickshell
import "ui"
import "spaces/pictures"
ShellRoot {
 id:root
 property int step:0
 Timer {interval:50;running:true;repeat:true;onTriggered:{try{
  if(root.step===0){WallpaperService.randomWallhaven();if(!WallpaperService.busy)throw new Error("action did not start");WallpaperService.randomWallhaven();root.step++;return;}
  if(WallpaperService.busy)return;
  if(WallpaperService.error || !WallpaperService.message)throw new Error("random action failed");
  if(SpaceState.runningIds.includes("pictures"))throw new Error("drawer opened Pictures");
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:8000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""",
            setup=action_setup,
        )

    def test_private_provider_selection_loads_command_package_and_reports_failure(self):
        def private_setup(root):
            import json

            setup(root)
            config = root / 'config/quickshell/desktop/spaces/pictures'
            package = config / 'providers/personal'
            package.mkdir(parents=True)
            (package / 'manifest.json').write_text(
                json.dumps(
                    {
                        'api_version': 1,
                        'command': ['python3', '{plugin_dir}/provider.py'],
                    }
                )
            )
            (package / 'provider.py').write_text("""import json,os,sys,time
request=json.load(sys.stdin)
time.sleep(.25)
if os.environ.get('FIXTURE_FAIL'):
 print(json.dumps({'success':False,'error':'Fixture provider is offline.'}))
else:
 print(json.dumps({'success':True,'items':[{'id':'private-video','title':'Private fixture','kind':'video','preview':'','ref':{'id':'private-video'}}],'next':0}))
""")
            (config / 'pictures.json').write_text(
                json.dumps(
                    {
                        'providers': [
                            {
                                'id': 'personal',
                                'name': 'Private collection',
                                'plugin': 'providers/personal',
                            },
                            {
                                'id': 'unavailable',
                                'name': 'Unavailable collection',
                                'plugin': 'providers/personal',
                                'env': {'FIXTURE_FAIL': '1'},
                            },
                        ]
                    }
                )
            )
            worker = root / 'spaces/pictures/backend.py'
            source = worker.read_text().replace(
                'from spaces.movies.worker import serve',
                'from spaces.pictures import providers\nfrom spaces.movies.worker import serve',
            )
            source = source.replace(
                "[PROVIDERS['wallhaven']]",
                "[PROVIDERS['wallhaven']]+providers.descriptors()",
            )
            source = source.replace(
                "if r['op']=='browse' and not r.get('favorites'):",
                "if r['op']=='browse' and not r.get('favorites') and r.get('provider')=='wallhaven':",
            )
            worker.write_text(source)

        self.run_qml(
            """import QtQuick
import Quickshell
import "ui"
ShellRoot {
 id:root
 InteractionState{id:interactions}
 SpaceHost{id:host;interactionState:interactions}
 property int step:0
 function check(v,m){if(!v)throw new Error(m);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer{interval:40;running:true;repeat:true;onTriggered:{try{
  if(root.step===0){SpaceState.open("pictures",Quickshell.screens[0]);root.step++;return;}
  const page=host.currentPage;if(!page)return;
  const choice=find(host.contentItem,"picturesProviderChoice");
  if(root.step===1){
   if(page.loading || !page.selected.id)return;
   check(page.providerOptions.length===3,"private packages not discovered");
   const preview=find(page,"picturePreviewFrame");
   check(preview.width<=preview.height*1.78+1 && preview.height<=360,"preview frame extends beyond the fitted image");
   choice.currentIndex=1;choice.activated(1);
   check(page.providerId==="personal" && page.loading && !page.selected.id && !page.wallpapers.length,"selection kept another provider's artwork");
   check(find(page,"picturesProviderLoading").visible,"provider loading state is missing");root.step++;return;
  }
  if(root.step===2){
   if(page.loading)return;
   check(!page.error && page.selected.provider==="personal" && page.selected.kind==="video","private command results not displayed");
   choice.currentIndex=2;choice.activated(2);check(!page.selected.id,"old private selection survived provider switch");root.step++;return;
  }
  if(root.step===3){if(page.loading)return;check(page.error==="Fixture provider is offline." && !page.selected.id,"provider failure left stale artwork or no error");SpaceState.close("pictures");console.log("DISPLAY_PASS");Qt.quit();}
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:10000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""",
            setup=private_setup,
        )

    def test_displays_header_has_one_badged_wallpaper_action(self):
        self.run_qml("""import QtQuick
import Quickshell
import "ui"
import "drawers"
ShellRoot {
 id:root
 QtObject {
  id:mock
  property var state:({available:false,displays:[],token:"fixture"})
  property bool loaded:true
  property bool busy:false
  property bool closing:false
  property string error:""
  function observe(owner,active){}
 }
 QtObject {
  id:wallpapers
  property bool busy:false
  property string error:""
  property string message:""
  property int calls:0
  function randomWallhaven(){calls++;}
 }
 FloatingWindow {implicitWidth:480;implicitHeight:200;visible:true
  DisplaysDrawer{id:drawer;visible:false;active:false;service:mock;wallpaperService:wallpapers}
  Loader{id:header;sourceComponent:drawer.headerActions}
 }
 function check(v,m){if(!v)throw new Error(m);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer{interval:250;running:true;onTriggered:{try{
  const button=find(header.item,"displayRandomWallpaper");
  check(button && find(button,"displayRandomWallpaperIcon").name==="image","wallpaper base icon is missing");
  check(find(button,"displayWallpaperShuffleBadge"),"shuffle badge is missing");
  let actions=0;for(const child of header.item.children??[])if(typeof child.clicked==="function")actions++;
  check(actions===2&&!find(header.item,"displaySave"),"Displays header has unexpected actions");
  check(find(header.item,"displaySettings").text==="Configure display arrangement","arrangement entry is missing");
  button.clicked();check(wallpapers.calls===1,"badged action does not randomize wallpaper");
  check(!SpaceState.runningIds.includes("pictures"),"wallpaper action opened Pictures");
  wallpapers.busy=true;check(!button.enabled,"busy action remains enabled");
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}""")
