"""Turns TTS character timestamps into short caption cues and SRT text."""

from __future__ import annotations

from dataclasses import dataclass

TimedWord = tuple[str, float, float]

MAX_WORDS_PER_CUE = 5
MAX_CHARS_PER_CUE = 30
MIN_CUE_SECONDS = 0.35
BREAK_PUNCTUATION = ".!?,;:"


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def words_with_times(
    chars: list[str], times: list[tuple[float, float]], offset: float = 0.0
) -> list[TimedWord]:
    words: list[TimedWord] = []
    current, start, end = "", 0.0, 0.0
    for char, (char_start, char_end) in zip(chars, times, strict=True):
        if char.isspace():
            if current:
                words.append((current, start + offset, end + offset))
                current = ""
            continue
        if not current:
            start = char_start
        current += char
        end = char_end
    if current:
        words.append((current, start + offset, end + offset))
    return words


def chunk_words(words: list[TimedWord]) -> list[Cue]:
    cues: list[Cue] = []
    buffer: list[TimedWord] = []

    def flush() -> None:
        if buffer:
            start, end = buffer[0][1], max(buffer[-1][2], buffer[0][1] + MIN_CUE_SECONDS)
            cues.append(Cue(start, end, " ".join(word for word, _, _ in buffer)))
            buffer.clear()

    for word in words:
        candidate = " ".join(w for w, _, _ in buffer + [word])
        if buffer and (len(buffer) >= MAX_WORDS_PER_CUE or len(candidate) > MAX_CHARS_PER_CUE):
            flush()
        buffer.append(word)
        if word[0][-1] in BREAK_PUNCTUATION:
            flush()
    flush()
    return cues


def to_srt(cues: list[Cue]) -> str:
    blocks = [
        f"{index}\n{_timestamp(cue.start)} --> {_timestamp(cue.end)}\n{cue.text}\n"
        for index, cue in enumerate(cues, start=1)
    ]
    return "\n".join(blocks)


def _timestamp(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
