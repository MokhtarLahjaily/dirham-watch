"""HTTP helpers with retries on network errors, 429 and 5xx responses."""

from __future__ import annotations

import logging

import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)
from tenacity.wait import wait_base

from dirham_watch import __version__

log = logging.getLogger(__name__)

USER_AGENT = f"dirham-watch/{__version__} (+https://github.com/MokhtarLahjaily/dirham-watch)"
TIMEOUT_SECONDS = 60
MAX_RETRY_AFTER_SECONDS = 120


class RetryableHTTPError(requests.HTTPError):
    """A response worth retrying: rate limiting or a server-side failure."""


class wait_retry_after(wait_base):
    """Wait as long as a 429/503 `Retry-After` header asks (capped), never less than `fallback`.

    Some servers answer 429 with `Retry-After: 0`; taking the longer of the two keeps the
    exponential backoff from collapsing into immediate retries.
    """

    def __init__(self, fallback: wait_base):
        self.fallback = fallback

    def __call__(self, retry_state) -> float:
        backoff = self.fallback(retry_state)
        error = retry_state.outcome.exception() if retry_state.outcome else None
        response = getattr(error, "response", None)
        header = response.headers.get("Retry-After", "") if response is not None else ""
        if header.strip().isdigit():
            return max(min(float(header), MAX_RETRY_AFTER_SECONDS), backoff)
        return backoff


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


@retry(
    retry=retry_if_exception_type((RetryableHTTPError, requests.ConnectionError, requests.Timeout)),
    stop=stop_after_attempt(6),
    wait=wait_retry_after(fallback=wait_exponential_jitter(initial=2, max=60)),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def get(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    response = session.get(url, params=params, headers=headers, timeout=TIMEOUT_SECONDS)
    if response.status_code == 429 or response.status_code >= 500:
        raise RetryableHTTPError(f"{response.status_code} from {response.url}", response=response)
    response.raise_for_status()
    return response
