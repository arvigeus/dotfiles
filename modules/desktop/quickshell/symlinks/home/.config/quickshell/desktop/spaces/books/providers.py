"""Generic JSON command providers owned by the Books worker."""

from spaces.pictures.command_provider import CommandRunner, safe_url
from spaces.pictures.provider_plugins import ProviderError


def normalize_result(row, provider):
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
    fields = (
        'id',
        'title',
        'authors',
        'year',
        'format',
        'language',
        'publisher',
        'pages',
        'identifiers',
        'size_bytes',
        'size',
        'cover_url',
        'description',
        'page_url',
        'ref',
    )
    result = {key: row[key] for key in fields if key in row}
    result.update(source='provider', provider=provider['name'], authors=authors)
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
