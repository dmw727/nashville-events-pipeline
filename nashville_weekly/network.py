"""Bounded, cached, polite public HTTP collection. No browser or login required."""
import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

USER_AGENT = 'NashvilleWeekly/1.0 (personal public-events calendar)'

class CollectionError(Exception):
    pass

class Client:
    def __init__(self, cache, offline=False, timeout=25, delay=1.0):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.offline, self.timeout, self.delay = offline, timeout, delay
        self.robots, self.locks, self.last = {}, {}, {}
        self.guard = threading.Lock()
        self.audit = []

    def _request(self, url, headers=None):
        for attempt in range(3):
            try:
                with urlopen(Request(url, headers={'User-Agent': USER_AGENT, 'Accept': '*/*', **(headers or {})}), timeout=self.timeout) as r:
                    raw = r.read(8_000_001)
                    if len(raw) > 8_000_000:
                        raise CollectionError('Response exceeds 8 MB limit')
                    return raw.decode(r.headers.get_content_charset() or 'utf-8', 'replace'), dict(r.headers), r.url
            except HTTPError as e:
                if e.code == 304:
                    return None, {}, url
                if e.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise CollectionError(f'HTTP {e.code}: {url}') from e
                retry = e.headers.get('Retry-After', '2')
                try: pause = min(30, max(1, int(retry)))
                except ValueError: pause = 2 ** (attempt + 1)
                time.sleep(pause)
            except (TimeoutError, OSError) as e:
                if attempt == 2:
                    raise CollectionError(str(e)) from e
                time.sleep(2 ** attempt)
        raise CollectionError('Request failed')

    def get(self, url):
        if urlsplit(url).scheme not in ('http', 'https'):
            raise CollectionError('Only public HTTP(S) URLs are supported')
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.cache / (key + '.json')
        cached = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        if self.offline:
            if not cached:
                raise CollectionError('Not in offline cache: ' + url)
            self.audit.append({'url': url, 'mode': 'offline', 'fetched_at': cached['fetched_at']})
            return cached['body']
        origin = '{0.scheme}://{0.netloc}'.format(urlsplit(url))
        with self.guard:
            lock = self.locks.setdefault(origin, threading.Lock())
        with lock:
            if origin not in self.robots:
                rp = RobotFileParser()
                try:
                    body, _, _ = self._request(origin + '/robots.txt')
                    rp.parse(body.splitlines())
                except CollectionError as e:
                    if 'HTTP 404:' in str(e) or 'HTTP 410:' in str(e):
                        rp.parse([])
                    else:
                        raise CollectionError('Cannot verify robots.txt: ' + str(e)) from e
                self.robots[origin] = rp
            rp = self.robots[origin]
            if not rp.can_fetch(USER_AGENT, url):
                raise CollectionError('Disallowed by robots.txt: ' + url)
            delay = max(self.delay, rp.crawl_delay(USER_AGENT) or 0)
            time.sleep(max(0, delay - (time.monotonic() - self.last.get(origin, 0))))
            headers = {}
            if cached:
                for old, new in [('ETag', 'If-None-Match'), ('Last-Modified', 'If-Modified-Since')]:
                    if cached.get('headers', {}).get(old): headers[new] = cached['headers'][old]
            try:
                body, response_headers, final_url = self._request(url, headers)
            finally:
                self.last[origin] = time.monotonic()
            now = datetime.now(timezone.utc).isoformat()
            if body is None:
                body = cached['body']
            else:
                record = {'url': url, 'final_url': final_url, 'fetched_at': now, 'headers': response_headers, 'body': body}
                tmp = path.with_suffix('.tmp')
                tmp.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
                tmp.replace(path)
            self.audit.append({'url': url, 'mode': 'live', 'checked_at': now})
            return body
