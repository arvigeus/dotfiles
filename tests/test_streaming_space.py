"""Real retained Space integration, asynchronous detail selection and hidden jobs."""

import unittest
import support
from test_streaming import RAW
from test_movies_space import setup as movies_setup


def setup(root):
    movies_setup(root)
    image = root / 'frame.ppm'
    image.write_bytes(b'P6\n16 9\n255\n' + bytes((70, 35, 100)) * 144)
    path = root / 'spaces/streaming/backend.py'
    fixture = """    import time
    fixture = FIXTURE
    backend = StreamingBackend()
    backend.key_path.parent.mkdir(parents=True, exist_ok=True)
    backend.key_path.write_text("fixture")
    def details(identity):
        time.sleep(.08)
        if identity == "fixture0000":
            raise StreamingError("Metadata temporarily unavailable")
        return dict(record(dict(fixture, id=identity)), backdrop=FRAME, thumbnail=FRAME)
    backend.commands.details = details
    def extract(target, **kwargs):
        return dict(entries=[dict(fixture, id="fixture%04d" % index, title="Video " + str(index), availability="subscriber_only" if index == 2 else "public") for index in range(24)])
    backend.commands.extract = extract
    def posts(channel, page):
        return dict(items=[dict(id="UgFixturePost000000000", url="https://www.youtube.com/post/UgFixturePost000000000", creator="Fixture creator", channel=channel["url"], channelId="", followedChannelUrl=channel["url"], avatar=FRAME, text="A creator update", published="1 day ago", timestamp=10, likes="4", images=[], poll=["Option one","Option two"], votes="20 votes", videos=[])], more=False)
    backend.posts.page = posts
    original_browse = backend.browse
    def browse(request):
        result = original_browse(request)
        result["items"] = [dict(row, backdrop=FRAME, thumbnail=FRAME) for row in result["items"]]
        return result
    backend.browse = browse
    class FixturePlayer:
        def __init__(self): self.playing = False
        def start(self, item, local, audio, start):
            self.playing = True; self.started = time.monotonic()
            return dict(playing=True, connecting=True, id=item["id"])
        def status(self): return dict(playing=self.playing, connecting=time.monotonic()-self.started < .2 if self.playing else False)
        def stop(self): self.playing=False
    backend.player = FixturePlayer()
    def generate(*args, **kwargs):
        time.sleep(.3)
        return "A useful summary at 01:00."
    insights.generate = generate
""".replace('FIXTURE', repr(RAW)).replace('FRAME', repr(image.as_uri()))
    path.write_text(
        path.read_text().replace('    backend = StreamingBackend()\n', fixture)
    )


def pagination_setup(root):
    setup(root)
    path = root / 'spaces/streaming/backend.py'
    source = path.read_text()
    fixture = """    previous_extract = backend.commands.extract
    def paged_extract(target, **options):
        if "paging" not in target and "failing" not in target:
            return previous_extract(target, **options)
        start = options.get("start", 1)
        if "failing" in target and start > 1:
            raise StreamingError("Fixture next-page failure")
        count = 24 if start < 49 else 6
        return dict(entries=[dict(fixture, id="paging%05d" % index, title="Video " + str(index)) for index in range(start, start + count)])
    backend.commands.extract = paged_extract
    original_posts = backend.posts.page
    def paged_posts(channel, page):
        item = original_posts(channel, page)["items"][0]
        return dict(items=[dict(item, id="UgPagingPost%012d" % index, avatar=item["avatar"] if index % 2 else "", poll=[], text="A paged creator update.\\nMore details about the update.") for index in range(page*12+1, page*12+13)], more=page < 2, pageKey="posts-"+str(page))
    backend.posts.page = paged_posts
"""
    path.write_text(
        source.replace(
            '    backend.posts.page = posts\n',
            '    backend.posts.page = posts\n' + fixture,
        )
    )


@unittest.skipUnless(support.QS, 'Quickshell is required')
class StreamingSpaceTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_auto_paging_for_rail_grid_and_posts_preserves_scroll_and_stops_when_hidden_or_failed(
        self,
    ):
        self.run_qml(
            """import QtQuick
import Quickshell
import "ui"
ShellRoot {
 id:root
 InteractionState{id:interactions}
 SpaceHost{id:host;interactionState:interactions}
 property int stage:0
 property int ticks:0
 property int generation:0
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer{interval:100;repeat:true;running:true;onTriggered:{try{
  if(stage===0){SpaceState.open("streaming",Quickshell.screens[0]);stage++;return;}
  const page=host.currentPage;
  if(!page||!page.initialized||page.loading||page.detailLoading||page.commandPending)return;
  const rail=find(page,"streamingRail"),grid=find(page,"streamingGrid"),posts=find(page,"streamingPostsFeed");
  if(stage===1){page.notify=()=>{};page.handleOpen({url:"paging"});stage++;return;}
  if(stage===2){check(page.videos.length===24,"initial video page wrong");rail.positionViewAtEnd();stage++;return;}
  if(stage===3){
   if(page.page<1)return;
   check(page.videos.length===48&&rail.contentX>0,"rail did not append or lost scroll");
   page.toggleLayout();grid.positionViewAtEnd();stage++;return;
  }
  if(stage===4){
   if(page.page<2)return;
   check(page.videos.length===54&&!page.more,"grid did not load final page");
   page.handleOpen({url:"fixture"});page.toggleLayout();stage++;return;
  }
  if(stage===5){check(page.videos.length===23,"replay fixture wrong");rail.positionViewAtEnd();stage++;return;}
  if(stage===6){
   if(page.page<1)return;
   check(page.videos.length===23&&!page.more,"repeated source page did not stop");
   page.handleOpen({url:"failing"});stage=60;return;
  }
  if(stage===60){rail.positionViewAtEnd();stage++;return;}
  if(stage===61){
   if(!page.error)return;
   check(page.error.includes("next-page"),"append error missing");root.generation=page.browseGeneration;ticks=0;stage++;return;
  }
  if(stage===62){
   if(++ticks<4)return;
   check(page.browseGeneration===root.generation,"failed page retried automatically");page.subscribe("@fixture");stage=7;return;
  }
  if(stage===7){page.switchTab("posts");stage++;return;}
  if(stage===8){
   check(page.posts.length===12,"initial Posts page wrong");
   if(posts.contentHeight<=posts.height)return;
   const avatar=find(page,"streamingPostAvatar:UgPagingPost000000000001");
   if(!avatar||avatar.status!==Image.Ready)return;
   check(find(page,"streamingPostAvatarFallback:UgPagingPost000000000002").visible,"missing avatar has no fallback");
   posts.positionViewAtEnd();stage++;return;
  }
  if(stage===9){
   if(page.page<1)return;
   check(page.posts.length===24&&posts.contentY>0,"Posts did not append or lost scroll");
   SpaceState.hide();posts.positionViewAtEnd();ticks=0;stage++;return;
  }
  if(stage===10){
   if(++ticks<4)return;
   check(page.page===1&&page.posts.length===24,"hidden feed loaded another page");
   SpaceState.open("streaming",Quickshell.screens[0]);stage++;return;
  }
  if(stage===11){
   if(page.page<2)return;
   check(page.posts.length===36&&!page.more,"restored Posts feed did not reach its end");
   SpaceState.close("streaming");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL stage "+stage,error.message+" "+error.stack);Qt.quit();}}}
 Timer{interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout stage "+stage);Qt.quit();}}
}""",
            pagination_setup,
        )

    def test_search_details_channels_and_hidden_analysis(self):
        self.run_qml(
            """import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "ui"
ShellRoot {
 id:root
 InteractionState { id:interactions }
 SpaceHost { id:host; interactionState:interactions }
 TestCase { id:input; when:false; parent:host.contentItem }
 property int stage:0
 property var retained:null
 property int notifications:0
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer { id:driver; interval:100; repeat:true; running:true; onTriggered:{driver.stop();try{
  if(stage===0){check(SpaceState.open("streaming",Quickshell.screens[0]),"Streaming not registered");stage++;return;}
  if(stage===10){SpaceState.open("streaming",Quickshell.screens[0]);stage++;return;}
  const page=host.currentPage;
  if(!page||!page.initialized||page.loading||page.detailLoading||page.commandPending)return;
  if(stage===1){
   check(page.tab==="feed"&&!page.channels.length,"initial feed wrong");
   check(page.toolbarTarget.children.length>0,"toolbar not reparented");
   page.notify=()=>notifications++;
   page.handleOpen({url:"fixture"});stage++;return;
  }
  if(stage===2){
   check(page.videos.length===23,"search failed: "+page.error);
   page.select(page.videos[0]);page.select(page.videos[1]);stage++;return;
  }
  if(stage===3){
   check(page.selected.id==="fixture0001","stale details replaced selection");
   check(!page.gridMode&&find(page,"streamingRail").visible,"Movies rail is not the default");
   check(!find(page,"streamingQuality"),"standalone quality selector remains");
   const watch=find(page,"streamingPlay");check(watch.text==="Watch"&&watch.options===undefined,"quality selector remains");
   const activity=find(host.contentItem,"spaceActivityIndicator");
   page.notice="Saved to Music.";
   check(activity&&!activity.busy&&!activity.visible&&!activity.tooltipText,"completion remained in header");
   function banner(item){if(item.visible&&item.text==="Saved to Music.")return true;return Array.from(item.children||[]).some(banner);}
   check(!banner(page),"routine completion remains in the page");page.notice="";
   for(const id of ["search","downloads","saved","history"])check(!find(host.contentItem,"streamingTab:"+id),"removed tab remains: "+id);
   const discover=find(host.contentItem,"streamingTab:feed"),posts=find(host.contentItem,"streamingTab:posts");
   check(discover.text==="Discover"&&discover.iconName==="globe"&&posts.iconName==="file-text","Discover/Posts labels or icons missing");
   check(find(discover,"streamingTab:feedIcon").status===Image.Ready&&find(posts,"streamingTab:postsIcon").status===Image.Ready,"Discover/Posts icons did not load");
   check(!find(page,"streamingSave")&&page.save===undefined&&page.saved===undefined,"Watch Later functionality remains");
   check(!page.videos.some(video=>video.availability==="subscriber_only"),"members-only video remains");
   check(find(page,"streamingDetails").x<30,"rail details are not on the left");
   page.toggleLayout();input.wait(80);
   check(page.gridMode&&find(page,"streamingGrid").visible&&find(page,"streamingDetails").x>page.width*.5,"Movies split grid missing");
   page.detailTab="downloads";
   check(find(page,"streamingPlay").enabled&&find(page,"streamingAudio").enabled,"play/download actions missing");
   stage++;return;
  }
  if(stage===4){
   page.channelsOpen=true;check(page.dismissTransient()&&!page.channelsOpen,"channels Escape failed");
   page.subscribe("@fixture");stage++;return;
  }
  if(stage===5){
   check(page.channels.length===1&&find(page,"streamingSubscribe").text==="Unsubscribe","subscription action did not toggle");
   page.startJob("analyze",{videoId:page.selected.id});retained=page;stage++;return;
  }
  if(stage===6){
   check(page.jobsActive,"analysis not accepted");SpaceState.hide();stage++;return;
  }
  if(stage===7){
   if(retained.jobsActive)return;
   check(!retained.active&&retained.answer.includes("01:00")&&notifications===1,"hidden analysis lost result");
   SpaceState.open("streaming",Quickshell.screens[0]);stage++;return;
  }
  if(stage===8){
   check(page===retained&&page.selected.id==="fixture0001","hide destroyed view");
   check(page.detailTab==="summary","analysis did not open the Summary tab");
   check(page.dismissTransient()&&page.detailTab==="overview","detail tab Escape failed");
   page.switchTab("posts");stage++;return;
  }
  if(stage===9){
   check(page.posts.length===1,"Posts view missing");
   page.switchTab("feed");check(page.videos.length===23,"search view was not retained");
   SpaceState.close("streaming");stage++;return;
  }
  if(stage===11){
   check(page!==retained&&page.channels.length===1&&page.gridMode,"private state/layout not restored");
   page.notify=()=>{};page.handleOpen({url:"fixture"});stage++;return;
  }
  if(stage===12){
   check(page.detailError.includes("temporarily"),"metadata failure was not shown");
   find(page,"streamingPlay").clicked();stage++;return;
  }
  if(stage===13){
   if(page.playOpening)return;
   check(!host.opened&&page.playback.playing,"Watch did not launch after metadata failure");
   SpaceState.open("streaming",Quickshell.screens[0]);page.switchTab("posts");stage++;return;
  }
  if(stage===14){
   check(page.posts.length===1&&find(page,"streamingPostsFeed").visible,"combined Posts feed missing");
   const avatar=find(page,"streamingPostAvatar:UgFixturePost000000000");
   if(!avatar||avatar.status!==Image.Ready)return;
   check(!find(page,"streamingPostAvatarFallback:UgFixturePost000000000").visible,"loaded avatar retained placeholder");
   page.toggleSubscription(page.posts[0]);stage++;return;
  }
  if(stage===15){
   check(!page.channels.length&&!page.posts.length,"unsubscribe did not update Posts feed");
   page.subscribe("@fixture");stage++;return;
  }
  if(stage===16){
   check(page.posts.length===1&&page.followedChannel(page.posts[0]),"resubscribe did not restore Posts");
   SpaceState.close("streaming");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL stage "+stage,error.message+" "+error.stack);Qt.quit();}finally{driver.restart();}}}
 Timer{interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout stage "+stage);Qt.quit();}}
}""",
            setup,
        )


if __name__ == '__main__':
    unittest.main()
