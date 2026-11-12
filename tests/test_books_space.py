"""Books uses production workers, controls and the retained fullscreen host."""

import json
import sys
import unittest

import support
from test_movies_space import setup as movies_setup

sys.path.insert(0, str(support.DESKTOP))
from spaces.books.backend import BooksBackend


def setup(root):
    movies_setup(root)
    # qBittorrent/scan stub: one unidentified file, never a real Documents folder.
    (root / 'spaces/movies/torrent_backend.py').write_text("""import json,sys,time
for line in sys.stdin:
 r=json.loads(line);op=r['op']
 if op=='scan':
  assert not r.get('path') and r.get('kind')=='book',r
  time.sleep(.15)
  result=dict(imported=[],review=[dict(token='unknown',path='/Books/Unknown.epub',guess=dict(title='Unknown'),reason='Choose the matching catalogue title.')],limited=False)
 else:result=[]
 print(json.dumps(dict(id=r['id'],result=result)),flush=True)
""")
    backend = BooksBackend(
        root / 'config/quickshell/desktop/spaces/books/books.json',
        root / 'data/quickshell/desktop/spaces/books',
        root / 'cache/quickshell/desktop/spaces/books',
    )
    book = dict(
        id='OL100W',
        title='Fixture book',
        authors=[dict(id='OL1A', name='Fixture author')],
        firstPublishYear=2024,
        editionCount=2,
        languages=['eng'],
        subjects=['Computing'],
        description='A saved synopsis',
        ratingAverage=4.2,
        ratingCount=12,
        coverSmall='',
        coverLarge='',
    )
    artwork = root / 'book-art.svg'
    artwork.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="450"><rect width="300" height="450" fill="#315a68"/><text x="35" y="130" fill="white" font-size="30">Fixture book</text></svg>'
    )
    book['coverSmall'] = artwork.as_uri()
    book['coverLarge'] = artwork.as_uri()
    backend.put_cache('work:OL100W', book)
    backend._save_favorite(book, True)
    backend.put_cache(
        'author:OL1A',
        dict(id='OL1A', name='Fixture author', biography='A saved biography'),
    )
    backend.close()
    path = root / 'spaces/books/backend.py'
    source = path.read_text()
    # Use the real request/response path and database without contacting any provider.
    fixture = """    original_browse = BooksBackend.browse
    BooksBackend.browse = lambda self, request: original_browse(self, dict(request, favorites=True))
    BooksBackend.author_details = lambda self, request: dict(id="OL1A",name="Fixture author",biography="A saved biography")
    BooksBackend.author_works = lambda self, request: dict(items=self.browse({})["items"],next="")
    BooksBackend.editions = lambda self, request: dict(items=[dict(id="OL100M", title="Fixture edition", isbn=["9780306406157"], languages=["eng"])],next="")
    def delayed_download(self, request):
        os.environ["XDG_DOCUMENTS_DIR"] = str(self.data / "test-documents")
        def action():
            for _ in range(8):
                check_cancelled(); time.sleep(0.1)
            with self.staging_directory() as directory:
                source = directory / "fixture.epub"
                source.write_bytes(b"fixture book")
                book = request["book"]
                title = dict(book,kind="book",author="Fixture author",year=2024)
                return dict(path=self.local.add(title,source))
        return self.downloads.start("Fixture download", action)
    BooksBackend.queue_provider_download = delayed_download
"""
    path.write_text(
        source.replace(
            '    backend = BooksBackend()\n', fixture + '    backend = BooksBackend()\n'
        )
    )


def setup_invalid_providers(root):
    setup(root)
    config = root / 'config/quickshell/desktop/spaces/books/books.json'
    config.parent.mkdir(parents=True, exist_ok=True)
    config.touch(mode=0o600)
    provider = dict(name='Duplicate', command=['false'])
    config.write_text(json.dumps(dict(providers=[provider, provider])))


@unittest.skipUnless(support.QS, 'Quickshell is required')
class BooksSpaceTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_layout_details_escape_retention_jobs_and_independent_close(self):
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
 function click(item){input.mouseClick(item,item.width/2,item.height/2);}
 Timer {id:driver;interval:80;running:true;repeat:false;onTriggered:{try{
  if(root.step===0){SpaceState.open("books",Quickshell.screens[0]);root.step++;return;}
  const page=host.currentPage;if(!page||page.loading||page.detailLoading)return;
  if(root.step===1){
   check(page.books.length===1&&page.selected.title==="Fixture book","saved catalogue missing");
   check(page.personal.favorite,"favorite missing");
   check(!find(page,"bookCover"),"overview repeats the catalogue cover");
   const background=find(host.contentItem,"booksBackground");
   check(background&&background.color.toString()==="#000000","Books background is not black");
   check(!find(host.contentItem,"booksBackdrop"),"Books still loads a backdrop");
   const synopsis=find(page,"bookDescription");
   check(synopsis.visible&&synopsis.width>300,"synopsis does not share the detail column");
   const toolbar=find(host.contentItem,"booksToolbar");const hide=find(host.contentItem,"hideSpace");
   check(toolbar.parent===page.toolbarTarget&&toolbar.visible,"toolbar missing from common host");
   check(Math.abs(toolbar.mapToItem(host.contentItem,0,0).y+toolbar.height/2-hide.mapToItem(host.contentItem,0,0).y-hide.height/2)<1,"toolbar not beside hide");
   const rail=find(page,"catalogueRail");const grid=find(page,"catalogueGrid");
   check(rail.visible&&!grid.visible&&rail.height>200,"rail geometry wrong");
   click(find(host.contentItem,"layoutButton"));input.wait(40);
   check(grid.visible&&Math.abs(grid.width/page.width-0.51)<0.01,"grid proportions wrong");
   const saved=page.books.slice();
   page.updateCatalogue(Array.from({length:28},(_,i)=>Object.assign({},saved[0],{id:"OL"+(100+i)+"W"})),false);
   for(const width of [709.92,1250.01,1294.38,1290.3]) {
    grid.width=width;grid.forceLayout();input.wait(20);
    const columns=Math.max(2,Math.floor(width/155));
    const last=grid.itemAtIndex(columns-1),next=grid.itemAtIndex(columns);
    check(last&&next&&last.y===0&&next.y>0,"grid dropped its last column at "+width);
    check(width-(last.x+last.width)<columns+9,"blank column remains beside detail at "+width);
   }
   grid.width=Qt.binding(()=>page.width*0.51);page.updateCatalogue(saved,false);
   const spinner=find(host.contentItem,"booksLoadingIndicator");
   for(const flag of ["detailLoading","offersLoading","providerResolving","findOffersLoading","authorLoading","editionsLoading"]) {
    page.tab=flag==="authorLoading"?"author":flag==="editionsLoading"?"editions":"overview";
    page[flag]=true;check(page.busy&&spinner.running&&spinner.visible,"toolbar spinner ignored "+flag);page[flag]=false;
   }
   page.tab="overview";
   check(!find(page,"booksFind").showLoading,"Find still has nested spinners");
   page.searchOpen=true;const search=find(host.contentItem,"bookSearch");search.text="fixture";
   host.escapeHandler();check(host.opened&&search.text===""&&page.searchOpen,"search clear priority wrong");
   host.escapeHandler();check(host.opened&&!page.searchOpen,"search close priority wrong");
   Theme.setMode("light");input.wait(40);
   check(find(page,"bookDescription").color.toString()==="#ffffff","light desktop broke the immersive reading palette");
   page.filtersOpen=true;host.escapeHandler();check(host.opened&&!page.filtersOpen,"filters Escape hid Books");
   click(find(page,"editionsTab"));root.step++;return;
  }
  if(root.step===2){
   if(page.editionsLoading||!page.editions.length)return;
   check(page.tab==="editions"&&find(page,"editionList").count===1,"editions missing");
   host.escapeHandler();check(host.opened&&page.tab==="overview","edition Escape hid Books");
   page.showAuthor(page.selected.authors[0]);root.step++;return;
  }
  if(root.step===3){
   if(page.authorLoading||!page.authorWorks.length)return;
   check(page.authorDetails.biography==="A saved biography","author missing");
   host.escapeHandler();check(page.tab==="overview"&&host.opened,"author Escape hid Books");
   click(find(host.contentItem,"booksLibraryTab"));root.step=20;return;
  }
  if(root.step===20){
   check(page.localMode&&!page.scanOpen,"library tab opened the review");
   click(find(host.contentItem,"booksRefreshButton"));
   check(page.localScan.scanning&&!page.scanOpen,"Refresh did not scan directly");
   root.step=22;return;
  }
  if(root.step===22){
   if(page.localScan.scanning||!page.scanOpen)return;
   check(page.localScan.review.length===1&&!page.localScan.showScanControls,"review has scan path controls");
   check(find(page,"catalogueGrid").visible&&page.tab==="overview","review replaced the catalogue");
   host.escapeHandler();check(host.opened&&!page.scanOpen,"review Escape hid Books");
   // A review that finishes after leaving My Library waits until returning.
   click(find(host.contentItem,"booksRefreshButton"));click(find(host.contentItem,"booksBrowseTab"));
   root.step=23;return;
  }
  if(root.step===23){
   if(page.localScan.scanning)return;
   check(!page.scanOpen&&page.reviewPending,"review opened outside My Library");
   click(find(host.contentItem,"booksLibraryTab"));
   check(page.scanOpen&&!page.reviewPending,"deferred review lost");
   click(find(host.contentItem,"booksBrowseTab"));check(!page.scanOpen,"review stayed over Browse");
   root.step=21;return;
  }
  if(root.step===21){
   page.downloadOffer({title:"Fixture download"});root.retained=page;
   host.dismiss();check(SpaceState.runningIds.includes("books")&&!page.active,"hide destroyed Books");
   check(!find(host.contentItem,"booksLoadingIndicator").running,"hidden toolbar spinner kept running");
   root.step=4;return;
  }
  if(root.step===4){
   const service=Array.from(root.retained.data).find(item=>item.objectName==="booksService");
   if(!service.jobs.some(job=>job.state==="finished"))return;
   check(SpaceState.open("books",Quickshell.screens[0])&&host.currentPage===root.retained,"restore recreated Books");
   check(host.currentPage.gridMode,"layout lost on restore");
   SpaceState.open("movies",Quickshell.screens[0]);root.step++;return;
  }
  if(root.step===5){
   if(SpaceState.currentId!=="movies")return;
   check(root.retained.localFiles.length===1,"hidden download was not refreshed on restore");
   const movies=host.currentPage;
   SpaceState.close("books");input.wait(40);
   check(host.opened&&host.currentPage===movies&&SpaceState.runningIds.includes("movies")&&!SpaceState.runningIds.includes("books"),"Books close disturbed Movies");
   SpaceState.open("books",Quickshell.screens[0]);root.step++;return;
  }
  if(root.step===6){
   check(host.currentPage!==root.retained&&page.gridMode,"fresh instance or layout restore failed");
   SpaceState.close("movies");
   const hide=find(host.contentItem,"hideSpace");click(hide);
   check(!host.opened&&SpaceState.runningIds.includes("books"),"X did not hide Books");
   SpaceState.close("books");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",error.message+" "+error.stack);Qt.quit();}finally{driver.restart();}}}
 Timer {interval:11000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout at "+root.step);Qt.quit();}}
}
""",
            setup=setup,
        )

    def test_setup_errors_refresh_scope_and_subject_filters(self):
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
 Timer {id:driver;interval:80;running:true;repeat:false;onTriggered:{try{
  if(root.step===0){SpaceState.open("books",Quickshell.screens[0]);root.step++;return;}
  const page=host.currentPage;if(!page||page.loading||page.detailLoading||!page.selected.id)return;
  if(root.step===1){
   if(!page.setupError)return;
   // The catalogue loaded after init failed; its success must not hide the problem.
   check(page.error===""&&page.setupError.includes("unique"),"provider setup error lost: "+page.setupError);
   const message=find(page,"booksError");
   check(message.visible&&message.text===page.setupError,"provider setup error not shown");
   check(!page.providerNames.length&&!find(page,"readOnlineButton").visible,"invalid providers still offered");
   const book=page.selected;
   page.clearSelection();page.selectBook(Object.assign({},book,{favorite:false}));
   check(!page.personal.favorite,"fixture selection already favorite");
   page.refreshBook();root.step++;return;
  }
  if(root.step===2){
   // Refresh replaces metadata only; the selection's favorite reply still applies.
   if(!page.personal.favorite)return;
   check(page.selected.description==="A saved synopsis"&&!("warning" in page.selected),"refreshed details wrong");
   check(page.favorites===false&&!page.localMode,"fixture starts outside Browse");
   page.favorites=true;page.browse(false,false);root.step++;return;
  }
  if(root.step===3){
   const subject=find(page,"bookSubject");
   check(subject&&subject.visible,"subject filter missing");
   input.mouseClick(subject,subject.width/2,subject.height/2);
   check(!page.favorites&&!page.localMode&&page.filters.subject==="Computing","subject filter stayed in Favorites");
   SpaceState.close("books");console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",error.message+" "+error.stack);Qt.quit();}finally{driver.restart();}}}
 Timer {interval:11000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout at "+root.step);Qt.quit();}}
}
""",
            setup=setup_invalid_providers,
        )
