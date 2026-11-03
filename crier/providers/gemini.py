"""Google Gemini: structured text (analysis, scripts), scene images and voiceover."""

from __future__ import annotations

import base64
import logging
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from crier.models import Language
from crier.ports import ParsedResult, ProviderError, SpeechResult
from crier.providers.http import ApiHttp, retry_after_header
from crier.providers.wav import to_wav, wav_duration
from crier.settings import GeminiSettings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
BLOCKING_FINISH_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "IMAGE_SAFETY"}


class GeminiError(ProviderError):
    """A failed or blocked Gemini request."""


class GeminiClient:
    label = "Gemini"

    def __init__(
        self, settings: GeminiSettings, http: httpx.Client | None = None, backoff_s: float = 2.0
    ) -> None:
        if not settings.api_key:
            raise GeminiError("GEMINI_API_KEY is not set")
        self._settings = settings
        self._api = ApiHttp(
            name="Gemini",
            base_url=settings.base_url,
            headers={"x-goog-api-key": settings.api_key},
            error=GeminiError,
            client=http,
            backoff_s=backoff_s,
            retry_hint=google_retry_delay,
        )

    def parse(self, *, instructions: str, prompt: str, schema: type[T]) -> ParsedResult[T]:
        body = {
            "systemInstruction": {"parts": [{"text": instructions}]},
            "contents": [_user_turn(prompt)],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": json_schema_for(schema),
            },
        }
        payload = self._generate(self._settings.text_model, body)
        text = "".join(part.get("text", "") for part in _answer_parts(payload))
        if not text.strip():
            raise GeminiError(f"Gemini returned no {schema.__name__} output")
        try:
            value = schema.model_validate_json(text)
        except ValidationError as exc:
            raise GeminiError(f"Gemini returned an invalid {schema.__name__}: {exc}") from exc
        usage = payload.get("usageMetadata") or {}
        log.info("gemini %s usage=%s", schema.__name__, usage.get("totalTokenCount"))
        return ParsedResult(value, [], usage)

    def generate_image(self, prompt: str, aspect_ratio: str = "9:16") -> bytes:
        body = {
            "contents": [_user_turn(prompt)],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "imageConfig": {"aspectRatio": aspect_ratio},
            },
        }
        payload = self._generate(self._settings.image_model, body)
        images = [blob for blob in _blobs(payload) if blob[0].startswith("image/")]
        if not images:
            raise GeminiError("Gemini returned no image")
        return images[-1][1]

    def tts(self, text: str, *, language: Language) -> SpeechResult:
        s = self._settings
        voice = s.tts_voice_en if language == "en" else s.tts_voice_es
        speech_config: dict[str, Any] = {
            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}
        }
        language_code = s.tts_language_en if language == "en" else s.tts_language_es
        if language_code:
            speech_config["languageCode"] = language_code
        body = {
            "contents": [_user_turn(text)],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": speech_config},
        }
        payload = self._generate(s.tts_model, body)
        audio = [blob for blob in _blobs(payload) if blob[0].startswith("audio/")]
        if not audio:
            raise GeminiError("Gemini TTS returned no audio")
        wav = to_wav(audio[0][1], audio[0][0])
        return SpeechResult.with_estimated_timing(wav, text, wav_duration(wav), "wav")

    def list_models(self) -> list[str]:
        payload = self._api.json("GET", "/models", params={"pageSize": 1000})
        return [m["name"].removeprefix("models/") for m in payload.get("models") or []]

    def close(self) -> None:
        self._api.close()

    def _generate(self, model: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._api.json("POST", f"/models/{model}:generateContent", json=body)


def json_schema_for(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic's JSON schema with `$defs` references inlined (simplest form for Gemini)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, list):
            return [resolve(item) for item in node]
        if not isinstance(node, dict):
            return node
        resolved = {key: resolve(value) for key, value in node.items() if key != "$ref"}
        ref = node.get("$ref", "")
        if ref.startswith("#/$defs/"):
            return {**resolve(defs[ref.removeprefix("#/$defs/")]), **resolved}
        return resolved

    return resolve(schema)


def google_retry_delay(response: httpx.Response) -> float | None:
    """The wait Google asks for in a `google.rpc.RetryInfo` error detail ("59s" -> 59.0)."""
    header = retry_after_header(response)
    if header is not None:
        return header
    try:
        details = response.json().get("error", {}).get("details") or []
    except ValueError:
        return None
    for detail in details:
        if str(detail.get("@type", "")).endswith("google.rpc.RetryInfo"):
            return float(str(detail.get("retryDelay", "")).removesuffix("s"))
    return None


def _user_turn(text: str) -> dict[str, Any]:
    return {"role": "user", "parts": [{"text": text}]}


def _answer_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The final (non-thought) parts of the first candidate; raises if blocked."""
    block = (payload.get("promptFeedback") or {}).get("blockReason")
    if block:
        raise GeminiError(f"Gemini blocked the request: {block}")
    candidates = payload.get("candidates") or []
    if not candidates:
        raise GeminiError("Gemini returned no candidates")
    candidate = candidates[0]
    if candidate.get("finishReason") in BLOCKING_FINISH_REASONS:
        raise GeminiError(f"Gemini stopped: {candidate['finishReason']}")
    parts = (candidate.get("content") or {}).get("parts") or []
    return [part for part in parts if not part.get("thought")]


def _blobs(payload: dict[str, Any]) -> list[tuple[str, bytes]]:
    blobs = []
    for part in _answer_parts(payload):
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            mime = str(inline.get("mimeType") or inline.get("mime_type") or "").lower()
            blobs.append((mime, base64.b64decode(inline["data"])))
    return blobs
