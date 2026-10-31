# Style lab

A test tool, not part of the daily pipeline. It renders the same Short
in three looks so the owner can pick one (2026-10-31): A "Punch",
B "Premium", C "Case File". Topic: the 1986 Lake Nyos disaster.

## Run it (about 6 minutes on 4 cores)

    python scripts/style_lab/fetch_assets.py /tmp/lab        # photos, fonts, music
    python scripts/style_lab/voice_lab.py /tmp/lab/voice     # edge-tts + word timings
    python scripts/style_lab/render_lab.py /tmp/lab output   # -> output/test_A/B/C.mp4

Render single frames instead of a video: `render_lab.py /tmp/lab out C t=0 t=12.5`.

## How it works

- `voice_lab.py`: one edge_tts call per sentence. WordBoundary events
  give exact word times; sentences are trimmed and joined with a
  per-style gap.
- `render_lab.py`: Pillow composes every 1080x1920 frame (Ken Burns on
  photos, the animated `LakeDiagram`, captions from the word times,
  overlays). Frames go to ffmpeg as raw RGB. Audio is voice + music
  (ducked with sidechaincompress) + synthesized SFX, normalized to
  -14 LUFS.
- `sfx.py`: whoosh, boom, pop, riser, shutter, typewriter key, stamp and
  swell, all made with numpy (no samples, no licenses).

## Asset licenses (credit these in the video description)

- Photos, Wikimedia Commons: USGS/NASA public domain (lake1986,
  lake1992, lake2001, landsat, vent, cow, timeline), CC0 (nyoslake),
  and "Hills and farm land, Njap" (CC BY-SA 4.0: credit its author).
- Music: Kevin MacLeod (incompetech.com), CC BY 4.0. "Volatile Reaction"
  (A), "Echoes of Time" (B), "Darkest Child" (C). Required credit line:
  `Music: "<title>" by Kevin MacLeod (incompetech.com), licensed under CC BY 4.0`.
- Fonts: Google Fonts, SIL Open Font License.

## Sandbox notes

- edge_tts pins certifi's CA bundle. Behind a TLS-inspecting proxy, point
  certifi at the proxy CA in the calling process only. CI doesn't need this.
- Wikimedia returns 429 to bursts from shared IPs. The fetcher spaces
  requests and backs off; send a descriptive User-Agent.
