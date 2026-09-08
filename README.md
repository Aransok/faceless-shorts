# faceless-shorts

Automated pipeline that produces and uploads YouTube Shorts across two
content templates (programming tips, facts). See [SPEC.md](SPEC.md) for
the full design, [ROADMAP.md](ROADMAP.md) for build phases, and
[CLAUDE.md](CLAUDE.md) for the rules governing how this project gets
built.

## Local setup

Besides `pip install -r requirements.txt`, two system-level tools aren't
pip-installable and must be present on PATH:
- **ffmpeg** (encodes the frame sequences into video; already handled in
  CI via `apt-get install ffmpeg` — for local Windows dev, `winget install
  Gyan.FFmpeg`)
- **claude** CLI, logged in (`npm install -g @anthropic-ai/claude-code`,
  then `claude login`) — only needed when `LLM_BACKEND=claude_code`.

Status: Phase 3a (programming visuals) in progress.
