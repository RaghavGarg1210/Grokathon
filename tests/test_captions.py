from crier.render.captions import Cue, chunk_words, to_srt, words_with_times


def _timed(text: str, step: float = 0.1):
    chars = list(text)
    return chars, [(i * step, (i + 1) * step) for i in range(len(chars))]


def test_words_with_times_applies_offset():
    chars, times = _timed("Hi there")
    words = words_with_times(chars, times, offset=10.0)
    assert [w for w, _, _ in words] == ["Hi", "there"]
    assert words[0][1] == 10.0
    assert round(words[1][2], 2) == 10.8


def test_chunks_break_on_punctuation_and_length():
    chars, times = _timed(
        "Apply now. The grant covers paint, signs and lighting for shops downtown"
    )
    cues = chunk_words(words_with_times(chars, times))
    texts = [cue.text for cue in cues]
    assert texts[0] == "Apply now."
    assert all(len(text.split()) <= 5 for text in texts)
    assert all(len(text) <= 30 for text in texts)
    assert all(cue.end > cue.start for cue in cues)


def test_srt_format():
    srt = to_srt([Cue(0.0, 1.25, "Hello"), Cue(61.5, 62.0, "World")])
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,250\nHello\n")
    assert "2\n00:01:01,500 --> 00:01:02,000\nWorld" in srt
