# Build roadmap

Work through these phases in order. Each phase has a clear "done when"
check — don't move to the next phase until it passes. Commit after each
phase.

## Phase 0 — Scaffold
- Create the folder structure from `SPEC.md`.
- `pipeline/state.py`: SQLite schema + helper functions
  (`create_video`, `get_video`, `update_video`, `list_by_status`).
- `config/.env.example` with every key the later phases will need
  (LLM_BACKEND, TTS_BACKEND, FACTS_VISUAL_SOURCE, API keys, YouTube OAuth
  client path, REQUIRE_REVIEW).
- Done when: `python -c "from pipeline.state import init_db; init_db()"`
  creates a working SQLite file with the `videos` table.

## Phase 1 — Script generation
- `pipeline/plan.py`: given a template name, build the prompt from
  `config/prompts/`, call the configured LLM backend, parse out topic +
  script + hook, save a new row to state.
- Write both prompt template files with a strong instruction to include
  one genuine hook/opinion/gotcha per script (this is the anti-templating
  requirement from `SPEC.md`).
- Done when: running `plan.py` standalone for both templates prints a
  distinct, non-generic script each time (run it 3x per template and
  confirm no two scripts are near-identical).

## Phase 2 — Voice
- `pipeline/voice.py`: script text in, audio file out, using the
  configured TTS backend.
- Done when: a generated script produces a clear, correctly-paced audio
  file (spot check by listening).

## Phase 3a — Programming visuals
- `pipeline/visuals_code.py`: given a code snippet (part of the script
  output for the programming template), render a syntax-highlighted
  typing animation as a video clip.
- Done when: output is a clean, readable vertical video clip matching
  the script's code.

## Phase 3b — Facts visuals
- `pipeline/visuals_facts.py`: given keywords from the script, fetch or
  generate matching background visuals per `FACTS_VISUAL_SOURCE`.
- Done when: output is a relevant vertical background clip/image set for
  a sample facts script.

## Phase 4 — Assembly
- `pipeline/assemble.py`: combine voice + visuals + background music
  into one raw vertical video.
- Add the subscribe/share CTA overlay per `SPEC.md` (Pillow-rendered
  text + icon badge, fade in/out, upper third of frame).
- Done when: a full raw video plays back correctly with audio synced to
  visuals, and the CTA overlay appears at the right time without
  covering where captions will later go.

## Phase 5 — Captions
- `pipeline/captions.py`: transcribe the voice track with `faster-whisper`
  for word-level timestamps, burn in styled captions.
- Done when: captions appear on screen in sync with the spoken words in
  the final video.

## Phase 6 — Metadata
- `pipeline/metadata.py`: generate title/description/tags from the
  script + hook via the same LLM backend as Phase 1.
- Done when: output metadata is specific to the video (not generic
  boilerplate) and fits YouTube's field limits.

## Phase 7 — Review queue
- `scripts/review.py`: CLI to list `awaiting_review` videos, open the
  final video file, and mark `approved` or `rejected`.
- Done when: a video can be reviewed and its status changes accordingly.

## Phase 8 — YouTube upload
- `pipeline/upload.py`: OAuth2 setup (one-time interactive auth to get a
  refresh token, stored securely), then upload `approved` videos with
  their metadata.
- Confirm with the owner before writing this phase: which Google account
  to authorize against, and whether AI-content disclosure should be set.
- Done when: an approved test video uploads successfully as unlisted or
  private (don't default to public while testing).

## Phase 9 — Orchestrator
- `pipeline/orchestrator.py` + `scripts/run_daily.py`: run the full
  pipeline for N videos/day, split across templates, calling each stage
  in order per video, updating state, and skipping/resuming
  partially-completed videos from a previous run.
- Done when: `python scripts/run_daily.py --count 5` produces 5 videos
  end to end (or leaves them correctly `awaiting_review`) in one run,
  and re-running it after an interrupted run resumes rather than
  duplicating work.

## Phase 10 — Post-launch fixes & follow-ups (tracked 2026-09-06)

Phase 8 is live: the first real video is uploaded to the ByteBits channel
(`UCIjxsUi8aJhkvnYGZzQo74Q`, private). These items came up after launch —
tracked here so they survive a session restart, worked in priority order
(1 and 3 are quick, 4 matters most for the actual A/B-testing goal, 2 is
blocked on the owner's action so lowest urgency).

### 1. Hashtag specificity — DONE
`config/prompts/metadata_template.txt` requires `#Shorts` first (a real
platform quirk: API-uploaded vertical videos under 60s aren't reliably
classified as Shorts without it, unlike app-uploaded ones) plus 4-6 more
hashtags. Constraint to enforce going forward: YouTube's hard cap is 15
hashtags combined across title+description — exceeding it silently
discards ALL hashtags, not just the extras, so never add volume. The
prompt must require hashtags specific to THAT video's exact subject (a
pointers video gets `#Pointers #CBugs`, not a recycled generic block like
`#ProgrammingBugs #CodingTips` on every video) so tags stay genuinely
distinct video to video — target is `#Shorts` + 4-6 specific tags, never
more. Verified on the live video: pushed via `pipeline.upload.
update_remote_metadata()` (needed the OAuth scope bumped from
`youtube.upload`+`youtube.readonly` to `youtube.force-ssl`, since
`videos.update`/`delete` aren't covered by upload-only scope — done, new
token confirmed to resolve to ByteBits before use).

### 2. Custom thumbnails per video — DONE
Phone verification completed 2026-09-06. `pipeline/thumbnails.py`
extracts a still frame from the rendered final video (v1 — a branded
title-card graphic is a possible v2 later, not needed now): for
programming, the last output-bearing step's hold period (real code +
real output on screen); for facts, near the hook rather than the outro.
A second candidate timestamp plus a `blackdetect`-based sanity check
avoid landing mid-transition. Every pick is logged to
`data/thumbnails.json` (timestamp + candidates + output path) so a bad
thumbnail is debuggable later. Wired into `pipeline/upload.py`'s
`upload()` — runs automatically after every future upload, failure is
non-fatal (the main video is already live by that point).

Verified against a real live video: the API accepts a vertical
1280x2276 extraction without rejecting it — YouTube auto-composites its
own 16:9 CDN thumbnail slots from it (blurred background fill), and the
real result keeps code/output/caption clearly legible. Known gap: the
first 3 CI-produced videos (uploaded before this was wired in, and
before it existed at all) don't have custom thumbnails, since thumbnail
generation needs the rendered file that only exists on the ephemeral
runner during that job — not retroactively fixable without re-rendering.

### 3. CTA badge brand colors — DONE
`pipeline/assemble.py`'s "SUBSCRIBE FOR MORE" end badge now uses the same
teal-to-indigo gradient as the rebranded programming terminal chrome
(`pipeline/brand.py`, shared between both) instead of generic
black/white. Verified via a real extracted frame showing the gradient
badge composited correctly over a real video with no transparency
fringing.

### 4. View tracking / weekly stats — IN PROGRESS
Deferred since early in the build until real videos existed on the
channel — they do now (first live video uploaded 2026-09-06), so this is
unblocked and is the highest-value remaining item (it's what makes the
`approach`/`cta_angle` A/B-testing data actually usable).

- `data/videos.json` — DONE. `pipeline/upload.py`'s `_log_uploaded_video()`
  appends {video_id, youtube_video_id, uploaded_at, template, approach}
  after every successful `upload()`, and the one video uploaded before
  this existed has been backfilled with its real `publishedAt` from the
  YouTube API (not a guessed timestamp).
- Still to build: a weekly GitHub Actions workflow (matches the
  daily-shorts.yml pattern
  already planned in SPEC.md's Scheduling section) that calls
  `videos.list` with `part=statistics` for videos uploaded in the past 7
  days and records view/like/comment counts. Stay on the free Data API
  quota — no YouTube Analytics OAuth scope unless the basic stats call
  proves insufficient (original constraint, still holds).
- A weekly markdown/CSV report ranking approaches (`storytelling_hook` /
  `fast_cuts` / `deadpan_facts`) by average views, committed to
  `reports/week-YYYY-WW.md` — this is the actual payoff of the approach-
  rotation system built in Phase 6.

### 5. Review gate retired for CI-produced videos — DONE (2026-09-06)
Explicitly superseded the SPEC.md non-negotiable ("a rendered video
should NOT auto-publish... for at least the first several weeks") for
the CI pipeline specifically, given how much verification happened this
session. `daily-shorts.yml` now runs `REQUIRE_REVIEW=false` +
`UPLOAD_VISIBILITY=scheduled` — CI videos go straight from render to a
scheduled public release, 2-4 random hours apart (see
`pipeline/upload.py`'s `_next_publish_time()`), no human checkpoint.
Local/manual uploads via `scripts/review.py` still default to private
unless `UPLOAD_VISIBILITY` is set otherwise. Retiring-the-gate item
below is effectively done for this track; local manual runs still have
the option to review first.

## Phase 11 — Quiz longform track (2026-09-06) — DONE

A second, separate content track alongside the daily Shorts pipeline:
horizontal 1920x1080, 4-5 minute Python quiz videos on the main channel,
weekly cadence (not daily). New pieces, all reusing the Shorts
pipeline's TTS/music/caption/upload/persona/CTA-rotation systems rather
than duplicating them:

- `config/prompts/quiz_template.txt` + `pipeline/plan_quiz.py` — 8-10
  questions with 4 options + explanation each, intro/outro, routed
  through `persona.py`/`cta.py` (not `approaches.py` — the hook/structure
  rotation is specifically for the Shorts A/B test).
- `video_steps` schema extended with `card_type`/`options`/
  `correct_index` — each question is TWO steps (question card, then
  reveal card), matching the existing per-step-audio-duration
  architecture rather than a new one.
- `pipeline/visuals_quiz.py` — question/countdown/reveal cards in the
  brand colors (`pipeline/brand.py`, shared with the Shorts chrome), a
  shrinking countdown bar during a silent think-time tail
  (`_build_padded_audio()` appends real silence to question-step audio
  so video and audio durations stay in sync).
- `pipeline/thumbnails.py`'s `generate_quiz_thumbnail()` — a designed
  curiosity-driven graphic ("CAN YOU PASS THIS QUIZ?" + question count),
  not frame-extraction — the thumbnail is the main click-through driver
  for this format, unlike a Short.
- `config/prompts/metadata_quiz_template.txt` — longer description, no
  #Shorts, at most 1-2 hashtags (this format doesn't lean on hashtags for
  reach the way Shorts do). Category: Education (27).
- `pipeline/orchestrator.py`'s `run_weekly_quiz()` + `scripts/
  run_weekly_quiz.py` + `.github/workflows/weekly-quiz.yml` (Wednesdays,
  same CI pattern as daily-shorts.yml — REQUIRE_REVIEW=false,
  UPLOAD_VISIBILITY=scheduled).
- `scripts/weekly_report.py` explicitly excludes `quiz_longform` from the
  Shorts approach-ranking comparison, per the original requirement.

**Resolution-agnostic fixes needed along the way** (assemble.py and
captions.py previously hardcoded the 1080x1920 Shorts frame):
`assemble.py`'s CTA badge position and `captions.py`'s caption
font-size/margin now derive from the real video's probed dimensions.
Caption vertical placement can't share one ratio across orientations — a
vertical Short has real empty space below its panel for a "lower/middle"
caption zone; a landscape frame's panel fills most of the height, so
captions there need a thin strip right at the very bottom instead. Font
size scales off the shorter dimension (1080 either way) so text reads at
a consistent relative size regardless of orientation.

**Real bugs caught during verification, not just "should work":**
1. Captions directly overlapped the last option row on the first real
   render — fixed by making the quiz panel's size dynamic (computed once
   from the longest question across the whole video, like
   visuals_code.py already does) and reserving a real bottom strip
   captions can't be drawn into.
2. The first real full-length render took 18+ minutes and hadn't
   finished — `pipeline/brand.py`'s gradient generator did a pure-Python
   per-pixel-column loop that scaled with the target width, called fresh
   on every single video frame (thousands of frames for a 4+ minute
   video). Fixed at the root (a small fixed-size gradient strip + PIL's
   C-level resize, regardless of target size) plus caching the panel's
   static border/fill once per video instead of recomputing it per frame,
   and rendering static-content frame spans (narration, intro/outro) once
   and reusing the same PNG bytes rather than re-running Pillow draw
   calls per identical frame. Verified: full ~4.3-minute video render
   dropped to ~2 minutes.

Verified end to end with a real video (9 real, correct Python gotchas —
floating point equality, bool/int subclassing, slice-out-of-range,
mutable default args, dict ordering, banker's rounding, chained
comparisons, closures in loops, small-int caching): real frames confirm
the layout fix, real metadata generated is specific to the actual
questions covered, not generic.

## Phase 12 — Post-launch fixes round 2 (2026-09-07) — DONE

Quiz workflow paused (`gh workflow disable weekly-quiz.yml`) while these
landed. Re-enabled 2026-09-07 after the owner confirmed the long-form
render fixed (real video watched, both the earlier and the follow-up
vertical-overflow fix verified). Cadence also changed at re-enable time:
1x/week -> 2x/week (Wed + Sat) — owner-confirmed intentional change, not
a drift from the original spec. Plan: watch the first 1-2 automated
runs manually before treating this as fully unattended.

1. **Quiz font overflow** — option text had zero wrapping/shrinking at
   all (unlike question text, which already word-wrapped); long options
   rendered past the row/panel edge. Fixed with `_fit_multiline`/
   `_fit_single_line` (shrink-in-a-loop, floor size, then truncate as a
   last resort) plus a named `SAFE_MARGIN_FRACTION` (5%) applied on top
   of the panel's own padding. Fitting is computed once per question
   (not per frame) since the countdown timer increase (below) would
   otherwise reintroduce a per-frame cost. Verified against the same
   option that nearly overflowed before.
   - **Follow-up (still 2026-09-07): this fix was incomplete.** User
     reported overflow still visible at the real 3/6/7 minute marks.
     Root cause was different from #1 above: a long QUESTION (5-6
     wrapped lines at the fixed base font size) made
     `_compute_panel_geometry`'s precomputed panel height insufficient,
     but the function only clamped `panel_h` to the available space
     (`min(content_h, available_h)`) without ever shrinking what
     actually gets drawn — so option rows got pushed past the clamped
     panel's own bottom edge. Confirmed via real extracted frames:
     option D rendering fully outside the panel border, off-frame.
     Fixed by having `_compute_panel_geometry` shrink the base question
     font size in a loop (same principle as #1, applied to the shared
     vertical budget instead of one line's width) before the panel size
     is ever fixed. Verified programmatically across all 9 real
     questions in the affected video (worst case 64px of real margin)
     and by re-rendering and re-extracting frames at the exact reported
     timestamps.
2. **Quiz captions removed, 30s per-question timer** — `captions.py`
   skips real transcription/burn-in for `quiz_longform` (copies
   video_path -> final_path, still advances through the "captioned"
   status name so the rest of the pipeline doesn't need a special
   case). `COUNTDOWN_SECONDS` raised 3.0 -> 30.0, pushing total length
   further into long-form territory (verified real video: 501.8s ≈
   8.4 min, up from ~4.3 min). Note: faster-whisper is local/free, not a
   paid API — the real savings is render time, not cost. Redirecting
   that time (more questions/video, a different voice, more videos/day)
   is left as an open decision, not decided here.
3. Low view counts on day 1 — no code issue, YouTube's new-channel trust
   phase; not actionable, no changes made.
4. **Shorts script repetition** — `config/approaches.yaml`'s pools
   expanded from 2-3 to 18 entries per slot per approach.
   `pipeline/approaches.py`'s `pick_style()` now prefers phrases not
   used in the last 15 videos (`data/phrase_usage.json`), falling back
   to the full pool only if it's fully cycled. `config/persona.md` gained
   an explicit sentence-rhythm-variety instruction (repetition lives in
   sentence shape as much as word choice). Verified: 10 consecutive
   picks from an 18-entry pool, all unique.
5. **Caption drift after pauses** — root cause was re-transcribing our
   own TTS output with Whisper, which loses accuracy right around
   silence gaps. Fixed at the root: `voice.py`'s edge_tts synthesis now
   requests `boundary="WordBoundary"` and captures real word-level
   timestamps directly from the same synthesis call (a `.words.json`
   sidecar per audio segment) — no transcription step at all for this
   backend. `captions.py` prefers these when present (cumulative offset
   per concatenated step), falling back to the original Whisper+
   alignment path only for backends without native timestamps (kokoro —
   this fallback is logically unchanged but not re-verified live, since
   kokoro isn't the active backend). Real gotcha: edge_tts defaults to
   `boundary="SentenceBoundary"`; the word-level events don't appear
   unless requested explicitly.
6. **Caption font/style overhaul** — switched from JetBrains Mono to
   Poppins ExtraBold (OFL-licensed, `assets/fonts/`) for captions
   specifically (code panels keep JetBrains Mono — different UI
   element, no brand conflict). Pure white text, black outline
   (`BorderStyle=1`, no background box), single high-contrast accent
   color for the active word, `Bold: 0` since ExtraBold doesn't need
   synthetic bolding stacked on top. Repositioning note: literal
   "center-to-upper-third" would collide with our centered code/facts
   panel — the real concern (Shorts app UI chrome covering the bottom
   ~25%/top ~15% on a real device) is addressed with a moderate margin
   increase (0.323 -> 0.38 of height) instead of a full relocation into
   the panel's own space.

## Phase 13 — Post-launch fixes round 3 + Sauce Recipe series (2026-09-07) — DONE

1. **CI state-save push race** — the "commit updated state" step in all
   three workflows did a bare `git push` with no retry. A concurrent push
   (a manual push landing on `main` mid-run) rejected the run's own
   commit, which then vanished with the ephemeral runner — this happened
   for real and silently dropped a completed YouTube upload's state.db
   record (recovered by hand via the YouTube Data API, see the git log
   for that commit). Fixed in `daily-shorts.yml`, `weekly-quiz.yml`,
   `weekly-stats.yml`: retries up to 3 times with `git pull --rebase` in
   between on rejection. Verified by reproducing the exact race in a
   throwaway git repo (two clones racing to push) and confirming
   recovery with nothing lost, plus a real clean first-attempt push on
   the next live run.
2. **Caption sentence-boundary bleed** — the caption chunker used a fixed
   4-word sliding window with zero punctuation awareness, so a sentence's
   last word landed on the same card as the next sentence's first word
   ("warned me about I", period silently gone). Root cause was two
   things: edge_tts's WordBoundary text carries no punctuation at all
   (verified directly against the library), and the chunker never
   accounted for sentence boundaries even once punctuation existed. Fixed
   by aligning native timestamps back onto the real punctuated
   script_text (reusing the existing Whisper-alignment machinery, renamed
   `_align_script_to_timed_words` since it's no longer Whisper-specific)
   and hard-splitting caption cards on `.`/`!`/`?` (not comma — no
   observed bug there, and it'd make captions needlessly choppy).
3. **Code panel / caption layout collision on regular Shorts** — the code
   panel (`visuals_code.py`) was vertically centered with unbounded
   height (no cap on code line count), with zero coordination with
   `captions.py`'s caption zone — confirmed geometrically that even a
   modest 5-line snippet's panel already overlapped where captions
   render. Fixed by adding `CAPTION_MARGIN_V_RATIO_PORTRAIT`,
   `CAPTION_TEXT_HEIGHT_RATIO`, and `TOP_SAFE_ZONE_RATIO` to
   `pipeline/brand.py` as a single source of truth both files import,
   and giving `visuals_code.py` a width+height font-shrink loop
   (mirroring the pattern already used in `visuals_quiz.py`) so the
   panel always fits the real safe band instead of growing into it.
   Verified with real font-metric math across 3-30 line snippets and a
   real rendered frame with the safe-zone boundaries drawn on top.
4. **Fabricated personal-experience hooks, root cause** — a real render
   opened with "Here's the story nobody warned me about," the exact
   pattern an earlier persona.md addition this session was meant to ban.
   Traced one level deeper than the missing persona rule: that phrase
   (and 9 others like it — "the time this went wrong," "someone told me
   this once," "I wish I was making this up") were literal entries in
   `config/approaches.yaml`'s `storytelling_hook.hook_openers` pool,
   directly contradicting the persona rule by handing the LLM the exact
   phrase as a suggested example. Rewrote all 10 to keep the same
   dramatic tone while framing the surprise around the fact's own story,
   not a personal anecdote; the other two pools (fast_cuts,
   deadpan_facts) were checked and were already clean.
5. **Persona split by template** — `persona_guidance_block()` injected
   Python-specific pet-peeves (mutable default arguments, benchmarks)
   into every template's prompt unconditionally, including facts videos
   about unrelated topics. Split `config/persona.md` into a
   template-agnostic core plus per-template pet-peeves files
   (`persona_pet_peeves_dev.md` for programming/facts/quiz_longform,
   `persona_pet_peeves_sauce_recipe.md` for the new series below);
   `pipeline/persona.py` now takes a `template` argument and raises
   loudly for an unmapped one instead of guessing.
6. **New: "Sauce Secrets" recipe series** — a second Shorts content
   track (3 sauces per video, real ingredients/method, own recurring
   voice) added to the daily rotation alongside programming/facts
   (`orchestrator.py`'s `TEMPLATES` tuple — owner chose folding into the
   existing daily cadence over a separate lower-frequency workflow).
   Turned out to need far less new code than the original spec assumed:
   `visuals_facts.py`'s existing Pexels B-roll pipeline (search per beat,
   download, trim-to-narration-duration, crossfade) already does
   everything the spec called "B-roll fetch" and "clip assembly" for —
   broadened its template guard (`_STOCK_FOOTAGE_TEMPLATES`) instead of
   building a parallel system. `plan.py`'s existing facts-style parsing
   (3 beats, each `script_text` + `keywords`) already matches "3 sauces,
   each narration + B-roll keywords" — new template is just a dict entry
   plus `config/prompts/sauce_recipe_template.txt`. Captions needed zero
   changes. Owner explicitly chose to ship v1 without on-screen
   ingredient/step overlays (matches the facts template's existing
   narration+B-roll+captions shape, no new rendering code) — a real,
   tracked gap, not silently dropped: on-screen overlays, a visually
   distinct thumbnail template, and the playlist itself (manual, YouTube
   Studio) are the series' own known follow-ups once the format's
   proven. Verified end-to-end with a synthetic LLM response run through
   the real parser and real `state.db` writes (cleaned up after), plus
   confirming `visuals_facts`'s broadened guard accepts the new template.

## Phase 14 — Authenticity/variety audit (2026-09-08) — IN PROGRESS

Owner-requested 5-item plan (audit, audio authenticity, structural
variety, niche separation, a new "Higher or Lower" format), worked one
item at a time with a plan presented before each. Items 1-3 done;
items 4-5 not started.

1. **Audit** — found two systems already partially built that the
   request assumed didn't exist: hook/phrase rotation
   (`config/approaches.yaml`, 18 variants x 3 approaches, 15-video
   recent-exclusion) and a loudness-relative music bed (`assemble.py`,
   `facts`/`quiz_longform` only). Real gaps confirmed: single fixed TTS
   voice/rate for every video, no sentence-boundary pause control, a
   single music track (`lofi_pulse.mp3`) so no real bed variety yet,
   `sauce_recipe` silently missing from `MUSIC_TEMPLATES`, single fixed
   visual theme for programming, one fixed CTA overlay design.
2. **Audio authenticity** — done:
   - `EDGE_TTS_RATE = "+8%"` (1.08x) on every synthesis call; verified
     for real (0.927 byte-size ratio vs. the +0% baseline).
   - Real sentence-boundary pauses: the obvious approach (an embedded
     `<break time=.../>` tag) is genuinely broken with edge_tts --
     confirmed it gets spoken aloud as literal words, not respected as
     SSML (no raw-SSML entry point on the library's public API). Real
     fix: split multi-sentence text into separate synthesis calls,
     concatenated -- `SENTENCE_PAUSE_SECONDS` landed at 0.0, not a
     guessed value, because splitting alone already produces a natural
     ~0.45s gap at the boundary (measured, not assumed); an explicit
     0.22s pad on top overshot to ~0.73s.
   - `MUSIC_TEMPLATES` extended to all four templates (was facts/quiz
     only); fixes the real `sauce_recipe` omission.
   - TTS voice: owner chose a single swap over a rotating pool (a
     rotating voice reads as *less* consistent, not more). 4 real
     candidate voices (Brian/Christopher/Roger/Steffan Neural) generated
     as actual audio samples and sent for a real listen — pick pending.
3. **Structural variety** — done:
   - Extracted `pipeline/rotation.py`'s generic `pick_rotating()` from
     `approaches.py`'s hook-phrasing logic (real reuse, confirmed before
     building anything new — `approaches.py` refactored to call it too,
     not left as a parallel copy).
   - 5-theme rotation for the programming code panel (monokai + dracula,
     nord, one-dark, solarized-dark — all verified real pygments styles).
     Panel chrome colors (frame/divider/output-label) are *derived* from
     each theme's own bg/text color, not 20 hand-tuned constants;
     verified the derivation against monokai's existing values first.
     Output-text green picked by hand per theme from its real palette.
     Brand border/flash ring/tab chrome confirmed to stay fixed across
     themes. Window=2 (not the hook pool's 15 — would be a permanent
     no-op on a 5-item pool).
   - 3 CTA overlay variants (position/timing/phrasing) replacing the one
     fixed badge. Window=1 (owner confirmed the 3-item pool has the same
     exhaustion risk as the theme pool).
   - Real, related gap found and fixed while building this (not
     explicitly requested): `_pick_music_track()` had zero recent-
     exclusion at all — harmless with one track, a real repeat risk once
     more exist. Same rotation mechanism, window=1.
   - Verified: real rendered grid of all 5 themes against actual code,
     real rendered CTA badges for all 3 variants, both viewed directly.
4. Niche separation and the "Higher or Lower" format: not started as a
   quiz-format add-on -- superseded by the Phase 16 game-night track,
   which subsumes "Higher or Lower" as one of five round modules.

## Phase 15 — CTA comment fix + cheap signal collection (2026-09-08) — DONE

Two owner-scoped items: fix a real comment-posting bug (hypothesis
tested before any fix), then cheap data/branding additions explicitly
scoped to *not* include scoring/weighting/prompt-injection yet.

1. **CTA auto-comment 403, root cause confirmed by test, not guessed** --
   hypothesis was "does `commentThreads.insert` fire before the video is
   actually public?" Tested directly: posted a real comment against an
   already-public video (succeeded instantly), confirming the identical
   call fails only while the video is still private. `upload()` now only
   attempts an immediate comment when `visibility == "public"`;
   `post_pending_cta_comments()` (new, hourly workflow) batches
   `videos().list` against uploaded-but-uncommented rows and posts once
   they're really public. Bounded to
   `CTA_COMMENT_CATCHUP_MAX_AGE_DAYS = 3` to avoid a retroactive burst
   across the 19 pre-existing uploaded videos on first run. Live
   diagnostic comment posted then deleted (`comments().delete()`) to
   avoid a real visible side effect from the test itself.
2. **Genome tag capture (data collection only, no scoring)** --
   `generate_metadata()` now writes `genome_hook_style`,
   `genome_concept_type`, `genome_item_count`, `genome_visual_density`
   per video. Nothing reads these yet.
3. **Real analytics sync** -- `pipeline/stats.py`'s `sync_analytics()`
   pulls real views/likes/comment_count for uploaded videos in a
   48h-14d age window, daily cron. Verified against a real video (146
   views / 7 likes written for real).
4. **Episode counter badge** -- "EP N" rendered top-right in the
   programming code panel's title bar, from
   `count_uploaded("programming") + 1` (real upload count, not a
   manually tracked value). Verified via a real rendered frame (EP 11)
   before committing.
5. **New CTA variant** -- `save_for_later_early`, fires at 15% into the
   video (earlier than the other 3) since "save this" only makes sense
   before a viewer might swipe away.
6. **Code-panel retyping fix (the bigger structural one)** -- was
   clearing and retyping the *entire* panel on every step, even lines
   unchanged since the previous step. Now diffs each step's lines
   against the previous step's (`difflib`, on the same plain text
   `_layout_lines()` renders from, so diffing and rendering can't
   disagree) and only clears/retypes lines that actually changed; a
   border flash is the sole "something changed" cue (the old two-stage
   fade-to-blank transition was removed entirely). Verified by
   re-rendering the real "Java Integer Cache" script end-to-end and
   confirming at both real transition points (t~=22.3-23.0s and
   t~=42.3s) that only the actually-differing lines animate.
7. **Self-caught production risk, fixed structurally** -- 4 new
   state.db columns landed in code but the migrated `state.db` binary
   was never re-committed; an unrelated `git checkout -- state.db`
   cleanup silently reverted the local copy too, reproducing a real
   `sqlite3.OperationalError: no such column` crash that would have hit
   the already-scheduled hourly comment-catchup workflow on its next
   run. Fixed both the immediate data (`state.db` re-migrated and
   committed) and the root cause: `init_db()` now runs unconditionally
   at `pipeline/state.py` import time instead of only from that
   module's own `__main__` block, so a schema change in code can never
   again ship without actually being applied.

Explicitly deferred by the owner until there's real signal (40-50+
videos): performance scoring, exploit/explore weighting, few-shot
prompt injection of "winning" scripts, Related Video API linking.

## Phase 16 — Game-night production line (2026-09-08) — IN PROGRESS

Owner commitment: 2 game-night videos/week (Tue/Fri) + 1 quiz/week.
Plan for items 1-2 (5 game modules + shared infra) presented and
approved before any render code, per explicit request. Quiz moves to
Saturday (better spacing against Tue/Fri game nights than Wednesday --
gaps of 3/1/3 days vs. 1/2/4); Wednesday's quiz cron entry gets dropped
once the new workflow scheduling lands (Phase 16 item 5, not started).

Items 1-3 done, verified with REAL LLM calls (not mocked):
- **`pipeline/games/`** -- `base.py` (GameSession, `select_rounds()`,
  `verify_claim()`, the shared `make_beat()` schema) plus one module per
  round type: `memory.py`, `what_changed.py`, `risk_or_safe.py` (fully
  algorithmic, no LLM), `higher_or_lower.py` and `prediction.py`
  (LLM-proposed real numeric claims, gated by `verify_claim()` before
  they can ship).
- **`select_rounds()`** verified against 2000+ real trials: zero
  adjacent-repeat violations, always a full 5-type variety set at
  count=5.
- **`verify_claim()`** verified against a real known-true claim (Everest
  8849m -- CONFIRMED) and a real known-false one (Everest 3000m --
  REJECTED, with a real correct correction offered back). Real cost:
  ~4-5s per call (a real `claude` CLI subprocess).
- **False-precision rejection, found and fixed for real.** The initial
  100% substitution rate for higher_or_lower/prediction (both fell back
  in the first real run) turned out to be two separate real bugs, not
  one calibration issue:
  1. `verify_claim()`'s prompt was genuinely too strict (rejecting
     accurate-but-precisely-stated values like "8849.0m" over rounding).
     Relaxed to explicitly confirm reasonable rounding/source variation,
     and both generation prompts now ask for sensibly-rounded values
     with "approximately"/"roughly" narration instead of fabricated
     decimal precision.
  2. **A real parsing bug**, found while checking *why* two still-correct
     claims (Great Wall length, Eiffel Tower steps) kept getting
     rejected after the prompt fix: the model sometimes reasons out loud
     despite the "respond in EXACTLY this format" instruction, emitting
     a first `VERDICT: REJECTED` that its own follow-up reasoning then
     reverses to a final `VERDICT: CONFIRMED` -- and `_VERDICT_PATTERN
     .search()` was grabbing the FIRST match, silently taking the
     model's abandoned draft answer instead of its real one. Fixed by
     taking the LAST verdict match instead (the model's settled answer),
     with `corrected` only read back when that final verdict is
     REJECTED. Confirmed via the raw model output for both cases before
     believing the diagnosis, not guessed.
  Re-verified with 3 full real `plan_game_night()` runs after both
  fixes: 6/6 higher_or_lower/prediction slots surfaced as themselves
  (zero fallback substitutions), vs. 2/2 substituted before. Content
  spot-checked and reads naturally with the new rounded framing (e.g.
  "roughly 110 kilometers an hour," "approximately 1,454 feet"). All 3
  test videos removed from state.db after inspection.
- **`pipeline/plan_game.py`** -- assembles one episode: picks rounds,
  threads one `GameSession` through them, folds in a rotated (not
  LLM-generated) intro/outro line, substitutes on verification failure.
  Verified with a real end-to-end run: 37 real steps, 5 real rounds,
  session math confirmed by hand (70 points / 2 lives, arithmetic
  checked against each round's real pass/fail), no-adjacent-repeat held
  in the real generated sequence. Test video removed from state.db after
  inspection (state.db's binary diff afterward was pure SQLite page
  churn, confirmed identical real row set before discarding it).
- `pipeline/state.py`: `video_steps` gets `round_type`, `round_index`,
  `beat_type`, `round_data_json`, `lives_after`, `points_after` (same
  `ALTER TABLE ADD COLUMN` migration pattern as every prior schema
  change). `pipeline/persona.py` maps `game_night` to the existing dev
  pet-peeves file (no game-night-specific opinions yet).

**Item 4 done -- real rendered test episode, verified.**
`pipeline/visuals_game.py` (1920x1080, same brand panel/border chrome as
visuals_quiz.py, reused via the new `pipeline/render_text.py` extraction
rather than a third copy of the same fitting logic) renders every beat
type: a generic centered-text card for intro/rule/countdown/suspense/
score, and a bespoke gameplay/reveal visual per round type (chip rows for
memory, a before/after attribute table for what_changed, two choice
cards for risk_or_safe, a shared versus-card layout for
higher_or_lower/prediction) -- plus a persistent lives/points HUD and
round-type label drawn from the beat's own stored, real session values,
never re-derived.

**Real bug caught and fixed during first-render testing**: the
higher_or_lower/prediction versus cards centered subject names at a
fixed font size with no width fit -- fine for short placeholder names in
early testing, but a real LLM-generated name ("Empire State Building
height") rendered past the card edge. Fixed by routing both cards'
name/value text through `fit_single_line` (shrink-then-ellipsis) before
centering, same primitive already proven in visuals_quiz.py. Re-verified
with deliberately long real names (Burj Khalifa/One World Trade Center)
before trusting it.

Also closed the exact `MUSIC_TEMPLATES` gap this project already knows
the shape of (sauce_recipe shipped without it, found and fixed in Phase
14) -- added `game_night` up front this time instead of waiting to
rediscover the same omission.

**Full pipeline run, real and end-to-end**: `plan_game_night()` ->
`voice()` -> `visuals_game()` -> `assemble()` -> `captions()` ->
`generate_metadata()`, stopping safely at `awaiting_review`
(`REQUIRE_REVIEW=true`, confirmed before running -- no upload attempted).
~169s render time after planning. Real output inspected at 6 timestamps
across the full 120s video: HUD/round-label/CTA-overlay/burned-in
captions all render correctly and simultaneously with no collisions;
session math (lives/points) matches the narration and the on-screen
reveal cards at every checked point; the real round sequence for this
episode was memory/prediction/risk_or_safe/higher_or_lower/what_changed
-- all 5 types, zero repeats, confirming the round-selector's variety
rule on real generated content, not just the earlier synthetic trials.
Test video sent to the owner directly, then fully removed from state.db
and assets/output afterward.

Not started: item 5 (new GH Actions workflow(s) for Tue/Fri game night,
folding in the Wed->Sat quiz-day move -- Saturday chosen for more even
weekly spacing against Tue/Fri: gaps of 3/1/3 days vs. Wednesday's
1/2/4).

**Real owner feedback after watching item 4's test episode (2026-09-08),
STATUS: NOT RESOLVED -- read before touching this again.** Reaction: "too
fast", "the ai plays by himself", "we dont need captions on longterm",
"i dont like it at all". Three concrete fixes shipped and re-verified by
re-rendering:
1. Dropped the entire simulated contestant/lives/points system (was the
   "AI plays by himself" complaint) -- every round now just presents its
   content and reveals the real answer, no invented win/loss judgment,
   no HUD, no red/green coloring (one neutral highlight color instead).
2. Turned off burned-in captions for game_night entirely (matches
   quiz_longform's existing behavior).
3. Added a minimum real hold duration for gameplay/reveal/countdown
   beats (padded with silence when the driving narration line is
   shorter) -- the actual mechanism behind "too fast": a visual card the
   viewer needs seconds to read was sometimes on screen for well under a
   second.

Owner watched this second pass and said it's **still bad** -- session
ended on session-limit pressure before getting specifics on what's still
wrong. Do NOT assume the above 3 fixes were the wrong ones or start
guessing at a 4th round of changes -- get the owner's specific reaction
to this second test episode first. Real possibilities not yet
investigated: the new min-hold durations may still not be long enough
(or too long/inconsistent); the per-round visual designs themselves
(chip rows, before/after table, versus cards) may just not be
compelling regardless of pacing; 5 rounds x ~115s may be the wrong
format shape entirely (too long, too short, wrong round count); the
whole "steps table + PIL card renderer" approach inherited from
quiz_longform may not be the right visual language for this format at
all. Don't rebuild anything else in Phase 16 until this is actually
diagnosed with the owner.

## Phase 17 — Narration authenticity & anti-hallucination system (2026-09-08) — DONE

Owner-provided spec (full text in session transcript) for making narration
read as deliberately written by a knowledgeable human editor, not
generic-content-mill output. Owner scoped this explicitly: replace/rewrite
the existing persona system (not layer on top of it), add a real
post-generation review/reject pipeline stage (not prompt-only), and apply
to programming/facts/sauce_recipe (quiz_longform/game_night out of
scope — game_night is separately blocked, see Phase 16 below).

1. **`config/persona.md` rewritten** — kept what already worked (tone,
   sentence-rhythm variety, subscribe-not-follow, banned-phrase list,
   concrete-detail rule) and folded in the new stricter rules: an explicit
   Notice/Explain/Connect/Remove editorial thinking process, an
   anti-hallucination rule (adapted from the owner's spec — this pipeline
   has no separate research/grounding step feeding these templates, so
   "don't invent a plausible-sounding fact" replaces "not supported by
   supplied source material," same intent), the visual-complementarity
   rule, the topic-swap test, and a stronger no-fabricated-personal-
   experience rule (kept the existing stance-vs-event distinction, since
   it already correctly allowed "I ran into something weird here" while
   banning a claimed specific memory — the new spec's stricter examples
   were folded into that existing test rather than replacing it).
2. **Per-template editorial identity split** — `persona_pet_peeves_dev.md`
   (shared programming/facts/quiz_longform/game_night) split into
   `persona_pet_peeves_programming.md` and `persona_pet_peeves_facts.md`,
   each now carrying a distinct "editorial identity" section (Programming
   Narrator vs. Facts Narrator, per the owner's spec) on top of the
   existing recurring-opinions pet-peeves list, which was kept rather than
   rewritten (still accurate, still template-appropriate).
   `persona_pet_peeves_sauce_recipe.md` got the same identity-section
   treatment; quiz_longform/game_night still map to the original
   `persona_pet_peeves_dev.md`, untouched — out of scope, and game_night
   specifically is still blocked pending the owner's diagnosis of the
   Phase 16 test episode. `pipeline/persona.py`'s `_PET_PEEVES_FILE`
   mapping updated accordingly.
3. **New review/reject pipeline stage** — `pipeline/review_script.py`
   (`review_script()`) sends the plain narration (hook + beat scripts
   only, no field labels/code/keywords — those would confuse a reviewer
   checking for authentic-sounding narration) to a new prompt,
   `config/prompts/script_reviewer_template.txt`, adapted from the
   owner's spec. `pipeline/plan.py`'s `_generate_reviewed()` wires this
   into `plan()`: generate, review, and if `REWRITE_REQUIRED`, feed the
   reviewer's own feedback back into a rewrite prompt (up to
   `REVIEW_MAX_REWRITES = 2` attempts) before raising — caught by
   `orchestrator.run_daily()`'s existing try/except around `plan()`, same
   fail-soft handling as a malformed-output parse error, so one
   template's slot failing doesn't take down the run. Verdict parsing
   takes the LAST `APPROVED`/`REWRITE_REQUIRED` match, not the first —
   deliberately reusing the exact lesson Phase 16's `verify_claim()`
   learned the hard way (a model that reasons out loud can emit a draft
   verdict its own follow-up reasoning reverses).
4. **Tests** — `tests/test_review_script.py` and `tests/test_plan.py`
   cover the pure logic (verdict parsing including the last-match case,
   narration extraction excludes code/keywords, rewrite-prompt
   construction, the generate/review/rewrite loop with a mocked
   `call_llm`/`review_script`) per `CLAUDE.md`'s testing rule — no real
   LLM calls in the test suite itself. All passing.
5. **Real end-to-end verification — two real bugs found and fixed along
   the way, not just threshold-tuned.** Ran `plan('facts')` and
   `plan('programming')` for real against the actual `claude_code`
   backend (confirmed reachable in this environment), five real runs
   total before landing on a config that converges:
   - Runs 1-2 (`facts`, `programming`, `REVIEW_MAX_REWRITES = 2`): both
     exhausted the budget and were still rejected. Feedback each round
     was legitimate (a CTA line interrupting narration, repeated
     sentence shapes, a near-verbatim repeated phrase, a stock hook
     phrase) — not overly strict nitpicking. Presented to the owner
     rather than guessing; chose to raise the budget over loosening the
     anti-hallucination rule.
   - Run 3 (`facts`, budget raised to 4): still rejected, but every
     single one of the 3 real failures so far had independently flagged
     the CTA line specifically. Traced this to a real bug, not a
     threshold problem: `pipeline/cta.py`'s own `direct_ask`/
     `mid_script_aside` angle instructions modeled the exact "subscribe
     if [vague thing]" pattern `persona.md`'s new rules ban — the LLM
     was faithfully following `cta.py`'s own example straight into a
     rejection. Fixed `cta.py`'s instructions and examples to drop the
     vague-conditional shape and require the CTA line meet the same
     authenticity bar as the rest of the script.
   - Run 4 (`facts`, budget 4, CTA fixed): the CTA complaint was gone
     (confirming that fix), but still rejected on a new issue — vague
     mechanical transitions between the three facts ("doing something
     similar", "has one too") plus a repeated comparison stated twice.
     Presented to the owner again: this read as the Facts Narrator's
     "real connecting theme" bar being reasonable but the reviewer's
     "no mechanical transitions" criterion being too strict for a tight
     30-40-word-per-fact rapid format, where a full transition can't
     always spell out the parallel. Owner chose to ease that specific
     rule rather than raise the budget further. Reworded criterion 5 in
     `config/prompts/script_reviewer_template.txt` to flag only literal
     placeholder transitions ("moving on", "next", "number two"), not a
     short plain connective phrase — and added the matching guidance to
     `persona_pet_peeves_facts.md` so generation and review agree on the
     same bar (the exact CTA mismatch, fixed for the same reason).
   - Run 5 (`facts`, after the transition-rule fix): **approved on the
     first draft, no rewrite needed** — a real connecting theme (units
     of measurement literally born from manual labor: an acre, one
     horsepower, a knot), a genuine stance-based reaction ("Very
     scientific, I know."), and a specific, on-topic CTA.
   - Run 6 (`programming`, same fixed config): **also approved on the
     first draft** — banker's rounding in Python's `round()`, a real,
     accurate explanation of *why* (avoids upward bias in repeated
     rounding), CTA specific to the video's own theme ("Subscribe for
     more defaults languages don't call out clearly").

   All 6 test videos removed from `state.db` and `data/phrase_usage.json`
   reverted after each run; `state.db`'s own binary diff afterward was
   pure SQLite page churn against the already-committed baseline, same
   as Phase 16's precedent — discarded rather than committed.

6. **`sauce_recipe` verification — a third instance of the same bug
   class, in a different system.** First two attempts hit `call_llm`'s
   pre-existing 120s subprocess timeout before a response came back at
   all (environmental — this session's `claude` CLI subprocess slowing
   down after ~9 real calls already made during this verification pass;
   unrelated to any code here, and it cleared up on retry). The third
   attempt reached real review and got rejected on one line: "Here's the
   detail that makes this whole thing make sense: ..." — flagged as
   empty-hype generic phrasing. That exact string, word for word, is a
   literal entry in `config/approaches.yaml`'s `storytelling_hook.
   hook_openers` pool (the currently-active approach per `config.yaml`),
   fed straight into every template's prompt by `pipeline/approaches.py`'s
   `style_guidance_block()` and — confirmed by checking the actual text
   of the earlier `programming` failure in item 5 above — the LLM copies
   these near-verbatim rather than just drawing inspiration from them.
   The exact same root cause as the `cta.py` bug (item 5, run 3), just a
   different injection point, and the pool's own header comment already
   documented this failure MODE happening once before for a different
   rule (a fabricated-personal-experience phrase, fixed in Phase 13) —
   the new stricter anti-filler rules just reopened it with a fresh set
   of phrases. Audited all 18 `storytelling_hook.hook_openers` entries
   against `persona.md`'s new rules: kept the 4 that promise something
   real (an explanation, a corrected misconception), rewrote the other
   14 that were empty-hype/vague-escalation shapes ("buckle up", "stay
   with me", "sounds fake ... doesn't", "gets weirder the longer you sit
   with it", "stranger than the fact itself", vague "twist"). Re-verified
   for real immediately after: **`sauce_recipe` approved on the first
   draft** — a real connecting theme (three sauces sharing one
   fat-to-acid ratio), real technique and quantities, a CTA specific to
   the video's own content. `fast_cuts`/`deadpan_facts` pools have the
   same class of entries and were NOT audited (not the active approach,
   so not currently reachable) — flagged here so the same bug doesn't
   quietly resurface if `config.yaml`'s `current_approach` ever switches
   to one of them.

All 7 real test videos across this verification pass removed from
`state.db` after inspection, `data/phrase_usage.json` reverted each
time, `state.db`'s own binary diff confirmed as pure SQLite page churn
against the committed baseline and discarded rather than committed —
same pattern as Phase 16's precedent. No real render/upload attempted
either way — this phase only touches script generation (Phase 1),
nothing downstream. Worth watching in production: the review pass adds
real LLM-call cost/time per video (worst case 5 generation + 5 review
calls at the current budget of 4), though every template that's been
exercised for real now converges on the first draft with no rewrite.

## Later (not part of initial build)
- Moving the scheduler/trigger to an always-on free-tier VM
- Alerting on repeated failures
- ~~Retiring the review gate once the channel has a track record~~ — done
  for CI-produced videos, see Phase 10 #5 above
- Facebook/Instagram cross-posting via Meta Graph API — needs manual
  setup first (Meta app, Page/IG linking, long-lived Page token) before
  any pipeline code gets written; see the owner's own notes for the full
  checklist and API flow when ready.
