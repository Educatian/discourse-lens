"""Rate-limited HTTP client for API calls (OpenAlex, Crossref, Anthropic).

Adapted from ai-literacy-corpus http.py — robots.txt logic dropped since
we're hitting documented public APIs, not crawling. Per-host token bucket
+ tenacity retry with exponential backoff retained.
"""
from __future__ import annotations
import threading
import time
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

CONTACT = "jewoong.moon@gmail.com"
USER_AGENT = f"discourse-lens/0.1 (+UA ADDIE Lab; research; contact: {CONTACT})"


class RateLimiter:
    """Per-host token bucket. Default 5 rps; OpenAlex polite pool tolerates 10."""
    def __init__(self, default_rps: float = 5.0):
        self.default_rps = default_rps
        self._last: dict[str, float] = {}
        self._rps: dict[str, float] = {}
        self._lock = threading.Lock()

    def set_rate(self, host: str, rps: float) -> None:
        with self._lock:
            self._rps[host] = rps

    def acquire(self, host: str) -> None:
        with self._lock:
            rps = self._rps.get(host, self.default_rps)
            min_interval = 1.0 / rps
            last = self._last.get(host, 0.0)
            now = time.monotonic()
            wait = (last + min_interval) - now
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.monotonic()


class FetchClient:
    def __init__(self, default_rps: float = 5.0, timeout: float = 30.0):
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
            http2=False,
        )
        self.limiter = RateLimiter(default_rps)
        # Per the OpenAlex polite-pool docs: include mailto in the request,
        # but we set hosts conservatively here.
        self.set_host_rate("api.openalex.org", 8.0)
        self.set_host_rate("api.crossref.org", 4.0)

    def set_host_rate(self, host: str, rps: float) -> None:
        self.limiter.set_rate(host, rps)

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        reraise=True,
    )
    def get_json(self, url: str, params: dict | None = None) -> dict:
        host = urlparse(url).netloc
        self.limiter.acquire(host)
        r = self.client.get(url, params=params)
        if r.status_code >= 500 or r.status_code == 429:
            r.raise_for_status()
        if r.status_code >= 400:
            # Don't retry 4xx (other than 429); surface as ValueError
            raise ValueError(f"HTTP {r.status_code} from {url}: {r.text[:300]}")
        return r.json()

    def close(self) -> None:
        self.client.close()
