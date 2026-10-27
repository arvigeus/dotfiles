"""Movies runs through the real SpaceHost with isolated media workers."""

import re
import unittest
import support


def setup(root):
    path = root / 'ui/InteractionWindow.qml'
    source = path.read_text().replace(
        'PanelWindow {',
        'FloatingWindow {\n implicitWidth: 1440; implicitHeight: 900',
        1,
    )
    source = source.replace(
        '    anchors { top: true; bottom: true; left: true; right: true }\n', ''
    )
    source = source.replace('    exclusionMode: ExclusionMode.Ignore\n', '')
    source = re.sub(r'^    WlrLayershell\..*\n', '', source, flags=re.M)
    path.write_text(source)
    # Real catalogue, aliases and worker transport; seeded cache avoids APIs.
    import sys

    sys.path.insert(0, str(support.DESKTOP))
    from spaces.movies.backend import Backend

    backend = Backend(
        root / 'config/quickshell/desktop/spaces/movies/media.json',
        root / 'data/quickshell/desktop/spaces/movies',
        root / 'cache',
    )
    movie = dict(
        id='tt001',
        imdbId='tt001',
        kind='movie',
        title='Fixture movie',
        year='2024',
        overview='A saved movie',
        poster='',
        backdrop='',
    )
    backend.put(backend.browse_key('movie', '', {}, ''), dict(items=[movie], next=''))
    backend.save_title(movie)
    backend.put('detail:tt001', movie)
    backend.put('art:tt001', dict(title=movie, warnings=[], version=3))
    # Providers and qBittorrent are not contacted by the fixture.
    (root / 'spaces/movies/torrent_backend.py').write_text(
        "import json,sys\nfor line in sys.stdin:\n r=json.loads(line);print(json.dumps(dict(id=r['id'],result=[])),flush=True)\n"
    )


@unittest.skipUnless(support.QS, 'Quickshell is required')
class MoviesSpaceTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_real_host_hide_restore_close_and_native_page(self):
        self.run_qml(
            """import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "ui"
import "drawers"
ShellRoot {
 id:root
 InteractionState { id:interactions }
 SpaceHost { id:host; interactionState:interactions }
 QtObject { id:mockSession
  property var state:({capabilities:{},scheduledShutdown:""})
  property bool busy:false
  property string error:""
  property bool sleepPaused:false
  property bool lockingPaused:false
  property bool pausesAvailable:false
  function refresh(){}
 }
 FloatingWindow { id:drawerWindow;implicitWidth:480;implicitHeight:900;visible:false
  SpacesDrawer { id:drawer;anchors.fill:parent;active:drawerWindow.visible;screen:Quickshell.screens[0];service:mockSession }
 }
 property int step:0
 property var retained:null
 TestCase { id:input; when:false; parent:host.contentItem }
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer { id:driver;interval:100;running:true;repeat:false;onTriggered:{try{
  if(root.step===0){check(SpaceState.open("movies",Quickshell.screens[0]),"open failed");root.step++;return;}
  if(root.step===1){
   if(!host.currentPage||host.currentPage.loading||host.currentPage.titleLoading)return;
   check(host.currentPage.titles.length===1,"cached catalogue missing");
   const toolbar=find(host.contentItem,"movieToolbar");
   const hideButton=find(host.contentItem,"hideSpace");
   check(Math.abs(toolbar.mapToItem(host.contentItem,0,0).y+toolbar.height/2-hideButton.mapToItem(host.contentItem,0,0).y-hideButton.height/2)<1,"toolbar is not beside hide button");
   check(toolbar.x>=0&&toolbar.width===host.currentPage.toolbarTarget.width,"toolbar escaped its host slot");
   root.retained=host.currentPage;host.currentPage.searchOpen=true;
   host.escapeHandler();check(host.opened&&!host.currentPage.searchOpen,"Escape priority failed");
   host.currentPage.filtersOpen=true;
   const genre=find(host.contentItem,"genrePicker");genre.popup.open();input.wait(50);
   host.escapeHandler();check(host.opened&&!genre.popup.visible&&host.currentPage.filtersOpen,"popup Escape hid space");
   host.escapeHandler();check(host.opened&&!host.currentPage.filtersOpen,"filter Escape hid space");
   host.currentPage.gridMode=true;
   host.currentPage.save({favorite:true});
   const gallery=Array.from(host.currentPage.data).find(item=>item.objectName==="movieGallery");
   check(gallery,"gallery missing");gallery.show([],0,"Fixture");input.wait(50);
   const hide=find(host.contentItem,"hideSpace");input.mouseClick(hide,hide.width/2,hide.height/2);
   check(!host.opened&&!gallery.visible&&SpaceState.runningIds.includes("movies"),"gallery blocked hide or hide destroyed instance");
   check(!toolbar.visible,"hidden page kept its toolbar active");
   root.step++;return;
  }
  if(root.step===2){
   check(SpaceState.open("movies",Quickshell.screens[0]),"restore failed");
   check(host.currentPage===root.retained,"restore recreated page");
   check(host.currentPage.titles.length===1&&host.currentPage.gridMode,"state lost");
   host.dismiss();drawerWindow.visible=true;input.wait(50);
   const close=find(drawer,"closeSpace:movies");check(close.visible,"running close absent");
   const entry=find(drawer,"space:movies");
   const highlight=find(drawer,"spaceRowHighlight:movies");
   input.mouseMove(entry,entry.width/2,entry.height/2);input.wait(30);
   check(highlight.color===Theme.accentSurface,"entry did not highlight its row");
   input.mouseMove(close,close.width/2,close.height/2);input.wait(30);
   check(highlight.color===Theme.accentSurface,"hovering X lost the row highlight");
   check(highlight.width>=entry.width+close.width,"row highlight excludes X");
   input.mouseClick(close,close.width/2,close.height/2);
   check(!host.opened&&!SpaceState.runningIds.length&&drawerWindow.visible,"drawer close opened Space or kept running state");
   drawerWindow.visible=false;
   root.step++;return;
  }
  if(root.step===3){check(!host.currentPage,"close kept page");check(!find(host.contentItem,"movieToolbar"),"close left a toolbar behind");SpaceState.open("movies",Quickshell.screens[0]);root.step++;return;}
  if(root.step===4){if(!host.currentPage||host.currentPage.loading)return;if(!host.currentPage.personal.favorite)return;check(host.currentPage!==root.retained,"fresh open reused disposed page");SpaceState.close("movies");console.log("DISPLAY_PASS");Qt.quit();}
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}finally{driver.start();}} }
 Timer { interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();} }
}""",
            setup=setup,
        )

    def test_tab_loading_survives_late_responses_and_tracks_the_visible_tab(self):
        def delayed_setup(root):
            setup(root)
            # Use the real transport and backend with deterministic delayed reads.
            (root / 'spaces/movies/backend.py').write_text(
                """import sys,time
sys.path.insert(0, %r)
from spaces.movies.backend import Backend
from spaces.movies.worker import serve
backend=Backend()
def handle(request):
 op=request['op']
 if op=='watch':time.sleep(0.2);return []
 if op=='spoilers':time.sleep(0.7);return {'text':'Fixture spoiler'}
 if op=='collections':time.sleep(0.3);return {'sections':[]}
 if op=='person':time.sleep(0.3);return {'name':'Fixture actor','credits':[]}
 return backend.handle(request)
serve(handle)
"""
                % str(support.DESKTOP)
            )

        self.run_qml(
            """import QtQuick
import QtQuick.Controls
import Quickshell
import "ui"
ShellRoot {
 id:root
 InteractionState { id:interactions }
 SpaceHost { id:host;interactionState:interactions }
 property int step:0
 property double requestedAt:0
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer { interval:40;running:true;repeat:true;onTriggered:{try{
  if(root.step===0){SpaceState.open("movies",Quickshell.screens[0]);root.step++;return;}
  const page=host.currentPage;
  if(!page||page.loading||page.titleLoading)return;
  const status=find(host.contentItem,"movieLoadingIndicator");const spinner=status;
  if(root.step===1){page.extra("watch");check(status.visible&&spinner.running,"Services has no spinner");page.extra("spoilers");root.requestedAt=Date.now();root.step++;return;}
  if(root.step===2){
   if(Date.now()-root.requestedAt<350)return;
   check(page.tab==="spoilers"&&status.visible&&spinner.running,"older Services response hid the Spoilers spinner");
   page.tab="overview";check(!status.visible,"inactive tab spinner leaked");
   page.tab="spoilers";check(status.visible,"returning to pending tab lost spinner");root.step++;return;
  }
  if(root.step===3){if(page.extraLoading)return;check(page.spoiler==="Fixture spoiler"&&!status.visible,"finished Spoilers kept spinner");page.openCollections(false);check(status.visible,"Collections has no spinner");root.step++;return;}
  if(root.step===4){if(page.collectionsLoading)return;check(!status.visible,"finished Collections kept spinner");page.showPerson({id:"fixture",name:"Fixture actor"});check(status.visible,"filmography has no spinner");root.step++;return;}
  if(root.step===5){if(page.extraLoading)return;check(!status.visible,"finished filmography kept spinner");SpaceState.close("movies");console.log("DISPLAY_PASS");Qt.quit();}
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}} }
 Timer {interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""",
            setup=delayed_setup,
        )

    def test_gallery_spinner_and_artwork_cache_survive_delegate_recreation(self):
        def cache_setup(root):
            setup(root)
            (root / 'spaces/movies/image_cache.py').write_text(
                """import io,sys,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,%r)
from spaces.movies.image_cache import ArtworkCache
from spaces.movies.worker import serve
counter=Path(%r)
class Response(io.BytesIO):headers={'Content-Type':'image/svg+xml'}
def download(*args,**kwargs):
 counter.write_text(str(int(counter.read_text())+1) if counter.exists() else '1')
 time.sleep(.15)
 return Response(b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="red"/></svg>')
with patch('spaces.movies.image_cache.urllib.request.urlopen',side_effect=download):
 serve(ArtworkCache().handle)
"""
                % (str(support.DESKTOP), str(root / 'downloads'))
            )

        self.run_qml(
            """import QtQuick
import Quickshell
import Quickshell.Io
import "ui"
import "spaces/movies"
ShellRoot {
 id:root
 property int step:0
 property int waited:0
 FloatingWindow { id:window;implicitWidth:800;implicitHeight:600;visible:true
  Loader { id:gallery;anchors.fill:parent;sourceComponent:Component{ImageGallery{}} }
  Loader { id:poster;active:false;sourceComponent:Component{CrossfadeImage{width:120;height:180;imageWidth:400;source:"https://fixture.invalid/image"}} }
 }
 FileView {id:counter;path:Qt.resolvedUrl("downloads").toString().replace("file://","");blockLoading:true;printErrors:false}
 function check(v,m){if(!v)throw new Error(m);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer {interval:40;running:true;repeat:true;onTriggered:{try{
  if(root.step===0){gallery.item.show([{url:"https://fixture.invalid/image"}],0,"Fixture");root.step++;return;}
  if(root.step===1||root.step===3){
   const image=find(gallery.item.contentItem,"galleryImage");
   if(image.loadStatus!==Image.Ready)return;
   const spinner=find(gallery.item.contentItem,"gallerySpinner");
   check(!spinner.visible&&!spinner.running,"gallery spinner remained after image decoded");
   counter.reload();check(counter.text()==="1","artwork was downloaded again");
   gallery.item.close();gallery.active=false;
   if(root.step===3){check(ImageCache.consumers===0,"cache worker has remaining owners");root.step=4;return;}
   root.step++;return;
  }
  if(root.step===2){gallery.active=true;gallery.item.show([{url:"https://fixture.invalid/image"}],0,"Fixture again");root.step++;return;}
  if(root.step===4){poster.active=true;root.step++;return;}
  if(root.step===5){
   if(!poster.item.hasImage||poster.item.loading)return;
   const image=find(poster.item,poster.item.frontIsA ? "imageA" : "imageB");
   check(image.sourceSize.width<=180,"poster was decoded larger than its on-screen size");
   counter.reload();check(counter.text()==="1","recreated poster made another download");
   poster.active=false;check(ImageCache.consumers===0,"poster kept cache alive after close");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""",
            setup=cache_setup,
        )

    def test_movie_has_one_spinner_until_images_and_inventory_finish(self):
        def delayed_setup(root):
            setup(root)
            (root / 'art.svg').write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="240"><rect width="160" height="240" fill="orange"/></svg>'
            )
            (root / 'spaces/movies/backend.py').write_text(
                """import sys,time
sys.path.insert(0,%r)
from spaces.movies.backend import Backend
from spaces.movies.worker import serve
backend=Backend()
def handle(request):
 op=request['op']
 if op=='personal':time.sleep(.65 if request['title']['id']=='tt001' else .1)
 if op=='local_files':time.sleep(1.5 if request['title']['id']=='tt001' else .1)
 if op in ('details','artwork'):
  time.sleep(.1)
  title=dict(request['title'],plot='Fixture synopsis',logo='https://fixture.invalid/'+request['title']['id']+'/logo',backdrop='https://fixture.invalid/'+request['title']['id']+'/backdrop')
  return {'title':title,'warnings':[]} if op=='artwork' else title
 return backend.handle(request)
serve(handle,workers=8)
"""
                % str(support.DESKTOP)
            )
            (root / 'spaces/movies/image_cache.py').write_text(
                """import sys,time
sys.path.insert(0,%r)
from spaces.movies.worker import serve
def handle(request):
 time.sleep(.35 if request['url'].endswith('logo') else .8)
 return %r
serve(handle)
"""
                % (str(support.DESKTOP), (root / 'art.svg').as_uri())
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
 property bool sawImagesLoading:false
 property bool sawFinalInventory:false
 function check(v,m){if(!v)throw new Error(m);}
 function inspect(item){
  let count=item.visible&&item.running===true&&item.foreground!==undefined&&item.track!==undefined ? 1 : 0;
  check(!(item.visible&&typeof item.text==="string"&&/^Loading(?:[ .…]|$)/.test(item.text)),"loading text is visible");
  for(const child of item.children??[])count+=inspect(child);
  return count;
 }
 Timer {interval:30;running:true;repeat:true;onTriggered:{try{
  if(root.step===0){SpaceState.open("movies",Quickshell.screens[0]);root.step++;return;}
  const page=host.currentPage;if(!page||!page.selected.id)return;
  if(root.step===1&&!page.detailLoading&&!page.artworkLoading&&!page.personalLoading&&page.filesLoading)root.sawFinalInventory=true;
  if(root.step===2&&!page.detailLoading&&!page.artworkLoading&&!page.personalLoading&&!page.filesLoading&&page.titleLoading)root.sawImagesLoading=true;
  check(inspect(host.contentItem)===(page.busy?1:0),"movie has duplicate or missing spinners");
  if(page.busy)return;
  check(!page.filesLoading&&!page.personalLoading,"spinner disappeared before inventory finished");
  if(root.step===1){check(root.sawFinalInventory,"did not observe final inventory request");page.selectTitle({id:"tt002",kind:"movie",title:"Next movie"});root.step++;return;}
  check(root.sawImagesLoading,"spinner did not wait for artwork to decode");
  SpaceState.close("movies");console.log("DISPLAY_PASS");Qt.quit();
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""",
            setup=delayed_setup,
        )

    def test_backdrop_uses_current_poster_for_slow_failed_and_superseded_images(self):
        def backdrop_setup(root):
            for name, color in [
                ('old', 'red'),
                ('poster', 'orange'),
                ('next-poster', 'green'),
            ]:
                (root / (name + '.svg')).write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="240"><rect width="160" height="240" fill="%s"/></svg>'
                    % color
                )
            (root / 'spaces/movies/image_cache.py').write_text(
                """import sys,time
sys.path.insert(0,%r)
from spaces.movies.worker import serve
def handle(request):
 url=request['url']
 time.sleep(1.5 if 'slow' in url else .04)
 if 'failed' in url:raise ValueError('Fixture image unavailable')
 return %r
serve(handle)
"""
                % (str(support.DESKTOP), (root / 'old.svg').as_uri())
            )

        self.run_qml(
            """import QtQuick
import Quickshell
import "spaces/movies"
ShellRoot {
 id:root
 property int step:0
 property double started:0
 property bool sawPoster:false
 FloatingWindow {id:window;implicitWidth:800;implicitHeight:600;visible:true
  MovieBackdrop {id:backdrop;anchors.fill:parent;ownerKey:"old";source:Qt.resolvedUrl("old.svg");poster:Qt.resolvedUrl("poster.svg")}
 }
 Connections {target:backdrop;function onUsingPosterChanged(){if(backdrop.usingPoster)root.sawPoster=true;}}
 function check(v,m){if(!v)throw new Error(m);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function switchTo(key,url,poster){backdrop.ownerKey=key;backdrop.poster=Qt.resolvedUrl(poster);backdrop.source=url;root.started=Date.now();root.sawPoster=false;}
 Timer {interval:30;running:true;repeat:true;onTriggered:{try{
  const image=find(backdrop,"movieBackdropImage"),poster=find(backdrop,"moviePosterBackdrop");
  if(root.step===0){if(!image.hasImage||backdrop.loading)return;switchTo("fast","https://fixture.invalid/fast","poster.svg");root.step++;return;}
  if(root.step===1){if(image.transitioning||image.displayedSource.toString()!==backdrop.source.toString())return;check(!root.sawPoster,"fast backdrop unnecessarily showed poster");switchTo("slow","https://fixture.invalid/slow","next-poster.svg");root.step++;return;}
  if(root.step===2){if(Date.now()-root.started<150)return;check(image.hasImage&&!backdrop.usingPoster,"old backdrop lost transition grace");root.step++;return;}
  if(root.step===3){if(Date.now()-root.started<1200)return;check(backdrop.usingPoster&&!image.hasImage&&backdrop.loading,"slow backdrop did not yield to poster");check(poster.displayedSource.toString().endsWith("next-poster.svg"),"fallback shows another movie's poster");root.step++;return;}
  if(root.step===4){if(backdrop.loading||!image.hasImage)return;check(!backdrop.usingPoster&&image.displayedSource.toString()===backdrop.source.toString(),"ready backdrop did not replace poster");switchTo("obsolete","https://fixture.invalid/slow-obsolete","poster.svg");root.step++;return;}
  if(root.step===5){if(Date.now()-root.started<1200)return;check(backdrop.usingPoster,"superseded request kept old backdrop");switchTo("latest","https://fixture.invalid/latest","next-poster.svg");root.step++;return;}
  if(root.step===6){if(Date.now()-root.started<1100)return;check(image.displayedSource.toString()===backdrop.source.toString()&&!backdrop.loading,"late obsolete image replaced latest backdrop");switchTo("missing","","poster.svg");root.step++;return;}
  if(root.step===7){if(Date.now()-root.started<1200)return;check(backdrop.usingPoster&&!image.hasImage&&!backdrop.loading,"missing backdrop did not use poster");check(image.opacity*image.imageOpacity+poster.opacity*poster.imageOpacity>.65,"fallback transition dipped to black");switchTo("failed","https://fixture.invalid/failed","poster.svg");root.step++;return;}
  if(root.step===8){if(Date.now()-root.started<2400||backdrop.loading)return;check(backdrop.usingPoster&&!image.hasImage,"failed backdrop lost poster fallback");check(poster.displayedSource.toString().endsWith("/poster.svg"),"failed backdrop has wrong fallback");console.log("DISPLAY_PASS");Qt.quit();}
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""",
            setup=backdrop_setup,
        )

    def test_recent_metadata_is_reused_and_explicit_refresh_bypasses_it(self):
        def metadata_setup(root):
            setup(root)
            (root / 'spaces/movies/backend.py').write_text("""import json,sys,time
count=0
for line in sys.stdin:
 r=json.loads(line);count+=1;time.sleep(.05)
 print(json.dumps({'id':r['id'],'result':{'networkReads':count}}),flush=True)
""")

        self.run_qml(
            """import QtQuick
import Quickshell
import "spaces/movies"
ShellRoot {
 id:root
 MediaService {id:service}
 property var results:[]
 property int step:0
 function save(value,error){if(error)throw new Error(error);root.results=root.results.concat([value.networkReads]);}
 function check(v,m){if(!v)throw new Error(m);}
 Timer{interval:30;running:true;repeat:true;onTriggered:{try{
  if(root.step===0){service.fetch("details",{title:{id:"tmdb:movie:123",tmdbId:123,kind:"movie"}},save);service.fetch("details",{title:{id:"tmdb:movie:123",tmdbId:123,kind:"movie"}},save);root.step++;return;}
  if(root.step===1){if(root.results.length<2)return;check(root.results[0]===1&&root.results[1]===1,"duplicate reads were not coalesced");service.fetch("details",{title:{id:"tt001",imdbId:"tt001",tmdbId:123,kind:"movie",plot:"enriched"}},save);root.step++;return;}
  if(root.step===2){if(root.results.length<3)return;check(root.results[2]===1,"revisiting metadata made another request");service.fetch("details",{title:{id:"tmdb:movie:123",tmdbId:123,kind:"movie"},refresh:true},save);root.step++;return;}
  if(root.step===3){if(root.results.length<4)return;check(root.results[3]===2,"explicit refresh reused old metadata");console.log("DISPLAY_PASS");Qt.quit();}
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""",
            setup=metadata_setup,
        )
