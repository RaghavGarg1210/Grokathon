# Grill decisions - County Crier (Grokathon)

Human questions asked: 7 / 25
Analysis resolutions: 22 / 100

## Scope
- Repos / paths in scope: `Grokathon` (empty repo, no commits)
- Common libraries / shared packages: none yet
- Runtime / services / data: Tavily search, Gemini (structured output, image generation, TTS), Magic Hour image-to-video (D-008); xAI optional
- Docs / source of truth: docs.x.ai (model and tool names still unverified)
- Out of scope: extending TerraTrends code; all 159 Georgia counties (6–10 for the demo); auto-publishing; bids, RFPs, zoning and other non-funding content (D-006); scraping X (AR-010)
- Codebase graph: graph_unavailable (repo is empty, nothing to index)

## Context brief
- Goal: Find Georgia county and local-government programs from X and the web, verify them on official pages, and turn them into short plain-language explainer videos for small-business owners.
- Current understanding: An 8-step pipeline: pick → find → extract → verify → rank → script → render → draft. Scoped to 3–4 counties and 2–3 business types.
- Artifacts and graph evidence: The user's plan only. No code yet.
- Assumptions / constraints: Hackathon time box; the demo must work live or from cached results.
- Unknowns / risks: How much county posting actually happens on X; how long a video clip can be; time left; team size.
- Hidden gems:
  - A "posted N hours ago → video in 2 minutes" freshness demo is something only Grok can do.
  - County bid and RFP notices are money small businesses can win, not just money they can apply for.
  - Chambers of commerce and Small Business Development Centers (SBDCs) already have the audience but no video team.
  - The human approver can be the publisher's own communications person, which turns the safety rule into a product feature.
- Next artifact: The phase 0 API check, then the project scaffold and `config/sources.yaml` (see the Build plan in Readiness).

## Human questions log
### Q01 - 2026-11-02
Decision: Time and team budget
Why it matters: Sets the cut line in the 7-phase plan.
Options: A. <8h solo  B. 8–24h, 1–2 people  C. 24h+ or a team of 3+
Recommendation: Plan for B and cut to A if needed.
Question: How many hours are left, and how many people are on the team?
Human answer: 1 hour total.
Decision ID: D-001

### Q02 - 2026-11-02
Decision: The moment that should impress judges
Why it matters: Decides where polish time goes.
Options: A. Video quality  B. Live freshness (a real post from today becomes a verified video)  C. Breadth (map, counties, growth score)
Recommendation: B
Question: Pick A, B or C.
Human answer: C (breadth)
Decision ID: D-002

### Q03 - 2026-11-02
Decision: How to position against TerraTrends
Why it matters: Judges may see "similar to the London winner" as derivative.
Options: A. Companion built for TerraTrends' audience  B. Standalone ("civic info → short video"), with TerraTrends mentioned once  C. No mention
Recommendation: B
Question: Pick A, B or C.
Human answer: B (standalone, mention TerraTrends once)
Decision ID: D-003

### Q04 - 2026-11-02
Decision: Time and team budget, asked again after the 1-hour limit was lifted
Why it matters: Sets the stack and how much of the product gets built. Replaces Q01.
Options: A. 3–8h solo  B. 8–24h, 1–2 people  C. 24h+ or 3+ people
Recommendation: none (a fact only the Human knows)
Question: How much time and how many people do you have now?
Human answer: A (3–8 hours, solo)
Decision ID: D-004

### Q05 - 2026-11-02
Decision: The customer: who publishes the videos and who pays
Why it matters: Distribution is the hardest problem; this sets the main user, the user interface, the approval flow and the business model.
Options: A. Business owners directly (alerts)  B. Chambers, SBDCs and county economic development offices (they approve and publish to their own audience; paid tool)  C. County Crier's own media channels
Recommendation: B
Question: Pick A, B or C.
Human answer: B
Decision ID: D-005

### Q06 - 2026-11-02
Decision: What content is covered
Why it matters: Sets how many items there are, the noise level, and the nonpartisan risk.
Options: A. Funding programs only  B. Funding plus bids, RFPs and deadlines  C. Anything that affects businesses
Recommendation: B
Question: Pick A, B or C.
Human answer: A (funding only)
Decision ID: D-006

### Q07 - 2026-11-02
Decision: Which AI providers run the pipeline
Why it matters: The Human has no xAI or X API keys, only Tavily, Gemini and Magic Hour keys.
Options: A. Replace xAI with Tavily, Gemini and Magic Hour  B. Pluggable: each step picks its provider in `.env`  C. Keep xAI only
Recommendation: B
Question: Pick A, B or C, and say what Gemini should do.
Human answer: B, with Gemini doing "everything ideally, we dont have access to grok or x api keys"
Decision ID: D-008

## Analysis resolutions log
### AR-001 - 2026-11-02
Decision: Data source when X is thin
Why it matters: Many rural Georgia counties rarely post on X, so `x_search` may return nothing and the demo would be empty.
Options considered:
- A. X only (pure Grok story, high risk of empty results)
- B. X first, then `web_search` limited to .gov sites, with results cached (balanced)
- C. Web only (safe but loses the reason to use Grok)
Recommendation / default: B. Use X as the trigger and .gov pages as the source of truth. Do a 15-minute check of the handle list in phase 1 and pick counties that really post.
Resolution: B
Evidence / source: The plan already restricts web search to .gov domains. County X activity is an assumption still to check in phase 1.
Status: analysis-confirmed
Decision ID: AR-001

### AR-002 - 2026-11-02
Decision: How a 30–45 second video gets made
Why it matters: Video generation APIs usually return short clips, so a single 30–45 second render is unlikely.
Options considered:
- A. One long generated clip (probably impossible)
- B. 3–5 short generated B-roll clips plus a TTS voiceover and burned-in captions, joined with ffmpeg
- C. Slides plus TTS only
Recommendation / default: B, with C as the fallback.
Resolution: B. Check the clip length limit in phase 1.
Evidence / source: The plan says rendering is an async polling job. Clip length is unverified.
Status: analysis-confirmed
Decision ID: AR-002

### AR-003 - 2026-11-02
Decision: Main audience
Why it matters: The original idea says "people or business owners", and two audiences means two script styles.
Options considered: A. Residents  B. Small-business owners  C. Both
Recommendation / default: B. It matches TerraTrends and gives the clearest "money available" hook.
Resolution: B. Residents are a stretch goal.
Evidence / source: The user's plan.
Status: artifact-derived
Decision ID: AR-003

### AR-004 - 2026-11-02
Decision: Accuracy and liability
Why it matters: A widely shared video with the wrong deadline or eligibility harms viewers and loses credibility with judges.
Options considered: A. Trust the extraction  B. Verify against the official page, show the source link, and require human approval  C. Show only manually curated programs
Recommendation / default: B
Resolution: B. Every result and every video shows the source URL and the date it was checked.
Evidence / source: The user's plan rules.
Status: artifact-derived
Decision ID: AR-004

### AR-005 - 2026-11-02
Decision: Is the growth score worth building?
Why it matters: It takes time and isn't the core value.
Options considered: A. Full model  B. A static, precomputed score per county from one Census/BLS pull  C. Drop it
Recommendation / default: B. Hardcode a small JSON file for 3–4 counties. It is the first thing to cut after Spanish.
Resolution: B
Evidence / source: The plan's cut order.
Status: analysis-confirmed
Decision ID: AR-005

### AR-006 - 2026-11-02
Decision: Demo reliability
Why it matters: Live API calls and video jobs can be slow or fail on stage.
Options considered: A. Live only  B. Live attempt, with cached JSON and pre-rendered videos as automatic fallback  C. Fully recorded demo
Recommendation / default: B
Resolution: B
Evidence / source: The plan's phase 6.
Status: analysis-confirmed
Decision ID: AR-006

### AR-007 - 2026-11-02
Decision: How to get breadth with only 1 hour
Why it matters: The Human chose breadth but has 1 hour, and live calls for each county cannot finish during a demo.
Options considered:
- A. Live search per county on click (slow, fragile)
- B. A batch script over 8–12 counties that runs in the background while the UI is built and caches to `data/programs.json`; the UI reads the cache (fast, shows breadth)
- C. Hand-curated JSON (fast, but not a Grok story)
Recommendation / default: B. Keep one "refresh this county live" button to prove the pipeline is real.
Resolution: B
Evidence / source: D-001 (1 hour) and D-002 (breadth)
Status: analysis-confirmed
Decision ID: AR-007

### AR-008 - 2026-11-02
Decision: Stack for a 1-hour build
Why it matters: FastAPI plus a hand-written web page costs about 15 minutes of UI work.
Options considered: A. FastAPI plus HTML  B. Streamlit with a Plotly Georgia county map (one file)  C. Next.js
Recommendation / default: B. It gives a map, tables and video playback quickly.
Resolution: B
Evidence / source: D-001
Status: analysis-confirmed (under review: the 1-hour limit was lifted, see Q04)
Decision ID: AR-008

### AR-009 - 2026-11-02
Decision: Real people in generated video
Why it matters: Generating a mayor's face or voice is a deepfake risk, and judges and counties would reject it.
Options considered:
- A. Generate officials' likeness (risky, possibly illegal)
- B. Use no real-person likeness: B-roll, maps, text cards, and a neutral narrator, quoting officials only as on-screen text with a source
- C. No video at all (loses the hook)
Recommendation / default: B
Resolution: B. This is a hard rule written into the video prompt template.
Evidence / source: The plan's nonpartisan and accuracy rules; general deepfake policy risk.
Status: analysis-confirmed
Decision ID: AR-009

### AR-010 - 2026-11-02
Decision: How data is collected from X
Why it matters: The original idea says "scrape". Scraping X breaks its terms of service, which is fatal for the pitch and the product.
Options considered: A. Scrape X  B. Use only xAI's `x_search` and `web_search` tools, plus official RSS feeds and pages  C. Manual entry
Recommendation / default: B
Resolution: B. The pitch says "monitors", not "scrapes".
Evidence / source: The xAI API tool list in the plan.
Status: analysis-confirmed
Decision ID: AR-010

### AR-011 - 2026-11-02
Decision: Spanish support
Why it matters: Owners who don't speak English are the ones most likely to miss county programs. Georgia has large Hispanic business communities in places like Gwinnett, Hall and Whitfield counties.
Options considered: A. English only  B. English and Spanish for every script and video  C. Many languages
Recommendation / default: B. Translating the script and the voiceover costs little extra.
Resolution: B. Spanish is back in scope now that there's more time.
Evidence / source: Georgia demographics (general knowledge, check before claiming numbers on stage).
Status: analysis-confirmed (confidence: medium)
Decision ID: AR-011

### AR-012 - 2026-11-02
Decision: What the county map shows
Why it matters: With a standalone pitch (D-003), a county growth score borrowed from TerraTrends no longer carries the story.
Options considered: A. County growth score  B. Open opportunities per county (count, dollars available, nearest deadline), with "matches your business" filtering  C. Both, with growth as an optional layer
Recommendation / default: C. Lead with B; growth is an optional layer.
Resolution: C. This replaces AR-005.
Evidence / source: D-002 and D-003
Status: analysis-confirmed
Decision ID: AR-012

### AR-013 - 2026-11-02
Decision: How often to check for new programs
Why it matters: A one-off search is a demo. Ongoing monitoring is a product. The "new this week" view is also what brings people back.
Options considered: A. Search on demand  B. A daily scan per county, keeping only new or changed items (keyed by source URL plus program name), and only those create drafts  C. Real-time streaming
Recommendation / default: B
Resolution: B
Evidence / source: Product need; streaming is not confirmed in the API.
Status: analysis-confirmed
Decision ID: AR-013

### AR-014 - 2026-11-02
Decision: How to avoid empty counties when coverage is funding only
Why it matters: Funding-only content (D-006) is sparse, and many rural counties rarely announce their own programs.
Options considered: A. County programs only (many empty counties)  B. Include state and federal programs that apply to the county (for example from Georgia DCA, OneGeorgia, SBA and USDA Rural Development), tagged by level (county, state or federal)  C. Lower the verification bar
Recommendation / default: B. Never lower verification.
Resolution: B
Evidence / source: D-006 and AR-001
Status: analysis-confirmed (confidence: medium; agency names need checking in phase 1)
Decision ID: AR-014

### AR-015 - 2026-11-02
Decision: The core workflow for the chamber or SBDC user
Why it matters: With a B2B customer (D-005), the product is an approval inbox, not a public feed.
Options considered: A. A public feed  B. An inbox of new verified programs, leading to a draft (script, video, caption, in English and Spanish), then edit or regenerate, then approve, then export the video and caption  C. Auto-post after approval
Recommendation / default: B. Never auto-post.
Resolution: B
Evidence / source: D-005 and AR-004
Status: analysis-confirmed
Decision ID: AR-015

### AR-016 - 2026-11-02
Decision: The stack for 3–8 hours, solo
Why it matters: A solo builder can't afford separate front-end and back-end work.
Options considered: A. FastAPI plus React  B. Streamlit plus SQLite plus ffmpeg, all Python  C. Next.js full stack
Recommendation / default: B. Keeps AR-008 now that the time is known.
Resolution: B
Evidence / source: D-004
Status: analysis-confirmed
Decision ID: AR-016

### AR-017 - 2026-11-02
Decision: How to find posts and analyze them
Why it matters: Separate search and extraction calls double the cost and the delay.
Options considered: A. Search call, then a separate structured extraction call  B. One `responses.parse` call with `x_search` plus `text_format` (docs.x.ai confirms tools and structured output work together)  C. Ask for free text and parse it ourselves
Recommendation / default: B. Code then checks every returned post URL and handle against the configured accounts and the citations.
Resolution: B
Evidence / source: docs.x.ai structured outputs page ("Structured outputs with tools"); `crier/scan.py`
Status: artifact-derived
Decision ID: AR-017

### AR-018 - 2026-11-02
Decision: How captions get drawn
Why it matters: The local Homebrew ffmpeg 8.1 has no `subtitles` or `drawtext` filter (no libass or freetype).
Options considered: A. Require a custom ffmpeg build  B. Draw captions, labels and the source card as PNGs with Pillow, overlay them with ffmpeg `overlay` and an `enable` time window, and also export the SRT file  C. Use soft subtitles only
Recommendation / default: B. It works on any ffmpeg.
Resolution: B
Evidence / source: Output of `ffmpeg -filters`; `crier/render/`
Status: artifact-derived
Decision ID: AR-018

### AR-019 - 2026-11-02
Decision: How to find mayor announcements without X API access
Why it matters: Without X Search, the app can't read X accounts directly.
Options considered: A. Tavily search restricted to x.com and twitter.com for configured handles, plus Tavily search restricted to each city's official domains, then Gemini structured extraction  B. Gemini with Google Search grounding  C. Scrape X
Recommendation / default: A. Every briefing URL must be one that Tavily actually returned ("grounded"), so the model can't invent posts. Official city pages count as sources, so cities scan without handles.
Resolution: A
Evidence / source: Tavily `/search` reference (`include_domains`, `start_date`, `end_date`); `crier/scanners.py`, `crier/scan.py`
Status: artifact-derived
Decision ID: AR-019

### AR-020 - 2026-11-02
Decision: How to verify without Grok web search
Why it matters: Verification is the trust core of the product.
Options considered: A. Tavily search restricted to the official domains, then Gemini compares the pages with the claim  B. Mark everything as announced only
Recommendation / default: A. A cited official URL must be one of the search results. Announcements that come from an official city page are verified by their source.
Resolution: A
Evidence / source: `crier/verifiers.py`, `crier/verify.py`
Status: artifact-derived
Decision ID: AR-020

### AR-021 - 2026-11-02
Decision: How to time captions with Gemini TTS
Why it matters: Gemini TTS returns audio without word timestamps; Grok TTS had them.
Options considered: A. Spread the characters across the measured audio length, with longer weights on punctuation  B. Run speech-to-text alignment  C. Show the whole beat text at once
Recommendation / default: A. It's close enough for 3–5 word cues and adds no API calls. Raw PCM is wrapped as WAV; Gemini 3.8 TTS already returns WAV.
Resolution: A
Evidence / source: Gemini speech-generation docs (unary output is WAV at 24 kHz; older models return headerless L16 PCM); `crier/ports.py`, `crier/providers/wav.py`
Status: artifact-derived
Decision ID: AR-021

### AR-022 - 2026-11-02
Decision: How to make hero video clips without Grok Imagine
Why it matters: Hero mode is the visual "wow".
Options considered: A. Magic Hour image-to-video from each Gemini still (upload URL, PUT, create the job, poll `/v1/video-projects/{id}`)  B. Stills only
Recommendation / default: A, with `ltx-2.5` as the default model (1–60 s clips, available on free tiers). Clip lengths are clamped per model. A failed clip falls back to the animated still.
Resolution: A
Evidence / source: Magic Hour image-to-video API reference; `crier/providers/magic_hour.py`
Status: artifact-derived
Decision ID: AR-022

## Decisions
| ID | Decision | Reason | Tradeoff | Source | Confidence | Q ref | Follow-up | Status |
|----|----------|--------|----------|--------|------------|-------|-----------|--------|
| D-001 | 1 hour total | Hackathon clock | - | Human | high | Q01 | - | superseded by D-004 |
| D-002 | Breadth is the impressive moment | Map of many counties | Less video polish | Human | high | Q02 | Map becomes the coverage view (AR-012) | human-answered |
| D-003 | Standalone pitch; mention TerraTrends once | Avoid looking derivative | Lose some borrowed credibility | Human | high | Q03 | One README line | human-answered |
| D-004 | 3–8 hours, solo | Builder capacity | One stack, strict cut order | Human | high | Q04 | Timebox each phase | human-answered |
| D-005 | Customer is chambers, SBDCs and county economic development offices | They already have the audience; video is their gap | Slower sales cycle (not a hackathon concern) | Human | high | Q05 | Demo as a chamber staff member | human-answered |
| D-006 | Funding programs only | Focus and trust | Fewer items, so add state and federal programs (AR-014) | Human | high | Q06 | - | superseded by D-007 |
| D-007 | Monitor Georgia mayors' X posts for programs and schemes **and** business-affecting decisions; make educational videos for small-business owners | The Human's build request on 2026-11-02 | More content and more nonpartisan risk, mitigated by the campaign/personal filter and neutral, attributed summaries | Human | high | - | - | human-directed |
| D-008 | Georgia only. Pluggable providers per step; defaults are Tavily (search), Gemini (analysis, scripts, images, voice) and Magic Hour (video). xAI stays optional. | The Human has keys for Tavily, Gemini and Magic Hour, not xAI or X | X coverage comes from search instead of the X API (AR-019); captions are timed by estimate (AR-021) | Human | high | Q07 | Confirm model names with `scripts.smoke_test` | human-answered |

## Readiness
Verdict: ready_with_followups

Build status (2026-11-02): implemented per `README.md`, with 98 tests passing (including mocked HTTP tests for every provider and a real local ffmpeg render). Keys are in `.env`; `scripts.smoke_test` passes live for Tavily search, Gemini structured output (`gemini-3-flash-preview`; `gemini-3.8-flash` returned 503 "high demand") and Gemini TTS. The Gemini key is free tier (5 requests/minute per model), so `ApiHttp` now waits for the server's requested retry delay (up to 65 s). Open follow-ups:
- Run `scripts.smoke_test --image --video` to confirm Gemini images and Magic Hour (both cost credits; free-tier Gemini may not allow image generation).
- Optionally run `scripts.discover_handles` and review the suggested handles (none are hard-coded; cities already scan their official websites).
- Run `scripts.seed` for demo data.
- Listen to the Gemini voices and pick `GEMINI_TTS_VOICE_EN` and `GEMINI_TTS_VOICE_ES`.

### Product definition
- Name: County Crier
- One-liner: County Crier watches Georgia funding announcements on X and official sites, and gives your chamber a verified, ready-to-post 40-second explainer in English and Spanish.
- Customer: The communications or program staff at a chamber of commerce, an SBDC, or a county economic development office.
- Who benefits: Small-business owners who would otherwise miss the funding.
- Core loop: Daily scan, then a new verified funding program, then a draft (script, video, caption, source card; English and Spanish), then staff edit and approve, then export and post on their own channels.
- Trust rules: Every claim links to its official source and the date it was checked; no real-person likeness; nonpartisan; never auto-post.
- Coverage view: A Georgia map with counties colored by open funding (count, dollars, nearest deadline). Growth is an optional layer.
- Business model, one line: A subscription per organization. Don't claim revenue on stage.
- Success metrics: Drafts approved, time from announcement to post, clicks on source links.

### Data model
- Program: id, title, level (county/state/federal), counties[], business_types[], amount, deadline, eligibility, source_url, x_post_url, verified_at, confidence, status (new/verified/rejected/expired)
- Draft: id, program_id, language (en/es), script, caption, video_path, status (draft/approved/rejected), edited_by

### Build plan (about 5.5–6.5 hours)
0. (15 min) Check the xAI API: model list, `x_search` filters, `web_search` domain filter, the video job API and clip length, and the TTS endpoint.
1. (45 min) Write `config/sources.yaml`: 6–10 counties (2 or more rural); handles for each county, city, chamber and development authority; plus state and federal agency handles and domains.
2. (60 min) Pipeline: discover with `x_search`, extract to Program using structured output, verify with `web_search` limited to official domains (drop anything unconfirmed or expired), and store in SQLite with a dedupe key.
3. (60 min) Draft generator: write the script (40 seconds, plain language, English and Spanish) and the caption, start the video job early, run TTS, and assemble with ffmpeg ending on a source card.
4. (60–90 min) Streamlit app with three tabs: Inbox, Draft review (edit, regenerate, approve or reject, export), and Coverage map.
5. (30 min) Pre-render 2–3 approved drafts and add a cached fallback mode.
6. (30 min) README, pitch, and demo rehearsal.

Checkpoint at the end of phase 2: if X gives fewer than 5 verified programs across the counties, lean on official-domain web search of state and federal agencies.

Cut order if behind: Coverage map, then the Spanish voiceover (keep Spanish captions), then generated clips (use slides plus TTS). Never cut verification or the source link.
