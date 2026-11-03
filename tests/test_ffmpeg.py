from pathlib import Path

import pytest

from crier.render import ffmpeg


def test_narration_track_pads_each_beat():
    cmd = ffmpeg.narration_track([Path("a.mp3"), Path("b.mp3")], [1.5, 2.25], Path("out.m4a"))
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "apad=whole_dur=1.500" in graph and "apad=whole_dur=2.250" in graph
    assert graph.endswith("concat=n=2:v=0:a=1[out]")


def test_narration_track_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        ffmpeg.narration_track([Path("a.mp3")], [1.0, 2.0], Path("out.m4a"))


def test_overlay_chain_enables_each_overlay_in_its_window():
    overlays = [
        ffmpeg.Overlay(Path("a.png"), 0.0, 1.0, "170"),
        ffmpeg.Overlay(Path("b.png"), 1.0, 2.5, "H-h-330"),
    ]
    cmd = ffmpeg.overlay_and_mux(Path("body.mp4"), Path("voice.m4a"), overlays, Path("out.mp4"))
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "[0:v][2:v]overlay" in graph and "[v1][3:v]overlay" in graph
    assert "between(t,1.00,2.50)" in graph
    assert cmd[cmd.index("-map") + 1] == "[v2]"


def test_overlay_without_overlays_maps_streams_directly():
    cmd = ffmpeg.overlay_and_mux(Path("body.mp4"), Path("voice.m4a"), [], Path("out.mp4"))
    assert "-filter_complex" not in cmd and "0:v" in cmd


def test_still_clip_frame_count_matches_duration():
    cmd = ffmpeg.still_clip(Path("s.jpg"), 2.0, Path("o.mp4"))
    assert cmd[cmd.index("-frames:v") + 1] == "60"
    assert "-loop" not in cmd


def test_video_clip_loops_and_trims_without_audio():
    cmd = ffmpeg.video_clip(Path("v.mp4"), 3.5, Path("o.mp4"))
    assert cmd[cmd.index("-stream_loop") + 1] == "-1"
    assert cmd[cmd.index("-t") + 1] == "3.500"
    assert "-an" in cmd


def test_run_raises_render_error_on_failure():
    with pytest.raises(ffmpeg.RenderError):
        ffmpeg.run(["ffmpeg", "-i", "/nonexistent/file.mp4", "/tmp/never.mp4"])
