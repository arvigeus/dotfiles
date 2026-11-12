"""Generic JSON command providers owned by the Books worker."""

from spaces.pictures.command_provider import CommandRunner, safe_url
from spaces.pictures.provider_plugins import ProviderError


TEXT_FIELDS = ('format', 'language', 'publisher', 'size', 'description')
NUMBER_FIELDS = ('year', 'pages', 'size_bytes')


def _whole_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdecimal():
        return int(value.strip())
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return value if isinstance(value, int) and value >= 0 else None


def normalize_result(row, provider):
    """Keep the documented offer fields, typed as the shell displays them."""
    if (
        not isinstance(row, dict)
        or not isinstance(row.get('title'), str)
        or not row['title'].strip()
        or 'ref' not in row
    ):
        raise ProviderError('Search returned an invalid book offer.')
    authors = row.get('authors', [])
    if not isinstance(authors, list) or not all(
        isinstance(author, str) for author in authors
    ):
        raise ProviderError('Search authors must be a list of text values.')
    # id and ref stay opaque: they name the offer for its provider.
    result = {key: row[key] for key in ('id', 'identifiers', 'ref') if key in row}
    for key in TEXT_FIELDS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    for key in NUMBER_FIELDS:
        value = _whole_number(row.get(key))
        if value is not None:
            result[key] = value
    result.update(
        source='provider',
        provider=provider['name'],
        title=row['title'],
        authors=authors,
    )
    for key in ('cover_url', 'page_url'):
        result[key] = safe_url(row.get(key))
    return result


class CommandProviders(CommandRunner):
    def __init__(self):
        super().__init__(label='Books')

    def search(self, provider, query, page=0, limit=10):
        payload = self.call(
            provider, {'op': 'search', 'query': query, 'page': page, 'limit': limit}
        )
        if not isinstance(payload.get('results'), list):
            raise ProviderError('Search response must contain a results list.')
        return [normalize_result(row, provider) for row in payload['results']]

    def resolve(self, provider, ref, purpose=None):
        request = {'op': 'resolve', 'ref': ref}
        if purpose:
            request['purpose'] = purpose
        payload = self.call(provider, request)
        url = safe_url(payload.get('url'))
        if not url:
            raise ProviderError('Provider returned an invalid web URL.')
        return {'url': url}
