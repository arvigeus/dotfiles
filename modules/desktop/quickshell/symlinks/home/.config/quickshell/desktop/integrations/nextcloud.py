"""Nextcloud account (nextcloud.json), private app password, and scoped DAV transport."""

import base64
import json
import os
import stat
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NextcloudError(ValueError):
    pass


class CredentialMissing(NextcloudError):
    pass


def config_root():
    base = os.environ.get('XDG_CONFIG_HOME') or ''
    root = Path(base) if os.path.isabs(base) else Path.home() / '.config'
    return root / 'quickshell/desktop/integrations'


def password_path(root=None):
    return (root or config_root()) / 'nextcloud-app-password'


def read_json(path):
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise NextcloudError(
            f'Cannot read {path.name}. Check its JSON syntax and permissions.'
        ) from error
    if not isinstance(data, dict):
        raise NextcloudError(f'{path.name} must contain a JSON object.')
    return data


def validate_account(data):
    """Return the canonical {url, username} account; other keys are ignored."""
    url = data.get('url', '')
    username = data.get('username', '')
    if not isinstance(url, str) or not isinstance(username, str):
        raise NextcloudError('Set an HTTPS URL and username in nextcloud.json.')
    try:
        parsed = urlsplit(url)
        port = parsed.port  # Raises ValueError for a malformed or out-of-range port.
    except ValueError as error:
        raise NextcloudError(
            'Set a valid HTTPS instance URL in nextcloud.json.'
        ) from error
    if (
        parsed.scheme != 'https'
        or not parsed.hostname
        or port == 0
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not username.strip()
        or ':' in username
        or any(char.isspace() for char in url)
        or any(part in ('.', '..') for part in unquote(parsed.path).split('/'))
    ):
        raise NextcloudError(
            'Set an HTTPS instance URL and username in nextcloud.json.'
        )
    return {'url': url.rstrip('/') + '/', 'username': username.strip()}


def load_account(root=None):
    path = (root or config_root()) / 'nextcloud.json'
    if not path.exists():
        return None
    return validate_account(read_json(path))


def app_password(root=None):
    """Read nextcloud-app-password: a regular file owned by you, mode 0600, not a symlink."""
    return _secret(password_path(root), 'app password')


def music_api_key(root=None):
    """Music's Subsonic key belongs to the same shared account as DAV."""
    return _secret((root or config_root()) / 'nextcloud-music-api-key', 'Music API key')


def _secret(path, label):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError as error:
        raise CredentialMissing(
            'Save the Nextcloud ' + label + ' with mode 0600.'
        ) from error
    except OSError as error:
        raise NextcloudError('Cannot open the Nextcloud ' + label + ' file.') from error
    with os.fdopen(descriptor) as source:
        info = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
        ):
            raise NextcloudError(
                'The Nextcloud ' + label + ' file must be owned by you with mode 0600.'
            )
        try:
            secret = source.read(65537).strip()
        except (OSError, UnicodeError) as error:
            raise NextcloudError('Cannot read the Nextcloud ' + label + '.') from error
    if not secret or len(secret) > 65536 or '\n' in secret or '\r' in secret:
        raise NextcloudError('The Nextcloud ' + label + ' is empty or invalid.')
    return secret


class SameOriginRedirect(HTTPRedirectHandler):
    def __init__(self, allowed):
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not self.allowed(newurl):
            raise NextcloudError(
                'Nextcloud redirected outside the configured DAV scope.'
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class DAVClient:
    def __init__(self, account, *, scope, opener=None):
        self.account = validate_account(account)
        self.base = self.account['url']
        self.username = self.account['username']
        self.origin = urlsplit(self.base).netloc
        self.home = self.base + scope.lstrip('/')
        password = app_password()
        self.auth = (
            'Basic '
            + base64.b64encode((self.username + ':' + password).encode()).decode()
        )
        self.opener = opener or build_opener(SameOriginRedirect(self.allowed))

    def allowed(self, url):
        parsed = urlsplit(url)
        return (
            parsed.scheme == 'https'
            and parsed.netloc == self.origin
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
            and url.startswith(self.home)
            and not any(part in ('.', '..') for part in unquote(parsed.path).split('/'))
        )

    def request(self, method, url, body=None, headers=None):
        if not self.allowed(url):
            raise NextcloudError(
                'The Nextcloud DAV URL is outside the configured account scope.'
            )
        request = Request(
            url,
            data=body,
            method=method,
            headers={
                'User-Agent': 'DesktopShell/1.0',
                'Accept': 'application/xml, text/calendar',
                **(headers or {}),
                'Authorization': self.auth,
            },
        )
        try:
            with self.opener.open(request, timeout=18) as response:
                data = response.read(16 * 1024 * 1024 + 1)
                if len(data) > 16 * 1024 * 1024:
                    raise NextcloudError(
                        'The Nextcloud response is too large. Select fewer collections.'
                    )
                return data, response.headers
        except HTTPError as error:
            error.close()
            if error.code in (401, 403):
                raise NextcloudError(
                    'Nextcloud rejected the app password or account access.'
                ) from error
            if error.code == 412:
                raise NextcloudError(
                    'The item changed on Nextcloud. Refresh and try again.'
                ) from error
            if error.code in (400, 415, 422):
                raise NextcloudError(
                    'Nextcloud rejected the submitted data (HTTP '
                    + str(error.code)
                    + ').'
                ) from error
            raise NextcloudError(
                'Nextcloud returned HTTP ' + str(error.code) + ' during ' + method + '.'
            ) from error
        except (URLError, OSError) as error:
            raise NextcloudError(
                'Nextcloud is unreachable. Check your connection.'
            ) from error
