"""Writes the bilingual 30-45 second explainer script for a briefing."""

from __future__ import annotations

from crier.models import Briefing, VideoScript
from crier.ports import LanguageModel

MIN_BEATS = 3
MAX_BEATS = 5
MAX_WORDS_PER_BEAT = 45

SCENE_RULES = (
    "Vertical 9:16 shot. Warm, documentary style. Georgia small-business setting. "
    "No identifiable real people, no politicians, no faces in close-up, "
    "no text, no signs with words, no logos."
)

SCRIPT_INSTRUCTIONS = f"""\
You write short explainer videos that help Georgia small-business owners understand local \
government news. Write a 30-45 second script in {MIN_BEATS}-{MAX_BEATS} beats:
1. Hook: who should care, in one sentence.
2. What changed or what is offered, attributed to the mayor or city.
3. Who it affects and what to do.
4. Deadline (if any) and "Details at the official link in the caption."

Rules:
- Plain language, about a 6th-grade reading level. Neutral tone, no hype, no opinions.
- Only use facts from the briefing. Never invent amounts, dates, or eligibility.
- Each beat: narration_en and a natural Latin American Spanish narration_es with the same meaning, \
at most {MAX_WORDS_PER_BEAT} words each.
- on_screen_text_en/es: at most 6 words.
- scene_prompt: an English visual description for an AI image/video model. {SCENE_RULES}
- caption_en/es: 1-3 sentences for a social post. End with the official link if given, \
otherwise the source link."""


class ScriptError(ValueError):
    """The model returned a script that breaks the format rules."""


def build_script_prompt(briefing: Briefing) -> str:
    link = briefing.official_url or briefing.post_url
    deadline = briefing.deadline.isoformat() if briefing.deadline else "none"
    return (
        f"City: {briefing.city}, Georgia. Source: {briefing.source_label}, "
        f"{briefing.posted_on.isoformat()}.\n"
        f"Type: {briefing.category}. Headline: {briefing.headline}\n"
        f"What changed: {briefing.what_changed}\n"
        f"Who it affects: {', '.join(briefing.who_it_affects) or 'local businesses'}\n"
        f"What to do: {briefing.what_to_do}\n"
        f"Deadline: {deadline}. Amount: {briefing.amount or 'none'}.\n"
        f"Link for caption: {link}"
    )


def write_script(llm: LanguageModel, briefing: Briefing) -> VideoScript:
    result = llm.parse(
        instructions=SCRIPT_INSTRUCTIONS,
        prompt=build_script_prompt(briefing),
        schema=VideoScript,
    )
    script = result.value
    validate_script(script)
    return enforce_scene_rules(script)


def validate_script(script: VideoScript) -> None:
    if not MIN_BEATS <= len(script.beats) <= MAX_BEATS:
        raise ScriptError(f"expected {MIN_BEATS}-{MAX_BEATS} beats, got {len(script.beats)}")
    for index, beat in enumerate(script.beats, start=1):
        for text in (beat.narration_en, beat.narration_es):
            if not text.strip():
                raise ScriptError(f"beat {index} has empty narration")
            if len(text.split()) > MAX_WORDS_PER_BEAT * 1.5:
                raise ScriptError(f"beat {index} narration is too long")


def enforce_scene_rules(script: VideoScript) -> VideoScript:
    beats = [
        beat
        if SCENE_RULES in beat.scene_prompt
        else beat.model_copy(update={"scene_prompt": f"{beat.scene_prompt.strip()} {SCENE_RULES}"})
        for beat in script.beats
    ]
    return script.model_copy(update={"beats": beats})
