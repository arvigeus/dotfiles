"""Music shares the retained host and list presentation, with owned hidden playback."""
import unittest
import support
from test_movies_space import setup as movies_setup


def setup(root):
    movies_setup(root)
    import shutil
    shutil.copytree(support.DESKTOP/"integrations",root/"integrations",dirs_exist_ok=True)
    path = root / 'spaces/music/backend.py'
    fixture = '''
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
        return dict(command=["sleep","60"],ipcPath="")
    return _original_dispatch(args)
'''
    (root/'spaces/music/cloud_fixture.py').write_text('''import json,sys
song=dict(id="cloud1",kind="song",source="nextcloud",account="fixture",title="Saved song",artist="Artist",artistIds=["a1"],album="Album",albumId="b1",duration=120)
for line in sys.stdin:
 r=json.loads(line);op=r["op"];result={}
 if op=="browse":
  items=[song] if r.get("query") or r.get("starred") else [dict(song,id=str(i),local=i==0) for i in range(r.get("offset",0),r.get("offset",0)+50)]
  result=dict(items=items,limit=r.get("offset",0)+50,hasMore=not r.get("query") and r.get("offset",0)<50)
 elif op=="cover":result=""
 elif op=="local-refresh":result=dict(version="fixture")
 elif op=="queue":result=dict(items=[song])
 elif op=="index-status":result=dict(ready=True,indexing=False,version="fixture")
 elif op=="entity-browse":
  items=[dict(id="b1",kind="album",source="nextcloud",account="fixture",title="Album",artist="Artist")] if r.get("category")=="albums" else [dict(song,title="Deep artist track" if r.get("query")=="deep" else "Artist track" if r["entity"]["kind"]=="artist" else "Album track")]
  result=dict(items=items,total=len(items),limit=len(items),hasMore=False)
 elif op=="favorite":result=dict(item=dict(r["item"],starred=r["value"]))
 elif op=="artist":result=dict(artist=r["artist"],songs=[dict(song,title="Artist track")],albums=[dict(id="b1",kind="album",source="nextcloud",account="fixture",title="Album",artist="Artist")])
 elif op=="album":result=dict(album=r["album"],songs=[dict(song,title="Album track")])
 elif op=="genres":result=[dict(id="Rock",name="Rock")]
 if isinstance(result,dict) and op!="index-status":result.update(index=dict(ready=True,indexing=False,version="fixture"),cached=True)
 print(json.dumps(dict(id=r["id"],result=result)),flush=True)
''')
    (root/'spaces/music/artwork.py').write_text("import json,sys\nfor line in sys.stdin:\n r=json.loads(line);print(json.dumps(dict(id=r['id'],result='')),flush=True)\n")
    main=root/'spaces/music/Main.qml'
    main.write_text(main.read_text().replace('backend: "cloud.py"','backend: "cloud_fixture.py"').replace('property var deliverNotification: (title,body) => Quickshell.execDetached([','property var deliverNotification: (title,body) => console.log(['))
    source = path.read_text()
    path.write_text(source.replace('\ndef main():', fixture + '\ndef main():'))


@unittest.skipUnless(support.QS, 'Quickshell required')
class MusicSpaceTests(unittest.TestCase):
    run_qml = support.run_qml
    def test_two_tabs_context_search_infinite_loading_navigation_pickers_and_lifecycle(self):
        self.run_qml('''import QtQuick
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
}''', setup=setup)


    def test_information_view_edit_cover_save_and_move_are_separate(self):
        def info_setup(root):
            setup(root)
            from PySide6.QtGui import QImage
            image=QImage(64,64,QImage.Format.Format_RGB32);image.fill(0xff0066aa)
            image.save(str(root/'cover.png'));(root/'covers').mkdir();image.save(str(root/'covers/cover.png'))
            (root/'spaces/music/artwork.py').write_text("import json,sys\nfrom pathlib import Path\nfor line in sys.stdin:\n r=json.loads(line);print(json.dumps(dict(id=r['id'],result=(Path(__file__).parents[2]/'cover.png').as_uri())),flush=True)\n")
            (root/'spaces/music/local_files.py').write_text("""import json,sys
jobs=[];tags={"title":"Saved song","artist":"Artist","album":"Album","lyrics":""}
for line in sys.stdin:
 r=json.loads(line);op=r['op'];result={}
 if op=='states':result=[]
 elif op=='jobs':result=dict(jobs=jobs)
 elif op=='file-job':
  action=r['action'];rel=r.get('relativePath',r.get('song',{}).get('serverPath','/album/song.flac').lstrip('/'))
  if action=='save':
   assert 'relativePath' not in r,'Save must not move the file'
   tags.update(r['tags'])
  if action=='move':assert 'tags' not in r and 'artwork' not in r,'Move must not edit metadata'
  value=dict(action=action,path='/home/fixture/Music/'+rel,synced=action!='info',relativePath=rel,local=action!='move',tags=dict(tags),signature=[1,2,len(jobs)],pendingUpload=False,fileInfo='FLAC · 24-bit · 96 kHz · Stereo')
  identifier=str(len(jobs));jobs.append(dict(job_id=identifier,title='Fixture',state='finished',result=value));result=dict(job_id=identifier)
 print(json.dumps(dict(id=r['id'],result=result)),flush=True)
""")
        self.run_qml("""//@ pragma UseQApplication
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
  id:preview;property int reads:0;property int lyricReads:0
  function request(op,args,callback){
   if(op==="song-info"){reads++;Qt.callLater(()=>callback({tags:{title:"Saved song",artist:"Artist",album:"Album",lyrics:""},relativePath:"album/song.flac"},""));}
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
   if(!find(info.contentItem,"musicInfoCover").imageReady)return;
   check(!info.editing&&!info.ready&&!info.dirty&&files.jobs.length===0,"viewing prepared a local file");
   check(preview.reads===1&&preview.lyricReads===0,"lyrics fetched automatically");
   const comment=find(info.contentItem,"musicTag:comment");check(comment.parent.visible&&comment.readOnly&&comment.placeholderText,"missing fields are hidden or editable");
   check(find(info.contentItem,"musicTag:title").readOnly&&find(info.contentItem,"musicLyrics").readOnly,"preview fields editable");
   check(info.relativePath==="album/song.flac"&&!find(info.contentItem,"musicMovePath").readOnly,"server path missing");
   check(!find(info.contentItem,"musicChooseCover").visible,"cover edit shown in view mode");
   click(find(info.contentItem,"musicInfoCover"));input.wait(30);check(!info.coverPicker.visible&&!info.busy,"cover image opened a blocker");
   click(find(info.contentItem,"musicFetchLyrics"));root.step++;return;
  }
  if(root.step===3){
   if(info.lookingUp)return;check(info.draft.lyrics==="Fetched lyrics"&&!info.dirty&&preview.lyricReads===1,"explicit read-only lyric fetch failed");
   click(find(info.contentItem,"musicEditMetadata"));root.step++;return;
  }
  if(root.step===4){
   check(info.editing&&info.ready&&!find(info.contentItem,"musicTag:title").readOnly,"Edit did not prepare metadata");
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
   check(info.relativePath==="album/song.flac"&&files.jobs.length===2,"Save moved or re-prepared the file");
   type(find(info.contentItem,"musicMovePath"),"album/renamed.flac");check(find(info.contentItem,"musicMove").enabled&&!find(info.contentItem,"musicEditMetadata").enabled,"path draft can mix with metadata editing");
   click(find(info.contentItem,"musicMove"));root.step++;return;
  }
  if(root.step===6){
   check(info.relativePath==="album/renamed.flac"&&!info.editing&&!info.song.local&&files.jobs.length===3,"Move downloaded or edited the song");
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
}""",setup=info_setup)

    def test_switching_songs_ignores_stale_lyrics_without_blocking_the_next_lookup(self):
        self.run_qml('''import QtQuick
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
}''',setup=setup)

    def test_reopening_an_interrupted_preview_retries_without_accepting_stale_data(self):
        self.run_qml('''import QtQuick
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
}''',setup=setup)

    def test_stopped_file_worker_settles_accepted_jobs(self):
        self.run_qml('''import QtQuick
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
}''',setup=setup)

def playback_setup(root):
    import wave
    movies_setup(root)
    import shutil
    shutil.copytree(support.DESKTOP/"integrations",root/"integrations",dirs_exist_ok=True)
    for name in ('first','second'):
        with wave.open(str(root/(name+'.wav')),'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(8000);audio.writeframes(b'\0\0'*16000)
    path=root/'spaces/music/backend.py'
    source=path.read_text().replace('    command.extend(("--user-agent=" + user_agent, "--", stream_url))','    command.extend(("--ao=null", "--user-agent=" + user_agent, "--", stream_url))')
    path.write_text(source)


@unittest.skipUnless(support.QS, 'Quickshell required')
class MusicPlaybackTests(unittest.TestCase):
    run_qml=support.run_qml
    def test_real_mpv_pause_seek_volume_hidden_queue_completion_and_process_cleanup(self):
        self.run_qml('''import QtQuick
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
}''',setup=playback_setup)
