import base64
import json

import httpx
import pytest

from crier.models import ScanResult
from crier.providers.gemini import (
    GeminiClient,
    GeminiError,
    google_retry_delay,
    json_schema_for,
)
from crier.providers.wav import to_wav, wav_duration
from tests.fakes import make_settings, scanned_post

PCM_ONE_SECOND = b"\x00\x00" * 24_000


def _client(tmp_path, handler, seen: list | None = None) -> GeminiClient:
    def record(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return handler(request)

    http = httpx.Client(transport=httpx.MockTransport(record))
    return GeminiClient(make_settings(tmp_path).gemini, http=http, backoff_s=0)


def _candidate(*parts: dict) -> dict:
    return {"candidates": [{"content": {"parts": list(parts)}, "finishReason": "STOP"}]}


def _inline(mime: str, data: bytes) -> dict:
    return {"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}}


def test_parse_sends_json_schema_and_validates_answer(tmp_path):
    seen: list[httpx.Request] = []
    answer = ScanResult(posts=[scanned_post()]).model_dump_json()
    payload = _candidate({"text": "thinking...", "thought": True}, {"text": answer})
    client = _client(tmp_path, lambda r: httpx.Response(200, json=payload), seen)
    result = client.parse(instructions="sys", prompt="find posts", schema=ScanResult)
    assert result.value.posts[0].headline == scanned_post().headline
    request = seen[0]
    assert request.url.path.endswith("/models/gemini-test:generateContent")
    assert request.headers["x-goog-api-key"] == "gemini-test"
    body = json.loads(request.content)
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"
    config = body["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert "$ref" not in json.dumps(config["responseJsonSchema"])


def test_parse_rejects_invalid_json(tmp_path):
    payload = _candidate({"text": '{"posts": "nope"}'})
    client = _client(tmp_path, lambda r: httpx.Response(200, json=payload))
    with pytest.raises(GeminiError, match="invalid ScanResult"):
        client.parse(instructions="s", prompt="p", schema=ScanResult)


def test_blocked_prompt_raises(tmp_path):
    payload = {"promptFeedback": {"blockReason": "SAFETY"}}
    client = _client(tmp_path, lambda r: httpx.Response(200, json=payload))
    with pytest.raises(GeminiError, match="blocked"):
        client.parse(instructions="s", prompt="p", schema=ScanResult)


def test_generate_image_requests_vertical_aspect_and_decodes(tmp_path):
    seen: list[httpx.Request] = []
    payload = _candidate({"text": "Here you go"}, _inline("image/png", b"\x89PNGdata"))
    client = _client(tmp_path, lambda r: httpx.Response(200, json=payload), seen)
    assert client.generate_image("a shop") == b"\x89PNGdata"
    config = json.loads(seen[0].content)["generationConfig"]
    assert config["imageConfig"] == {"aspectRatio": "9:16"}
    assert "IMAGE" in config["responseModalities"]


def test_tts_wraps_raw_pcm_and_estimates_caption_timing(tmp_path):
    seen: list[httpx.Request] = []
    payload = _candidate(_inline("audio/L16;codec=pcm;rate=24000", PCM_ONE_SECOND))
    client = _client(tmp_path, lambda r: httpx.Response(200, json=payload), seen)
    speech = client.tts("Hola, negocios.", language="es")
    assert speech.audio[:4] == b"RIFF" and speech.extension == "wav"
    assert speech.duration == pytest.approx(1.0)
    assert len(speech.chars) == len(speech.times) == len("Hola, negocios.")
    assert speech.times[-1][1] == pytest.approx(1.0)
    config = json.loads(seen[0].content)["generationConfig"]
    assert config["responseModalities"] == ["AUDIO"]
    assert config["speechConfig"]["languageCode"] == "es-US"
    assert config["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Kore"


def test_tts_passes_through_wav(tmp_path):
    wav = to_wav(PCM_ONE_SECOND)
    payload = _candidate(_inline("audio/wav", wav))
    speech = _client(tmp_path, lambda r: httpx.Response(200, json=payload)).tts("Hi", language="en")
    assert speech.audio == wav


def test_wav_duration_trusts_byte_count_over_placeholder_header():
    wav = bytearray(to_wav(PCM_ONE_SECOND))
    wav[40:44] = (0xFFFFFFFF).to_bytes(4, "little")
    assert wav_duration(bytes(wav)) == pytest.approx(1.0)


def test_json_schema_inlines_nested_models():
    schema = json_schema_for(ScanResult)
    assert "$defs" not in schema
    assert "headline" in schema["properties"]["posts"]["items"]["properties"]


def test_google_retry_delay_reads_retry_info():
    quota = {
        "error": {
            "code": 429,
            "details": [
                {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": []},
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "59s"},
            ],
        }
    }
    assert google_retry_delay(httpx.Response(429, json=quota)) == 59.0
    assert google_retry_delay(httpx.Response(503, json={"error": {"code": 503}})) is None
    assert google_retry_delay(httpx.Response(503, text="not json")) is None
