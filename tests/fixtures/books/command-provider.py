"""Offline command fixture speaking only the generic Books provider protocol."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

request = json.load(sys.stdin)
mode = os.environ.get("FIXTURE_MODE", "normal")
root = Path(os.environ["FIXTURE_ROOT"]) if os.environ.get("FIXTURE_ROOT") else None
if root:
    with (root / (request["op"] + "-calls")).open("a") as output:
        output.write("called\n")
if mode == "timeout":
    if root:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        (root / "child-pid").write_text(str(child.pid))
    time.sleep(30)
if mode == "failure":
    print(json.dumps({"success": False, "error": "Search unavailable. Retry later."}))
    sys.exit(1)
if mode in ("stderr", "private-error"):
    detail = (
        "Cannot connect "
        + os.environ.get(os.environ.get("FIXTURE_ENV_KEY", ""), "")
        + " https://example.org/private?token=short-lived"
    )
    if mode == "stderr":
        print(detail, file=sys.stderr)
        sys.exit(2)
    print(json.dumps({"success": False, "error": detail}))
    sys.exit(1)
if mode == "multiple-json":
    print("{}\n{}")
    sys.exit(0)
if mode == "array":
    print("[]")
    sys.exit(0)
if request["op"] == "resolve":
    reference = request["ref"]
    url = os.environ.get("FIXTURE_URL", "https://example.org/read?token=short-lived")
    if request.get("purpose") == "download" and os.environ.get("FIXTURE_DOWNLOAD_BASE"):
        url = (
            os.environ["FIXTURE_DOWNLOAD_BASE"]
            + "/book."
            + reference["file"]
            + "?token=short-lived"
        )
    response = {"success": True, "url": url}
    if root:
        (root / "resolved-ref.json").write_text(json.dumps(reference))
else:
    results = []
    for fmt in ("epub", "pdf"):
        results.append(
            {
                "id": "OL100W",
                "title": "The Example Book",
                "authors": ["Ada Lovelace"],
                "year": 2001,
                "format": fmt,
                "language": "eng",
                "publisher": "Example Press",
                "pages": 312,
                "identifiers": ["978-0-000000-00-1"],
                "size_bytes": 2048000,
                "size": "2 MB",
                "cover_url": "https://example.org/cover.jpg",
                "description": "A generic fixture edition.",
                "page_url": "https://example.org/book",
                "ref": {"file": fmt},
            }
        )
        if mode == "echo":
            results[-1]["ref"].update(
                request=request,
                argv=sys.argv[1:],
                env=os.environ.get(os.environ.get("FIXTURE_ENV_KEY", ""), ""),
            )
    response = {
        "success": True,
        "query": request["query"],
        "count": len(results),
        "results": results,
    }
print("Separate diagnostic channel", file=sys.stderr)
print(json.dumps(response))
