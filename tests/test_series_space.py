"""Series uses the Movies presentation with independent workers and lifecycle."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import support
from test_movies_space import setup as movies_setup

sys.path.insert(0, str(support.DESKTOP))
from spaces.movies.backend import Backend


def setup(root):
    movies_setup(root)
    backend = Backend(root/'config/quickshell/desktop/spaces/series/media.json',
                      root/'data/quickshell/desktop/spaces/series', root/'cache')
    show = dict(id='tt101', imdbId='tt101', kind='tv', title='Fixture series', year='2024',
                plot='A saved series', poster='', backdrop='',
                ratings=[dict(source='TMDB', value=84), dict(source='IMDb', value=7.9),
                         dict(source='Rotten Tomatoes', value=90), dict(source='Metacritic', value=66)])
    backend.put(backend.browse_key('tv', '', {}, ''), dict(items=[show], next=''))
    backend.save_title(show)
    backend.put('detail:tt101', show)
    backend.put('art:tt101', dict(title=show, warnings=[], version=3))
    backend.put('episodes:' + json.dumps(['tt101', None, '']), dict(seasons=['1', '2']))
    for season in ('1', '2'):
        backend.put('episodes:' + json.dumps(['tt101', season, '']),
                    dict(items=[dict(season=season, number=1, title='Season ' + season + ' premiere', plot='Fixture synopsis')], next=''))


@unittest.skipUnless(support.QS, 'Quickshell is required')
class SeriesSpaceTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_episode_spinner_paints_in_real_toolbar_and_after_restore(self):
        from PySide6.QtGui import QImage

        def delayed_setup(root):
            setup(root)
            (root / 'spaces/movies/backend.py').write_text('''import sys,time
sys.path.insert(0,%r)
from spaces.movies.backend import Backend
from spaces.movies.worker import serve
backend=Backend()
def handle(request):
 if request['op']=='episodes' and request.get('season') is not None:time.sleep(1.5)
 return backend.handle(request)
serve(handle,workers=8)
''' % str(support.DESKTOP))

        with tempfile.TemporaryDirectory() as directory:
            pictures = [Path(directory) / name for name in ('loading.png', 'restored.png')]
            self.run_qml('''import QtQuick
import QtTest
import Quickshell
import "ui"
ShellRoot {
 id:root
 InteractionState{id:interactions}
 SpaceHost{id:host;interactionState:interactions}
 TestCase{id:input;when:false;parent:host.contentItem}
 property int step:0
 property var retained:null
 property double started:0
 property bool capturing:false
 function check(v,m){if(!v)throw new Error(m);}
 function find(item,name,seen){
  if(!item)return null;seen=seen||new Set();if(seen.has(item))return null;seen.add(item);
  if(item.objectName===name)return item;
  for(const child of [...(item.children||[]),...(item.data||[])]){const found=find(child,name,seen);if(found)return found;}
  return null;
 }
 function spinnerCount(item){
  let count=item.visible&&item.running===true&&item.foreground!==undefined&&item.track!==undefined?1:0;
  for(const child of item.children??[])count+=spinnerCount(child);
  return count;
 }
 function capture(spinner,path){
  capturing=true;
  spinner.grabToImage(result=>{check(result.saveToFile(path),"could not capture spinner");capturing=false;step++;});
 }
 Timer{id:driver;interval:40;running:true;repeat:true;onTriggered:{driver.stop();try{
  if(capturing)return;
  if(step===0){SpaceState.open("series",Quickshell.screens[0]);step++;return;}
  const page=host.currentPage;if(!page)return;
  const activity=find(host.contentItem,"spaceActivityIndicator"),spinner=find(host.contentItem,"movieLoadingIndicator");
  if(step===1){
   if(page.busy)return;
   retained=page;page.tab="episodes";page.loadEpisodes(false);started=Date.now();step++;return;
  }
  if(step===2){
   if(Date.now()-started<150)return;
   check(page.episodeLoading&&spinner.visible&&spinner.running,"episode request has no spinner");
   check(spinner.width===28&&spinner.height===28,"toolbar ring has no size");
   check(spinnerCount(host.contentItem)===1,"episode request has duplicate or missing page spinners");
   check(activity.tooltipText==="Loading episodes…","tooltip does not describe current work");
   input.mouseMove(activity,14,14);capture(spinner,LOADING_IMAGE);return;
  }
  if(step===3){
   const tooltip=find(activity,"spaceActivityTooltip");if(!tooltip.visible)return;
   check(tooltip.text==="Loading episodes…","hover tooltip lost current request");
   SpaceState.hide();check(!spinner.visible&&!spinner.running&&!tooltip.visible&&!activity.tooltipText,"hidden page kept activity");
   SpaceState.open("series",Quickshell.screens[0]);started=Date.now();step++;return;
  }
  if(step===4){
   if(Date.now()-started<150)return;
   check(page===retained&&page.episodeLoading,"restore lost pending episode request");
   check(spinnerCount(host.contentItem)===1,"restore has duplicate or missing spinner");
   capture(spinner,RESTORED_IMAGE);return;
  }
  if(step===5){
   if(page.episodeLoading)return;
   check(page.episodes.length===1&&!spinner.visible&&!spinner.running&&!activity.tooltipText,"completed episode request kept activity");
   SpaceState.close("series");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",step,error.message);Qt.quit();}finally{driver.restart();}}}
 Timer{interval:10000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout",step);Qt.quit();}}
}'''.replace('LOADING_IMAGE', json.dumps(str(pictures[0])))
                 .replace('RESTORED_IMAGE', json.dumps(str(pictures[1]))), setup=delayed_setup)
            for path in pictures:
                image = QImage(str(path))
                self.assertFalse(image.isNull(), path.name)
                red = sum(image.pixelColor(x,y).alpha() > 128
                          and image.pixelColor(x,y).red() > 150
                          and image.pixelColor(x,y).green() < 80
                          and image.pixelColor(x,y).blue() < 80
                          for x in range(image.width()) for y in range(image.height()))
                self.assertGreater(red, 30, f'{path.name}: visible/running spinner rendered blank')

    def test_seasons_ratings_and_independent_hide_restore_close(self):
        self.run_qml('''import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "ui"
import "spaces/movies"
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
 FloatingWindow {id:drawerWindow;implicitWidth:480;implicitHeight:900;visible:true
  SpacesDrawer {id:drawer;anchors.fill:parent;active:drawerWindow.visible;screen:Quickshell.screens[0];service:session}
 }
 property int step:0
 property var seriesPage:null
 property var moviesPage:null
 function check(v,m){if(!v)throw new Error(m);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function checkRatings(item){
  if(item.objectName.startsWith("rating:")){
   const row=item.contentItem;
   check(row.children[1].x-row.children[0].x-row.children[0].width===6,"rating icon/score gap stretched");
   check(item.width<105,"rating pair too wide: " + item.width + " content " + row.implicitWidth);
  }
  for(const child of item.children??[])checkRatings(child);
 }
 Timer {interval:60;running:true;repeat:true;onTriggered:{try{
  if(root.step===0){
   const entry=find(drawer,"space:series");input.mouseClick(entry,entry.width/2,entry.height/2);
   check(SpaceState.runningIds.includes("series"),"drawer cannot open series");drawerWindow.visible=false;root.step++;return;
  }
  const page=host.currentPage;
  if(!page||page.busy)return;
  if(root.step===1){
   root.seriesPage=page;check(page.kind==="tv"&&page.spaceId==="series","wrong kind/namespace");
   check(page.titles.length===1&&page.selected.title==="Fixture series","series catalogue missing");
   check(!page.gridMode,"initial layout differs from Movies");
   check(page.seasons.length===2,"seasons missing");
   checkRatings(page);
   const episodesTab=find(host.contentItem,"episodesTab");check(episodesTab.visible,"episodes tab hidden");
   input.mouseClick(episodesTab,episodesTab.width/2,episodesTab.height/2);root.step++;return;
  }
  if(root.step===2){
   check(page.episodes.length===1&&page.episodes[0].season==="1","first season missing");
   const picker=find(page,"seasonPicker");picker.currentIndex=1;picker.activated(1);root.step++;return;
  }
  if(root.step===3){
   check(page.episodes[0].season==="2","season switch missing");
   const toggle=find(host.contentItem,"catalogueLayoutToggle");input.mouseClick(toggle,toggle.width/2,toggle.height/2);page.save({favorite:true});
   SpaceState.open("movies",Quickshell.screens[0]);root.step++;return;
  }
  if(root.step===4){
   root.moviesPage=page;check(page.kind==="movie"&&page.selected.title==="Fixture movie","Movies disturbed");
   check(!root.seriesPage.active&&SpaceState.runningIds.length===2,"switch disposed series");
   check(page.gridMode===false,"Series preferences leaked into Movies");
   SpaceState.open("series",Quickshell.screens[0]);root.step++;return;
  }
  if(root.step===5){
   check(page===root.seriesPage&&page.gridMode&&page.tab==="episodes"&&page.episodes[0].season==="2","restore lost Series state");
   page.searchOpen=true;host.escapeHandler();check(host.opened&&!page.searchOpen,"Escape priority broken");
   host.escapeHandler();check(!host.opened&&SpaceState.runningIds.length===2,"hide disposed instances");
   drawerWindow.visible=true;input.wait(30);
   const close=find(drawer,"closeSpace:series");check(close.visible,"Series close absent");
   input.mouseClick(close,close.width/2,close.height/2);
   check(SpaceState.runningIds.length===1&&!host.opened,"drawer close disturbed Movies or opened Series");drawerWindow.visible=false;
   SpaceState.open("movies",Quickshell.screens[0]);root.step++;return;
  }
  if(root.step===6){check(page===root.moviesPage,"close recreated Movies");SpaceState.open("series",Quickshell.screens[0]);root.step++;return;}
  if(root.step===7){
   check(page!==root.seriesPage&&page.personal.favorite,"fresh open lost Series favorite");
   check(page.gridMode,"Series preference not restored");
   check(page.tab==="overview","fresh open reused disposed navigation");
   SpaceState.close("movies");SpaceState.close("series");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}''', setup=setup)
