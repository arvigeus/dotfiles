"""Shared Nextcloud Music transport; credentials stay in authenticated POST bodies."""
import hashlib
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from integrations import nextcloud


class MusicError(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise MusicError("Nextcloud Music redirected the request. Check the shared account URL.")


class SubsonicClient:
    METHODS = frozenset()

    def __init__(self, account=None, key=None, opener=None):
        account = nextcloud.load_account() if account is None else account
        if not account:
            raise MusicError("Configure the shared Nextcloud account to use your Music library.")
        self.account = nextcloud.validate_account(account)
        self.key = nextcloud.music_api_key() if key is None else key
        self.endpoint = self.account["url"] + "index.php/apps/music/subsonic/rest/"
        self.account_id = hashlib.sha256(json.dumps(self.account, sort_keys=True).encode()).hexdigest()
        self.opener = opener or build_opener(NoRedirect())

    def open(self, method, args, headers=None):
        if method not in self.METHODS:
            raise MusicError("Unsupported Nextcloud Music operation.")
        body = urlencode({**args, "u": self.account["username"], "p": self.key,
                          "v": "1.16.1", "c": "QuickshellDesktop", "f": "json"}).encode()
        request = Request(self.endpoint + method + ".view", data=body, method="POST",
                          headers={"Content-Type": "application/x-www-form-urlencoded",
                                   "Accept": "application/json", "User-Agent": "QuickshellDesktop/1.0", **(headers or {})})
        return self.opener.open(request, timeout=15)

    def request(self, method, **args):
        if method not in self.METHODS:
            raise MusicError("Unsupported Nextcloud Music operation.")
        try:
            with self.open(method, args) as response:
                payload = response.read(4 * 1024 * 1024 + 1)
            if len(payload) > 4 * 1024 * 1024:
                raise MusicError("Nextcloud Music returned too much data.")
            result = json.loads(payload).get("subsonic-response")
            if not isinstance(result, dict):
                raise ValueError()
        except HTTPError as error:
            error.close()
            raise MusicError("Nextcloud Music returned HTTP " + str(error.code) + ".") from None
        except (URLError, OSError):
            raise MusicError("Nextcloud Music is unreachable. Saved library data remains available.") from None
        except (ValueError, TypeError, AttributeError):
            raise MusicError("Nextcloud Music returned an unreadable response.") from None
        if result.get("status") != "ok":
            error = result.get("error")
            value = error.get("code") if isinstance(error, dict) else None
            code = str(value) if type(value) is int else "unknown"
            # Provider error bodies can echo submitted values; never return them.
            raise MusicError("Nextcloud Music rejected the request (code " + code + "). Check the shared Music API key.")
        return result

