"""Voiceover: one TTS call per beat so each scene can match its narration length."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from crier.models import Language
from crier.ports import SpeechSynthesizer
from crier.render.captions import Cue, chunk_words, words_with_times

BEAT_PADDING_S = 0.35


@dataclass
class Narration:
    language: Language
    beat_audio: list[Path] = field(default_factory=list)
    beat_durations: list[float] = field(default_factory=list)
    cues: list[Cue] = field(default_factory=list)

    @property
    def beat_starts(self) -> list[float]:
        starts, total = [], 0.0
        for duration in self.beat_durations:
            starts.append(total)
            total += duration
        return starts

    @property
    def total(self) -> float:
        return sum(self.beat_durations)


def narrate(
    speech: SpeechSynthesizer, texts: list[str], *, language: Language, out_dir: Path
) -> Narration:
    out_dir.mkdir(parents=True, exist_ok=True)
    narration = Narration(language=language)
    offset = 0.0
    for index, text in enumerate(texts):
        result = speech.tts(text, language=language)
        path = out_dir / f"{language}_beat{index}.{result.extension}"
        path.write_bytes(result.audio)
        duration = result.duration + BEAT_PADDING_S
        narration.beat_audio.append(path)
        narration.beat_durations.append(duration)
        narration.cues += chunk_words(words_with_times(result.chars, result.times, offset))
        offset += duration
    return narration
