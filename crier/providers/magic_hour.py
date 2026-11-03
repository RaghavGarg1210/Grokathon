"""Magic Hour image-to-video: animates each scene still into a short clip."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from crier.ports import ProviderError
from crier.providers.http import ApiHttp
from crier.settings import MagicHourSettings

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 5
FAILED_STATUSES = {"error", "canceled"}
# Allowed clip lengths (seconds) per model, from the image-to-video API reference.
MODEL_SECONDS = {
    "default": (3, 15),
    "ltx-2.5": (1, 60),
    "kling-3.0": (3, 15),
    "kling-4.0": (3, 30),
    "minimax-h3": (1, 30),
    "seedance-2.0": (4, 15),
    "seedance-2.5": (4, 30),
}
FALLBACK_SECONDS = (4, 10)


class MagicHourError(ProviderError):
    """A failed Magic Hour request or video job."""


class MagicHourClient:
    label = "Magic Hour"

    def __init__(
        self,
        settings: MagicHourSettings,
        *,
        resolution: str,
        poll_timeout_s: int,
        http: httpx.Client | None = None,
        poll_interval_s: float = POLL_INTERVAL_S,
        backoff_s: float = 2.0,
    ) -> None:
        if not settings.api_key:
            raise MagicHourError("MAGIC_HOUR_API_KEY is not set")
        self._settings = settings
        self._resolution = resolution
        self._poll_timeout_s = poll_timeout_s
        self._poll_interval_s = poll_interval_s
        self._api = ApiHttp(
            name="Magic Hour",
            base_url=settings.base_url,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            error=MagicHourError,
            client=http,
            backoff_s=backoff_s,
        )

    def start_video(
        self, prompt: str, *, image: bytes | None, duration: int, aspect_ratio: str = "9:16"
    ) -> str:
        """Starts an image-to-video job. The clip keeps the still's 9:16 framing."""
        if not image:
            raise MagicHourError("Magic Hour image-to-video needs a scene still")
        body = {
            "name": "County Crier scene",
            "end_seconds": clamp_seconds(self._settings.video_model, duration),
            "model": self._settings.video_model,
            "resolution": self._resolution,
            "audio": False,
            "style": {"prompt": prompt},
            "assets": {"image_file_path": self._upload_image(image)},
        }
        payload = self._api.json("POST", "/v1/image-to-video", json=body)
        if not payload.get("id"):
            raise MagicHourError("Magic Hour did not return a video id")
        log.info("magic hour job %s: %s credits", payload["id"], payload.get("credits_charged"))
        return str(payload["id"])

    def wait_for_video(
        self, job_id: str, on_progress: Callable[[int], None] | None = None
    ) -> bytes:
        deadline = time.monotonic() + self._poll_timeout_s
        while True:
            data = self._api.json("GET", f"/v1/video-projects/{job_id}")
            status = data.get("status")
            if status == "complete":
                return self._api.download(_download_url(job_id, data))
            if status in FAILED_STATUSES:
                error = data.get("error") or {}
                raise MagicHourError(f"Video {job_id} {status}: {error.get('message', 'unknown')}")
            if on_progress:
                on_progress(0)
            if time.monotonic() > deadline:
                raise MagicHourError(f"Video {job_id} timed out")
            time.sleep(self._poll_interval_s)

    def close(self) -> None:
        self._api.close()

    def _upload_image(self, image: bytes) -> str:
        is_png = image.startswith(b"\x89PNG")
        extension, mime = ("png", "image/png") if is_png else ("jpg", "image/jpeg")
        payload = self._api.json(
            "POST",
            "/v1/files/upload-urls",
            json={"items": [{"type": "image", "extension": extension}]},
        )
        items = payload.get("items") or []
        if not items or not items[0].get("upload_url") or not items[0].get("file_path"):
            raise MagicHourError("Magic Hour did not return an upload URL")
        self._api.put_bytes(items[0]["upload_url"], image, mime)
        return str(items[0]["file_path"])


def clamp_seconds(model: str, seconds: int) -> int:
    low, high = MODEL_SECONDS.get(model, FALLBACK_SECONDS)
    return max(low, min(high, seconds))


def _download_url(job_id: str, data: dict[str, Any]) -> str:
    downloads = data.get("downloads") or []
    if not downloads or not downloads[0].get("url"):
        raise MagicHourError(f"Video {job_id} finished without a download URL")
    return str(downloads[0]["url"])
