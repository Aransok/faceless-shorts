# Session handoff — game-night track

Quick-reference status for picking this back up from any device. Full
engineering detail lives in `ROADMAP.md` Phase 15/16 — this file is the
short version.

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
