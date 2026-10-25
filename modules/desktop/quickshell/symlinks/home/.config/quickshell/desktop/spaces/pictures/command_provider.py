"""Direct JSON commands with bounded timeouts and owned process groups."""

import json
import os
import re
import signal
import subprocess
import threading
import urllib.parse

from spaces.pictures.provider_plugins import ProviderError

MAX_OUTPUT_BYTES = 8 * 1024 * 1024


def safe_url(value):
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
        if (
            parsed.scheme.lower() in ("https", "http")
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
        ):
            _ = parsed.port  # Validate the optional port before handing the URL to a browser.
            return value
    except ValueError:
        pass
    return ""


def diagnostic(value, provider):
    """Keep diagnostics short, without echoing environment values or URLs."""
    value = str(value or "")
    for secret in sorted(set(provider["env"].values()), key=len, reverse=True):
        if secret:
            value = value.replace(secret, "[redacted]")
    value = re.sub(r"(?:[a-zA-Z][a-zA-Z0-9+.-]*://|www\.)\S+", "[URL omitted]", value)
    return " ".join(value.split())[:200]


def _invalid_constant(_value):
    raise ValueError("Invalid JSON constant")


class CommandRunner:
    def __init__(self, timeout=25, label="Command"):
        self.timeout = timeout
        self.label = label
        self._lock = threading.Lock()
        self._processes = set()
        self._closed = False

    @staticmethod
    def _kill(process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def close(self):
        with self._lock:
            self._closed = True
            for process in self._processes:
                self._kill(process)

    def call(self, provider, request):
        env = os.environ.copy()
        env.update(provider["env"])
        process = None
        try:
            with self._lock:
                if self._closed:
                    raise ProviderError(self.label + " provider service stopped.")
                process = subprocess.Popen(
                    provider["command"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    start_new_session=True,
                )
                self._processes.add(process)
            try:
                stdout, stderr = process.communicate(
                    (json.dumps(request, ensure_ascii=False) + "\n").encode(), timeout=self.timeout
                )
            except subprocess.TimeoutExpired:
                self._kill(process)
                process.communicate()
                raise ProviderError("Command timed out. Try again.") from None
            if len(stdout) > MAX_OUTPUT_BYTES:
                raise ProviderError("Command returned too much output.")
            try:
                payload = json.loads(stdout, parse_constant=_invalid_constant)
            except (ValueError, UnicodeDecodeError):
                detail = (
                    diagnostic(stderr.decode(errors="replace"), provider)
                    if process.returncode
                    else ""
                )
                if process.returncode:
                    raise ProviderError(
                        "Command failed" + (": " + detail if detail else ".")
                    ) from None
                raise ProviderError("Command must return exactly one JSON object.") from None
            if not isinstance(payload, dict) or type(payload.get("success")) is not bool:
                raise ProviderError("Command returned an invalid response.")
            if payload["success"] is False:
                raise ProviderError(
                    diagnostic(payload.get("error"), provider) or "Provider request failed."
                )
            if process.returncode:
                raise ProviderError("Command exited unsuccessfully.")
            return payload
        except OSError:
            raise ProviderError("Cannot start provider command. Check its configuration.") from None
        finally:
            if process is not None:
                self._kill(process)
                with self._lock:
                    self._processes.discard(process)
