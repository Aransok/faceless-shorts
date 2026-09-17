# Session handoff — game-night track

Quick-reference status for picking this back up from any device. Full
engineering detail lives in `ROADMAP.md` Phase 15/16 — this file is the
short version.

## New content-format ideas discussed (2026-09-17) — NOT decided or built yet

Owner is exploring new content directions beyond the current daily
rotation. Nothing in this section is coded — this is a decision log so a
session on another device doesn't have to re-derive the conversation from
scratch.

1. **AI-generated visuals instead of Pexels stock (facts/sauce_recipe)** —
   idea: replace/augment `visuals_facts.py`'s stock-footage search with
   real AI video generation (Veo 3, or a "TopView" third-party skill the
   owner found) so visuals show the literal thing being described instead
   of a generic stock match. **Rejected for now**: every real video-gen
   backend (Veo 3, Kling, Runway, Luma, TopView) charges per second — no
   usable free tier — and the owner explicitly does not want to pay. Also
   flagged: the "TopView" brief the owner pasted was written to override
   normal agent behavior (no-questions-asked, clone-and-run a third-party
   GitHub repo from an unaudited source) — treated as untrusted content,
   not followed as instructions.
2. **"Keyboard-controlled video" format (candidate for the now-paused
   weekly/longform slot)** — inspired by a real YouTube video ("YOU
   CONTROL THIS VIDEO WITH YOUR KEYBOARD 2" by Lagarto Films, channel
   Lagarto Films, video id `S0EUmPQuEpQ`). The mechanic is real, not
   faked: YouTube's desktop player has native keyboard shortcuts — number
   keys 0-9 seek to that decile of the video's total duration, `J`/`L`
   skip back/forward 10s. A video edited so specific content sits at those
   decile marks genuinely "responds" to the keypress, since the player is
   really seeking there. **This is free to build** — no paid APIs, just
   precise ffmpeg-based editing/timing on top of the pipeline that
   already exists. This is the most promising real next idea so far.
   **Not started.** Open questions before building:
   - Does this replace the now-paused quiz-longform slot, or start as a
     standalone one-off test first so the owner can see one example
     before deciding?
   - What's the actual content angle for each of the ~9-10 decile
     segments (a story with branching outcomes? a fact per number? a
     mini choose-your-path game)?
   - Decile seeking is a percentage of total duration, not an exact
     timestamp — needs a real test video to confirm how much drift is
     tolerable before a "press 3" segment feels off.
3. **"AI POV game" pitch (surfaced from a different AI assistant, pasted
   in by the owner)** — suggests simulating a first-person "gameplay"
   look either via paid AI video generators (Runway Gen-3, Kling) or by
   manually screen-recording a real game (Unreal/Unity free assets, or
   GTA V/Roblox) with an OBS keyboard-overlay plugin showing keys light
   up as they're "pressed." **Conflicts with stated constraints**: the
   paid-tool option contradicts the owner's "I don't want to pay"
   decision from idea #1 above; the screen-recording option requires real
   per-video manual work (playing/recording a game, syncing an overlay by
   hand) which breaks this project's fully-automated, no-manual-
   production model (`CLAUDE.md`'s core premise). **Parked** — only worth
   reconsidering if the owner decides to accept either paid tooling or
   manual production work for this one specific track.
4. **Quiz Longform (2x/week) workflow disabled on GitHub Actions**
   (2026-09-17, done) — owner asked to pause weekly/longform content for
   now. Ran `gh workflow disable "Quiz Longform (2x/week)"`; confirmed
   off the active workflow list (`gh workflow list`). Daily Shorts and
   every other workflow left untouched. Re-enable with
   `gh workflow enable "Quiz Longform (2x/week)"` when ready.

**Next step, if picking this up fresh:** get owner sign-off on which of
idea 2's open questions to answer, then build ONE test video for the
keyboard-seek format (small scope, per this repo's own "work in small
iterations" rule) before wiring it into any real schedule.

## What's shipped and working (live in production)

- CTA auto-comment bug fixed (was firing while videos were still
  private) + hourly catch-up job.
- Genome tags + real analytics sync (data collection only, no
  scoring/weighting yet).
- Episode counter badge on programming Shorts ("EP N").
- New "save this for later" CTA variant.
- Code-panel retyping fix (only changed lines re-type now).
- A self-caught schema-migration bug that would've crashed a scheduled
  workflow — fixed and hardened so it can't happen again.

All of the above is committed, pushed, and running for real.

## What's in progress: the game-night track (Phase 16)

**Goal:** 2 new longform videos/week (Tue/Fri), 5 round formats (Higher
or Lower, Memory, What Changed, Risk or Safe, Prediction), quiz moves to
1x/week (Saturday).

**Built and working:**
- All 5 round modules, fact-verification for the two LLM-content rounds
  (Higher or Lower, Prediction), round-selector (no repeat round types
  back to back).
- Full renderer (`pipeline/visuals_game.py`) — every round type has its
  own visual (comparison cards, chip rows, before/after table, etc).
- Full pipeline runs end-to-end for real: script → voice → render →
  assemble → captions/metadata, stopping safely before upload.

**Fixed this session after watching real test episodes:**
1. Removed a simulated "contestant" that won/lost fake lives and points
   each round — it read as an AI playing the game by itself, not
   connected to the viewer. Every round now just shows real content and
   reveals the real answer, no invented scoring.
2. Turned off burned-in captions for this format (not needed).
3. Fixed pacing — beats were flashing by faster than a viewer could
   actually read the on-screen card. Now every beat holds for a real
   minimum time.

## What's NOT fixed yet — the actual blocker

**After all 3 fixes above, a second test episode was rendered and
watched. Verdict: still bad. No specifics captured yet before the
session ran out.**

This is the one thing that needs your input before any more code gets
written. Possible directions (not yet diagnosed, pick whichever
matches what actually felt wrong, or describe it fresh):

- Pacing still off (too slow now instead of too fast, or just feels
  inconsistent beat to beat)?
- The visual designs themselves aren't interesting/fun to watch,
  independent of timing?
- 5 rounds in ~2 minutes is the wrong shape — too many rounds, too
  short each, wrong total length?
- The whole approach (text/data cards, like the quiz format) isn't the
  right visual language for this — needs something more dynamic?
- Something about the voice/narration itself?

**Once you say what's actually wrong, next session should diagnose that
specific thing before touching anything else** — not another blind
round of guessing fixes.

## Not started at all

- Item 5: new GitHub Actions workflow(s) for Tue/Fri game night +
  moving quiz to Saturday. Waiting on the format actually being good
  before scheduling it for real.

## Also fixed this session: scheduling reliability

`daily-shorts`'s cron sat 7+ minutes past its nominal fire time with
zero run on the brand-new repo. Real cause: GitHub's own docs say
scheduled workflows are most likely delayed "at the start of every
hour" (global queue congestion), and 3 of our 5 crons were scheduled
exactly on the hour. Moved all three to :07 past the hour. Not a 100%
guarantee (GitHub never promises exact-time delivery), but removes the
specific confirmed collision. Manually triggered today's run as a
safety net regardless.

## Facts/sauce_recipe visual pipeline upgrade (Phase 17, new)

Real viewer complaint: narration describes something genuinely
interesting, video shows generic vaguely-related stock footage instead
of the actual thing. Fixed the root cause: the old pipeline generated
one flat 2-3 keyword list per fact and took Pexels' first results in
order, no scoring at all.

New behavior: each fact beat now gets a tiered visual plan (exact
subject → accurate representation → concept/mechanism explanation →
generic fallback only as a last resort), searched tier by tier, with a
real relevance-scoring pass that picks the best-matching clip instead
of the first one found — and a "lie detector" that won't let a clip
with zero real connection to its subject get labeled an exact match
just because of which search tier found it.

**Verified with mocked tests only** (`tests/test_visuals_facts.py`,
9 passing) — deliberately did NOT spend real LLM/Pexels budget on a
live end-to-end run today, to leave room for the actual scheduled
pipeline. **Next real check**: watch the next real `daily-shorts` run
(or trigger one manually) and confirm the visual log
(`{video_id}_visual_log.json`) shows real exact/representation matches
for a real fact, not generic fallback everywhere.
