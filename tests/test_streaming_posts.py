"""Public Posts parsing/pagination, visibility and canonical subscription identity."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import support
from test_streaming import RAW, VIDEO
from spaces.streaming.backend import StreamingBackend
from spaces.streaming.posts import PostsClient, image_url, normalize, parse_page, script_json, selected_posts
from spaces.streaming.storage import StreamingError

CHANNEL_ID = "UCabcdefghijklmnopqrstuv"
CHANNEL = dict(url="https://www.youtube.com/@fixture", name="Fixture creator", id=CHANNEL_ID)


def renderer(number=1, **patch):
    value = dict(postId="UgFixturePost" + str(number).zfill(12), authorText=dict(runs=[dict(text="Fixture creator")]),
                authorEndpoint=dict(browseEndpoint=dict(browseId=CHANNEL_ID)),
                contentText=dict(runs=[dict(text="A public creator update.")]), publishedTimeText=dict(simpleText="2 days ago"),
                voteCount=dict(simpleText="42"))
    value.update(patch)
    return value


def thread(number=1, **patch):
    return dict(backstagePostThreadRenderer=dict(post=dict(backstagePostRenderer=renderer(number, **patch))))


def continuation(token):
    return dict(continuationItemRenderer=dict(continuationEndpoint=dict(continuationCommand=dict(token=token))))


def initial(contents):
    return dict(contents=dict(twoColumnBrowseResultsRenderer=dict(tabs=[dict(tabRenderer=dict(
        title="Posts", selected=True, endpoint=dict(commandMetadata=dict(webCommandMetadata=dict(url="/@fixture/posts"))),
        content=dict(sectionListRenderer=dict(contents=contents))))])))


class PostsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backend = StreamingBackend(self.root / "config", self.root / "data", self.root / "cache")
        self.addCleanup(self.backend.close)

    def test_posts_preserve_text_images_poll_video_and_skip_members_or_comment_cursors(self):
        image = dict(thumbnails=[dict(url="https://yt3.ggpht.com/fixture", width=800)])
        post = thread(backstageAttachment=dict(postMultiImageRenderer=dict(images=[dict(backstageImageRenderer=dict(image=image))])))
        post["backstagePostThreadRenderer"]["replies"] = continuation("comment-cursor")
        data = initial([post, thread(2, backstageAttachment=dict(pollRenderer=dict(choices=[dict(text=dict(simpleText="Yes")), dict(text=dict(simpleText="No"))], totalVotes=dict(simpleText="200 votes")))),
                        thread(3, backstageAttachment=dict(videoRenderer=dict(videoId=VIDEO["id"], title=dict(simpleText="A shared video")))),
                        thread(4, sponsorsOnlyBadge={}), continuation("posts-cursor")])
        items, cursor = parse_page(selected_posts(data), CHANNEL, now=1000000)
        self.assertEqual(len(items), 3); self.assertEqual(cursor, "posts-cursor")
        self.assertEqual(items[0]["images"], ["https://yt3.ggpht.com/fixture"])
        self.assertEqual(items[0]["timestamp"], 1000000 - 2 * 86400)
        self.assertEqual(items[1]["poll"], ["Yes", "No"])
        self.assertEqual(items[2]["videos"][0]["url"], VIDEO["url"])
        self.assertIsNone(normalize(renderer(membersOnlyBadge={}), CHANNEL))
        self.assertIsNone(normalize(dict(renderer(), postId="../../not-a-post"), CHANNEL))
        unsafe = normalize(renderer(backstageAttachment=dict(backstageImageRenderer=dict(image=dict(thumbnails=[dict(url="file:///etc/passwd")])))), CHANNEL)
        self.assertEqual(unsafe["images"], [])

    def test_client_reads_real_script_shape_and_uses_persisted_post_continuations(self):
        context = dict(client=dict(clientName="WEB", clientVersion="fixture-version"))
        html = 'ytcfg.set("EARLY", "value");ytcfg.set(' + json.dumps(dict(INNERTUBE_CONTEXT=context)) + ');var ytInitialData = ' + json.dumps(initial([thread(), continuation("next-page")])) + ';'
        self.assertEqual(script_json(html, r"ytcfg\.set\(\s*", "INNERTUBE_CONTEXT")["INNERTUBE_CONTEXT"], context)
        calls = []
        def fetch(url, body=None, supplied=None):
            calls.append((url, body, supplied))
            if body is None: return html
            return dict(onResponseReceivedActions=[dict(appendContinuationItemsAction=dict(continuationItems=[thread(2)]))])
        client = PostsClient(self.root / "posts", fetch)
        first = client.page(CHANNEL, 0); self.assertEqual(len(first["items"]), 1); self.assertTrue(first["more"])
        restarted = PostsClient(self.root / "posts", fetch)
        second = restarted.page(CHANNEL, 1); self.assertEqual(len(second["items"]), 1); self.assertFalse(second["more"])
        self.assertEqual(calls[1][1], dict(context=context, continuation="next-page"))
        self.assertEqual(len(calls), 2)
        ended = restarted.page(CHANNEL, 10)
        self.assertEqual(ended["items"], []); self.assertFalse(ended["more"])
        self.assertEqual(len(calls), 2, "an exhausted creator was fetched again as other creators continued")
        cache = next((self.root / "posts").glob("*.json")); self.assertEqual(cache.stat().st_mode & 0o777, 0o600)
        for bad in (-1, True, 2**31):
            with self.assertRaises(StreamingError): client.page(CHANNEL, bad)

    def test_channel_avatars_accept_youtube_protocol_relative_googleusercontent_urls(self):
        author = dict(thumbnails=[dict(url="//yt3.googleusercontent.com/channel=s32", width=32),
                                  dict(url="//yt3.googleusercontent.com/channel=s76", width=76)])
        item = normalize(renderer(authorThumbnail=author), CHANNEL)
        self.assertEqual(item["avatar"], "https://yt3.googleusercontent.com/channel=s76")
        for value in ("//evil.example/avatar", "https://yt3.googleusercontent.com.evil.example/avatar",
                      "http://yt3.googleusercontent.com/avatar", "//name:secret@yt3.googleusercontent.com/avatar"):
            self.assertEqual(image_url(value), "")

    def test_forward_posts_paging_has_bounded_cursors_and_stops_repeated_tokens(self):
        context = dict(client=dict(clientName="WEB", clientVersion="fixture-version"))
        html = 'ytcfg.set(' + json.dumps(dict(INNERTUBE_CONTEXT=context)) + ');var ytInitialData = ' + json.dumps(initial([thread(), continuation("cursor-1")])) + ';'
        repeat = False
        def fetch(url, body=None, supplied=None):
            if body is None: return html
            page = int(body["continuation"].split("-")[1])
            token = body["continuation"] if repeat else "cursor-" + str(page + 1)
            return dict(onResponseReceivedActions=[dict(appendContinuationItemsAction=dict(continuationItems=[thread(page + 1), continuation(token)]))])
        client = PostsClient(self.root / "deep-posts", fetch)
        for page in range(41):
            self.assertTrue(client.page(CHANNEL, page)["more"])
        state = json.loads(next((self.root / "deep-posts").glob("*.json")).read_text())
        self.assertLessEqual(len(state["tokens"]), 32)
        self.assertTrue(client.page(CHANNEL, 40)["more"], "a legitimate replay was treated as a cursor loop")
        repeat = True
        self.assertFalse(client.page(CHANNEL, 41)["more"])

    def test_different_hidden_only_pages_have_distinct_progress_keys(self):
        self.backend.handle(dict(op="subscribe", url=CHANNEL["url"]))
        def extract(target, **options):
            start = options["start"]
            return dict(entries=[dict(RAW, id=f"member{index:05}", availability="subscriber_only") for index in range(start, start + 12)])
        self.backend.commands.extract = extract
        first = self.backend.handle(dict(op="browse", tab="feed", page=0))
        second = self.backend.handle(dict(op="browse", tab="feed", page=1))
        self.assertEqual(first["items"], []); self.assertEqual(second["items"], [])
        self.assertTrue(first["more"]); self.assertNotEqual(first["pageKey"], second["pageKey"])

    def test_public_posts_merge_deduplicate_filter_and_fall_back_to_cached_snapshot(self):
        self.backend.handle(dict(op="subscribe", url=CHANNEL["url"], name=CHANNEL["name"], channelId=CHANNEL_ID))
        self.backend.handle(dict(op="subscribe", url="@other"))
        older = normalize(renderer(), CHANNEL, now=1000000)
        recent = normalize(renderer(2, publishedTimeText=dict(simpleText="1 hour ago")), dict(CHANNEL, url="https://www.youtube.com/@other"), now=1000000)
        self.backend.posts.page = Mock(side_effect=lambda channel, page: dict(items=[older, recent] if channel["url"] == CHANNEL["url"] else [recent], more=True))
        result = self.backend.handle(dict(op="browse", tab="posts"))
        self.assertEqual([p["id"] for p in result["items"]], [recent["id"], older["id"]])
        self.backend.posts.page.side_effect = StreamingError("Offline")
        offline = self.backend.handle(dict(op="browse", tab="posts", refresh=True))
        self.assertEqual(offline["items"], result["items"]); self.assertFalse(offline["more"])
        self.assertIn("Offline", offline["warning"])

    def test_members_only_rows_are_hidden_even_from_cached_feeds(self):
        self.backend.handle(dict(op="subscribe", url=CHANNEL["url"]))
        self.backend.commands.extract = Mock(return_value=dict(id=CHANNEL_ID, channel=CHANNEL["name"], uploader_url=CHANNEL["url"],
            entries=[dict(RAW, availability="subscriber_only"), dict(RAW, id="fixture0001", availability="public")]))
        result = self.backend.handle(dict(op="browse", tab="feed"))
        self.assertEqual([v["id"] for v in result["items"]], ["fixture0001"])
        self.backend.commands.extract.side_effect = StreamingError("Must use cache")
        self.assertEqual(self.backend.handle(dict(op="browse", tab="feed"))["items"], result["items"])

    def test_follow_identity_matches_handles_canonical_ids_and_unsubscribe_aliases(self):
        self.backend.handle(dict(op="subscribe", url=CHANNEL["url"]))
        self.backend.commands.extract = Mock(return_value=dict(id=CHANNEL_ID, channel_id=CHANNEL_ID, channel=CHANNEL["name"],
                                                              uploader_url=CHANNEL["url"], entries=[RAW]))
        result = self.backend.handle(dict(op="browse", tab="feed"))
        self.assertEqual(result["channels"][0]["id"], CHANNEL_ID)
        self.assertEqual(result["items"][0]["followedChannelUrl"], CHANNEL["url"])
        canonical = "https://www.youtube.com/channel/" + CHANNEL_ID
        result = self.backend.handle(dict(op="subscribe", url=canonical, channelId=CHANNEL_ID))
        self.assertEqual(len(result["channels"]), 1)
        result = self.backend.handle(dict(op="unsubscribe", url=canonical))
        self.assertEqual(result["channels"], [])


if __name__ == "__main__":
    unittest.main()
