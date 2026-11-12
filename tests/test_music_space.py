"""Music shares the retained host and list presentation, with owned hidden playback."""

import unittest
import support
from test_movies_space import setup as movies_setup


def setup(root):
    movies_setup(root)
    path = root / 'spaces/music/backend.py'
    fixture = """
_fixture_song = dict(id="1",kind="song",source="apple",title="Fixture song",artist="Fixture artist",album="Fixture album",duration=120)
_original_dispatch = dispatch
def dispatch(args):
    op = args["op"]
    if op == "search-page": return dict(items=[_fixture_song],limit=1,hasMore=False)
    if op == "genres": return [dict(id="1",name="Rock")]
    if op == "lyrics": return dict(available=True,lyrics="Fixture lyrics",provider="Fixture")
    if op == "download-capabilities": return dict(track=False,album=False)
    if op == "play":
        import time
        time.sleep(.15)
        # A path the backend never accepts: polls answer "not ready", cleanup is a no-op.
        return dict(command=["sleep","60"],ipcPath="/nonexistent/mpv-0123456789abcdef.sock")
    return _original_dispatch(args)
"""
    (root / 'spaces/music/cloud_fixture.py').write_text("""import json,sys
song=dict(id="cloud1",kind="song",source="nextcloud",account="fixture",title="Saved song",artist="Artist",artistIds=["a1"],album="Album",albumId="b1",duration=120)
for line in sys.stdin:
 r=json.loads(line);op=r["op"];result={}
 if op=="browse":
  items=[song] if r.get("query") else [dict(song,id=str(i),local=i==0) for i in range(r.get("offset",0),r.get("offset",0)+50)]
  result=dict(items=items,limit=r.get("offset",0)+50,hasMore=not r.get("query") and r.get("offset",0)<50)
 elif op=="cover":result=""
 elif op=="local-refresh":result=dict(version="fixture")
 elif op=="queue":result=dict(items=[song])
 elif op=="index-status":result=dict(ready=True,indexing=False,version="fixture")
 elif op=="entity-browse":
  items=[dict(id="b1",kind="album",source="nextcloud",account="fixture",title="Album",artist="Artist")] if r.get("category")=="albums" else [dict(song,title="Deep artist track" if r.get("query")=="deep" else "Artist track" if r["entity"]["kind"]=="artist" else "Album track")]
  result=dict(items=items,total=len(items),limit=len(items),hasMore=False)
 elif op=="artist":result=dict(artist=r["artist"],songs=[dict(song,title="Artist track")],albums=[dict(id="b1",kind="album",source="nextcloud",account="fixture",title="Album",artist="Artist")])
 elif op=="album":result=dict(album=r["album"],songs=[dict(song,title="Album track")])
 elif op=="genres":result=[dict(id="Rock",name="Rock")]
 if isinstance(result,dict) and op!="index-status":result.update(index=dict(ready=True,indexing=False,version="fixture"),cached=True)
 print(json.dumps(dict(id=r["id"],result=result)),flush=True)
""")
    (root / 'spaces/music/artwork.py').write_text(
        "import json,sys\nfor line in sys.stdin:\n r=json.loads(line);print(json.dumps(dict(id=r['id'],result='')),flush=True)\n"
    )
    main = root / 'spaces/music/Main.qml'
    text = main.read_text()
    for old, new in (
        ('backend: "cloud.py"', 'backend: "cloud_fixture.py"'),
        # Fixtures must never reach the session's notification server.
        (
            'property var deliverNotification: (title, body) => Quickshell.execDetached([',
            'property var deliverNotification: (title, body) => console.log("NOTIFY", [',
        ),
    ):
        assert text.count(old) == 1, 'Main.qml changed; update the fixture: ' + old
        text = text.replace(old, new)
    main.write_text(text)
    source = path.read_text()
    assert source.count('\ndef main():') == 1, 'backend.py changed; update the fixture'
    path.write_text(source.replace('\ndef main():', fixture + '\ndef main():'))


@unittest.skipUnless(support.QS, 'Quickshell required')
class MusicSpaceTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_two_tabs_context_search_infinite_loading_navigation_pickers_and_lifecycle(
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
 property var retained:null
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer {id:driver;interval:100;repeat:false;running:true;onTriggered:{try{
  if(root.step===0){check(SpaceState.open("music",Quickshell.screens[0]),"Music missing");root.step++;return;}
  const page=host.currentPage;
  if(!page||(SpaceState.currentId==="music"&&(!page.initialized||page.loading)))return;
  if(root.step===1){
   check(page.section==="library"&&page.rows.length===50,"Nextcloud library missing: "+page.error);
   const toolbar=find(host.contentItem,"musicToolbar"),hide=find(host.contentItem,"hideSpace");
   check(find(toolbar,"musicLibraryTab")&&find(toolbar,"musicDiscoverTab")&&!find(toolbar,"musicSection"),"wrong top navigation");
   check(Math.abs(toolbar.mapToItem(host.contentItem,0,0).y+toolbar.height/2-hide.mapToItem(host.contentItem,0,0).y-hide.height/2)<1,"toolbar not beside X");
   check(find(host.contentItem,"musicBackground").color.toString()==="#000000","background not black");
   find(page,"musicList").positionViewAtEnd();root.step++;return;
  }
  if(root.step===2){
   if(page.rows.length<100)return;
   check(page.rows.length===100,"infinite library page missing");
   find(page,"musicList").positionViewAtBeginning();input.wait(40);
   const info0=find(page,"musicInfo:0"),info1=find(page,"musicInfo:1");
   check(info0.mapToItem(page,0,0).x===info1.mapToItem(page,0,0).x,"cached song moved Info column");
   check(find(page,"musicDuration:0").mapToItem(page,0,0).x===find(page,"musicDuration:1").mapToItem(page,0,0).x,"cached song moved duration column");
   check(!find(page,"musicDownload:0").visible&&find(page,"musicDownload:1").visible&&find(page,"musicDownloadSlot:0").width===find(page,"musicDownloadSlot:1").width,"download space collapsed");
   page.searchOpen=true;input.wait(30);
   const search=find(host.contentItem,"musicSearch");
   check(!find(host.contentItem,"musicArtists").visible&&!find(host.contentItem,"musicAlbums").visible&&!find(host.contentItem,"musicPlaylists").visible,"library filters open by default");
   input.mouseClick(find(host.contentItem,"musicFilters"));
   check(find(host.contentItem,"musicArtists").visible&&find(host.contentItem,"musicAlbums").visible&&find(host.contentItem,"musicPlaylists").visible,"library pickers missing");
   check(!find(host.contentItem,"musicFavoritesFilter"),"favorites still visible");
   search.text="saved";page.browse(false);root.step++;return;
  }
  if(root.step===3){
   check(page.rows.length===1&&page.rows[0].source==="nextcloud","library search escaped its source");
   root.step++;return;
  }
  if(root.step===4){page.changeSection("discover");root.step++;return;}
  if(root.step===5){
   check(page.rows.length===1&&page.rows[0].source==="apple"&&!find(host.contentItem,"musicSearch").text,"Discover did not restore its own state: "+JSON.stringify(page.rows)+" / "+find(host.contentItem,"musicSearch").text+" / "+page.error);
   check(!find(host.contentItem,"musicPendingFilter").visible&&!find(host.contentItem,"musicPlaylists").visible,"library controls visible in Discover");page.searchOpen=true;find(host.contentItem,"musicSearch").text="catalogue";page.browse(false);root.step++;return;
  }
  if(root.step===6){page.changeSection("library");root.step++;return;}
  if(root.step===7){
   check(find(host.contentItem,"musicSearch").text==="saved"&&page.rows[0].source==="nextcloud","tab switch lost library search");
   page.openArtist(page.rows[0]);root.step++;return;
  }
  if(root.step===8){
   check(page.entity.kind==="artist"&&page.rows[0].title==="Artist track","artist songs missing");
   find(host.contentItem,"musicSearch").text="deep";page.browse(false);root.step=18;return;
  }
  if(root.step===18){check(page.rows[0].title==="Deep artist track","search did not use full indexed artist catalogue");find(host.contentItem,"musicSearch").clear();page.changeCategory("albums");root.step=9;return;}
  if(root.step===9){check(page.rows[0].kind==="album","artist albums missing");page.select(page.rows[0]);root.step++;return;}
  if(root.step===10){check(page.entity.kind==="album"&&page.rows[0].title==="Album track","album songs missing");page.back();page.back();root.step++;return;}
  if(root.step===11){
   check(!page.entity&&find(host.contentItem,"musicSearch").text==="saved","Back lost search context");
   Theme.setMode("light");input.mouseClick(find(host.contentItem,"musicArtists"));input.wait(20);const picker=Array.from(page.data).find(item=>item.objectName==="musicPicker");check(picker.width>=300,"picker collapsed to its button width");host.escapeHandler();check(host.opened,"picker Escape hid Music");
   host.escapeHandler();host.escapeHandler();check(host.opened,"search Escape hid Music");
   root.retained=page;page.select(page.rows[0]);root.step++;return;
  }
  if(root.step===12){
   const playback=Array.from(page.data).find(item=>item.objectName==="musicPlayback");if(!playback.playerProcess)return;
   check(Array.from(playback.data).find(item=>item.objectName==="musicStatusTimer").running,"visible playback is not polled");
   host.dismiss();check(SpaceState.runningIds.includes("music")&&playback.playerProcess.running,"hide stopped playback");
   check(!find(host.contentItem,"musicLoadingIndicator").running&&!Array.from(playback.data).find(item=>item.objectName==="musicStatusTimer").running,"hidden visual polling continued");
   SpaceState.open("music",Quickshell.screens[0]);check(host.currentPage===root.retained,"restore replaced Music");
   playback.stopPlayback();page.select(page.rows[0]);playback.stopPlayback();root.step++;return;
  }
  if(root.step===13){input.wait(250);check(!Array.from(page.data).find(item=>item.objectName==="musicPlayback").playerProcess,"late resolution restarted player");SpaceState.open("movies",Quickshell.screens[0]);root.step++;return;}
  if(root.step===14){if(SpaceState.currentId!=="movies")return;SpaceState.close("music");check(host.opened&&host.currentPage===page,"closing Music disturbed Movies");SpaceState.open("music",Quickshell.screens[0]);root.step++;return;}
  if(root.step===15){check(page!==root.retained&&page.section==="library","fresh instance failed");SpaceState.close("music");SpaceState.close("movies");console.log("DISPLAY_PASS");Qt.quit();}
 }catch(error){console.error("DISPLAY_FAIL",error.message+" "+error.stack);Qt.quit();}finally{driver.restart();}}}
 Timer {interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout at "+root.step);Qt.quit();}}
}""",
            setup=setup,
        )

    def test_saved_view_and_library_warnings_are_inline_without_stopping_paging(self):
        def setup_warnings(root):
            setup(root)
            cloud = root / 'spaces/music/cloud_fixture.py'
            source = cloud.read_text()
            browse = 'result=dict(items=items,limit=r.get("offset",0)+50,hasMore=not r.get("query") and r.get("offset",0)<50)'
            local = 'elif op=="local-refresh":result=dict(version="fixture")'
            self.assertEqual((source.count(browse), source.count(local)), (1, 1))
            cloud.write_text(
                source.replace(
                    browse,
                    browse[:-1]
                    + ',warning="Nextcloud is unavailable. Showing the saved library view.")',
                ).replace(
                    local,
                    local[:-1] + ',warning="2 local audio file(s) could not be read.")',
                )
            )

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
 Timer {id:driver;interval:100;repeat:false;running:true;onTriggered:{try{
  if(root.step===0){check(SpaceState.open("music",Quickshell.screens[0]),"Music missing");root.step++;return;}
  const page=host.currentPage;
  if(!page||!page.initialized||page.loading)return;
  const message=find(page,"musicMessage");
  if(root.step===1){
   if(page.rows.length!==50||!page.libraryWarning)return;
   check(page.error===""&&message.visible,"warnings hidden or treated as errors");
   check(message.text.includes("saved library view")&&message.text.includes("could not be read"),"warning text missing: "+message.text);
   find(page,"musicList").positionViewAtEnd();root.step++;return;
  }
  if(root.step===2){
   // A persistent library warning must not stop infinite loading.
   if(page.rows.length<100)return;
   input.mouseClick(find(host.contentItem,"musicDiscoverTab"));root.step++;return;
  }
  if(root.step===3){
   if(page.section!=="discover")return;
   check(!message.text.includes("could not be read"),"library warning shown outside My Library");
   SpaceState.close("music");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",error.message);Qt.quit();}finally{driver.restart();}}}
 Timer {interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout",root.step);Qt.quit();}}
}
""",
            setup=setup_warnings,
        )

    def test_information_view_edit_cover_save_and_move_are_separate(self):
        def info_setup(root):
            setup(root)
            from PySide6.QtGui import QImage

            image = QImage(64, 64, QImage.Format.Format_RGB32)
            image.fill(0xFF0066AA)
            image.save(str(root / 'cover.png'))
            (root / 'covers').mkdir()
            image.save(str(root / 'covers/cover.png'))
            (root / 'spaces/music/artwork.py').write_text(
                "import json,sys\nfrom pathlib import Path\nfor line in sys.stdin:\n r=json.loads(line);print(json.dumps(dict(id=r['id'],result=(Path(__file__).parents[2]/'cover.png').as_uri())),flush=True)\n"
            )
            (root / 'spaces/music/local_files.py').write_text("""import json,sys
jobs=[];tags={"title":"Saved song","artist":"Artist","album":"Album","lyrics":""}
for line in sys.stdin:
 r=json.loads(line);op=r['op'];result={}
 if op=='states':result=[]
 elif op=='jobs':result=dict(jobs=jobs)
 elif op=='file-job':
  action=r['action'];rel=r.get('relativePath',r.get('song',{}).get('serverPath','/album/song.flac').lstrip('/'))
  if action=='save':
   assert 'relativePath' not in r,'Save must not move the file'
   assert 'playCount' not in r['tags'],'Save must not edit play count'
   tags.update(r['tags'])
  if action=='move':assert 'tags' not in r and 'artwork' not in r,'Move must not edit metadata'
  value=dict(action=action,path='/home/fixture/Music/'+rel,synced=action!='info',relativePath=rel,local=action!='move',tags=dict(tags),signature=str([1,2,len(jobs)]),pendingUpload=False,fileInfo='FLAC · 24-bit · 96 kHz · Stereo')
  identifier=str(len(jobs));jobs.append(dict(job_id=identifier,title='Fixture',state='finished',result=value));result=dict(job_id=identifier)
 print(json.dumps(dict(id=r['id'],result=result)),flush=True)
""")

        self.run_qml(
            """//@ pragma UseQApplication
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Window
import QtTest
import Quickshell
import "ui"
ShellRoot {
 id:root
 InteractionState {id:interactions}
 SpaceHost {id:host;interactionState:interactions}
 TestCase {id:input;when:false;parent:host.contentItem}
 QtObject {
  id:preview;property int reads:0;property int lyricReads:0;property int fileReads:0
  function request(op,args,callback){
   if(op==="song-info"){reads++;Qt.callLater(()=>callback({song:{playCount:17},tags:{title:"Saved song",artist:"Artist",album:"Album",lyrics:""},relativePath:"album/song.flac"},""));}
   else if(op==="file-tags"){fileReads++;Qt.callLater(()=>callback({tags:{title:"Saved song",artist:"Artist",album:"Album",comment:"Existing comment",lyrics:"Embedded lyrics"},fileInfo:"FLAC · 24-bit · 96 kHz · Stereo"},""));}
   else if(op==="lyrics"){lyricReads++;Qt.callLater(()=>callback({available:true,lyrics:"Fetched lyrics",provider:"Fixture"},""));}
  }
 }
 property int step:0
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function click(item){input.mouseClick(item,item.width/2,item.height/2);}
 function type(item,value){item.forceActiveFocus();input.keyClick(Qt.Key_A,Qt.ControlModifier);for(const c of value)input.keyClick(c);}
 Timer {id:driver;interval:80;repeat:false;running:true;onTriggered:{try{
  if(root.step===0){SpaceState.open("music",Quickshell.screens[0]);root.step++;return;}
  const page=host.currentPage;if(!page||!page.initialized||page.loading)return;
  const info=Array.from(page.data).find(item=>item.objectName==="musicInformation");
  const files=Array.from(page.data).find(item=>item.objectName==="musicFileService");
  if(root.step===1){info.catalogue=preview;info.showSong({id:"server-song",source:"nextcloud",kind:"song",account:"fixture",title:"Saved song"});root.step++;return;}
  if(info.busy||info.reading)return;
  if(root.step===2){
   if(info.loadingTags||!find(info.contentItem,"musicInfoCover").imageReady)return;
   check(!info.editing&&!info.dirty&&files.jobs.length===0,"viewing prepared a local file");
   check(preview.reads===1&&preview.lyricReads===0,"lyrics fetched automatically");
   check(preview.fileReads===1&&info.draft.comment==="Existing comment"&&info.draft.lyrics==="Embedded lyrics","Info did not load embedded metadata");
   const subtitle=find(info.contentItem,"musicFileInfo");check(subtitle.text===info.fileInfo+" · 17 plays"&&subtitle.parent.objectName==="musicInfoHeading","server play count missing from header");
   info.song=Object.assign({},info.song,{playCount:0});check(subtitle.text===info.fileInfo+" · 0 plays","zero play count hidden");
   info.song=Object.assign({},info.song,{playCount:1});check(subtitle.text===info.fileInfo+" · 1 play","singular play count incorrect");
   info.song=Object.assign({},info.song,{playCount:null});check(subtitle.text===info.fileInfo,"missing count shown as zero");
   info.song=Object.assign({},info.song,{playCount:17});
   const comment=find(info.contentItem,"musicTag:comment");check(comment.parent.visible&&comment.readOnly&&comment.placeholderText,"missing fields are hidden or editable");
   check(find(info.contentItem,"musicTag:title").readOnly&&find(info.contentItem,"musicLyrics").readOnly,"preview fields editable");
   check(info.relativePath==="album/song.flac"&&!find(info.contentItem,"musicMovePath").readOnly,"server path missing");
   check(!find(info.contentItem,"musicChooseCover").visible,"cover edit shown in view mode");
   click(find(info.contentItem,"musicInfoCover"));input.wait(30);check(!info.coverPicker.visible&&!info.busy,"cover image opened a blocker");
   click(find(info.contentItem,"musicFetchLyrics"));root.step++;return;
  }
  if(root.step===3){
   if(info.lookingUp||info.loadingTags)return;check(info.draft.lyrics==="Fetched lyrics"&&info.dirty&&info.editing&&preview.lyricReads===1,"fetched lyrics did not enable saving");
   check(files.jobs.length===0,"Fetching lyrics prepared an audio file");root.step++;return;
  }
  if(root.step===4){
   check(info.editing&&!find(info.contentItem,"musicTag:title").readOnly,"Edit did not enable metadata");
   check(preview.fileReads===1,"Edit reread already loaded metadata");
   check(find(info.contentItem,"musicFileInfo").text===info.fileInfo+" · 17 plays"&&info.draft.playCount===undefined,"editing changed play count or made it a tag");
   const header=find(info.contentItem,"musicInfoHeader"),heading=find(info.contentItem,"musicInfoHeading");
   check(find(info.contentItem,"musicCancelMetadata").parent===header&&find(info.contentItem,"musicCancelMetadata").text==="Cancel"&&!find(info.contentItem,"musicEditMetadata"),"Edit did not become Cancel in the header");
   check(find(info.contentItem,"musicSaveTags").parent===header,"Save is outside the header");
   check(find(info.contentItem,"musicFileInfo").parent===heading&&find(info.contentItem,"musicFileInfo").visible&&find(info.contentItem,"musicInfoTitle").text==="Song information","file details are not the subtitle");
   check(find(info.contentItem,"musicMovePath").readOnly&&!find(info.contentItem,"musicMove").enabled,"editing allows moving");
   check(info.draft.lyrics==="Fetched lyrics"&&info.dirty,"explicit lyrics were lost on editing");
   info.jobId="expected";info.busy=true;files.jobRequests.other={args:{action:"save"}};
   files.jobFinished({job_id:"other",state:"finished",result:{action:"save"}});
   check(info.busy&&info.jobId==="expected","unrelated job completed Info");info.busy=false;info.jobId="";delete files.jobRequests.other;
   const cover=find(info.contentItem,"musicChooseCover");check(cover.visible,"cover pencil missing in edit mode");
   check(cover.contentItem.width>=20&&cover.contentItem.height>=20,"cover pencil squeezed by button padding: "+cover.contentItem.width+"x"+cover.contentItem.height);
   input.mouseMove(heading,heading.width/2,heading.height/2);input.wait(180);
   check(cover.background.color.a===0,"cover pencil has an idle background");
   input.mouseMove(cover,cover.width/2,cover.height/2);input.wait(180);
   check(cover.background.color.a>0,"cover pencil has no hover background");
   check((info.coverPicker.options & FileDialog.DontUseNativeDialog)!==0&&info.coverPicker.popupType===Popup.Item,"picker can escape the shell layer");
   const previousPalette=String(info.parent.Window.window.palette.window);
   click(cover);input.wait(30);check(info.coverPicker.visible,"pencil did not open picker");input.keyClick(Qt.Key_Escape);input.wait(30);
   check(info.visible&&info.editing&&!info.coverPicker.visible,"Escape did not just close picker");
   check(String(info.parent.Window.window.palette.window)===previousPalette,"closing the picker changed the shell palette");
   click(cover);input.wait(30);host.dismiss();input.wait(30);check(!info.visible&&!info.coverPicker.visible,"hide left a modal picker");
   SpaceState.open("music",Quickshell.screens[0]);info.showSong(info.song);input.wait(30);
   info.coverPicker.currentFolder="file://"+Quickshell.shellPath("covers");click(cover);input.wait(100);
   const choices=find(info.parent.Window.window.contentItem,"fileDialogListView");check(choices&&choices.count===1,"cover folder missing");
   check(choices.palette.window===info.palette.window&&choices.palette.text===info.palette.text,"cover picker does not inherit the Music palette: "+choices.palette.window+" / "+info.palette.window);
   const image=choices.itemAtIndex(0);input.mouseDoubleClickSequence(image,image.width/2,image.height/2);input.wait(60);
   check(!info.coverPicker.visible&&!!info.coverDraft,"cover selection missing");
   type(find(info.contentItem,"musicTag:title"),"Edited title");
   const count=files.jobs.length;info.run("move");check(files.jobs.length===count,"Move ran during editing");
   click(find(info.contentItem,"musicSaveTags"));root.step++;return;
  }
  if(root.step===5){
   check(!info.editing&&!info.dirty&&!info.coverDraft&&info.draft.title==="Edited title"&&!info.song.notUploaded,"Save did not return to read-only mode");
   check(info.relativePath==="album/song.flac"&&files.jobs.length===1,"Save moved or re-prepared the file");
   type(find(info.contentItem,"musicMovePath"),"album/renamed.flac");check(find(info.contentItem,"musicMove").enabled&&!find(info.contentItem,"musicEditMetadata").enabled,"path draft can mix with metadata editing");
   click(find(info.contentItem,"musicMove"));root.step++;return;
  }
  if(root.step===6){
   check(info.relativePath==="album/renamed.flac"&&!info.editing&&!info.song.local&&files.jobs.length===2,"Move downloaded or edited the song");
   check(preview.lyricReads===1,"Save or Move fetched lyrics");
   click(find(info.contentItem,"musicInfoCover"));input.wait(30);check(!info.coverPicker.visible,"read-only cover is clickable after save");
   info.prepare();root.step=7;return;
  }
  if(root.step===7){
   click(find(info.contentItem,"musicCancelMetadata"));
   check(!info.editing&&find(info.contentItem,"musicTag:title").readOnly&&find(info.contentItem,"musicEditMetadata"),"header Cancel did not restore viewing mode");
   find(info.contentItem,"musicLyrics").forceActiveFocus();input.keyClick(Qt.Key_Escape);input.wait(30);check(host.opened&&!info.visible,"Info Escape hid Music");
   info.showSong(info.song);info.prepare();root.step=8;return;
  }
  if(root.step===8){
   const window=info.parent.Window.window,previousPalette=String(window.palette.window);
   click(find(info.contentItem,"musicChooseCover"));input.wait(30);check(info.coverPicker.visible,"picker did not reopen");
   SpaceState.close("music");input.wait(30);
   check(String(window.palette.window)===previousPalette,"destroying Music with the picker open retained its palette");
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",error.message+" "+error.stack);Qt.quit();}finally{driver.restart();}}}
 Timer {interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout at "+root.step);Qt.quit();}}
}""",
            setup=info_setup,
        )

    def test_immediate_editing_merges_late_tags_and_saves_only_explicit_changes(self):
        self.run_qml(
            """import QtQuick
import Quickshell
import "spaces/music"
ShellRoot {
 id:root
 property var previews:[]
 property var tags:[]
 property var lyrics:[]
 property var saves:[]
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 QtObject {id:fileService;function startJob(op,args,accepted){root.saves=root.saves.concat([args]);accepted("job","");}}
 QtObject {id:catalogue;function request(op,args,callback){
  if(op==="song-info")root.previews=root.previews.concat([callback]);
  else if(op==="file-tags")root.tags=root.tags.concat([callback]);
  else if(op==="lyrics")root.lyrics=root.lyrics.concat([callback]);
  else throw new Error("Unexpected request "+op);
 }}
 FloatingWindow {id:window;visible:true;implicitWidth:1000;implicitHeight:950
  MusicInfo {id:info;parent:window.contentItem;files:fileService;catalogue:catalogue}
 }
 Timer {interval:50;running:true;onTriggered:{try{
  info.showSong({id:"one",source:"nextcloud",serverPath:"/one.flac",title:"Preview title"});
  check(!info.editing&&info.loadingTags&&root.tags.length===1,"Info did not start its background metadata read");
  info.prepare();
  check(info.editing&&info.reading&&info.loadingTags&&!info.busy,"Edit waited for a file or preview");
  check(!find(info.contentItem,"musicTag:title").readOnly&&!find(info.contentItem,"musicTag:comment").readOnly,"loading fields blocked editing");
  check(root.saves.length===0&&root.lyrics.length===0,"Edit downloaded a song or fetched lyrics");
  info.editTag("title","My title");info.editTag("comment","");
  check(Object.keys(info.changes).length===2&&info.changes.comment==="","clearing an unknown comment was lost");
  root.tags[0]({tags:{title:"File title",comment:"Existing comment",composer:"Existing composer",lyrics:"Embedded lyrics"},signature:"[1, 2, 3]",fileInfo:"FLAC · 24-bit · 96 kHz"},"");
  check(info.draft.title==="My title"&&info.draft.comment===""&&info.draft.composer==="Existing composer","late tags overwrote an edit or failed to fill an untouched field");
  root.previews[0]({tags:{title:"Late API title",comment:""},knownFields:["title"],relativePath:"one.flac",fileInfo:"FLAC · 320 kbps"},"");
  check(info.draft.title==="My title"&&info.original.title==="File title","late preview replaced file tags");
  check(info.draft.lyrics==="Embedded lyrics"&&info.fileInfo==="FLAC · 24-bit · 96 kHz","late API response replaced embedded lyrics or format details");
  info.run("save");
  check(root.saves.length===1&&root.saves[0].tags.title==="My title"&&root.saves[0].tags.comment===""&&Object.keys(root.saves[0].tags).length===2,"Save included untouched or unknown fields");
  info.complete({},"Save failed");check(info.dirty&&info.draft.title==="My title","failure lost the draft");
  info.cancelEdits();info.prepare();info.loadFileTags();info.editTag("comment","New comment");
  info.run("save");
  root.tags[1]({tags:{comment:"Stale comment"}},"");
  check(info.draft.comment==="New comment","a superseded tag read changed a saving draft");
  info.complete({action:"save",synced:false,error:"Upload failed",path:"/fixture/one.flac",relativePath:"one.flac",tags:{title:"File title",comment:"New comment",lyrics:""},signature:"[4, 5, 6]"},"");
  check(!info.dirty&&info.editing&&info.song.pendingUpload&&find(info.contentItem,"musicSaveTags").enabled,"upload failure was not retryable");
  info.run("save");check(Object.keys(root.saves[2].tags).length===0,"retry rewrote tags");
  info.complete({action:"save",synced:true,relativePath:"one.flac",tags:{title:"File title",comment:"New comment",lyrics:""}},"");
  check(!info.editing&&!info.dirty,"retry did not settle the editor");
  info.showSong({id:"two",source:"nextcloud",serverPath:"/two.flac",title:"Second"});
  root.previews[1]({tags:{title:"Second"}},"");info.prepare();
  check(root.lyrics.length===0,"entering editing fetched lyrics");
  info.lookupLyrics();info.editTag("lyrics","Manual lyrics");
  root.lyrics[0]({available:true,lyrics:"Fetched lyrics"},"");
  check(info.draft.lyrics==="Manual lyrics"&&!info.lookingUp,"late lyrics replaced manual edits");
  info.cancelEdits();root.tags[2]({tags:{comment:"Cancelled read"}},"");
  check(!info.editing&&!info.dirty&&info.draft.comment==="Cancelled read","cancel stopped Info from loading metadata or restored discarded edits");
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(error){console.error("DISPLAY_FAIL",error.message+" "+error.stack);Qt.quit();}}}
}""",
            setup=setup,
        )

    def test_info_reuses_cached_tags_and_keeps_api_values_when_dav_fails(self):
        self.run_qml(
            """import QtQuick
import Quickshell
import "spaces/music"
ShellRoot {
 id:root
 property int fileReads:0
 property var pending:null
 function check(value,message){if(!value)throw new Error(message);}
 QtObject {id:fileService;function startJob(op,args,accepted){throw new Error("Info downloaded a song");}}
 QtObject {id:catalogue;function request(op,args,callback){
  if(op==="song-info"){
   if(args.song.local)callback({tags:{title:"Local title",comment:"Local comment",lyrics:"Local lyrics"},signature:"[1, 2, 3]",fileInfo:"FLAC · 24-bit"},"");
   else callback({tags:{title:"Server title",comment:""},knownFields:["title"]},"");
  }else if(op==="file-tags"){root.fileReads++;root.pending=callback;}
  else throw new Error("Info started a lyrics lookup");
 }}
 FloatingWindow {id:window;visible:true;implicitWidth:1000;implicitHeight:950
  MusicInfo {id:info;parent:window.contentItem;files:fileService;catalogue:catalogue}
 }
 Timer {interval:50;running:true;onTriggered:{try{
  info.showSong({id:"local",source:"nextcloud",serverPath:"/local.flac",local:true});
  check(info.draft.comment==="Local comment"&&info.draft.lyrics==="Local lyrics"&&root.fileReads===0&&!info.editing,"Info did not reuse existing file metadata");
  info.prepare();check(root.fileReads===0&&info.editing,"Edit reread cached metadata");info.cancelEdits();
  info.showSong({id:"remote",source:"nextcloud",serverPath:"/remote.flac"});
  check(root.fileReads===1&&info.loadingTags&&!info.editing,"Info did not request remote metadata");
  root.pending({},"Partial reads are unavailable");
  check(!info.loadingTags&&info.draft.title==="Server title"&&!info.knownFields.includes("comment")&&!info.editing,"DAV failure discarded API metadata or invented an empty value");
  info.prepare();info.editTag("comment","Replacement");
  check(info.dirty&&info.draft.comment==="Replacement"&&root.fileReads===2,"DAV failure blocked editing");
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(error){console.error("DISPLAY_FAIL",error.message);Qt.quit();}}}
}""",
            setup=setup,
        )

    def test_switching_songs_ignores_stale_lyrics_without_blocking_the_next_lookup(
        self,
    ):
        self.run_qml(
            """import QtQuick
import Quickshell
import "ui"
import "spaces/music"
ShellRoot {
 id:root
 property var callbacks:[]
 QtObject {id:fileService;function startJob(op,args){}}
 QtObject {id:lyricsService;function request(op,args,callback){if(op==="song-info"){callback({tags:{}},"");return;}root.callbacks=root.callbacks.concat([callback]);}}
 FloatingWindow {id:fixtureWindow;visible:true;implicitWidth:900;implicitHeight:850
  MusicInfo {id:info;parent:fixtureWindow.contentItem;files:fileService;catalogue:lyricsService}
 }
 Timer {interval:50;running:true;onTriggered:{try{
  info.showSong({id:"first",source:"music-local",title:"First",artist:"Artist"});
  info.lookupLyrics();\n  if(!info.lookingUp||root.callbacks.length!==1)throw new Error("first lookup missing");
  info.showSong({id:"second",source:"music-local",title:"Second",artist:"Artist"});
  info.lookupLyrics();\n  if(!info.lookingUp||root.callbacks.length!==2)throw new Error("old lookup blocked the next song");
  root.callbacks[0]({available:true,lyrics:"Wrong song",provider:"Fixture"},"");
  if(info.draft.lyrics||!info.lookingUp)throw new Error("stale callback changed the new song");
  root.callbacks[1]({available:true,lyrics:"Second lyrics",provider:"Fixture"},"");
  if(info.draft.lyrics!=="Second lyrics"||info.lookingUp)throw new Error("current lyrics missing");
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(error){console.error("DISPLAY_FAIL",error.message);Qt.quit();}}}
}""",
            setup=setup,
        )

    def test_reopening_an_interrupted_preview_retries_without_accepting_stale_data(
        self,
    ):
        self.run_qml(
            """import QtQuick
import Quickshell
import "spaces/music"
ShellRoot {
 id:root
 property int step:0
 property var callbacks:[]
 QtObject {id:fileService;function startJob(op,args,accepted){throw new Error("Preview downloaded audio");}}
 QtObject {id:previewService;function request(op,args,callback){root.callbacks=root.callbacks.concat([callback]);}}
 FloatingWindow {id:window;visible:true;implicitWidth:900;implicitHeight:850
  MusicInfo {id:info;parent:window.contentItem;files:fileService;catalogue:previewService}
 }
 property var song:({id:"one",source:"nextcloud",title:"Initial title"})
 Timer {interval:50;repeat:true;running:true;onTriggered:{try{
  if(root.step===0){info.showSong(root.song);root.step++;return;}
  if(root.step===1){info.close();root.step++;return;}
  info.showSong(root.song);
  if(root.callbacks.length!==2)throw new Error("Interrupted preview could not retry");
  root.callbacks[0]({tags:{title:"Stale title"},relativePath:"wrong.flac"},"");
  root.callbacks[1]({tags:{title:"Current title"},relativePath:"correct.flac"},"");
  if(info.reading||info.editing||info.draft.title!=="Current title"||info.relativePath!=="correct.flac")throw new Error("Stale preview won or viewing enabled edits");
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(error){console.error("DISPLAY_FAIL",error.message);Qt.quit();}}}
}""",
            setup=setup,
        )

    def test_seek_drag_ignores_position_polls_and_seeks_once_on_release(self):
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
 property int seeks:0
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer {id:driver;interval:100;repeat:false;running:true;onTriggered:{try{
  if(root.step===0){check(SpaceState.open("music",Quickshell.screens[0]),"Music missing");root.step++;return;}
  const page=host.currentPage;
  if(!page||!page.initialized||page.loading||page.rows.length!==50)return;
  const playback=Array.from(page.data).find(item=>item.objectName==="musicPlayback");
  if(root.step===1){page.select(page.rows[0]);root.step++;return;}
  if(root.step===2){
   if(!playback.playerProcess||playback.preparing)return;
   const seek=find(host.contentItem,"musicSeek");
   playback.positionChanged.connect(()=>root.seeks++);
   input.mousePress(seek,seek.leftPadding+2,seek.height/2);
   input.mouseMove(seek,seek.width*0.5,seek.height/2);
   input.mouseMove(seek,seek.width*0.75,seek.height/2);
   const dragged=seek.value;
   // A status poll arriving mid-drag must not pull the handle back.
   playback.position=3;
   check(seek.value===dragged&&dragged>30,"poll moved the handle during a drag: "+seek.value+" / "+dragged);
   root.seeks=0;
   input.mouseRelease(seek,seek.width*0.75,seek.height/2);
   check(root.seeks===1&&Math.abs(playback.position-dragged)<0.01&&Math.abs(seek.value-dragged)<0.01,"release did not seek once to the drag target: "+root.seeks+" "+playback.position+" "+seek.value);
   playback.stopPlayback();SpaceState.close("music");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",error.message);Qt.quit();}finally{driver.restart();}}}
 Timer {interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout",root.step);Qt.quit();}}
}""",
            setup=setup,
        )

    def test_queue_matches_the_visible_collection_and_plays_the_chosen_song(self):
        def queue_setup(root):
            setup(root)
            cloud = root / 'spaces/music/cloud_fixture.py'
            source = cloud.read_text()
            queue = 'elif op=="queue":result=dict(items=[song])'
            self.assertEqual(source.count(queue), 1)
            # Filtered queues return a different song than the visible lists.
            cloud.write_text(
                source.replace(
                    queue,
                    'elif op=="queue":result=dict(items=[dict(song,id="filtered")] if r.get("genreName") or r.get("pending") else [song])',
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
 function check(value,message){if(!value)throw new Error(message);}
 Timer {id:driver;interval:100;repeat:false;running:true;onTriggered:{try{
  if(root.step===0){check(SpaceState.open("music",Quickshell.screens[0]),"Music missing");root.step++;return;}
  const page=host.currentPage;
  if(!page||!page.initialized||page.loading)return;
  const playback=Array.from(page.data).find(item=>item.objectName==="musicPlayback");
  if(root.step===1){
   if(page.rows.length!==50)return;
   // The list changed after its last browse: the chosen song still plays.
   page.genreId="Rock";page.genreName="Rock";page.pendingOnly=true;
   page.select(page.rows[3]);root.step++;return;
  }
  if(root.step===2){
   if(!playback.currentTrack||playback.preparing)return;
   check(playback.currentTrack.id==="3","a different song played: "+playback.currentTrack.id);
   page.openArtist(page.rows[0]);root.step++;return;
  }
  if(root.step===3){
   if(page.entity?.kind!=="artist"||page.rows[0]?.title!=="Artist track")return;
   page.select(page.rows[0]);root.step++;return;
  }
  if(root.step===4){
   if(playback.currentTrack?.title!=="Saved song"&&playback.currentTrack?.id!=="filtered"||playback.preparing)return;
   // Library-level genre/upload filters do not apply inside an artist page.
   check(playback.queueSongs.length===1&&playback.queueSongs[0].id==="cloud1"&&playback.currentTrack.id==="cloud1","artist queue used hidden filters: "+JSON.stringify(playback.queueSongs.map(song=>song.id)));
   playback.stopPlayback();SpaceState.close("music");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",error.message);Qt.quit();}finally{driver.restart();}}}
 Timer {interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout",root.step);Qt.quit();}}
}""",
            setup=queue_setup,
        )

    def test_stopped_file_worker_settles_accepted_jobs(self):
        self.run_qml(
            """import QtQuick
import Quickshell
import "spaces/music"
ShellRoot {
 id:root
 property var failures:[]
 MusicService {id:service;startOnDemand:true;onJobFinished:job=>root.failures=root.failures.concat([job])}
 Timer {interval:30;running:true;onTriggered:{try{
  service.jobs=[{job_id:"accepted",state:"running"}];service.jobRequests={accepted:{args:{action:"info"}}};
  service.stopped=true;
  if(root.failures.length!==1||root.failures[0].job_id!=="accepted"||root.failures[0].state!=="failed")throw new Error("worker exit left an accepted job unresolved");
  if(service.activeJobCount||service.jobs.length)throw new Error("worker exit retained active jobs");
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(error){console.error("DISPLAY_FAIL",error.message);Qt.quit();}}}
}""",
            setup=setup,
        )


@unittest.skipUnless(support.QS, 'Quickshell required')
class MusicQueueTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_failed_start_previous_repeat_and_replaced_queue_positions(self):
        self.run_qml(
            """import QtQuick
import Quickshell
import "spaces/music"
ShellRoot {
 id:root
 property int step:0
 property var sent:[]
 property var command:["/nonexistent/music-player"]
 property var tracks:[{id:"a",title:"A"},{id:"b",title:"B"}]
 QtObject {id:service
  function request(op,args,callback){
   root.sent=root.sent.concat([op+(args.action?":"+args.action+":"+args.value:"")]);
   Qt.callLater(()=>callback(op==="play"?{command:root.command,ipcPath:"/fixture.sock"}:{},""));
   return root.sent.length;
  }
 }
 MusicPlayback {id:playback;active:false;service:service;controller:root}
 function recordKey(track){return track.id;}
 function songScopeKey(){return "fixture";}
 function check(value,message){if(!value)throw new Error(message);}
 function plays(){return root.sent.filter(value=>value==="play").length;}
 Timer {interval:150;running:true;repeat:true;onTriggered:{try{
  if(root.step===0){playback.playSongs(root.tracks,0);root.step++;return;}
  if(root.step===1){
   if(playback.preparing||!playback.playFailed)return;
   // A player that never starts must not look like playback.
   check(!playback.playerProcess&&playback.playMessage==="Could not start the audio player.","failed start looked like playback: "+playback.playMessage);
   root.command=["sleep","30"];playback.playSongs(root.tracks,0);root.step++;return;
  }
  if(root.step===2){
   if(!playback.playerProcess||playback.preparing)return;
   root.sent=[];playback.playPrevious();
   check(!playback.playerPaused&&root.sent.join()==="player-command:seek:0","Previous on the first song did not restart it: "+root.sent.join());
   root.sent=[];playback.playSongs(root.tracks.slice().reverse(),1);root.step++;return;
  }
  if(root.step===3){
   if(playback.preparing)return;
   // Play all from the current song starts the new queue at its position.
   check(plays()===1&&!playback.playerPaused&&playback.currentTrackIndex===1&&playback.currentTrack.id==="a","replacing the queue toggled the current song");
   root.sent=[];playback.repeatAllEnabled=true;playback.playSongs([root.tracks[0]],0);root.step++;return;
  }
  if(root.step===4){
   if(playback.preparing)return;
   root.sent=[];playback.playNext(false);root.step++;return;
  }
  if(root.step===5){
   if(playback.preparing)return;
   check(plays()===1&&!playback.playerPaused&&playback.playerProcess,"Next with repeat paused instead of restarting: "+root.sent.join());
   playback.stopPlayback();console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",error.message);Qt.quit();}}}
 Timer {interval:10000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout at "+root.step);Qt.quit();}}
}"""
        )


def playback_setup(root):
    import wave

    movies_setup(root)
    for name in ('first', 'second'):
        with wave.open(str(root / (name + '.wav')), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b'\0\0' * 16000)
    path = root / 'spaces/music/backend.py'
    source = path.read_text()
    # Without a null output, mpv exits at once in the audio-less test session.
    line = "    command.extend(('--user-agent=' + user_agent, '--', stream_url))"
    assert line in source, 'mpv command line changed; update the --ao=null fixture'
    path.write_text(
        source.replace(
            line,
            "    command.extend(('--ao=null', '--user-agent=' + user_agent, '--', stream_url))",
        )
    )


@unittest.skipUnless(support.QS, 'Quickshell required')
class MusicPlaybackTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_real_mpv_pause_seek_volume_hidden_queue_completion_and_process_cleanup(
        self,
    ):
        self.run_qml(
            """import QtQuick
import Quickshell
import "spaces/music"
ShellRoot {
 id:root
 property int step:0
 property int ticks:0
 property var tracks: [
  {id:"1",kind:"song",source:"local",title:"First",artist:"Fixture",duration:2,localPath:Qt.resolvedUrl("first.wav").toString().replace("file://","")},
  {id:"2",kind:"song",source:"local",title:"Second",artist:"Fixture",duration:2,localPath:Qt.resolvedUrl("second.wav").toString().replace("file://","")}
 ]
 MusicService {id:service;active:true}
 MusicPlayback {id:playback;active:true;service:service;controller:root}
 function recordKey(track){return track.kind+"|"+track.id;}
 function songScopeKey(){return "fixture";}
 function check(value,message){if(!value)throw new Error(message);}
 Timer {interval:100;running:true;repeat:true;onTriggered:{try{
  root.ticks++;
  if(root.step===0){playback.playSongs(root.tracks,0);root.step++;return;}
  if(root.step===1){if(!playback.playerProcess||!playback.ipcPath)return;
   service.request("player-state",{ipcPath:playback.ipcPath},(result,error)=>{if(result?.ready&&root.step===1){playback.togglePause();root.step++;}});return;}
  if(root.step===2){if(!playback.playerPaused)return;playback.changeVolume(35);playback.seekTo(.5);root.step++;return;}
  if(root.step===3){service.request("player-state",{ipcPath:playback.ipcPath},(result,error)=>{if(root.step!==3)return;check(result.paused&&Math.abs(result.volume-35)<1,"pause/volume failed");playback.togglePause();root.step++;});return;}
  if(root.step===4){if(playback.position<.5)return;playback.active=false;root.step++;return;}
  if(root.step===5){if(playback.currentTrackIndex!==1)return;check(!playback.active,"hidden playback was reactivated");root.step++;return;}
  if(root.step===6){if(playback.playerProcess)return;check(playback.playMessage==="Queue finished.","hidden queue did not finish: "+playback.playMessage);playback.stopPlayback();check(!playback.currentTrack&&playback.queueSongs.length===0,"stop did not clear queue");console.log("DISPLAY_PASS");Qt.quit();}
 }catch(error){console.error("DISPLAY_FAIL",error.message);Qt.quit();}}}
 Timer {interval:10000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout at "+root.step);Qt.quit();}}
}""",
            setup=playback_setup,
        )
