# Project instructions for Claude Code

This is `faceless-shorts`, an automation pipeline described in full in
`SPEC.md`. Read `SPEC.md` and `ROADMAP.md` before starting any work.
Build in the phase order given in `ROADMAP.md` — don't jump ahead to a
later phase before the current one is working and tested.

## Hard rules

- **Pure Python, standard tooling only.** No LangChain, CrewAI,
  Haystack, or similar orchestration frameworks. No n8n or other
  workflow-automation platforms — this pipeline is plain function calls
  chained together by `pipeline/orchestrator.py`.
- **No paid APIs by default.** Every external service used must have a
  free tier or be self-hosted/local. If a task seems to need a paid
  service, stop and ask rather than wiring it in.
- **Every pipeline stage is a plain function** that takes a `video_id`,
  reads what it needs from the state DB, does its work, and writes the
  result + new status back to the state DB. No stage should assume the
  previous stage just ran in the same process — always reload from state.
- **Fail soft, not hard.** Wrap each stage's body in try/except. On
  failure, set `status = 'failed'` and `error_message` in the state DB,
  log it, and move on to the next video rather than crashing the whole
  daily run.
- **Secrets** live in `.env` (never committed, never hardcoded). Use
  `python-dotenv`. `config/.env.example` documents every required key
  with a placeholder value.
- **Type hints on all function signatures.** Use `pathlib.Path` for file
  paths, not raw strings.

## Allowed dependencies (add more only if genuinely needed)

`ffmpeg-python` or `moviepy`, `faster-whisper`, `google-api-python-client`
+ `google-auth-oauthlib`, `pygments`, `Pillow`, `python-dotenv`, `requests`,
`sqlite3` (stdlib). TTS/LLM client libraries as needed for the chosen
backends in `SPEC.md`.

## How to run things while building

- Full daily run: `python scripts/run_daily.py --count 5`
- Single stage in isolation, for testing: each module in `pipeline/`
  should have a `if __name__ == "__main__":` block that runs it against
  one sample input and prints the result, so a stage can be verified
  without running the whole pipeline.
- Review queue: `python scripts/review.py list` / `approve <id>` /
  `reject <id>`

## Testing

Write tests for pure logic — prompt construction, filename generation,
state transitions, quota/backoff math. Don't write tests that make real
network/API calls or invoke local models; mock those boundaries.

## When something in SPEC.md is ambiguous

Ask before guessing, especially around: which TTS/visual backend to
default to, what the review-queue CLI should look like, and anything
touching the YouTube upload/OAuth flow (getting this wrong risks the
account, so confirm scopes and consent flow before writing that code).
