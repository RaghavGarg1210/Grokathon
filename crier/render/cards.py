"""Pillow-drawn overlays: captions, beat labels, the source card and fallback scenes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FRAME_SIZE = (1080, 1920)
BRAND = "COUNTY CRIER"
INK = (255, 255, 255, 255)
ACCENT = (255, 196, 0, 255)
PANEL = (10, 18, 32, 200)
BACKGROUND_TOP = (14, 32, 64)
BACKGROUND_BOTTOM = (6, 12, 24)

FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


@dataclass(frozen=True)
class SourceCard:
    title: str
    official_url: str | None
    post_url: str
    checked_on: str
    verified: bool
    language: str


def load_font(size: int, font_path: Path | None = None) -> ImageFont.FreeTypeFont:
    candidates = ([str(font_path)] if font_path else []) + list(FONT_CANDIDATES)
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size=size)


def wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and font.getlength(candidate) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def render_text_panel(
    text: str, out_path: Path, *, size: int = 64, color=INK, font_path: Path | None = None
) -> Path:
    """Transparent PNG with text on a rounded dark panel, sized to the text."""
    font = load_font(size, font_path)
    lines = wrap(text, font, FRAME_SIZE[0] - 200)
    line_height = int(size * 1.25)
    width = int(max(font.getlength(line) for line in lines)) + 80
    height = line_height * len(lines) + 50
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=28, fill=PANEL)
    for index, line in enumerate(lines):
        x = (width - font.getlength(line)) / 2
        draw.text((x, 25 + index * line_height), line, font=font, fill=color)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    return out_path


def render_fallback_scene(text: str, out_path: Path, font_path: Path | None = None) -> Path:
    """Branded gradient still used when image generation fails."""
    image = _gradient()
    draw = ImageDraw.Draw(image)
    font = load_font(88, font_path)
    lines = wrap(text, font, FRAME_SIZE[0] - 160)
    y = FRAME_SIZE[1] // 2 - len(lines) * 55
    for line in lines:
        draw.text(((FRAME_SIZE[0] - font.getlength(line)) / 2, y), line, font=font, fill=ACCENT)
        y += 110
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(out_path, quality=92)
    return out_path


def render_source_card(card: SourceCard, out_path: Path, font_path: Path | None = None) -> Path:
    es = card.language == "es"
    image = _gradient()
    draw = ImageDraw.Draw(image)
    brand, title, body, small = (load_font(s, font_path) for s in (60, 76, 44, 36))
    y = 220
    draw.text((90, y), BRAND, font=brand, fill=ACCENT)
    y += 140
    for line in wrap(card.title, title, FRAME_SIZE[0] - 180):
        draw.text((90, y), line, font=title, fill=INK)
        y += 95
    y += 60
    if card.official_url:
        y = _labeled(
            draw, "Fuente oficial:" if es else "Official source:", card.official_url, y, body, small
        )
    else:
        pending = (
            "Anunciado en X. Detalles oficiales pendientes."
            if es
            else "Announced on X. Official details pending."
        )
        draw.text((90, y), pending, font=body, fill=ACCENT)
        y += 90
    y = _labeled(draw, "Publicado en X:" if es else "Posted on X:", card.post_url, y, body, small)
    checked = "Verificado el" if es else "Checked on"
    status = "" if card.verified else (" (sin verificar)" if es else " (unverified)")
    draw.text((90, y), f"{checked} {card.checked_on}{status}", font=small, fill=INK)
    disclaimer = (
        "Solo informativo. Confirme los detalles en el enlace oficial."
        if es
        else "Informational only. Confirm details at the official link."
    )
    for index, line in enumerate(wrap(disclaimer, small, FRAME_SIZE[0] - 180)):
        draw.text((90, FRAME_SIZE[1] - 260 + index * 48), line, font=small, fill=INK)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(out_path, quality=92)
    return out_path


def _labeled(
    draw: ImageDraw.ImageDraw, label: str, value: str, y: int, label_font, value_font
) -> int:
    draw.text((90, y), label, font=label_font, fill=ACCENT)
    y += 62
    for line in _wrap_url(value, value_font, FRAME_SIZE[0] - 180):
        draw.text((90, y), line, font=value_font, fill=INK)
        y += 48
    return y + 50


def _wrap_url(url: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines, current = [], ""
    for char in url:
        if font.getlength(current + char) > max_width:
            lines.append(current)
            current = ""
        current += char
    return lines + [current] if current else lines


def _gradient() -> Image.Image:
    width, height = FRAME_SIZE
    image = Image.new("RGBA", FRAME_SIZE)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / height
        color = tuple(
            int(a + (b - a) * t) for a, b in zip(BACKGROUND_TOP, BACKGROUND_BOTTOM, strict=True)
        )
        draw.line([(0, y), (width, y)], fill=color + (255,))
    return image
