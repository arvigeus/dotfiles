"""Native store content labels. Missing or malformed labels remain unknown."""

import struct
import threading

from spaces.games import gog as gog_store

# Steam client appinfo.vdf v29: binary key/values whose keys index a string table.
APPINFO_MAGIC = 0x07564429
APPINFO_HEADER = 16
# appid and size, then state, update time, PICS token, SHA-1, change number and
# binary SHA-1 precede each app's key/values.
APPINFO_ENTRY = 8 + 60
MAX_APPINFO_BYTES = 128 * 1024 * 1024


def _steam_descriptors(ids):
    if not isinstance(ids, list) or any(type(value) is not int for value in ids):
        return None
    # Valve: Adult Only Sexual Content / Frequent Nudity or Sexual Content.
    # Some nudity (1), violence (2) and general mature content (5) don't qualify.
    if {3, 4}.intersection(ids):
        return True
    return False if set(ids).issubset({1, 2, 5}) else None


def steam_item(item, app_id):
    """Read one IStoreBrowseService/GetItems store item.

    Like the client cache, the store omits `content_descriptorids` when an app
    declares none. Unknown or region-restricted apps report another `success`.
    """
    if (
        not isinstance(item, dict)
        or item.get('success') != 1
        or str(item.get('appid')) != str(app_id)
    ):
        return None
    platforms = item.get('platforms')
    return {
        'nsfw': _steam_descriptors(item.get('content_descriptorids', [])),
        'linux': platforms.get('steamos_linux') is True
        if isinstance(platforms, dict)
        else None,
    }


def gog_nsfw_page(raw):
    """Product IDs and page count from one `tags=is:nsfw` catalogue page.

    Every product must carry the tag: if GOG ignored the filter, the page must
    not label the whole store NSFW.
    """
    products = raw.get('products') if isinstance(raw, dict) else None
    pages = raw.get('pages') if isinstance(raw, dict) else None
    if not isinstance(products, list) or type(pages) is not int or pages < 0:
        return None
    ids = []
    for product in products:
        if not isinstance(product, dict) or not isinstance(product.get('tags'), list):
            return None
        identifier = gog_store.product_id(product.get('id'))
        if not identifier or not any(
            isinstance(tag, dict) and tag.get('slug') == 'nsfw'
            for tag in product['tags']
        ):
            return None
        ids.append(identifier)
    return ids, pages


class SteamAppInfo:
    """Content descriptors and platforms from the Steam client's own app cache.

    The client keeps PICS data for owned and viewed apps, including the same
    `common/content_descriptors` the store API reports. Apps are parsed on
    demand and the index is rebuilt only when the file changes.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._version = None
        self._data = b''
        self._strings = []
        self._offsets = {}
        self._apps = {}

    def label(self, path, app_id):
        return (self.app(path, app_id) or {}).get('nsfw')

    def linux(self, path, app_id):
        return (self.app(path, app_id) or {}).get('linux')

    def app(self, path, app_id):
        try:
            stat = path.stat()
            version = (str(path), stat.st_mtime_ns, stat.st_size)
            app_id = int(app_id)
        except (OSError, ValueError):
            return None
        with self._lock:
            if version != self._version:
                self._load(path, version, stat.st_size)
            if app_id not in self._apps:
                self._apps[app_id] = self._read(app_id)
            return self._apps[app_id]

    def _load(self, path, version, size):
        self._version, self._data, self._strings = version, b'', []
        self._offsets, self._apps = {}, {}
        if size > MAX_APPINFO_BYTES:
            return
        try:
            data = path.read_bytes()
            magic, _, table = struct.unpack_from('<IIq', data, 0)
            if magic != APPINFO_MAGIC or not APPINFO_HEADER <= table < len(data):
                return
            count = struct.unpack_from('<I', data, table)[0]
            strings, position = [], table + 4
            for _ in range(count):
                end = data.index(b'\0', position)
                strings.append(data[position:end].decode('utf-8', 'replace'))
                position = end + 1
            offsets, position = {}, APPINFO_HEADER
            while position + 4 <= table:
                app_id = struct.unpack_from('<I', data, position)[0]
                if not app_id:
                    break
                size = struct.unpack_from('<I', data, position + 4)[0]
                end = position + 8 + size
                if size < APPINFO_ENTRY - 8 or end > table:
                    return
                offsets[app_id] = (position + APPINFO_ENTRY, end)
                position = end
            else:
                return
        except (OSError, struct.error, ValueError):
            return
        self._data, self._strings, self._offsets = data, strings, offsets

    def _read(self, app_id):
        if app_id not in self._offsets:
            return None
        try:
            values, _ = self._object(*self._offsets[app_id])
        except (struct.error, ValueError, IndexError, RecursionError):
            return None
        appinfo = values.get('appinfo')
        common = appinfo.get('common') if isinstance(appinfo, dict) else None
        if not isinstance(common, dict) or not common.get('type'):
            return None
        descriptors = common.get('content_descriptors', {})
        oslist = common.get('oslist', '')
        ids = (
            [
                int(value) if isinstance(value, str) and value.isdigit() else value
                for value in descriptors.values()
            ]
            if isinstance(descriptors, dict)
            else None
        )
        return {
            # An app without the section declares no descriptors.
            'nsfw': _steam_descriptors(ids),
            # Discontinued ports can keep `linux` here; the store is preferred.
            'linux': 'linux' in oslist.split(',') if isinstance(oslist, str) else None,
        }

    def _object(self, position, limit, depth=0):
        if depth > 32:
            raise ValueError('appinfo nesting is too deep')
        data, result = self._data, {}
        while position < limit:
            kind = data[position]
            position += 1
            if kind in (8, 11):
                return result, position
            key = self._strings[struct.unpack_from('<I', data, position)[0]]
            position += 4
            if kind == 0:
                result[key], position = self._object(position, limit, depth + 1)
            elif kind == 1:
                end = data.index(b'\0', position, limit)
                result[key] = data[position:end].decode('utf-8', 'replace')
                position = end + 1
            elif kind in (2, 4, 6):
                result[key] = struct.unpack_from('<i', data, position)[0]
                position += 4
            elif kind == 3:
                result[key] = struct.unpack_from('<f', data, position)[0]
                position += 4
            elif kind in (7, 10):
                result[key] = struct.unpack_from('<Q', data, position)[0]
                position += 8
            else:
                raise ValueError('unsupported appinfo value type')
        raise ValueError('truncated appinfo object')
