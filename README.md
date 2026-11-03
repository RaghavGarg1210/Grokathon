# County Crier

**Georgia mayors and city halls announce things that small businesses need to know. County Crier finds those announcements on the cities' official X accounts and websites, checks them against official government sites, and turns each one into a 40-second explainer video in English and Spanish, ready for a chamber of commerce to approve and post.**

Built for the Grokathon. Inspired by TerraTrends, aimed at a different job: telling owners what local government just changed and what to do about it.

## What it does

1. **Mayor Radar.** For about 10 Georgia cities, Tavily searches the official mayor and city X accounts and the city's official website for the last 30 days. Gemini reads the results and turns each announcement into a briefing: a program, a policy decision or a business event, summarized neutrally and scored for small-business relevance. Campaign and personal posts are filtered out. Only URLs that the search actually returned can become briefings, so the model cannot invent posts.
2. **Verification.** For each relevant X post, Tavily searches only that city's official domains plus Georgia state domains, and Gemini compares those pages to the claim. The result is one of: verified (with the official URL), announced only, or contradicted. Announcements that come from an official city page are verified by their source. Contradicted announcements can never become videos.
3. **Video Studio.** Gemini writes a bilingual script in 3–5 beats. Gemini TTS records the English and Spanish voiceovers, and captions are timed to the audio. Gemini makes the scene images; in "hero" mode, Magic Hour animates each image into a video clip. ffmpeg assembles a vertical 9:16 MP4 with burned-in captions and an end card showing the official source, the original post and the date checked.
4. **Human approval.** A reviewer edits, approves or rejects each video. Nothing is posted automatically. Approved videos export as MP4, SRT and post caption.

Trust rules built into the code:
- Every claim links to its source, and every source URL must come from a real search result.
- Only posts from configured official X handles, or pages on the city's official domains, are accepted.
- Generated scenes never show real people or politicians.
- Videos need verification or an explicit reviewer override.
- A daily budget caps renders that use AI video clips.

## Providers

Each step's provider is chosen in `.env`. By default the app needs only three keys: Tavily, Gemini and Magic Hour.

| Step | Default | Alternative |
| --- | --- | --- |
| Find and verify announcements (`CRIER_SEARCH_PROVIDER`) | Tavily search + the LLM below | `xai`: Grok X Search and web search |
| Analysis and scripts (`CRIER_LLM_PROVIDER`) | Gemini | `xai` |
| Scene images (`CRIER_IMAGE_PROVIDER`) | Gemini | `xai` (Grok Imagine) |
| Voiceover (`CRIER_TTS_PROVIDER`) | Gemini TTS | `xai` (Grok TTS) |
| Hero video clips (`CRIER_VIDEO_PROVIDER`) | Magic Hour image-to-video | `xai` (Grok Imagine video) |

If a key is missing, the app still opens. The sidebar names the missing key and the steps it would enable, and the corresponding buttons are disabled. Stills renders work without a video key. If image generation fails, the scenes fall back to branded cards.

## Setup

Requirements: Python 3.11+ and ffmpeg (`brew install ffmpeg`).

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
cp .env.example .env        # then set TAVILY_API_KEY, GEMINI_API_KEY, MAGIC_HOUR_API_KEY
```

Everything else in `.env.example` has working defaults.

## Run it

```bash
source .venv/bin/activate

# 1. Check keys, model names and one cheap call per provider
#    (add --image / --video to test media; those spend credits)
python -m scripts.smoke_test

# 2. Optional: find each city's mayor, official X handles and website, then review and apply.
#    Cities already scan their official websites without handles; handles add X posts.
python -m scripts.discover_handles
#    review config/sources.suggested.yaml, then:
python -m scripts.discover_handles --apply

# 3. Seed real results: scan all cities, verify, and render the top 3 videos (1 with video clips)
python -m scripts.seed --videos 3 --hero 1

# 4. Launch the app
python -m app.web          # then open http://localhost:8000
```

For a live demo, set `CRIER_DEMO_MODE=1`. "Make video" on an already-rendered briefing then replays the pipeline stages from cache instead of waiting minutes. "Scan now" always runs live.

Restart the server after editing `.env` or `config/sources.yaml`.

## Demo script (3 minutes)

1. **Radar.** "Ten Georgia cities. We read every mayor and city announcement from the last 30 days, on X and on the official city sites, and these are the ones a small business should care about." Point at the map and the badges.
2. **Scan now.** Run one city live and narrate the steps as they appear: searching sources, then verifying on official sites.
3. **Briefing.** The original post or city page sits next to the plain-language analysis. Show the "Verified on official site" badge and the official URL.
4. **Make video.** Play the English video, switch to the Spanish tab, and point at the source card at the end.
5. **Approve.** "Nothing auto-posts. The chamber approves it, downloads it, and posts it to the owners who follow them."

## Project layout

```
crier/               core package (no Streamlit imports)
  ports.py           capability protocols (search, LLM, images, voice, video, scanner, verifier)
  providers/         adapters: tavily, gemini, magic_hour, xai; registry picks them from .env
  scanners.py        Tavily + LLM extraction (default) or Grok X Search
  scan.py            validates findings: real search URL, official handle/domain, date window
  verifiers.py       official-domain search + LLM judgement (default) or Grok web search
  verify.py          verification status rules
  script.py          bilingual script + scene-prompt safety rules
  render/            voice, scenes, captions, cards (Pillow), ffmpeg, renderer
  pipeline.py        scan/verify/store, draft/render/approve, trust and budget rules
  store.py           SQLite (data/crier.db)
app/web.py           web UI server (stdlib only) + app/static/index.html (Radar, Briefing, Studio, Library)
scripts/             smoke_test, discover_handles, seed
config/sources.yaml  Georgia cities, official X handles, official domains
tests/               unit + provider boundary tests (mocked HTTP) + a full local render
```

Captions and cards are drawn with Pillow and overlaid with ffmpeg, so the default Homebrew ffmpeg works even without libass or freetype.

## Tests

```bash
python -m pytest -q     # includes a real ffmpeg render with fake providers
ruff check .
```

## Costs to watch

- Tavily: each city scan runs up to 2 searches (2 credits each at `advanced` depth), plus 1 search per verification.
- Gemini: one structured call per city scan and per verification, one per script, one image per beat, and one TTS call per beat per language.
- Magic Hour: credits are charged per clip when the job is queued and refunded on failure. Hero renders are capped by `CRIER_MAX_HERO_RENDERS_PER_DAY`.
- Generated images and clips are cached by prompt, so re-rendering after a caption edit doesn't pay for them twice.

## Known limits

- Tavily's coverage of X posts is partial; official city websites are the more reliable source. Configure handles for cities whose mayors post often.
- Gemini TTS does not return word timestamps, so caption timing is estimated from the text and the audio length. It is close but not frame-exact.
- Verification depends on the city's website having a page about the announcement. Fresh X announcements often show "Announced only" for a few days.
- The X post embed needs internet access in the browser.
