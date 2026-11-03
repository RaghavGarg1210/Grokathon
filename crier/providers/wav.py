"""Small WAV helpers for TTS engines that return raw 16-bit PCM or WAV bytes."""

from __future__ import annotations

import io
import re
import wave

DEFAULT_PCM_RATE = 24_000
WAV_HEADER_BYTES = 44


def to_wav(audio: bytes, mime_type: str = "") -> bytes:
    """Returns WAV bytes, wrapping headerless PCM (e.g. `audio/L16;rate=24000`) if needed."""
    if audio[:4] == b"RIFF":
        return audio
    match = re.search(r"rate=(\d+)", mime_type or "")
    rate = int(match.group(1)) if match else DEFAULT_PCM_RATE
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(audio)
    return buffer.getvalue()


def wav_duration(audio: bytes) -> float:
    """Seconds of audio, trusting the byte count over header sizes (streamed WAVs may
    carry placeholder lengths)."""
    with wave.open(io.BytesIO(audio), "rb") as reader:
        rate, channels, width = reader.getframerate(), reader.getnchannels(), reader.getsampwidth()
        header_frames = reader.getnframes()
    byte_frames = max(0, len(audio) - WAV_HEADER_BYTES) // (channels * width)
    return min(header_frames, byte_frames) / rate
