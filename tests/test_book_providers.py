import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import support
sys.path.insert(0, str(support.DESKTOP))
from spaces.books.backend import BooksBackend, BooksError, normalize_work, normalized_isbns
from spaces.movies.local import destination
from spaces.movies.paths import SPACE

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/books/command-provider.py"


class BookResponse(io.BytesIO):
    def __init__(
        self, body=b"%PDF-1.7\nfixture book", content_type="application/pdf", length=None, delay=0
    ):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(body) if length is None else length)
        self.delay = delay

    def geturl(self):
        return "https://example.org/book.pdf?token=short-lived"

    def read1(self, size=-1):
        return self.read(size)

    def read(self, size=-1):
        if self.delay:
            time.sleep(self.delay)
        return super().read(size)


class BookProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backend = BooksBackend(
            self.root / "books.json", self.root / "data", self.root / "cache"
        )
        self.addCleanup(self.backend.commands.close)
        self.addCleanup(self.backend.downloads.stop)
        self.documents = self.root / "documents"
        env = patch.dict(os.environ, {"XDG_DOCUMENTS_DIR": str(self.documents)})
        env.start()
        self.addCleanup(env.stop)
        self.provider = {
            "name": "Personal provider",
            "command": [sys.executable, str(FIXTURE)],
            "env": {},
        }
        self.book = {
            "id": "OL100W",
            "title": "The Example Book",
            "authors": [{"id": "OL1A", "name": "Ada Lovelace"}],
        }
        self.backend.put_cache("work:OL100W", self.book)
        self.editions(["9780000000001"])
        self.configure()

    def configure(self, rows=None, **extra):
        self.backend.config_path.write_text(
            json.dumps(
                {
                    "contact": "reader@example.org",
                    "providers": rows if rows is not None else [self.provider],
                    **extra,
                }
            )
        )

    def editions(self, isbns):
        self.backend.put_cache(
            "editions:OL100W:0", {"items": [{"id": "OL100M", "isbn": isbns}], "next": ""}
        )

    def plugin(self):
        package = self.root / "provider plugin"
        package.mkdir()
        shutil.copyfile(FIXTURE, package / "provider.py")
        (package / "manifest.json").write_text(
            json.dumps({"api_version": 1, "command": [sys.executable, "{plugin_dir}/provider.py"]})
        )
        return package, {"name": "Packaged provider", "plugin": package.name}

    def search(self, **extra):
        return self.backend.handle({"op": "providerSearch", "query": "Example", **extra})

    def test_optional_configuration_preserves_contact_and_omits_private_fields(self):
        self.configure(rows=[])
        self.assertEqual(self.backend.handle({"op": "init"})["providers"], [])
        self.assertEqual(self.backend.contact(), "reader@example.org")
        self.assertEqual(self.backend._request_interval(), 0.36)
        self.backend.config_path.write_text('{"contact":"reader@example.org"}')
        self.assertEqual(self.search()["items"], [])
        self.configure()
        initialized = self.backend.handle({"op": "init"})
        self.assertEqual(initialized["providers"], ["Personal provider"])
        self.assertNotIn("command", initialized)
        self.assertNotIn("env", initialized)

    def test_configuration_rejects_invalid_commands_env_names_and_duplicate_names(self):
        invalid = [
            None,
            {},
            [None],
            [{"name": "", "command": ["python3"]}],
            [self.provider | {"command": "python3 command.py"}],
            [self.provider | {"command": []}],
            [self.provider | {"command": ["a", 1]}],
            [self.provider | {"env": {"key": 5}}],
            [self.provider | {"env": {"bad=key": "x"}}],
            [self.provider | {"env": {"key": "\0"}}],
            [self.provider, self.provider],
        ]
        for rows in invalid:
            with self.subTest(rows=rows):
                self.backend.config_path.write_text(json.dumps({"providers": rows}))
                with self.assertRaises(BooksError):
                    self.backend.handle({"op": "init"})

    def test_direct_argument_array_environment_merge_stdin_and_multiple_formats(self):
        key = "FIXTURE_" + uuid.uuid4().hex.upper()
        marker = self.root / "must-not-exist"
        literal = "$(touch " + str(marker) + ")"
        self.provider["command"].append(literal)
        self.provider["env"] = {
            key: "configured value",
            "FIXTURE_ENV_KEY": key,
            "FIXTURE_MODE": "echo",
        }
        self.configure()
        with patch.dict(os.environ, {key: "inherited value", "FIXTURE_MODE": "normal"}):
            result = self.search(page=3, limit=17)
        self.assertEqual(result["warning"], "")
        self.assertEqual([row["format"] for row in result["items"]], ["epub", "pdf"])
        offer = result["items"][0]
        self.assertEqual(
            offer["ref"]["request"], {"op": "search", "query": "Example", "page": 3, "limit": 17}
        )
        self.assertEqual(offer["ref"]["argv"], [literal])
        self.assertEqual(offer["ref"]["env"], "configured value")
        self.assertFalse(marker.exists())
        self.assertEqual(offer["source"], "provider")
        self.assertEqual(offer["provider"], "Personal provider")
        self.assertEqual(offer["size_bytes"], 2048000)
        self.assertEqual(offer["publisher"], "Example Press")
        self.assertIsNone(normalize_work(offer))

    def test_plugin_loads_only_on_demand_and_uses_the_same_search_and_resolve_protocol(self):
        package, row = self.plugin()
        row["env"] = {"FIXTURE_ROOT": str(self.root)}
        self.configure([row])
        self.assertEqual(self.backend.handle({"op": "init"})["providers"], ["Packaged provider"])
        self.assertFalse((self.root / "search-calls").exists())
        offers = self.search()["items"]
        self.assertEqual([offer["format"] for offer in offers], ["epub", "pdf"])
        self.assertEqual(offers[0]["provider"], row["name"])
        response = self.backend.provider_resolve(
            {"provider": row["name"], "ref": offers[1]["ref"], "purpose": "read"}
        )
        self.assertEqual(response["url"], "https://example.org/read?token=short-lived")
        self.assertEqual(
            json.loads((self.root / "resolved-ref.json").read_text()), offers[1]["ref"]
        )
        with patch.object(books_urllib_request(), "urlopen", return_value=BookResponse()):
            job = self.finish_download(self.download(offers[1]))
        self.assertEqual(job["state"], "finished", job)
        self.assertTrue(Path(job["result"]["path"]).is_file())

    def test_plugin_env_file_is_literal_merged_reloaded_and_redacted(self):
        package, row = self.plugin()
        settings = package / "settings.env"
        key = "FIXTURE_" + uuid.uuid4().hex.upper()
        marker = self.root / "must-not-exist"
        literal = "$(touch " + str(marker) + ")"
        settings.write_text(
            f'# private settings\nexport {key}="{literal}"\nFIXTURE_ENV_KEY={key}\nFIXTURE_MODE=echo\nEMPTY=\nLITERAL=word#part\\end\nVARIABLE=$NAME # ignored comment\n'
        )
        row["env_file"] = "settings.env"
        self.configure([row])
        with patch.dict(os.environ, {key: "inherited"}):
            self.assertEqual(self.search()["items"][0]["ref"]["env"], literal)
        self.assertFalse(marker.exists())
        self.assertEqual(self.backend.providers()[0]["env"]["EMPTY"], "")
        self.assertEqual(self.backend.providers()[0]["env"]["LITERAL"], "word#part\\end")
        self.assertEqual(self.backend.providers()[0]["env"]["VARIABLE"], "$NAME")
        settings.write_text(
            f'{key}="new private value"\nFIXTURE_ENV_KEY={key}\nFIXTURE_MODE=echo\n'
        )
        self.assertEqual(self.search()["items"][0]["ref"]["env"], "new private value")
        row["env"] = {key: "explicit override"}
        self.configure([row])
        self.assertEqual(self.search()["items"][0]["ref"]["env"], "explicit override")
        row.pop("env")
        settings.write_text(
            f'{key}="new private value"\nFIXTURE_ENV_KEY={key}\nFIXTURE_MODE=private-error\n'
        )
        self.configure([row])
        warning = self.search()["warning"]
        self.assertIn("Cannot connect", warning)
        self.assertNotIn("new private value", warning)
        self.assertNotIn("short-lived", warning)

    def test_plugin_rejects_invalid_manifests_and_settings_without_exposing_values(self):
        package, row = self.plugin()
        for manifest in (
            [],
            {},
            {"api_version": True},
            {"api_version": 2},
            {"api_version": 1, "command": "python3"},
        ):
            with self.subTest(manifest=manifest):
                (package / "manifest.json").write_text(json.dumps(manifest))
                self.configure([row])
                with self.assertRaises(BooksError):
                    self.backend.handle({"op": "init"})
        (package / "manifest.json").unlink()
        self.configure([row])
        with self.assertRaisesRegex(BooksError, "plugin manifest"):
            self.backend.handle({"op": "init"})
        (package / "manifest.json").write_text(
            '{"api_version":1,"command":["python3","{plugin_dir}/provider.py"]}'
        )
        self.configure([row | {"command": ["python3"]}])
        with self.assertRaisesRegex(BooksError, "either"):
            self.backend.handle({"op": "init"})
        self.configure([row | {"env_file": "settings.env"}])
        for value in (
            'PRIVATE="secret value',
            "PRIVATE=secret unquoted value",
            "bad-key=private",
            "private without assignment",
        ):
            (package / "settings.env").write_text(value)
            with self.subTest(value=value), self.assertRaises(BooksError) as error:
                self.backend.handle({"op": "init"})
            self.assertNotIn("secret", str(error.exception))
            self.assertIn("line 1", str(error.exception))
        (package / "settings.env").unlink()
        with self.assertRaisesRegex(BooksError, "environment file"):
            self.backend.handle({"op": "init"})

    def test_command_env_file_is_relative_to_config_and_plugin_timeout_uses_owned_runtime(self):
        settings = self.root / "private.env"
        settings.write_text("FIXTURE_MODE=failure\n")
        self.configure([self.provider | {"env_file": settings.name}])
        self.assertIn("Search unavailable", self.search()["warning"])
        package, row = self.plugin()
        row["env"] = {"FIXTURE_MODE": "timeout", "FIXTURE_ROOT": str(self.root)}
        self.configure([row])
        with patch.object(self.backend.commands, "timeout", 0.3):
            self.assertIn("timed out", self.search()["warning"])
        self.assert_process_stopped(int((self.root / "child-pid").read_text()))

    def test_multiple_providers_keep_formats_and_partial_failures(self):
        second = self.provider | {"name": "Other provider"}
        third = self.provider | {"name": "Unavailable provider", "env": {"FIXTURE_MODE": "failure"}}
        self.configure([self.provider, second, third])
        result = self.search()
        self.assertEqual(len(result["items"]), 4)
        self.assertEqual(
            [row["provider"] for row in result["items"]],
            ["Personal provider"] * 2 + ["Other provider"] * 2,
        )
        self.assertIn("Unavailable provider: Search unavailable", result["warning"])

    def test_catalogue_browsing_details_and_editions_never_search_providers(self):
        with (
            patch.object(self.backend, "request", return_value={"num_found": 0, "docs": []}),
            patch.object(
                self.backend.commands,
                "search",
                side_effect=AssertionError("Provider search must be on demand"),
            ),
        ):
            self.backend.handle({"op": "init"})
            self.backend.browse({})
            self.backend.details({"book": self.book})
            self.backend.editions({"book": self.book})
            self.backend.personal({"book": self.book})

    def test_work_offers_use_exact_normalized_isbn_and_do_not_change_work_metadata(self):
        original = self.backend.details({"book": self.book})
        with patch.object(self.backend, "request", side_effect=AssertionError("No network needed")):
            offers = self.backend.handle({"op": "providerOffers", "book": self.book})
        self.assertEqual([row["format"] for row in offers["items"]], ["epub", "pdf"])
        self.assertTrue(all(row["match"] == "isbn" for row in offers["items"]))
        self.assertEqual(self.backend.details({"book": self.book}), original)
        self.editions(["9780000000002"])
        self.assertEqual(self.backend.provider_offers({"book": self.book})["items"], [])
        self.assertEqual(
            normalized_isbns({"isbn_10": ["0-306-40615-2"], "other": "9780000000001"}),
            {"9780306406157"},
        )

    def test_missing_isbn_requires_exact_title_and_known_author(self):
        self.editions([])
        self.assertEqual(len(self.backend.provider_offers({"book": self.book})["items"]), 2)
        for update in (
            {"title": "The Example Book Companion"},
            {"authors": [{"name": "Other Writer"}]},
            {"authors": []},
        ):
            self.backend.put_cache("work:OL100W", self.book | update)
            result = self.backend.provider_offers({"book": self.book | update})
            self.assertEqual(result["items"], [])

    def test_lookup_checks_later_editions_and_deduplicates_queries_without_merging_formats(self):
        self.backend.put_cache("editions:OL100W:0", {"items": [{"isbn": []}], "next": "24"})
        self.backend.put_cache(
            "editions:OL100W:24", {"items": [{"isbn": ["9780000000001"]}], "next": ""}
        )
        # Stable references across query responses identify repeated offers.
        rows = self.search()["items"]
        with patch.object(self.backend.commands, "search", return_value=rows) as search:
            result = self.backend.provider_offers({"book": self.book})
        self.assertEqual(search.call_args_list[0].args[1], "9780000000001")
        self.assertEqual(len(result["items"]), 2)

    def test_resolve_passes_any_opaque_ref_unchanged_and_never_caches_url(self):
        self.provider["env"] = {"FIXTURE_ROOT": str(self.root)}
        self.configure()
        refs = [{"nested": [1, False, None, {"key": "value"}]}, "opaque token", [1, "two"], None]
        for ref in refs:
            response = self.backend.handle(
                {"op": "providerResolve", "provider": self.provider["name"], "ref": ref}
            )
            self.assertEqual(response["url"], "https://example.org/read?token=short-lived")
            self.assertEqual(json.loads((self.root / "resolved-ref.json").read_text()), ref)
        with self.backend.db(self.backend.cache_db) as db:
            metadata = str(db.execute("SELECT * FROM cache").fetchall())
        self.assertNotIn("short-lived", metadata)
        self.assertNotIn("resolve", metadata)

    def test_provider_records_cannot_enter_work_author_edition_or_favorite_operations(self):
        row = self.search()["items"][0]
        for op in ("details", "personal", "editions", "save", "providerOffers"):
            with self.subTest(op=op), self.assertRaises(BooksError):
                self.backend.handle({"op": op, "book": row, "favorite": True})
        for op in ("authorDetails", "authorWorks"):
            with self.assertRaises(BooksError):
                self.backend.handle({"op": op, "author": row | {"id": "OL1A"}})
        self.assertEqual(self.backend.browse({"favorites": True})["items"], [])

    def test_diagnostics_redact_environment_values_and_urls(self):
        key = "FIXTURE_" + uuid.uuid4().hex.upper()
        for mode in ("stderr", "private-error"):
            self.provider["env"] = {
                "FIXTURE_MODE": mode,
                "FIXTURE_ENV_KEY": key,
                key: "private fixture value",
            }
            self.configure()
            warning = self.search()["warning"]
            self.assertIn("Cannot connect", warning)
            self.assertNotIn("private fixture value", warning)
            self.assertNotIn("short-lived", warning)
            self.assertNotIn("https://", warning)

    def test_errors_invalid_stdout_and_missing_command_are_concise(self):
        for mode in ("failure", "multiple-json", "array"):
            self.provider["env"] = {"FIXTURE_MODE": mode}
            self.configure()
            result = self.search()
            self.assertEqual(result["items"], [])
            self.assertTrue(result["warning"])
        self.provider["command"] = [str(self.root / "missing-command")]
        self.configure()
        self.assertIn("Cannot start provider command", self.search()["warning"])

    def test_resolution_rejects_removed_provider_missing_ref_and_unsafe_urls(self):
        for args in ({"provider": "Missing", "ref": {}}, {"provider": self.provider["name"]}):
            with self.assertRaises(BooksError):
                self.backend.handle({"op": "providerResolve", **args})
        for url in (
            "file:///tmp/book",
            "javascript:alert(1)",
            "https://user:pass@example.org",
            "https://@example.org",
            "https://example.org:bad",
            "https://",
            "https://example.org/\nprivate",
        ):
            self.provider["env"] = {"FIXTURE_URL": url}
            self.configure()
            with self.assertRaisesRegex(BooksError, "invalid web URL"):
                self.backend.provider_resolve({"provider": self.provider["name"], "ref": {}})

    def test_timeout_kills_command_and_its_children(self):
        self.provider["env"] = {"FIXTURE_MODE": "timeout", "FIXTURE_ROOT": str(self.root)}
        self.configure()
        start = time.monotonic()
        with patch.object(self.backend.commands, "timeout", 0.3):
            result = self.search()
        self.assertLess(time.monotonic() - start, 2)
        self.assertIn("timed out", result["warning"])
        child = int((self.root / "child-pid").read_text())
        self.assert_process_stopped(child)

    def download(self, offer=None, book=None):
        offer = offer or self.search()["items"][1]
        return self.backend.handle(
            {"op": "providerDownload", "offer": offer, "book": book or self.book}
        )["job_id"]

    def finish_download(self, job_id):
        for _ in range(300):
            row = next(
                j for j in self.backend.handle({"op": "jobs"})["jobs"] if j["job_id"] == job_id
            )
            if row["state"] not in ("queued", "running"):
                return row
            time.sleep(0.01)
        self.fail("Download did not settle")

    def test_download_resolves_fresh_link_and_uses_shared_torrent_destination_and_import(self):
        with (
            patch.object(
                self.backend.commands, "resolve", wraps=self.backend.commands.resolve
            ) as resolve,
            patch.object(books_urllib_request(), "urlopen", return_value=BookResponse()),
        ):
            job = self.finish_download(self.download())
        self.assertEqual(job["state"], "finished", job)
        expected = destination(
            self.book | {"kind": "book", "author": "Ada Lovelace"}, Path("book.pdf")
        )
        self.assertEqual(job["result"]["path"], str(expected))
        self.assertEqual(expected.read_bytes(), b"%PDF-1.7\nfixture book")
        self.assertEqual(resolve.call_args.args[2], "download")
        self.assertEqual(
            self.backend.local.files(self.book | {"kind": "book"})[0]["path"], str(expected)
        )
        self.assertTrue(expected.with_suffix(".pdf." + SPACE + ".json").is_file())
        self.assertNotIn("short-lived", json.dumps(self.backend.downloads.snapshots()))
        self.assertNotIn(
            b"short-lived", self.backend.local.data.joinpath("library.sqlite").read_bytes()
        )

    def test_unmatched_offer_imports_its_own_metadata_without_open_library_operations(self):
        offer = self.search()["items"][1] | {
            "title": "An Example Book Companion",
            "authors": ["Other Writer"],
            "identifiers": ["9780000000002"],
        }
        with (
            patch.object(books_urllib_request(), "urlopen", return_value=BookResponse()),
            patch.object(
                self.backend,
                "request",
                side_effect=AssertionError("Provider-only result must stay outside Open Library"),
            ),
        ):
            job = self.finish_download(self.download(offer))
        self.assertEqual(job["state"], "finished", job)
        record = self.backend.local.list("book")[0]
        self.assertEqual(record["source"], "provider")
        self.assertTrue(record["id"].startswith("book-command:"))
        self.assertEqual(record["title"], offer["title"])
        self.assertIn("Other Writer/An Example Book Companion (2001)", job["result"]["path"])
        self.assertEqual(self.backend.local.files(self.book | {"kind": "book"}), [])
        self.assertIsNone(normalize_work(record))

    def test_download_refuses_web_pages_empty_incomplete_files_and_does_not_leave_partials(self):
        for response in (
            BookResponse(b"<html>login</html>", "text/html"),
            BookResponse(b"<!doctype html>login", "application/octet-stream"),
            BookResponse(b""),
            BookResponse(b"partial", length=100),
        ):
            with (
                self.subTest(),
                patch.object(books_urllib_request(), "urlopen", return_value=response),
            ):
                job = self.finish_download(self.download())
            self.assertEqual(job["state"], "failed", job)
            self.assertEqual(self.backend.local.list("book"), [])
            self.assertFalse(list((self.backend.data / "downloads").iterdir()))
            self.assertNotIn("short-lived", job["error"])

    def test_download_deadline_cleans_up_partial_and_does_not_import(self):
        with patch('spaces.books.backend.TRANSFER_DEADLINE', 0.01), patch.object(
                books_urllib_request(), "urlopen", return_value=BookResponse(b"book", delay=0.03)):
            job = self.finish_download(self.download())
        self.assertEqual(job["state"], "failed", job)
        self.assertIn("timed out", job["error"])
        self.assertFalse(list((self.backend.data / "downloads").iterdir()))
        self.assertEqual(self.backend.local.list("book"), [])

    def test_download_failure_sanitizes_http_error_and_retry_resolves_again(self):
        offer = self.search()["items"][1]
        with patch.object(
            self.backend.commands, "resolve", wraps=self.backend.commands.resolve
        ) as resolve:
            with patch.object(
                books_urllib_request(),
                "urlopen",
                side_effect=HTTPError(
                    "https://example.org/?token=short-lived", 403, "private message", {}, None
                ),
            ):
                failed = self.finish_download(self.download(offer))
            with patch.object(books_urllib_request(), "urlopen", return_value=BookResponse()):
                retried = self.finish_download(self.download(offer))
        self.assertEqual(failed["state"], "failed")
        self.assertIn("HTTP 403", failed["error"])
        self.assertNotIn("short-lived", failed["error"])
        self.assertEqual(retried["state"], "finished", retried)
        self.assertEqual(resolve.call_count, 2)

    def test_download_resolution_failure_settles_job_without_requesting_a_file(self):
        offer = self.search()["items"][1]
        self.provider["env"] = {"FIXTURE_MODE": "failure"}
        self.configure()
        with patch.object(books_urllib_request(), "urlopen") as download:
            job = self.finish_download(self.download(offer))
        self.assertEqual(job["state"], "failed")
        self.assertIn("Search unavailable", job["error"])
        download.assert_not_called()

    def test_download_cancel_reports_progress_and_keeps_existing_files(self):
        with patch.object(
            books_urllib_request(),
            "urlopen",
            return_value=BookResponse(b"%PDF" + b"a" * 1048576, delay=0.03),
        ):
            identifier = self.download()
            for _ in range(100):
                job = next(
                    j
                    for j in self.backend.downloads.snapshots()["jobs"]
                    if j["job_id"] == identifier
                )
                if job["done"]:
                    break
                time.sleep(0.01)
            self.assertGreater(job["done"], 0)
            self.assertGreater(job["total"], job["done"])
            self.backend.handle({"op": "cancel_job", "job_id": identifier})
            self.assertEqual(self.finish_download(identifier)["state"], "cancelled")
        self.assertFalse(list((self.backend.data / "downloads").iterdir()))
        self.assertEqual(self.backend.local.list("book"), [])
        with patch.object(books_urllib_request(), "urlopen", return_value=BookResponse()):
            completed = self.finish_download(self.download())
        target = Path(completed["result"]["path"])
        with patch.object(
            books_urllib_request(), "urlopen", return_value=BookResponse(b"new content")
        ):
            duplicate = self.finish_download(self.download())
        self.assertEqual(duplicate["state"], "failed")
        self.assertEqual(target.read_bytes(), b"%PDF-1.7\nfixture book")

    def assert_process_stopped(self, pid):
        for _ in range(40):
            try:
                state = Path(f"/proc/{pid}/stat").read_text().split()[2]
            except FileNotFoundError:
                return
            if state == "Z":
                return
            time.sleep(0.025)
        self.fail("Provider process is still running")

    def test_real_worker_settles_requests_and_stops_owned_commands_on_termination(self):
        self.provider["env"] = {"FIXTURE_MODE": "timeout", "FIXTURE_ROOT": str(self.root)}
        config_root = self.root / "config/quickshell/desktop/spaces/books"
        config_root.mkdir(parents=True)
        (config_root / "books.json").write_text(json.dumps({"providers": [self.provider]}))
        env = dict(
            os.environ,
            XDG_CONFIG_HOME=str(self.root / "config"),
            XDG_DATA_HOME=str(self.root / "worker-data"),
            XDG_CACHE_HOME=str(self.root / "worker-cache"),
        )
        worker = subprocess.Popen(
            [sys.executable, str(support.DESKTOP / "spaces/books/backend.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self.addCleanup(lambda: worker.kill() if worker.poll() is None else None)
        worker.stdin.write(json.dumps({"id": 1, "op": "providerSearch", "query": "fixture"}) + "\n")
        worker.stdin.flush()
        for _ in range(80):
            if (self.root / "child-pid").exists():
                break
            time.sleep(0.025)
        self.assertTrue((self.root / "child-pid").exists())
        worker.send_signal(signal.SIGTERM)
        output, diagnostics = worker.communicate(timeout=3)
        self.assertEqual(worker.returncode, 0, diagnostics)
        response = json.loads(output)
        self.assertEqual(response["id"], 1)
        self.assertIn("warning", response["result"])
        self.assert_process_stopped(int((self.root / "child-pid").read_text()))


def books_urllib_request():
    from spaces.books import backend

    return backend.urllib.request



class BooksBlockedDownloadShutdownTests(unittest.TestCase):
    def test_close_bounds_blocked_transfer_and_removes_its_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / 'worker.py'
            script.write_text('''import time
from spaces.books import backend as b
class FixtureBackend(b.BooksBackend):
 def __init__(self):
  super().__init__()
  def blocked():
   with self.staging_directory() as directory:
    (directory / "partial.epub").write_bytes(b"partial")
    (self.data / "ready").touch()
    time.sleep(30)
  self.downloads.start("Blocked transfer",blocked)
b.BooksBackend=FixtureBackend
b.main()
''')
            env = {**os.environ, 'PYTHONPATH':str(support.DESKTOP),'QUICKSHELL_MEDIA_SPACE':'books',
                   'XDG_CONFIG_HOME':str(root/'config'),'XDG_DATA_HOME':str(root/'data'),
                   'XDG_CACHE_HOME':str(root/'cache')}
            worker = subprocess.Popen([sys.executable,str(script)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,text=True)
            try:
                data = root/'data/quickshell/desktop/spaces/books'
                for _ in range(100):
                    if (data/'ready').exists():break
                    time.sleep(0.02)
                self.assertTrue((data/'ready').exists())
                self.assertTrue(list((data/'downloads').rglob('partial.epub')))
                started = time.monotonic()
                worker.terminate(); worker.communicate(timeout=4)
                self.assertLess(time.monotonic()-started,3.5)
                self.assertEqual(worker.returncode,0)
                self.assertEqual(list((data/'downloads').iterdir()),[])
            finally:
                if worker.poll() is None:worker.kill();worker.communicate()


if __name__ == "__main__":
    unittest.main()
