"""Bounded, text-only public web research; no browser state or subresource loads."""

from html.parser import HTMLParser
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from integrations import private

MAX_BODY = 2 * 1024 * 1024
MAX_TEXT = 160000
USER_AGENT = 'Mozilla/5.0 (compatible; DesktopAssistant/1.0; text-only research)'


class WebError(ValueError):
    pass


def clean_url(value):
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 4096
        or any(ord(c) <= 32 or ord(c) == 127 for c in value)
        or '\\' in value
    ):
        raise WebError(
            'Use an HTTP or HTTPS URL without credentials or control characters.'
        )
    try:
        parsed = urlsplit(value)
        host = (
            (parsed.hostname or '').encode('idna').decode('ascii').lower().rstrip('.')
        )
        port = parsed.port
    except (ValueError, UnicodeError):
        raise WebError('The web URL is invalid.') from None
    if (
        parsed.scheme not in ('http', 'https')
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or '%' in host
    ):
        raise WebError('Use an HTTP or HTTPS URL without credentials.')
    if host == 'localhost' or host.endswith(
        ('.localhost', '.local', '.internal', '.lan', '.home')
    ):
        raise WebError('Web research accepts public hosts only.')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise WebError('Web research accepts public addresses only.')
    netloc = ('[' + host + ']') if ':' in host else host
    if port is not None:
        netloc += ':' + str(port)
    return urlunsplit((parsed.scheme, netloc, parsed.path or '/', parsed.query, ''))


def public_addresses(host, port):
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise WebError('The website could not be resolved.') from None
    addresses = list(dict.fromkeys(record[4][0] for record in records))
    if not addresses or any(
        not ipaddress.ip_address(address).is_global for address in addresses
    ):
        raise WebError('The website resolves to a non-public address.')
    return addresses


class Connection(http.client.HTTPConnection):
    def __init__(self, host, port, address, secure):
        self.address, self.secure = address, secure
        self.default_port = 443 if secure else 80
        super().__init__(host, port, timeout=10)

    def connect(self):
        # Connect to the validated address, while retaining the original Host
        # header, TLS hostname and certificate checks. DNS cannot rebind between
        # validation and connection. Environment proxy settings are not used.
        self.sock = socket.create_connection((self.address, self.port), self.timeout)
        if self.secure:
            try:
                self.sock = ssl.create_default_context().wrap_socket(
                    self.sock, server_hostname=self.host
                )
            except BaseException:
                self.sock.close()
                raise


def fetch(url):
    current = clean_url(url)
    for _redirect in range(4):
        parsed = urlsplit(current)
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        addresses = public_addresses(parsed.hostname, port)
        connection = Connection(
            parsed.hostname, port, addresses[0], parsed.scheme == 'https'
        )
        try:
            connection.request(
                'GET',
                urlunsplit(('', '', parsed.path, parsed.query, '')),
                headers={
                    'User-Agent': USER_AGENT,
                    'Accept': 'text/html,text/plain,application/rss+xml,application/json,application/xml;q=0.8',
                    'Accept-Encoding': 'identity',
                    'Connection': 'close',
                },
            )
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    raise WebError('The website returned an invalid redirect.')
                current = clean_url(urljoin(current, location))
                continue
            if response.status not in (200, 202):
                raise WebError(f'The website returned HTTP {response.status}.')
            encoding = response.getheader('Content-Encoding', 'identity').lower()
            if encoding not in ('', 'identity'):
                raise WebError('The website ignored the text-only transfer request.')
            length = response.getheader('Content-Length', '')
            if length.isdigit() and int(length) > MAX_BODY:
                raise WebError('The web response exceeds the 2 MiB limit.')
            body = response.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                raise WebError('The web response exceeds the 2 MiB limit.')
            mime = response.getheader('Content-Type', '').split(';')[0].strip().lower()
            charset = re.search(
                r'charset=["\']?([a-zA-Z0-9_.-]+)',
                response.getheader('Content-Type', ''),
                re.I,
            )
            try:
                text = body.decode(charset[1] if charset else 'utf-8', 'replace')
            except LookupError:
                text = body.decode('utf-8', 'replace')
            return dict(url=current, text=text, mime=mime, status=response.status)
        except (OSError, http.client.HTTPException):
            raise WebError('The website could not complete the request.') from None
        finally:
            connection.close()
    raise WebError('The website redirected too many times.')


class Page(HTMLParser):
    OMIT = {
        'script',
        'style',
        'template',
        'svg',
        'iframe',
        'object',
        'nav',
        'footer',
        'form',
        'noscript',
    }
    BLOCKS = {
        'p',
        'div',
        'section',
        'article',
        'main',
        'li',
        'h1',
        'h2',
        'h3',
        'h4',
        'tr',
        'br',
        'blockquote',
        'pre',
    }

    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url, self.title, self.parts, self.links = url, [], [], []
        self.stack, self.omit, self.in_title = [], 0, False
        self.anchor = None
        self.characters = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'title':
            self.in_title = True
        hidden = (
            tag in self.OMIT or 'hidden' in attrs or attrs.get('aria-hidden') == 'true'
        )
        if tag not in (
            'br',
            'img',
            'hr',
            'meta',
            'link',
            'input',
            'source',
            'area',
            'wbr',
            'embed',
        ):
            self.stack.append((tag, hidden))
            self.omit += int(hidden)
        if self.omit:
            return
        if tag in self.BLOCKS:
            self.append('\n')
        if tag == 'a' and not self.anchor:
            try:
                url = clean_url(urljoin(self.url, attrs.get('href', '')))
                self.anchor = {'url': url, 'title': []}
            except WebError:
                pass

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        if tag == 'a' and self.anchor:
            label = ' '.join(''.join(self.anchor['title']).split())
            if label and len(self.links) < 40:
                self.links.append(dict(title=label[:200], url=self.anchor['url']))
            self.anchor = None
        if tag in self.BLOCKS and not self.omit:
            self.append('\n')
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                self.omit -= sum(int(hidden) for _, hidden in self.stack[index:])
                del self.stack[index:]
                break

    def append(self, text):
        if self.characters < MAX_TEXT:
            self.parts.append(text[: MAX_TEXT - self.characters])
            self.characters += len(self.parts[-1])

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data[:500])
        if self.omit or self.in_title:
            return
        self.append(data)
        if self.anchor:
            self.anchor['title'].append(data[:500])

    def content(self):
        return '\n'.join(
            line
            for part in ''.join(self.parts).splitlines()
            if (line := ' '.join(part.split()))
        )


class SearchPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results, self.current, self.collect, self.depth = [], None, '', 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get('class', '').split()
        if tag == 'a' and ('result__a' in classes or 'result-link' in classes):
            if self.current:
                self.results.append(self.current)
            url = attrs.get('href', '')
            if url.startswith('//'):
                url = 'https:' + url
            parsed = urlsplit(urljoin('https://duckduckgo.com', url))
            if parsed.hostname in (
                'duckduckgo.com',
                'www.duckduckgo.com',
            ) and parsed.path.startswith('/l/'):
                url = parse_qs(parsed.query).get('uddg', [''])[0]
            try:
                url = clean_url(url)
            except WebError:
                self.current = None
                return
            self.current = dict(title='', url=url, snippet='')
            self.collect, self.depth = 'title', 1
        elif self.collect and tag not in ('br', 'img', 'hr', 'input', 'wbr'):
            self.depth += 1
        elif self.current and (
            'result__snippet' in classes or 'result-snippet' in classes
        ):
            self.collect, self.depth = 'snippet', 1

    def handle_endtag(self, tag):
        if tag in ('br', 'img', 'hr', 'input', 'wbr'):
            return
        if self.collect:
            self.depth -= 1
            if self.depth <= 0:
                self.collect = ''

    def handle_data(self, data):
        if self.collect and self.current:
            self.current[self.collect] += data

    def finish(self):
        if self.current:
            self.results.append(self.current)
            self.current = None
        return self.results


def configuration():
    path = (
        Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
        / 'quickshell/desktop/assistant-web.json'
    )
    try:
        text, _info = private.read(path, follow_symlinks=True)
        value = json.loads(text)
    except FileNotFoundError:
        return dict(provider='auto')
    if (
        not isinstance(value, dict)
        or set(value) - {'provider', 'url'}
        or value.get('provider', 'auto') not in ('auto', 'duckduckgo', 'searxng')
    ):
        raise WebError(
            'assistant-web.json requires provider: auto, duckduckgo or searxng, and an optional public SearXNG url.'
        )
    if value.get('provider') == 'searxng':
        value['url'] = clean_url(value.get('url'))
    return value


def search(query, limit=5):
    settings = configuration()
    providers = (
        ['duckduckgo_lite', 'duckduckgo']
        if settings.get('provider', 'auto') in ('auto', 'duckduckgo')
        else ['searxng']
    )
    failures = []
    for provider in providers:
        try:
            if provider.startswith('duckduckgo'):
                endpoint = (
                    'https://lite.duckduckgo.com/lite/'
                    if provider == 'duckduckgo_lite'
                    else 'https://html.duckduckgo.com/html/'
                )
                url = endpoint + '?' + urlencode({'q': query})
                response = fetch(url)
                if (
                    response['status'] == 202
                    or 'challenge-form' in response['text']
                    or 'anomaly.js' in response['text']
                ):
                    raise WebError('DuckDuckGo requested a browser verification.')
                parser = SearchPage()
                parser.feed(response['text'])
                results = parser.finish()
                if not results and not any(
                    label in response['text'].lower()
                    for label in ('no results', 'no more results')
                ):
                    raise WebError('DuckDuckGo returned an unrecognized search page.')
            else:
                url = (
                    settings['url']
                    + ('&' if '?' in settings['url'] else '?')
                    + urlencode({'q': query, 'format': 'json'})
                )
                response = fetch(url)
                value = json.loads(response['text'])
                results = [
                    dict(
                        title=item.get('title', ''),
                        url=item.get('url', ''),
                        snippet=item.get('content', ''),
                    )
                    for item in value.get('results', [])
                    if isinstance(item, dict)
                ]
            entries, seen = [], set()
            for item in results:
                try:
                    target = clean_url(item['url'])
                except WebError:
                    continue
                if target in seen:
                    continue
                seen.add(target)
                entries.append(
                    dict(
                        title=' '.join(str(item['title']).split())[:300],
                        url=target,
                        snippet=' '.join(str(item['snippet']).split())[:700],
                    )
                )
                if len(entries) >= limit:
                    break
            return dict(
                query=query,
                provider='DuckDuckGo'
                if provider.startswith('duckduckgo')
                else 'SearXNG',
                entries=entries,
                warning=' '.join(failures),
            )
        except (ValueError, TypeError, KeyError) as error:
            failures.append(str(error)[:240])
    raise WebError('Web search is unavailable. ' + ' '.join(failures))


def chunk(text, offset=0, max_chars=9000):
    content = (
        text[offset : offset + max_chars]
        .encode('utf-8')[:11000]
        .decode('utf-8', 'ignore')
    )
    end = offset + len(content)
    return dict(
        content=content,
        offset=offset,
        next_offset=end if end < len(text) else None,
        total_chars=len(text),
        has_more=end < len(text),
    )


def read_page(url, offset=0, max_chars=9000):
    response = fetch(url)
    mime = response['mime']
    if (
        mime in ('text/html', 'application/xhtml+xml')
        or not mime
        and response['text'].lstrip().startswith('<')
    ):
        parser = Page(response['url'])
        parser.feed(response['text'])
        title, text, links = (
            ' '.join(''.join(parser.title).split())[:300],
            parser.content(),
            parser.links,
        )
    elif mime.startswith('text/') or mime in (
        'application/json',
        'application/ld+json',
    ):
        title, text, links = (
            urlsplit(response['url']).hostname,
            response['text'][:MAX_TEXT],
            [],
        )
    else:
        raise WebError(
            'This resource is not a supported text page. Attach documents through the assistant instead.'
        )
    return dict(
        url=response['url'],
        title=title,
        links=links[:20],
        **chunk(text, offset, max_chars),
    )
