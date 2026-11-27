"""The layout toggle keeps catalogue metadata, actions and saved preferences."""

import hashlib
import json
import unittest

import support
from test_music_space import setup as music_setup
from test_radio_space import setup as radio_setup
from test_television import datasets
from test_television_space import setup as television_setup


def seed_logo(root, space, url):
    cache = root / 'cache/quickshell/desktop/spaces' / space / 'artwork'
    cache.mkdir(parents=True)
    icon = root / 'spaces/movies/ratings/rating_tmdb.png'
    (cache / (hashlib.sha256(url.encode()).hexdigest() + '.img')).write_bytes(
        icon.read_bytes()
    )


def radio_with_logo(root):
    radio_setup(root)
    url = 'https://station0.example.invalid/logo.png'
    backend = root / 'spaces/radio/backend.py'
    backend.write_text(
        backend.read_text().replace(
            'bitrate=128 if i%2 else 256',
            f'bitrate=128 if i%2 else 256, favicon={url!r} if i==0 else ""',
        )
    )
    seed_logo(root, 'radio', url)


def television_with_logo(root):
    url = 'https://channel0.example.invalid/logo.png'
    data = datasets()
    data['logos'] = [dict(channel='Fixture0.us', in_use=True, format='PNG', url=url)]
    television_setup(root, data)
    seed_logo(root, 'television', url)


@unittest.skipUnless(support.QS, 'Quickshell required')
class MediaListLayoutTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_catalogue_layout_switches_and_restores_after_reopen(self):
        cases = (
            ('music', music_setup, 'musicList', 'Saved song', 'Artist', 'musicCover:0'),
            (
                'radio',
                radio_with_logo,
                'radioStationList',
                'Station 0',
                'Vietnam',
                'radioLogo:0',
            ),
            (
                'television',
                television_with_logo,
                'televisionChannelList',
                'Channel 000',
                'United States',
                'televisionLogo:0',
            ),
        )
        for space, setup, list_name, title, metadata, artwork in cases:
            with self.subTest(space=space):
                self.run_qml(
                    """import QtQuick
import QtTest
import Quickshell
import "ui"
ShellRoot {
 InteractionState { id: interactions }
 SpaceHost { id: host; interactionState: interactions }
 TestCase { id: input; when: false; parent: host.contentItem }
 property var fixture: FIXTURE
 property int step: 0
 property real expandedHeight: 0
 function find(item, predicate) {
  if (!item || predicate(item)) return item;
  for (const child of item.children ?? []) {
   const match = find(child, predicate);
   if (match) return match;
  }
  return null;
 }
 function named(item, name) { return find(item, child => child.objectName === name); }
 function check(value, message) { if (!value) throw new Error(message); }
 Timer { id: driver; interval: 85; running: true; onTriggered: { try {
  if (step === 0) { SpaceState.open(fixture.space, Quickshell.screens[0]); step++; return; }
  const page = host.currentPage;
  if (!page?.initialized || page.loading || page.refreshing) return;
  const list = named(page, fixture.list);
  const row = list.currentItem;
  if (!row) return;
  const title = find(row, child => child.text === fixture.title);
  const metadata = find(row, child => child.text?.startsWith(fixture.metadata));
  const artwork = fixture.artwork && named(row, fixture.artwork);
  const toggle = named(page.toolbarTarget, fixture.space + "LayoutToggle");
  check(title && metadata && toggle, "missing entry or layout control");
  const titleCenter = title.mapToItem(row, 0, title.height / 2);
  const metadataCenter = metadata.mapToItem(row, 0, metadata.height / 2);
  if (step === 1) {
   if (fixture.space !== "music" && artwork?.status !== Image.Ready) return;
   check(!page.compactRows && metadataCenter.y > titleCenter.y + 8, "default did not stack text");
   if (fixture.artwork) check(artwork?.visible, "artwork missing in two-line view");
   if (fixture.space === "television") {
    const secondTitle = find(list, child => child.text === "Channel 001");
    check(secondTitle && Math.abs(secondTitle.mapToItem(list, 0, 0).x -
     title.mapToItem(list, 0, 0).x) < 1, "TV titles with and without logos are misaligned");
    check(named(list, "televisionLogoPlaceholder:1")?.visible &&
     !named(row, "televisionLogoPlaceholder:0")?.visible, "wrong TV logo placeholder visibility");
   }
   expandedHeight = row.height;
   input.mouseClick(toggle);
   step++; return;
  }
  check(page.compactRows && row.height < expandedHeight, "row did not shrink");
  check(metadata.width > 0 && metadataCenter.x > titleCenter.x &&
   Math.abs(metadataCenter.y - titleCenter.y) <= 2, "metadata did not move next to the title");
  check(!artwork?.visible && !artwork?.fetchEnabled, "compact rows still use artwork");
  if (fixture.space === "television")
   check(!named(list, "televisionLogoPlaceholder:1")?.visible, "compact TV shows a logo placeholder");
  check(named(row, fixture.space + "Play:0")?.visible, "compact rows lost playback");
  if (step === 2) {
   input.wait(100);
   SpaceState.close(fixture.space);
   SpaceState.open(fixture.space, Quickshell.screens[0]);
   step++; return;
  }
  input.mouseClick(toggle);
  check(!page.compactRows, "could not switch back to two-line entries");
  SpaceState.close(fixture.space);
  console.log("DISPLAY_PASS"); Qt.quit();
 } catch (error) { console.error("DISPLAY_FAIL", error.message); Qt.quit(); } finally { driver.restart(); } } }
 Timer { interval: 7000; running: true; onTriggered: { console.error("DISPLAY_FAIL timeout", step); Qt.quit(); } }
}""".replace(
                        'FIXTURE',
                        json.dumps(
                            dict(
                                space=space,
                                list=list_name,
                                title=title,
                                metadata=metadata,
                                artwork=artwork,
                            )
                        ),
                    ),
                    setup=setup,
                )
