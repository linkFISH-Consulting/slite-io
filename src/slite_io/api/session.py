from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import requests

DEFAULT_API_URL = "https://api.slite.com/v1"
log = logging.getLogger("slite_io")


class SliteApiSession(requests.Session):
    """A requests session with Slite authentication and retry handling."""

    base_url: str
    timeout: float
    max_attempts: int

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ):
        """Configure the base URL, auth header, timeout, and retry policy."""
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_attempts = max_attempts
        self._sleep = sleep
        self.headers.update(
            {
                "Accept": "application/json",
                "x-slite-api-key": api_key,
                "User-Agent": "slite-io/0.1.0",
            }
        )

    def request(
        self,
        method: str | bytes,
        url: str | bytes,
        *args: Any,
        **kwargs: Any,
    ) -> requests.Response:
        """Send a request, prefixing relative URLs and retrying transient errors."""
        if isinstance(url, str) and not url.startswith(("http://", "https://")):
            url = f"{self.base_url}/{url.lstrip('/')}"
        kwargs.setdefault("timeout", self.timeout)

        for attempt in range(self.max_attempts):
            log.debug("Slite API request: %s %s (attempt %d)", method, url, attempt + 1)
            response = super().request(method, url, *args, **kwargs)
            log.debug(
                "Slite API response: %s %s -> %d",
                method,
                url,
                response.status_code,
            )
            if response.status_code == 429 or response.status_code >= 500:
                if attempt + 1 < self.max_attempts:
                    delay = _retry_delay(response, attempt)
                    log.debug(
                        "Slite API retry after %ss for status %d",
                        delay,
                        response.status_code,
                    )
                    self._sleep(delay)
                    continue
            return response

        return response


def _retry_delay(response: requests.Response, attempt: int) -> float:
    """Return the server-requested delay or an exponential fallback."""
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    return 0.5 * (2**attempt)
