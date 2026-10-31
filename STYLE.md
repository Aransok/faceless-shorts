# STYLE.md: the "Case File" look

Owner-approved on 2026-10-31. This file is the contract for how every
`facts` and `sauce_recipe` Short looks, sounds and reads. Code follows
this file, not the other way round. **Do not change anything here
without the owner's explicit OK.** That applies to people and to AI
models (Sonnet included): fixing bugs is fine, changing the style is not.

Reference render: `scripts/style_lab/render_lab.py`, style `D` (A + C
mix). Rebuild it with the three commands in `scripts/style_lab/README.md`.
Pipeline code: `pipeline/casefile.py`, switched on by
`VISUAL_STYLE=casefile` in `.github/workflows/daily-shorts.yml`.

---

## 1. Format

- 1080x1920, 9:16, 30 fps, H.264, AAC 48 kHz.
- 20-30 seconds (55-75 spoken words). Never over 60 s.
- Built to loop: the last spoken words run straight into the first ones.

## 2. Script and hook rules

One subject per Short, told in exactly three beats (`FACT_1..3`):

1. **Payoff first.** Beat 1 opens with the single most surprising
   concrete claim (a real number, name or outcome) in the first words.
   No setup, no "did you know", no "imagine", no generic tease.
2. **The real why or how**, with one concrete detail and one honest
   opinion (the point of view is mandatory).
3. **The twist**, ending mid-thought on words that lead back into
   beat 1's first line when the video loops.

- 18-26 words per beat. Shorter is better.
- Facts must be real and checkable. If unsure about a number, pick a
  different subject.
- **No spoken CTA** in `facts`/`sauce_recipe` (it would break the loop).
- **No seasonal or holiday tie-ins** (Halloween had a median of 78 views).
- **Do:** "This lake killed 1,746 people in a single night, and not one
  of them drowned." ... "and every local knows exactly why"
- **Don't:** "Here are three crazy facts." / "Scientists can't explain
  this." / "Follow for more!" / three loosely related items in one video.

### Topic angles

- `facts`: one bizarre real thing from nature, science or history that
  carries a number: disasters with a strange cause, animals that
  shouldn't exist, objects with an unbelievable story, history that
  sounds made up. Skip the famous ones everyone has seen (honey never
  spoils, octopus hearts, bananas are berries, immortal jellyfish).
- `sauce_recipe`: one sauce with a "wait, that's how?" angle: the step
  everyone gets wrong, an ingredient that sounds wrong but works, a
  restaurant trick that takes two minutes.

## 3. On-screen text (the case-file layer)

The model writes these as extra lines after the normal fields. The code
validates them, and a bad or missing line just hides that element (it
never fails the video).

| Field | Limit | Example |
|---|---|---|
| `CASE_HEADER` | 2-5 words, max 32 chars | `LAKE NYOS, CAMEROON` / `TOUM` |
| `CASE_DATE` | a real date or year, max 12 chars, or `none` | `21.08.1986` |
| `STAMP` | 1-2 words, max 14 chars, or `none` | `NOT DROWNED` / `NO EGG` |
| `TAG_1..3` | one number or word from that beat, max 7 chars | `1,746`, `CO2`, `25 KM`, `2 MIN` |
| `TAG_LABEL_1..3` | 2-5 words, max 26 chars | `DEAD IN ONE NIGHT` |

Tags and labels only restate facts that are already in the script. They
never add new claims.

### Layout, top to bottom (y in pixels on the 1920-tall frame)

| Element | Exact spec |
|---|---|
| Top gradient | black, 780 px tall, alpha 235 at the top fading to 0 |
| Header | Special Elite 36 px, `#ECE6D6`, baseline row centered at y=132, 70 px side margins. Left: `CASE FILE  ·  {CASE_HEADER}` (`RECIPE FILE` for sauce). Right: `{CASE_DATE}` with a 20 px red (`#FF3B30`) dot blinking at 6 rad/s (alpha 120-255) |
| Tag (big word) | Anton 250 px, 6 px black stroke, shadow (0, 8) blur 14 alpha 190, centered at y=400. Beat 1 red `#FF3B30`, beat 2 yellow `#FFE14D`, beat 3 white. Enters with a scale pop 1.3 to 1.0 (ease-out-back, 0.18 s) and a 0.15 s fade |
| Tag label | Montserrat ExtraBold 44 px, white at 94%, +3 px tracking, soft shadow, centered at y=575. Types on left to right at 0.022 s per character |
| Evidence Polaroid (real photos only) | centered at y=1005, see section 4 |
| Stamp | Anton 118 px, `#D62626`, 10 px rounded border, distressed edges, rotated 13 degrees, at (W/2+110, 1095). Slams 1.8 to 1.0 in 0.12 s at beat 1's last word, gone when beat 2 starts |
| Captions | see below, centered at y=1460 |
| Bottom gradient + vignette | black 760 px, alpha 0 to 200; soft radial vignette |

Frame 0 must already show the header, beat 1's tag and its label, fully
drawn with no fade-in. That frame is what a viewer sees before deciding
to stay.

### Captions

- Montserrat Black 112 px, ALL CAPS, white; the word being spoken is
  yellow `#FFE14D`. Black stroke 12 px, shadow (0, 9) blur 10 alpha 190.
- 1-2 words per card (max 13 characters). Numbers and the beat's tag
  word get a card of their own at 140 px, all yellow.
- A new card pops in: scale 0.72 to 1.0, ease-out-back, 0.15 s. Hold
  0.25 s after the last word.
- No captions in the last 0.45 s (the loop seam).
- Max width 900 px, so captions never sit under the right-side buttons.

### On-screen subscribe badge

- No spoken CTA. One paper strip: Special Elite 34 px, dark text on
  `#ECE6D6`, rotated -2 degrees, centered at y=900.
- Text: `SUBSCRIBE FOR MORE CASES` (facts) or `SUBSCRIBE FOR MORE
  SAUCES` (sauce). Never the word "follow".
- Shown from 55% of the duration for 2.2 s, with 0.25 s fades.

### Safe zones (Shorts app UI covers these)

- Top 0-100: back/search icons. Only the header sits near it.
- Bottom 1540-1920: title, channel, music line. Nothing important there.
- Right x 930-1080 between y 900-1700: like/comment/share buttons.

## 4. Visuals

- **Full-bleed moving footage** (Pexels stock) fills the frame. A new
  clip about every 2.5 s.
- **Snap zoom on every cut:** the new shot starts at 1.14x and settles
  to 1.0x in 0.2 s (ease-out).
- **Framing cut:** any clip on screen longer than 2.4 s gets a punch-in
  at its midpoint (1.18x, slightly off-center). So something changes on
  screen every 1.2-2.5 s.
- **White flash** (alpha 200 to 0 in 0.12 s) at the start of beats 2
  and 3.
- **Shake** (24-30 px, decaying over 0.35 s) at 0 s and when the stamp
  lands.
- **Real photos** come from Wikimedia Commons, public domain or CC0
  only, at most 3 per video, 2.0 s each. They are always shown as
  **evidence Polaroids**, never stretched full screen:
  - photo 700x540 inside a `#ECE6D6` paper frame (26 px border, 92 px
    bottom strip)
  - Special Elite 30 px label `EXHIBIT  ·  {SUBJECT}` in the strip
  - a translucent tape strip on top, rotated 1.5-2.5 degrees, with a
    soft shadow
  - backdrop: a blurred copy of the same photo at 36% brightness
  - slams in over 0.2 s (scale 1.28 to 1.0 while the extra tilt
    settles)
- **No AI-generated images. No stock "talking head". No gameplay.** The
  animated diagrams in the style lab are for one-off specials, not the
  daily pipeline.

## 5. Sound

- **Voice:** edge-tts `en-US-AndrewMultilingualNeural`, rate `+10%`,
  normal pitch. 0.3 s pause between beats.
- **Music:**
  - `facts`: the dark tension bed in `assets/music/casefile/`
    ("Darkest Child", Kevin MacLeod, CC BY 4.0), starting at a
    different offset per video so no two Shorts share the same
    opening bars
  - `sauce_recipe`: the existing bed in `assets/music/`
  - continuous under the voice, about 15 dB below the narration's mean
    loudness
  - any CC BY track adds its credit line to the description
    automatically
- **Sound effects: none.** No whoosh, boom, pop, riser, typing, shutter
  or stamp sound. Not on cuts, not on text. (The owner asked twice: "no
  noise there", "the dumb sound is still there and annoys me so much".)
- Final mix normalized for Shorts (around -14 LUFS, peaks under -1 dBFS).

## 6. Do / Don't summary

| Do | Don't |
|---|---|
| One wild subject, payoff in the first words | Lists, "3 facts", seasonal tie-ins |
| A real number as the big tag on frame 0 | A tag the script never says |
| Real PD/CC0 photos as evidence Polaroids | Low-res photos blown up full screen, AI images |
| A visual change every 1.2-2.5 s | A shot held for 5+ s |
| Silent cuts, dark music bed | Any sound effect |
| Loop the last words into the first | "Follow for more", a spoken CTA, a wrap-up |

## 7. Changing this style

Only the owner changes this file. To try a variation, render it in
`scripts/style_lab/` first, show the owner, and only then update this
file and `pipeline/casefile.py` together, in one commit.
