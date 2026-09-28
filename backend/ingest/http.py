"""HTTP GET with retries for the public data sources (transient timeouts do happen)."""

import time
import urllib.error
import urllib.request

USER_AGENT = "Mozilla/5.0 (compatible; wine-price-tracker/0.1; research)"


def fetch(url: str, timeout: float = 120, attempts: int = 4, backoff_s: float = 15) -> bytes:
    """Return the response body; retry timeouts, connection errors and 429/5xx with growing waits."""
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500 or attempt == attempts:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == attempts:
                raise
        time.sleep(backoff_s * attempt)
    raise RuntimeError("unreachable")
