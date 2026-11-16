"""Shared HTTP fetch for every collector: timeout, retry with exponential backoff + jitter,
Retry-After support, no retry on permanent 4xx errors."""
import logging
import random
import time

import httpx

log = logging.getLogger("collectors.http")
# SECURITY: httpx logs full request URLs at INFO, and some APIs (TomTom) carry the key in the URL.
logging.getLogger("httpx").setLevel(logging.WARNING)
RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchError(Exception):
    """Raised when a source cannot be fetched after all retries."""


def _retry_after(resp: httpx.Response) -> float | None:
    v = resp.headers.get("Retry-After")
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def get_json(url: str, params: dict | None = None, *, headers: dict | None = None,
             client: httpx.Client | None = None, max_attempts: int = 3, base_delay: float = 1.0,
             timeout: float = 15.0, sleep=time.sleep) -> dict | list:
    own = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        last = "unknown error"
        for attempt in range(1, max_attempts + 1):
            delay = base_delay * 2 ** (attempt - 1)
            try:
                r = client.get(url, params=params, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last = type(e).__name__
            else:
                if r.status_code in RETRY_STATUS:
                    last = f"HTTP {r.status_code}"
                    delay = _retry_after(r) or delay
                elif r.status_code >= 400:  # permanent error: do not retry (and never log params: may hold API keys)
                    raise FetchError(f"HTTP {r.status_code} from {url}: {r.text[:200]}")
                else:
                    try:
                        return r.json()
                    except ValueError as e:
                        raise FetchError(f"Invalid JSON from {url}") from e
            if attempt < max_attempts:
                wait = min(delay, 30.0) + random.uniform(0, 0.25 * delay)
                log.warning("%s attempt %d/%d failed (%s); retrying in %.1fs", url, attempt, max_attempts, last, wait)
                sleep(wait)
        raise FetchError(f"{url} failed after {max_attempts} attempts: {last}")
    finally:
        if own:
            client.close()
