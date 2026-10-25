import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import sys
import support
sys.path.insert(0, str(support.DESKTOP))
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("books_backend", support.DESKTOP / "spaces/books/backend.py")
books = importlib.util.module_from_spec(spec)
spec.loader.exec_module(books)


class BooksBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.backend = books.BooksBackend(root / "config/books.json", root / "data", root / "cache")
        self.fixtures = ROOT / "tests/fixtures/books"
        self.book = {
            "id": "OL100W",
            "title": "The Example Book",
            "authors": [{"id": "OL1A", "name": "Ada Lovelace"}],
            "firstPublishYear": 1843,
            "coverId": "1200",
            "coverSmall": "https://covers.openlibrary.org/b/id/1200-M.jpg",
            "coverLarge": "https://covers.openlibrary.org/b/id/1200-L.jpg",
            "editionCount": 8,
            "subjects": ["Computing"],
            "subjectCount": 1,
            "languages": ["eng"],
            "ratingAverage": 4.3,
            "ratingCount": 12,
            "ebookAccess": "public",
            "hasFulltext": True,
            "openLibraryUrl": "https://openlibrary.org/works/OL100W",
        }

    def fixture(self, name):
        return json.loads((self.fixtures / name).read_text())

    def test_search_normalizes_work_identity_metadata_and_skips_editions(self):
        with patch.object(self.backend, "request", return_value=self.fixture("search.json")) as api:
            result = self.backend.browse({})
        self.assertEqual([item["id"] for item in result["items"]], ["OL100W", "OL101W"])
        first = result["items"][0]
        self.assertEqual(first["authors"], [{"id": "OL1A", "name": "Ada Lovelace"}])
        self.assertEqual(first["firstPublishYear"], 1843)
        self.assertEqual(
            first["coverSmall"], "https://covers.openlibrary.org/b/id/1200-M.jpg?default=false"
        )
        self.assertEqual(first["editionCount"], 8)
        self.assertEqual(first["ratingAverage"], 4.2)
        self.assertEqual(first["ratingCount"], 12)
        self.assertEqual(first["subjectCount"], 14)
        self.assertEqual(len(first["subjects"]), 12)
        self.assertEqual(api.call_args.args[0], "/search.json")
        self.assertEqual(api.call_args.args[1]["q"], "*:*")
        self.assertEqual(api.call_args.args[1]["sort"], "trending")
        self.assertIn("author_key", api.call_args.args[1]["fields"])
        self.assertNotIn("editions", api.call_args.args[1]["fields"])

    def test_missing_fields_are_normal_and_safe(self):
        result = books.normalize_work({"key": "/works/OL101W", "title": "Sparse Work"})
        self.assertEqual(result["title"], "Sparse Work")
        self.assertEqual(result["authors"], [])
        self.assertEqual(result["coverSmall"], "")
        self.assertIsNone(result["firstPublishYear"])
        self.assertIsNone(result["ratingAverage"])
        self.assertEqual(result["editionCount"], 0)
        self.assertFalse(result["hasFulltext"])
        self.assertIsNone(books.normalize_work({"key": "/books/OL100M", "title": "Edition"}))
        with self.assertRaises(books.BooksError):
            books.work_id("OL100M")

    def test_author_ids_survive_normalized_records_and_sparse_detail_merges(self):
        catalogue = books.normalize_work(
            {
                "key": "/works/OL5682519W",
                "title": "Dog Days",
                "author_name": ["Jeff Kinney"],
                "author_key": ["OL2832500A"],
            }
        )
        renormalized = books.normalize_work(catalogue)
        self.assertEqual(renormalized["authors"], [{"id": "OL2832500A", "name": "Jeff Kinney"}])

        hydrated = books.merge_book(
            catalogue,
            {
                "authors": [
                    {"name": "Jeff Kinney"},
                    {"id": "OL2832500A"},
                ]
            },
        )
        self.assertEqual(hydrated["authors"], [{"id": "OL2832500A", "name": "Jeff Kinney"}])

    def test_cached_sparse_author_duplicates_are_repaired_on_read(self):
        self.backend.put_cache(
            "work:OL100W",
            {
                "id": "OL100W",
                "title": "The Example Book",
                "authors": [{"id": "", "name": "Ada Lovelace"}, {"id": "OL1A", "name": ""}],
            },
        )
        result = self.backend.details({"book": self.book})
        self.assertEqual(result["authors"], [{"id": "OL1A", "name": "Ada Lovelace"}])

    def test_query_supports_text_isbn_subject_language_year_and_sort(self):
        response = {"num_found": 0, "docs": []}
        with patch.object(self.backend, "request", return_value=response) as api:
            self.backend.browse(
                {
                    "query": "9780000000001",
                    "filters": {
                        "subject": 'science "history',
                        "language": "eng",
                        "minYear": "1800",
                        "maxYear": "1900",
                        "sort": "newest",
                    },
                }
            )
        params = api.call_args.args[1]
        self.assertIn("9780000000001", params["q"])
        self.assertIn('subject:"science \\"history"', params["q"])
        self.assertIn("language:eng", params["q"])
        self.assertIn("first_publish_year:[1800 TO 1900]", params["q"])
        self.assertEqual(params["sort"], "new")

    def test_free_text_defaults_to_relevance_and_discovery_to_trending(self):
        with patch.object(
            self.backend, "request", return_value={"num_found": 0, "docs": []}
        ) as api:
            self.backend.browse({"query": "rambo"})
            self.assertNotIn("sort", api.call_args.args[1])
            self.backend.browse({})
            self.assertEqual(api.call_args.args[1]["sort"], "trending")
            self.backend.browse({"query": "rambo", "filters": {"sort": "trending"}})
            self.assertEqual(api.call_args.args[1]["sort"], "trending")
        self.assertEqual(
            books.browse_cache_key("rambo", {}, 0),
            books.browse_cache_key("rambo", {"sort": "relevance"}, 0),
        )
        self.assertNotEqual(
            books.browse_cache_key("rambo", {}, 0),
            books.browse_cache_key("rambo", {"sort": "trending"}, 0),
        )

    def test_free_text_escapes_lucene_operators_and_keeps_symbols_literal(self):
        with patch.object(
            self.backend, "request", return_value={"num_found": 0, "docs": []}
        ) as api:
            self.backend.browse({"query": "C++ (a:b)"})
        self.assertEqual(api.call_args.args[1]["q"], r"(C\+\+ \(a\:b\))")

    def test_language_filter_rejects_non_iso639_2_input(self):
        with self.assertRaisesRegex(books.BooksError, "three-letter"):
            self.backend.browse({"filters": {"language": "english"}})

    def test_no_key_is_required_and_contact_only_changes_the_shared_rate_limit(self):
        self.assertEqual(self.backend.handle({"op": "init"})["contactConfigured"], False)
        self.assertEqual(self.backend._request_interval(), 1.02)
        self.backend.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.backend.config_path.write_text(json.dumps({"contact": "reader@example.org"}))
        self.assertEqual(self.backend.handle({"op": "init"})["contactConfigured"], True)
        self.assertEqual(self.backend._request_interval(), 0.36)

    def test_catalogue_pagination_uses_offsets_and_work_counts(self):
        def response(path, params):
            offset = params["offset"]
            rows = [
                {"key": f"/works/OL{i}W", "title": f"Work {i}"}
                for i in range(offset, min(offset + books.PAGE_SIZE, 81))
            ]
            return {"num_found": 81, "docs": rows}

        with patch.object(self.backend, "request", side_effect=response) as api:
            page1 = self.backend.browse({})
            page2 = self.backend.browse({"offset": page1["next"]})
            page3 = self.backend.browse({"offset": page2["next"]})
        self.assertEqual(page1["next"], "40")
        self.assertEqual(page2["next"], "80")
        self.assertEqual(page3["next"], "")
        self.assertEqual(api.call_args_list[1].args[1]["offset"], 40)
        self.assertEqual(len(page3["items"]), 1)

    def test_fresh_browse_cache_and_snapshot_avoid_repeat_api_calls(self):
        payload = self.fixture("search.json")
        with patch.object(self.backend, "request", return_value=payload) as api:
            first = self.backend.browse({})
            snapshot = self.backend.snapshot({})
            second = self.backend.browse({})
        self.assertEqual(api.call_count, 1)
        self.assertEqual(snapshot["items"][0]["id"], first["items"][0]["id"])
        self.assertEqual(second["items"], first["items"])

    def test_stale_catalogue_is_kept_when_open_library_is_unavailable(self):
        with patch.object(self.backend, "request", return_value=self.fixture("search.json")):
            cached = self.backend.browse({})
        key = books.browse_cache_key("", {}, 0)
        with self.backend.db(self.backend.cache_db) as db:
            db.execute(
                "UPDATE cache SET updated=? WHERE key=?",
                (time.time() - books.CATALOGUE_TTL - 5, key),
            )
        with patch.object(self.backend, "request", side_effect=books.BooksError("offline")):
            stale = self.backend.browse({"refresh": True})
        self.assertEqual(stale["items"], cached["items"])
        self.assertIn("saved results", stale["warning"])

    def test_favorites_persist_by_work_id_and_search_locally_offline(self):
        self.backend.handle({"op": "save", "book": self.book, "favorite": True})
        restarted = books.BooksBackend(
            self.backend.config_path, self.backend.data, self.backend.cache
        )
        with patch.object(
            restarted, "request", side_effect=AssertionError("favorites should not hit the network")
        ):
            favorites = restarted.browse({"favorites": True, "query": "ada"})
            missing = restarted.browse({"favorites": True, "query": "9780000000001"})
        self.assertEqual([book["id"] for book in favorites["items"]], ["OL100W"])
        self.assertEqual(favorites["items"][0]["coverId"], "1200")
        self.assertEqual(missing["items"], [])
        restarted.handle({"op": "save", "book": self.book, "favorite": False})
        self.assertEqual(restarted.browse({"favorites": True})["items"], [])

    def test_details_are_hydrated_once_cached_and_keep_catalogue_values(self):
        with patch.object(self.backend, "request", return_value=self.fixture("work.json")) as api:
            details = self.backend.details({"book": self.book})
            repeated = self.backend.details({"book": self.book})
        self.assertEqual(api.call_count, 1)
        self.assertEqual(details["description"], "A short fixture synopsis for the selected work.")
        self.assertEqual(details["authors"][0]["name"], "Ada Lovelace")
        self.assertEqual(details["coverId"], "1200")
        self.assertEqual(details["editionCount"], self.book["editionCount"])
        self.assertEqual(details["ratingAverage"], self.book["ratingAverage"])
        self.assertEqual(details["ratingCount"], self.book["ratingCount"])
        self.assertTrue(details["hasFulltext"])
        self.assertEqual(repeated["description"], details["description"])

    def test_details_keep_saved_copy_after_temporary_error(self):
        with patch.object(self.backend, "request", return_value=self.fixture("work.json")):
            details = self.backend.details({"book": self.book})
        with patch.object(self.backend, "request", side_effect=books.BooksError("offline")):
            stale = self.backend.details({"book": self.book, "refresh": True})
        self.assertEqual(stale["description"], details["description"])
        self.assertIn("saved book details", stale["warning"])

    def test_author_profile_and_work_pages_are_normalized_and_paginated(self):
        with patch.object(self.backend, "request", return_value=self.fixture("author.json")) as api:
            author = self.backend.author_details({"author": {"id": "OL1A"}})
        self.assertEqual(author["name"], "Ada Lovelace")
        self.assertEqual(author["biography"], "English mathematician and writer.")
        self.assertTrue(author["image"].endswith("/a/id/76-M.jpg?default=false"))
        self.assertEqual(api.call_args.args[0], "/authors/OL1A.json")

        with patch.object(
            self.backend, "request", return_value=self.fixture("author-works.json")
        ) as api:
            works = self.backend.author_works({"author": {"id": "OL1A"}})
        self.assertEqual([book["id"] for book in works["items"]], ["OL200W", "OL201W"])
        self.assertEqual(works["next"], "2")
        self.assertEqual(api.call_args.args[1], {"limit": books.PAGE_SIZE, "offset": 0})

    def test_author_context_survives_cached_works_and_details(self):
        sparse = {"id": "OL200W", "title": "Work", "authors": [{"id": "OL1A", "name": ""}]}
        self.backend.put_cache("author-works:OL1A:0", {"items": [sparse], "next": ""})
        self.backend.put_cache("work:OL200W", sparse)
        person = {"id": "OL1A", "name": "Ada Lovelace"}
        with patch.object(self.backend, "request", side_effect=AssertionError("No network needed")):
            page = self.backend.author_works({"author": person})
            selected = self.backend.details({"book": page["items"][0]})
        self.assertEqual(selected["authors"], [person])

    def test_editions_are_lazy_paginated_and_keep_only_edition_differences(self):
        with patch.object(
            self.backend, "request", return_value=self.fixture("editions.json")
        ) as api:
            result = self.backend.editions({"book": self.book})
        self.assertEqual(api.call_args.args[0], "/works/OL100W/editions.json")
        self.assertEqual(api.call_args.args[1], {"limit": books.EDITION_PAGE_SIZE, "offset": 0})
        self.assertEqual(result["next"], "1")
        edition = result["items"][0]
        self.assertEqual(edition["id"], "OL100M")
        self.assertEqual(edition["year"], 2001)
        self.assertEqual(edition["languages"], ["eng"])
        self.assertEqual(edition["publishers"], ["Example Press"])
        self.assertEqual(edition["pages"], 312)
        self.assertEqual(edition["isbn"], ["9780000000001", "0000000000"])
        self.assertNotIn("authors", edition)

    def test_provider_errors_are_concise_and_do_not_echo_response_body(self):
        with patch.object(
            books.urllib.request,
            "urlopen",
            side_effect=HTTPError(
                "https://openlibrary.org/search.json?q=private", 429, "rate limit", {}, None
            ),
        ):
            with self.assertRaises(books.BooksError) as raised:
                self.backend.request("/search.json", {"q": "private"})
        self.assertEqual(str(raised.exception), "Open Library is busy. Wait a moment, then retry.")
        self.assertNotIn("private", str(raised.exception))



class BooksLocalIntegrationTests(unittest.TestCase):
    def test_scan_matches_open_library_and_registers_imported_books(self):
        from spaces.movies.torrent_backend import TorrentBackend, TorrentError
        import os
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'incoming/Example book.epub'; source.parent.mkdir()
            source.write_bytes(b'fixture epub')
            backend = TorrentBackend(config=root/'torrents.json',data=root/'data')
            with patch.object(backend,'qbit',side_effect=TorrentError('Offline')), patch.dict(os.environ,{'XDG_DOCUMENTS_DIR':str(root/'Documents')}):
                review = backend.scan({'kind':'book','path':str(source)})['review']
                self.assertEqual(len(review),1)
                catalogue = books.BooksBackend(config=root/'books.json',data=root/'data',cache=root/'cache')
                with patch('spaces.books.backend.BooksBackend',return_value=catalogue), patch.object(catalogue,'browse',return_value={'items':[{'id':'OL100W','title':'Example book','authors':[{'name':'Example author'}],'firstPublishYear':2024}]}):
                    matches = backend.scan_lookup({'token':review[0]['token'],'query':'Example book'})
                self.assertEqual(matches[0]['kind'],'book')
                self.assertEqual(matches[0]['author'],'Example author')
                result = backend.scan_import({'token':review[0]['token'],'title':matches[0]})
                self.assertTrue(Path(result['path']).is_file())
                self.assertEqual(backend.library.list('book')[0]['id'],'OL100W')
                self.assertEqual(len(backend.library.files(matches[0])),1)


if __name__ == "__main__":
    unittest.main()
