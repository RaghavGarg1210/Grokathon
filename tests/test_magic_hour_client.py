import json

import httpx
import pytest

from crier.providers.magic_hour import MagicHourClient, MagicHourError, clamp_seconds
from tests.fakes import make_settings

UPLOAD_URL = "https://storage.example.com/upload?sig=abc"
DOWNLOAD_URL = "https://cdn.example.com/video.mp4"


def _client(tmp_path, handler) -> MagicHourClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return MagicHourClient(
        make_settings(tmp_path).magic_hour,
        resolution="720p",
        poll_timeout_s=5,
        http=http,
        poll_interval_s=0,
        backoff_s=0,
    )


def test_start_video_uploads_still_then_creates_job(tmp_path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/files/upload-urls":
            return httpx.Response(
                200, json={"items": [{"upload_url": UPLOAD_URL, "file_path": "api-assets/1.jpg"}]}
            )
        if request.method == "PUT":
            return httpx.Response(200)
        return httpx.Response(200, json={"id": "vid_1", "credits_charged": 40})

    job = _client(tmp_path, handler).start_video("pan", image=b"\xff\xd8jpeg", duration=7)
    assert job == "vid_1"
    upload, put, create = requests
    assert json.loads(upload.content) == {"items": [{"type": "image", "extension": "jpg"}]}
    assert upload.headers["Authorization"] == "Bearer mh-test"
    assert str(put.url) == UPLOAD_URL and put.content == b"\xff\xd8jpeg"
    assert "Authorization" not in put.headers
    body = json.loads(create.content)
    assert body["assets"] == {"image_file_path": "api-assets/1.jpg"}
    assert body["end_seconds"] == 7 and body["model"] == "ltx-2.5"
    assert body["resolution"] == "720p" and body["audio"] is False
    assert body["style"] == {"prompt": "pan"}


def test_start_video_requires_a_still(tmp_path):
    with pytest.raises(MagicHourError, match="still"):
        _client(tmp_path, lambda r: httpx.Response(500)).start_video("p", image=None, duration=5)


def test_wait_for_video_polls_until_complete_and_downloads(tmp_path):
    statuses = iter(["queued", "rendering", "complete"])

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == DOWNLOAD_URL:
            assert "Authorization" not in request.headers
            return httpx.Response(200, content=b"mp4bytes")
        status = next(statuses)
        downloads = [{"url": DOWNLOAD_URL}] if status == "complete" else []
        return httpx.Response(200, json={"id": "vid_1", "status": status, "downloads": downloads})

    assert _client(tmp_path, handler).wait_for_video("vid_1") == b"mp4bytes"


def test_failed_job_raises_with_message(tmp_path):
    payload = {"status": "error", "error": {"message": "content rejected", "code": "x"}}
    client = _client(tmp_path, lambda r: httpx.Response(200, json=payload))
    with pytest.raises(MagicHourError, match="content rejected"):
        client.wait_for_video("vid_1")


def test_insufficient_credits_is_not_retried(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(402, json={"code": "insufficient_credits", "message": "no credits"})

    with pytest.raises(MagicHourError, match="402"):
        _client(tmp_path, handler).start_video("p", image=b"\xff\xd8", duration=5)
    assert calls["n"] == 1


@pytest.mark.parametrize(
    ("model", "seconds", "expected"),
    [("ltx-2.5", 30, 30), ("kling-3.0", 2, 3), ("seedance-2.0", 20, 15), ("unknown", 1, 4)],
)
def test_clip_length_respects_model_limits(model, seconds, expected):
    assert clamp_seconds(model, seconds) == expected
