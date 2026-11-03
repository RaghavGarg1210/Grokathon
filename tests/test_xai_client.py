import base64
import json

import httpx
import pytest
from openai import OpenAI
from pydantic import BaseModel

from crier.providers.xai import XaiClient, XaiError
from tests.fakes import make_settings


class Answer(BaseModel):
    summary: str


def _responses_payload() -> dict:
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": "grok-test",
        "status": "completed",
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "output": [
            {
                "type": "custom_tool_call",
                "id": "ctc_1",
                "call_id": "call_1",
                "name": "x_keyword_search",
                "input": "{}",
                "status": "completed",
            },
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"summary": "Grants open"}),
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://x.com/CityA/status/1",
                                "title": "post",
                                "start_index": 0,
                                "end_index": 1,
                            }
                        ],
                    }
                ],
            },
        ],
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def _client(tmp_path, handler) -> XaiClient:
    transport = httpx.MockTransport(handler)
    settings = make_settings(tmp_path).xai
    openai_client = OpenAI(
        api_key="k", base_url=settings.base_url, http_client=httpx.Client(transport=transport)
    )
    return XaiClient(
        settings,
        resolution="720p",
        poll_timeout_s=5,
        http=httpx.Client(transport=transport),
        openai_client=openai_client,
        backoff_s=0,
    )


def test_parse_returns_model_and_citations(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_responses_payload())

    client = _client(tmp_path, handler)
    result = client.parse(
        instructions="i",
        prompt="p",
        schema=Answer,
        tools=[{"type": "x_search", "allowed_x_handles": ["CityA"]}],
        max_turns=2,
    )
    assert result.value.summary == "Grants open"
    assert result.citations == ["https://x.com/CityA/status/1"]
    assert seen["body"]["tools"] == [{"type": "x_search", "allowed_x_handles": ["CityA"]}]
    assert seen["body"]["max_turns"] == 2
    assert seen["body"]["text"]["format"]["type"] == "json_schema"


def test_tts_decodes_audio_and_timestamps(tmp_path):
    payload = {
        "audio": base64.b64encode(b"mp3").decode(),
        "duration": 0.4,
        "audio_timestamps": {"graph_chars": ["H", "i"], "graph_times": [[0.0, 0.2], [0.2, 0.4]]},
    }
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=payload)

    speech = _client(tmp_path, handler).tts("Hola", language="es")
    assert speech.audio == b"mp3" and speech.chars == ["H", "i"] and speech.duration == 0.4
    assert seen["body"]["language"] == "es-MX" and seen["body"]["voice_id"] == "eve"


def test_request_retries_then_succeeds(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"data": [{"id": "grok-test"}]})

    assert _client(tmp_path, handler).list_models() == ["grok-test"]
    assert calls["n"] == 2


def test_client_error_is_not_retried(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, text="bad key")

    with pytest.raises(XaiError, match="401"):
        _client(tmp_path, handler).list_models()
    assert calls["n"] == 1


def test_video_blocked_by_moderation_raises(tmp_path):
    payload = {"status": "done", "video": {"url": "", "respect_moderation": False}}
    client = _client(tmp_path, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(XaiError, match="moderation"):
        client.wait_for_video("req_1")
