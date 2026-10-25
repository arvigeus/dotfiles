"""Small, account-scoped Nextcloud Music Subsonic client for saved radio stations."""
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


class MusicClient:
    METHODS = {"getInternetRadioStations", "createInternetRadioStation",
               "updateInternetRadioStation", "deleteInternetRadioStation"}

    def __init__(self, account=None, key=None, opener=None):
        account = nextcloud.load_account() if account is None else account
        if not account:
            raise MusicError("Configure the shared Nextcloud account to sync Radio favorites.")
        self.account = nextcloud.validate_account(account)
        self.key = nextcloud.music_api_key() if key is None else key
        self.endpoint = self.account["url"] + "index.php/apps/music/subsonic/rest/"
        self.account_id = hashlib.sha256(json.dumps(self.account, sort_keys=True).encode()).hexdigest()
        self.opener = opener or build_opener(NoRedirect())

    def request(self, method, **args):
        if method not in self.METHODS:
            raise MusicError("Unsupported Nextcloud Music operation.")
        # Subsonic accepts POST form data: credentials never enter URLs or argv.
        body = urlencode({**args, "u": self.account["username"], "p": self.key,
                          "v": "1.16.1", "c": "QuickshellDesktopRadio", "f": "json"}).encode()
        request = Request(self.endpoint + method + ".view", data=body, method="POST",
                          headers={"Content-Type": "application/x-www-form-urlencoded",
                                   "Accept": "application/json", "User-Agent": "QuickshellDesktop/1.0"})
        try:
            with self.opener.open(request, timeout=15) as response:
                payload = response.read(4 * 1024 * 1024 + 1)
            if len(payload) > 4 * 1024 * 1024:
                raise MusicError("Nextcloud Music returned too much data.")
            result = json.loads(payload).get("subsonic-response")
            if not isinstance(result, dict):
                raise ValueError()
        except HTTPError as error:
            raise MusicError("Nextcloud Music returned HTTP " + str(error.code) + ".") from None
        except (URLError, OSError):
            raise MusicError("Nextcloud Music is unreachable. Favorites remain saved locally.") from None
        except (ValueError, TypeError, AttributeError):
            raise MusicError("Nextcloud Music returned an unreadable response.") from None
        if result.get("status") != "ok":
            error = result.get("error")
            value = error.get("code") if isinstance(error, dict) else None
            code = str(value) if type(value) is int else "unknown"
            # Provider error bodies can echo submitted values; never return them.
            raise MusicError("Nextcloud Music rejected the request (code " + code + "). Check the shared Music API key.")
        return result

    def stations(self):
        result = self.request("getInternetRadioStations")
        if "internetRadioStations" not in result:
            raise MusicError("Nextcloud Music omitted its station list; favorites were preserved.")
        value = result["internetRadioStations"]
        rows = value.get("internetRadioStation", []) if isinstance(value, dict) else None
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise MusicError("Nextcloud Music returned an invalid station list.")
        if len(rows) > 1000:
            raise MusicError("Nextcloud Music has more than 1,000 stations; favorites were preserved.")
        for row in rows:
            if not str(row.get("id", "")).isdigit() or not isinstance(row.get("streamUrl"), str):
                raise MusicError("Nextcloud Music returned an invalid station record.")
        return rows
