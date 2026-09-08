# Faceless YouTube Shorts Automation — Spec

## What this is

An automated pipeline that produces YouTube Shorts across two content
templates and uploads them on a schedule, aiming for 5 videos/day once
proven out. Everything runs on the owner's own hardware (laptop with an
RTX 4060) plus free-tier services. No paid APIs, no n8n, no heavy
AI frameworks (no LangChain/CrewAI equivalents).

Content templates:
1. **Programming** — a short code-focused tip, gotcha, or "why this works"
   explanation, illustrated with an animated code render.
2. **Facts** — a genuinely interesting fact with a point of view or hook,
   not a generic listicle line, illustrated with stock or AI-generated
   visuals.

## Non-negotiable constraints

- **Cost**: $0 marginal cost per video. Every tool choice below is local
  or free-tier for a reason — don't swap in a paid API without discussing
  it first.
- **Originality over templating**: YouTube's "inauthentic content" policy
  demonetizes videos that look interchangeable or template-generated with
  no real creative input. Every script MUST include one genuine
  hook/opinion/gotcha that isn't just filling in a fact — see
  `config/prompts/`.
- **Resumable**: the pipeline must survive being killed mid-run. State
  lives in SQLite (see Data model), and re-running the orchestrator picks
  up unfinished videos instead of starting over.
- **Human review gate**: for at least the first several weeks, a rendered
  video should NOT auto-publish. It lands in a review queue and a human
  (the owner) approves or rejects it before upload. This is a config flag
  (`REQUIRE_REVIEW=true`), not a hardcoded behavior — it should be easy to
  flip off later.

## Architecture — three stages

```
Plan & script  ->  Voice & video  ->  Publish
```

### Stage 1: Plan & script (`pipeline/plan.py`)
- Input: a template name (`programming` | `facts`).
- Picks or generates a topic (avoid repeating recent topics — check state DB).
- Generates a script (~110-145 words, ~40-55 seconds spoken) using the
  matching prompt template in `config/prompts/`. (Empirically, edge_tts
  paces close to ~2.6 words/sec — aim for the lower half of this range
  if targeting comfortably under 55s.)
- Output: `script_text` (narration only — prose, no literal code syntax
  or symbols, since TTS mispronounces things like `cart=[]`) + a short
  `hook` field (used later for the title) + for the **programming**
  template only, a separate `code_snippet` field holding the actual
  code to visualize. `script_text` should describe the code in words
  ("an empty list assigned as a default argument..."); `code_snippet`
  is the literal code Phase 3a renders. These are deliberately separate
  so narration stays natural while the visual still shows real code.
- LLM backend is pluggable:
  - **Primary**: Claude Code CLI in headless mode (`claude -p "<prompt>"`),
    using the owner's existing Claude Pro subscription. Low volume
    (5-10 calls/day) so it won't meaningfully touch Pro's usage window.
  - **Fallback / zero-shared-quota option**: local Ollama model
    (`qwen2.5:7b-instruct` or `llama3.1:8b-instruct`), called via
    Ollama's local HTTP API (`http://localhost:11434`).
  - Backend selection via `LLM_BACKEND` env var (`claude_code` | `ollama`).

### Stage 2: Voice & video (`pipeline/voice.py`, `visuals_code.py`,
`visuals_facts.py`, `assemble.py`, `captions.py`)
- **Voice**: TTS the script.
  - Primary: Kokoro (local, GPU-accelerated via the RTX 4060).
  - Fallback: `edge-tts` (free cloud TTS, no API key, zero local setup).
  - Backend selection via `TTS_BACKEND` env var.
- **Visuals — programming template**: render a syntax-highlighted,
  animated "typing" effect for the code snippet using `pygments` for
  highlighting + Pillow for frame rendering (or Manim if richer
  animation is needed). Fully local, no external calls.
- **Visuals — facts template**: source background footage/images from
  Pexels or Pixabay's free APIs using keywords extracted from the script,
  OR generate an image via Pollinations.ai's free image API, OR run a
  local SDXL-Turbo pass if the owner wants fully original visuals.
  Configurable via `FACTS_VISUAL_SOURCE` env var (`stock` | `pollinations`
  | `local_sd`).
- **Assembly**: combine voice track + visuals into a raw vertical
  (1080x1920) video with `ffmpeg`/`moviepy`. Add background music bed
  (royalty-free, stored in `assets/music/`) at low volume.
- **Subscribe/share CTA**: every video gets a brief animated overlay
  prompting the viewer to subscribe/follow, added during this stage.
  Rendered with Pillow (same approach as the Phase 3a code renderer, no
  new dependency) — simple text + icon badge, fades in around 80%
  through the video, holds ~2-3 seconds, fades out. Position it in the
  upper third of the frame, since captions (Phase 5) occupy the
  lower/middle safe zone — the two must not visually overlap. One
  reusable asset/template is fine; it doesn't need to vary per video.
- **Captions**: run `faster-whisper` locally on the voice track to get
  word-level timestamps, then burn in styled captions during assembly
  (or as a second ffmpeg pass).

### Stage 3: Publish (`pipeline/metadata.py`, `upload.py`)
- Generate title, description, and tags from the script + hook (LLM call,
  same backend as Stage 1).
- If `REQUIRE_REVIEW=true`: mark state as `awaiting_review` and stop.
  A separate small CLI (`scripts/review.py`) lets the owner list pending
  videos, watch them, and mark `approved`/`rejected`.
- Upload approved videos via the YouTube Data API v3
  (`google-api-python-client`, OAuth2 with a stored refresh token).
  Include appropriate title/description/tags; mark disclosure of
  AI-generated content per YouTube's synthetic media policy if the
  visuals are AI-generated.

## Data model

SQLite, one table, `videos`:

| column           | type    | notes                                          |
|------------------|---------|------------------------------------------------|
| id               | TEXT PK | uuid                                           |
| template         | TEXT    | `programming` \| `facts`                       |
| status           | TEXT    | see status flow below                          |
| topic            | TEXT    |                                                 |
| script_text      | TEXT    | narration only, no literal code/symbols        |
| code_snippet     | TEXT    | programming template only; literal code for the visual |
| hook             | TEXT    |                                                 |
| audio_path       | TEXT    |                                                 |
| video_path       | TEXT    | raw, before captions                           |
| final_path       | TEXT    | after caption burn-in                          |
| title            | TEXT    |                                                 |
| description      | TEXT    |                                                 |
| tags             | TEXT    | comma-separated                                |
| youtube_video_id | TEXT    | set after successful upload                    |
| error_message    | TEXT    | last error, if any                             |
| created_at       | TEXT    | ISO timestamp                                  |
| updated_at       | TEXT    | ISO timestamp                                  |

Status flow: `planned -> scripted -> voiced -> visuals_ready -> assembled ->
captioned -> metadata_ready -> awaiting_review -> approved -> uploaded`
(or `failed` from any stage, with `error_message` set).

## Folder structure

```
faceless-shorts/
  config/
    .env.example
    prompts/
      programming_template.txt
      facts_template.txt
  pipeline/
    __init__.py
    state.py          # SQLite read/write helpers
    plan.py
    voice.py
    visuals_code.py
    visuals_facts.py
    assemble.py
    captions.py
    metadata.py
    upload.py
    orchestrator.py   # runs N videos/day across both templates
  assets/
    fonts/
    music/
    output/
  scripts/
    run_daily.py       # cron entrypoint
    review.py          # CLI to approve/reject pending videos
  tests/
  CLAUDE.md
  SPEC.md
  ROADMAP.md
  README.md
```

## Scheduling & execution

No orchestration platform (no n8n). The full pipeline runs inside a
single GitHub Actions workflow (`.github/workflows/daily-shorts.yml`),
triggered on a cron schedule, calling `scripts/run_daily.py` end to end
— script generation through upload — in one job. This removes any
dependency on the laptop being on.

Because Actions runners have no GPU, the CI defaults are:
- `LLM_BACKEND=claude_code` — via the Claude Code CLI authenticated
  with a `CLAUDE_CODE_OAUTH_TOKEN` secret (from `claude setup-token`),
  which draws on the owner's existing Pro subscription rather than
  billing per API token.
- `TTS_BACKEND=edge_tts` (Kokoro stays available for local/laptop runs
  only, where the GPU is present).
- `FACTS_VISUAL_SOURCE=stock` or `pollinations` (not local SD).

**State persistence**: the runner's filesystem is ephemeral, so
`state.db` is committed back to the repo at the end of each run (small
SQLite file, `[skip ci]` on the commit message to avoid re-triggering).
Rendered audio/video files are deleted after a successful upload rather
than committed, to keep repo size in check.

**Review, in the CI context**: rather than the interactive
`scripts/review.py` queue, videos upload with `UPLOAD_VISIBILITY=private`
while `REQUIRE_REVIEW=true`. The owner reviews and flips them public
from YouTube Studio directly. Once the channel has a track record,
switching `UPLOAD_VISIBILITY` to `public` fully automates publishing.

If 24/7 execution independent of GitHub-hosted runner minutes is ever
needed (unlikely at 5 videos/day), the same workflow can move to a
self-hosted runner later — not part of the initial build.

## Out of scope for v1

- Multi-channel support
- Analytics dashboard
- Auto-A/B testing of hooks/thumbnails
- Fully unattended publishing (the review gate stays on until explicitly
  turned off)
