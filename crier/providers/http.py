"""Shared HTTP plumbing for provider clients: auth headers, retries, readable errors."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from crier.ports import ProviderError

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
MAX_WAIT_S = 65.0

RetryHint = Callable[[httpx.Response], float | None]


def new_http_client(timeout_s: float = 180) -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(timeout_s, connect=15), follow_redirects=True)


def retry_after_header(response: httpx.Response) -> float | None:
    """Seconds from a numeric `Retry-After` header (the HTTP-date form is ignored)."""
    try:
        return max(float(response.headers.get("retry-after", "")), 0.0)
    except ValueError:
        return None


class ApiHttp:
    """Calls one provider's REST API. Auth headers are sent only to `base_url`, never to
    pre-signed upload/download URLs (storage services reject foreign auth headers).

    Retryable failures wait `backoff_s**attempt`, or longer if the server asks for it via
    `retry_hint`. A server-requested wait above `max_wait_s` (e.g. a daily quota) fails fast."""

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        headers: dict[str, str],
        error: type[ProviderError],
        client: httpx.Client | None = None,
        backoff_s: float = 2.0,
        retry_hint: RetryHint = retry_after_header,
        max_wait_s: float = MAX_WAIT_S,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._name = name
        self._base_url = base_url.rstrip("/")
        self._headers = headers
        self._error = error
        self._client = client or new_http_client()
        self._backoff_s = backoff_s
        self._retry_hint = retry_hint
        self._max_wait_s = max_wait_s
        self._sleep = sleep

    def json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.request(method, path, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise self._error(f"{self._name} {method} {path} returned invalid JSON") from exc

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self._base_url}{path}"
        headers = {**self._headers, **kwargs.pop("headers", {})}
        return self._send(method, url, path, headers=headers, **kwargs)

    def put_bytes(self, url: str, data: bytes, content_type: str) -> None:
        self._send("PUT", url, "upload", content=data, headers={"Content-Type": content_type})

    def download(self, url: str) -> bytes:
        return self._send("GET", url, "download").content

    def close(self) -> None:
        self._client.close()

    def _send(self, method: str, url: str, label: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            wait = self._backoff_s**attempt
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                if attempt == MAX_ATTEMPTS:
                    raise self._error(f"{self._name} {method} {label} failed: {exc}") from exc
            else:
                if response.status_code < 400:
                    return response
                requested = self._requested_wait(response)
                if (
                    response.status_code not in RETRY_STATUSES
                    or attempt == MAX_ATTEMPTS
                    or (requested is not None and requested > self._max_wait_s)
                ):
                    raise self._failure(method, label, response)
                wait = max(wait, requested or 0.0)
            self._sleep(wait)
        raise self._error(f"{self._name} {method} {label} failed after {MAX_ATTEMPTS} attempts")

    def _requested_wait(self, response: httpx.Response) -> float | None:
        try:
            return self._retry_hint(response)
        except (ValueError, TypeError, KeyError, AttributeError):
            return None

    def _failure(self, method: str, label: str, response: httpx.Response) -> ProviderError:
        return self._error(
            f"{self._name} {method} {label} -> {response.status_code}: {response.text[:300]}"
        )
