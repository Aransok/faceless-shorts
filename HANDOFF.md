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
   **Not started.** Content angle chosen by the owner (2026-09-17): a
   narrated fantasy "choose your path" story, text narration + simple
   visuals. **Confirmed by the owner**: "WoW" was only a genre/tone
   reference (epic fantasy), not a request to use actual World of
   Warcraft IP — flagged that Blizzard's trademarked names/lore/
   characters would be a real legal risk on a monetized channel, owner's
   own follow-up confirmed an ORIGINAL fantasy setting (own world name,
   own factions) is what's wanted, not licensed IP. Mechanically: TTS
   narration + simple styled story cards (same Pillow-based rendering
   approach already used by `game_night`/`quiz_longform`), branch points
   where the viewer
   presses 1/2/3 and the real YouTube decile-seek lands them on that
   path. Still open before building:
   - **Rollout, decided (2026-09-18): standalone test video first.** One
     test episode, no schedule change yet — owner sees a real example
     before deciding whether this replaces the paused quiz-longform
     slot.
   - Branch structure: how many decision points, how many endings, is it
     a single linear-with-detours story or a real branching tree (a real
     tree needs many more segments/keyframes than 9-10 decile slots can
     hold cleanly — likely needs to stay a single main path with a
     handful of "press to see a bonus/alternate beat" detours, not a
     full RPG-style branching narrative).
   - **World/setting, decided (2026-09-18): "Veylorn: The Sundering."**
     An ancient empire shattered decades ago in a magical cataclysm
     ("the Sundering"); three factions fill the vacuum:
     - **The Ashcrown Wardens** — disciplined remnants of the old
       empire's army, want to restore central rule.
     - **The Wildkin Clans** — free tribes and nature-magic
       practitioners who see the empire's fall as a chance for
       something freer, distrust the Wardens.
     - **The Hollow Choir** — secretive scholars investigating what
       actually caused the Sundering, morally ambiguous.
     Protagonist: an unnamed Wanderer/Envoy who moves between the three
     factions episode to episode — this is what makes "choices are
     in-episode flavor only" work: the Wanderer's overall arc is fixed
     by the story bible, viewer keypresses only flavor how THIS
     episode's encounter plays out. Tone: dark-but-hopeful epic
     fantasy, plain invented terms throughout.
     Naming check done deliberately: an early draft used "Legion" and
     "Covenant" for two factions — both are real, specific World of
     Warcraft proper nouns (the Burning Legion / *Legion* expansion;
     the four *Shadowlands* Covenants), not generic fantasy words in
     this context, and a real monetization/copyright risk on a
     monetized channel — renamed to Wardens/Clans before locking this
     in. Same scrutiny applies to any future faction/place/item name
     added to this setting — check against actual WoW (or other major
     franchise) proper nouns specifically, not just "does it sound
     fantasy-ish."
   - Decile seeking is a percentage of total duration, not an exact
     timestamp — needs a real test video to confirm how much drift is
     tolerable before a "press 3" segment feels off.
   - **Visual source, decided (2026-09-17): Pollinations.ai**
     (`image.pollinations.ai`, https://github.com/pollinations/pollinations)
     for the story's visuals instead of plain text cards or Pexels stock.
     Genuinely free, no API key, no signup, open-source, generates images
     from a plain URL (works with `requests`, already an allowed
     dependency — no new infra). Uses the Flux model, well-suited to
     fantasy-art prompts (dragons, throne rooms, forests) in a way Pexels'
     real-photo stock never could be for an original fantasy setting.
     Rate limit for anonymous use is roughly 1 request/15s — fine at this
     pipeline's per-video image volume. Plan: one generated image per
     story beat, prompted from that beat's own scene description, same
     shape as `visuals_facts.py`'s one-visual-per-fact-beat pattern.
     Pexels stays available as a fallback only if a genuinely photoreal
     (non-illustrated) shot is ever wanted. Not yet integrated into any
     code — next session's actual build step.
   - **Series continuity, decided (2026-09-17):** this is meant to be an
     ongoing series across many videos, not one-off standalone stories —
     owner wants a consistent big-picture storyline that carries forward
     episode to episode. Resolved design questions:
     - **Viewer choices are in-episode flavor only** (owner's explicit
       pick over the branching-canon alternative) — the main storyline
       advances the same way regardless of which path a viewer picks;
       keyboard choices change bonus/detour beats within that one
       episode, never what the next episode covers. Keeps this from
       becoming a combinatorial branching-state problem over a long
       series.
     - **A persistent "story bible"** carries the actual continuity: world
       name, factions, main characters, the planned arc, and a running
       summary of what's happened so far. Reuses this pipeline's existing
       pattern (`recent_topics()`/`recent_facts()` in `pipeline/state.py`
       already read prior state into a generation prompt) — same idea,
       new use: a new `state.db` table holds the current arc/character/
       world summary, read into every new episode's generation prompt for
       consistency, then appended to after that episode is planned so the
       next one has the up-to-date state. Not yet designed at the schema
       level or built — next session's job, alongside the Pollinations
       integration above.
3. **"AI POV game" pitch (surfaced from a different AI assistant, pasted
   in by the owner)** — suggested simulating a first-person "gameplay"
   look either via paid AI video generators (Runway Gen-3, Kling) or by
   manually screen-recording a real game (Unreal/Unity free assets, or
   GTA V/Roblox) with an OBS keyboard-overlay plugin showing keys light
   up as they're "pressed." **Rejected by the owner (2026-09-17)** — paid
   tooling contradicts the "I don't want to pay" decision from idea #1
   above, and manual screen-recording breaks this project's fully-
   automated, no-manual-production model (`CLAUDE.md`'s core premise).
   Not being pursued; only the free keyboard-overlay-animation piece
   (drawable with Pillow, no recording needed, since the pipeline already
   knows the script/timing) is worth reusing, folded into idea 2 above.
4. **Quiz Longform (2x/week) workflow disabled on GitHub Actions**
   (2026-09-17, done) — owner asked to pause weekly/longform content for
   now. Ran `gh workflow disable "Quiz Longform (2x/week)"`; confirmed
   off the active workflow list (`gh workflow list`). Daily Shorts and
   every other workflow left untouched. Re-enable with
   `gh workflow enable "Quiz Longform (2x/week)"` when ready.

**Next step, if picking this up fresh:** get owner sign-off on (a) the
original-fantasy-setting-vs-WoW-IP question and (b) idea 2's other open
questions above, then build ONE test video for the keyboard-seek fantasy
story format (small scope, per this repo's own "work in small
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
