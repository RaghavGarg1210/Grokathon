"""xAI (Grok): optional provider for X search, text, Imagine images/video and TTS."""

from __future__ import annotations

import base64
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

import httpx
from openai import OpenAI, OpenAIError
from pydantic import BaseModel

from crier.models import Language
from crier.ports import ParsedResult, ProviderError, SpeechResult
from crier.providers.http import ApiHttp
from crier.settings import XaiSettings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
POLL_INTERVAL_S = 5


class XaiError(ProviderError):
    """A failed xAI request or video job."""


class XaiClient:
    label = "Grok"

    def __init__(
        self,
        settings: XaiSettings,
        *,
        resolution: str,
        poll_timeout_s: int,
        http: httpx.Client | None = None,
        openai_client: OpenAI | None = None,
        poll_interval_s: float = POLL_INTERVAL_S,
        backoff_s: float = 2.0,
    ) -> None:
        if not settings.api_key:
            raise XaiError("XAI_API_KEY is not set")
        self._settings = settings
        self._resolution = resolution
        self._poll_timeout_s = poll_timeout_s
        self._poll_interval_s = poll_interval_s
        self._openai = openai_client or OpenAI(
            api_key=settings.api_key, base_url=settings.base_url, timeout=300, max_retries=2
        )
        self._api = ApiHttp(
            name="xAI",
            base_url=settings.base_url,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            error=XaiError,
            client=http,
            backoff_s=backoff_s,
        )

    def parse(
        self,
        *,
        instructions: str,
        prompt: str,
        schema: type[T],
        tools: list[dict[str, Any]] | None = None,
        max_turns: int | None = None,
    ) -> ParsedResult[T]:
        kwargs: dict[str, Any] = {
            "model": self._settings.text_model,
            "instructions": instructions,
            "input": prompt,
            "text_format": schema,
        }
        if tools:
            kwargs["tools"] = tools
        if max_turns:
            kwargs["extra_body"] = {"max_turns": max_turns}
        try:
            response = self._openai.responses.parse(**kwargs)
        except OpenAIError as exc:
            raise XaiError(f"Grok request failed: {exc}") from exc
        if response.output_parsed is None:
            raise XaiError(f"Grok returned no {schema.__name__} output")
        usage = response.usage.model_dump() if response.usage else {}
        log.info("grok %s usage=%s", schema.__name__, usage.get("server_side_tool_usage_details"))
        return ParsedResult(response.output_parsed, _extract_citations(response), usage)

    def list_models(self) -> list[str]:
        return [model["id"] for model in self._api.json("GET", "/models").get("data", [])]

    def generate_image(self, prompt: str, aspect_ratio: str = "9:16") -> bytes:
        body = {
            "model": self._settings.image_model,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "response_format": "b64_json",
        }
        items = self._api.json("POST", "/images/generations", json=body).get("data") or []
        if not items or not items[0].get("b64_json"):
            raise XaiError("Image generation returned no image")
        return base64.b64decode(items[0]["b64_json"])

    def start_video(
        self, prompt: str, *, image: bytes | None, duration: int, aspect_ratio: str = "9:16"
    ) -> str:
        body: dict[str, Any] = {
            "model": self._settings.video_model,
            "prompt": prompt,
            "duration": max(1, min(15, duration)),
            "aspect_ratio": aspect_ratio,
            "resolution": self._resolution,
        }
        if image:
            body["image"] = {"url": _data_url(image)}
        request_id = self._api.json("POST", "/videos/generations", json=body).get("request_id")
        if not request_id:
            raise XaiError("Video generation did not return a request_id")
        return request_id

    def wait_for_video(
        self, job_id: str, on_progress: Callable[[int], None] | None = None
    ) -> bytes:
        deadline = time.monotonic() + self._poll_timeout_s
        while True:
            data = self._api.json("GET", f"/videos/{job_id}")
            status = data.get("status")
            if status == "done":
                video = data.get("video") or {}
                if not video.get("url") or video.get("respect_moderation") is False:
                    raise XaiError(f"Video {job_id} was blocked by moderation")
                return self._api.download(video["url"])
            if status in {"failed", "expired"}:
                raise XaiError(f"Video {job_id} {status}: {data.get('error')}")
            if on_progress:
                on_progress(int(data.get("progress") or 0))
            if time.monotonic() > deadline:
                raise XaiError(f"Video {job_id} timed out")
            time.sleep(self._poll_interval_s)

    def tts(self, text: str, *, language: Language) -> SpeechResult:
        s = self._settings
        body = {
            "text": text,
            "voice_id": s.tts_voice_en if language == "en" else s.tts_voice_es,
            "language": "en" if language == "en" else s.tts_language_es,
            "with_timestamps": True,
        }
        payload = self._api.json("POST", "/tts", json=body)
        stamps = payload.get("audio_timestamps") or {}
        chars = list(stamps.get("graph_chars") or [])
        times = [(float(t[0]), float(t[1])) for t in stamps.get("graph_times") or []]
        if not payload.get("audio") or len(chars) != len(times):
            raise XaiError("TTS returned malformed audio or timestamps")
        duration = float(payload.get("duration") or (times[-1][1] if times else 0.0))
        return SpeechResult(base64.b64decode(payload["audio"]), chars, times, duration, "mp3")

    def close(self) -> None:
        self._api.close()


def _data_url(image: bytes) -> str:
    mime = "image/png" if image.startswith(b"\x89PNG") else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(image).decode()}"


def _extract_citations(response: Any) -> list[str]:
    urls: list[str] = []
    for citation in getattr(response, "citations", None) or []:
        if isinstance(citation, str):
            urls.append(citation)
        elif isinstance(citation, dict) and citation.get("url"):
            urls.append(citation["url"])
    for item in getattr(response, "output", None) or []:
        for content in getattr(item, "content", None) or []:
            for annotation in getattr(content, "annotations", None) or []:
                url = getattr(annotation, "url", None)
                if url:
                    urls.append(url)
    return list(dict.fromkeys(urls))
