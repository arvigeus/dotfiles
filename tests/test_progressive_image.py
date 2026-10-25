"""Artwork previews upgrade to originals and share downloads with the backdrop."""
import unittest
import support


def setup(root):
    for name, size, color in [('low', 120, 'red'), ('full', 2400, 'green')]:
        (root / (name + '.svg')).write_text('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d"><rect width="100%%" height="100%%" fill="%s"/></svg>' % (size, size // 2, color))
    (root / 'spaces/movies/image_cache.py').write_text('''import sys,time,json,threading
from pathlib import Path
sys.path.insert(0,%r)
from spaces.movies.worker import serve
counts={}
lock=threading.Lock()
def handle(r):
 key='full' if r['url'].endswith('/full') else 'low'
 with lock:
  counts[key]=counts.get(key,0)+1
  Path(%r).write_text(json.dumps(counts))
 time.sleep(.75 if key=='full' else .03)
 return (Path(%r)/(key+'.svg')).as_uri()
serve(handle)
''' % (str(support.DESKTOP), str(root / 'counts.json'), str(root)))


@unittest.skipUnless(support.QS, 'Quickshell is required')
class ProgressiveImageTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_preview_is_replaced_by_original_and_downloads_are_shared(self):
        self.run_qml('''import QtQuick
import Quickshell
import Quickshell.Io
import "spaces/movies"
ShellRoot {
 id:root
 property int step:0
 ArtworkCache{id:cache;spaceId:"pictures"}
 FloatingWindow{id:window;implicitWidth:800;implicitHeight:600;visible:true
  MovieBackdrop{id:backdrop;anchors.fill:parent;cacheService:cache;ownerKey:"first";source:"https://fixture.invalid/full";poster:"https://fixture.invalid/low"}
  ProgressiveImage{id:preview;width:620;height:310;cacheService:cache;ownerKey:"first";fillMode:Image.PreserveAspectFit;source:"https://fixture.invalid/full";previewSource:"https://fixture.invalid/low"}
 }
 FileView{id:counts;path:Qt.resolvedUrl("counts.json").toString().replace("file://","");blockLoading:true;printErrors:false}
 function check(v,m){if(!v)throw new Error(m);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer{interval:25;running:true;repeat:true;onTriggered:{try{
  if(root.step===0){if(!preview.usingPreview)return;check(preview.displayedSource.toString().endsWith('/low'),"low-quality image was not shown first");root.step++;return;}
  if(preview.loading || preview.transitioning || backdrop.loading)return;
  check(preview.hasImage && !preview.usingPreview && preview.displayedSource.toString().endsWith('/full'),"detail remained on thumbnail");
  const full=find(preview,"progressiveFullImage");
  const decoded=find(full,full.frontIsA?"imageA":"imageB");
  check(decoded.sourceSize.width>=620,"original was decoded below display resolution");
  check(!backdrop.usingPoster,"backdrop remained on preview");
  counts.reload();const requests=JSON.parse(counts.text());
  check(requests.full===1 && requests.low===1,"detail and backdrop downloaded the same source twice");
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:8000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}''', setup=setup)
