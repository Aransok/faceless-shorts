# BiteBits Family Game Night — Long-Form Automated Video Format

**Status:** Spec accepted 2026-09-10. Supersedes further work on the
Shorts-length `game_night` track from ROADMAP.md Phase 16 (which stays
explicitly blocked — see that phase's note — real feedback was "too
fast" and "still bad" after two fix passes with no further specifics).
This is not a continuation of that blocked work; it's a different
delivery format (10-20 minute long-form) built on the same underlying
game-mechanic infrastructure, which was never what the owner's feedback
called "bad" — the *pacing/format* was. See ROADMAP.md's Phase 21 entry
for the current build status, what already exists vs. what's new, and
the phase-by-phase plan.

---

You are working inside the existing BiteBits automated faceless YouTube pipeline.

Your task is to design and implement a new long-form content format for the project:

# FAMILY GAME NIGHT

This is NOT simply a quiz format.

This is NOT just Python Quiz with different questions.

This should become a reusable, highly automated long-form entertainment format built around multiple kinds of games that families, friends, couples, and groups can play together while watching the video.

The viewer should feel like the video is hosting a game night.

The video itself should act as the game host.

The system must be fully automated once implemented.

The desired end-to-end flow is:

```text
Game episode concept generated
        ↓
Games and rounds generated
        ↓
Answers and solutions validated
        ↓
Game pacing and timing planned
        ↓
Narration generated
        ↓
Voice generated automatically
        ↓
Visual scenes rendered automatically
        ↓
Countdowns and reveals rendered automatically
        ↓
Captions optionally rendered
        ↓
Music and sound effects added automatically
        ↓
Quality checks run automatically
        ↓
Video assembled automatically
        ↓
Metadata generated automatically
        ↓
Thumbnail generated automatically
        ↓
Scheduled upload
```

There must be no human manually creating rounds, editing scenes, choosing answers, animating game pieces, or assembling videos.

The human should be able to start the pipeline and receive a finished Family Game Night episode.

The system should be designed as a reusable framework, not a one-off script for a single video.

---

# 1. CORE PRODUCT VISION

The Family Game Night format should feel fundamentally different from BiteBits' existing Python Quiz videos.

The Python Quiz format is educational.

The Family Game Night format is entertainment.

The goal is not:

> "Answer a series of questions."

The goal is:

> "Put the video on a TV, gather people together, compete, laugh, argue over answers, and see who wins."

The viewer should be able to play with:

- family
- friends
- a partner
- children where appropriate
- parents
- siblings
- groups

The video must work without requiring a website, app, controller, or physical host.

The game mechanics must be understandable directly from the screen.

The viewer pauses only if they choose to.

The default experience should be:

```text
Video starts
        ↓
Host explains game
        ↓
Players answer out loud / mentally / write down answers
        ↓
Countdown happens
        ↓
Answer or result is revealed
        ↓
Players track their own score
        ↓
Next round begins
```

The system should be suitable for long-form YouTube and should prioritize watch time and replayability.

The format should have enough variety that a 10–20 minute episode does not feel like the same question repeated twenty times.

---

# 2. MOST IMPORTANT DESIGN RULE: THE VIDEO MUST GIVE PEOPLE TIME TO PLAY

A major problem in automated game generation is that the generator behaves as though it is playing against itself.

It may:

- reveal answers immediately
- explain too quickly
- move to the next round too fast
- generate a game that is interesting to read but impossible to play in real time
- give inconsistent countdown lengths
- generate narration during the thinking period
- accidentally solve the puzzle while the viewer is still supposed to solve it

This must NOT happen.

The Family Game Night system must explicitly distinguish between:

```text
HOST TIME
```

and:

```text
PLAYER TIME
```

During HOST TIME:

- narrator explains
- narrator introduces the challenge
- visuals may animate
- instructions appear

During PLAYER TIME:

- the viewer gets time to think
- the viewer gets time to discuss
- the viewer gets time to shout an answer
- the answer is NOT revealed
- the narrator should generally remain silent or use minimal non-spoiling encouragement
- the visual must clearly communicate that the game is still active

The generator must never treat the absence of narration as wasted time.

Thinking time is gameplay.

Silence is sometimes part of the game.

A countdown is gameplay.

The system must be designed around this principle.

---

# 3. CONTENT FORMAT

Each episode should contain multiple game mechanics.

Do not create an entire 15-minute video consisting only of trivia questions.

A typical episode should feel like:

```text
INTRO
        ↓
GAME 1
        ↓
GAME 2
        ↓
GAME 3
        ↓
SHORT SCORE BREAK / TRANSITION
        ↓
GAME 4
        ↓
GAME 5
        ↓
FINAL CHALLENGE
        ↓
ENDING / SCORE REVEAL
```

The exact number of games can vary.

The system should support episode durations approximately between:

```text
10 minutes
and
20 minutes
```

depending on the generated format.

Do not force every episode to the exact same duration.

The duration should come naturally from the number of rounds and required player time.

---

# 4. GAME TYPES TO SUPPORT

The framework must be modular.

A game is not just a question.

A game type is a reusable mechanic.

Each mechanic should have:

- generation logic
- validation logic
- rendering logic
- timing rules
- reveal logic
- scoring logic
- difficulty controls

The first implementation should support several fundamentally different game types.

Do not attempt to implement every possible party game.

Implement a strong foundation that can grow.

The initial recommended game types are below.

---

# GAME TYPE A — HIGHER OR LOWER

The player sees two values or two things.

They must guess which is:

- bigger
- smaller
- more expensive
- older
- faster
- longer
- more populated
- heavier
- more calories
- more searched
- etc.

Example:

```text
Which has more people?

CITY A
vs
CITY B
```

The player gets thinking time.

Then:

```text
3
2
1
```

The answer is revealed.

The system should support data-backed comparisons where practical.

The system must not hallucinate numerical facts.

If data is required:

- use validated sources already available to the pipeline
- use static datasets where practical
- validate before rendering
- reject uncertain facts

Do not invent numbers.

---

# GAME TYPE B — GUESS THE CONNECTION

Show several words, images, objects, concepts, or clues.

The player must identify what connects them.

Example conceptually:

```text
APPLE
AMAZON
ORANGE
BLACKBERRY
```

Possible answer:

```text
Technology companies / brands
```

The actual generated content must be logically valid.

The connection must not be vague enough that multiple unrelated answers are equally plausible.

The system must validate:

- all clues genuinely connect
- the intended answer is reasonably clear
- the connection is not based on obscure arbitrary logic
- the answer can be explained after reveal

Difficulty can vary by:

- obviousness
- number of clues
- abstraction level

The reveal should explain the connection.

---

# GAME TYPE C — WHAT DOESN'T BELONG?

Show a group of items.

One does not belong.

Example:

```text
DOG
CAT
HORSE
CAR
```

The viewer identifies:

```text
CAR
```

The generator must avoid ambiguous cases.

There must be a clear intended answer.

The answer should have a clear explanation.

The system should support:

- words
- icons
- images
- objects
- categories
- facts

Example:

```text
Mercury
Venus
Earth
Moon
```

The viewer identifies the item that does not belong.

The explanation should clarify the category.

---

# GAME TYPE D — SPOT THE DIFFERENCE / WHAT CHANGED?

Show a scene.

Give the viewer time to observe it.

Then:

- briefly hide the scene
- modify one or more elements
- show the changed scene

Ask:

```text
WHAT CHANGED?
```

This is especially suitable for procedural generation.

Do not depend on manually created images for every episode.

Build the scene using reusable assets.

Example scene assets:

- chair
- lamp
- plant
- book
- clock
- picture
- cup
- ball
- cat
- etc.

The procedural scene generator can:

1. choose a scene template
2. place several objects
3. save the initial state
4. alter one or more objects
5. render both states
6. reveal the answer

Possible changes:

- object removed
- object added
- object moved
- object color changed
- object size changed
- object rotated

The generator must store the exact change.

The answer must come from deterministic scene state, not LLM memory.

This game type is ideal for automation because the renderer already knows exactly what changed.

---

# GAME TYPE E — MEMORY CHALLENGE

Show several items.

Give the viewer time to memorize them.

Remove the items.

Ask a question.

Example:

```text
Remember these objects:

APPLE
KEY
UMBRELLA
CLOCK
BOOK
```

After the display disappears:

```text
WHICH ITEM WAS THIRD?
```

or:

```text
WHAT COLOR WAS THE UMBRELLA?
```

or:

```text
WHICH ITEM WAS NOT PRESENT?
```

The system must generate the question from the exact scene state.

Do not let the LLM invent the answer independently.

The deterministic game data should be the source of truth.

---

# GAME TYPE F — RIDDLE ROUND

Present a riddle.

The viewer gets a defined thinking period.

Then reveal the answer.

Riddles require strong validation.

The system must reject:

- riddles with multiple equally valid answers
- broken logic
- copied/near-copied protected text if sourcing externally
- hallucinated explanations
- culturally obscure references unless intentionally configured

The system should prefer short, understandable riddles.

The answer reveal should include a concise explanation.

Do not make every round a riddle.

This is one mechanic among several.

---

# GAME TYPE G — WOULD YOU RATHER / FAMILY VOTE

This is not necessarily scored.

The screen presents two options.

Example:

```text
WOULD YOU RATHER:

Always be 10 minutes late
OR
Always be 20 minutes early?
```

The family votes.

After a short period, the narrator can:

- reveal an interesting perspective
- reveal poll results if reliable data exists
- introduce the next round

This creates discussion and laughter.

This mechanic should not be overused.

It works well as a pacing break between more competitive games.

The system must avoid sensitive, dangerous, inappropriate, or highly divisive topics.

Keep it broadly family-friendly.

---

# GAME TYPE H — WHO / WHAT AM I?

Reveal clues gradually.

The viewer must identify:

- an object
- an animal
- a place
- a historical thing
- a fictional object where legally and editorially appropriate

Example:

```text
CLUE 1:
I can be found in many homes.

PLAYER TIME

CLUE 2:
I am usually opened and closed.

PLAYER TIME

CLUE 3:
I help separate one room from another.

ANSWER:
A DOOR
```

The system must ensure each clue is accurate.

The answer should become progressively easier.

The viewer should be able to guess before the final clue.

Scoring can reward earlier guesses.

For example:

```text
Guess after clue 1 = 3 points
Guess after clue 2 = 2 points
Guess after clue 3 = 1 point
```

---

# GAME TYPE I — RAPID FIRE FINAL ROUND

A short final sequence.

Fast pacing.

Several simple challenges.

Example:

```text
5 QUESTIONS
5 SECONDS EACH
```

or:

```text
NAME 3 THINGS IN 10 SECONDS
```

This should be the energetic ending.

Do not make it impossible.

The goal is excitement.

---

# 5. INITIAL IMPLEMENTATION SCOPE

Do not implement every game above if doing so would destabilize the pipeline.

Build the framework correctly.

For version one, prioritize:

1. Higher or Lower
2. Guess the Connection
3. Odd One Out
4. Spot the Difference / What Changed
5. Memory Challenge
6. Who / What Am I
7. Rapid Fire Final Round

Riddles and Would You Rather can be added if they fit cleanly.

The important architectural requirement is that adding a new game type later should be straightforward.

A new game should ideally be implemented as a new module/class/handler conforming to a shared interface.

Do not hardcode the entire Family Game Night episode in one enormous script.

---

# 6. GAME DATA MUST BE STRUCTURED

Do not allow the LLM to directly generate free-form narration and then attempt to infer the game mechanics from the narration.

The source of truth must be structured game data.

The architecture should conceptually be:

```text
LLM / DATA SOURCE
        ↓
STRUCTURED GAME SPECIFICATION
        ↓
VALIDATION
        ↓
GAME ENGINE
        ↓
SCENE PLAN
        ↓
NARRATION
        +
VISUALS
        +
TIMING
        ↓
RENDER
```

A conceptual game specification might look like:

```json
{
  "game_type": "higher_lower",
  "title": "Which Has More?",
  "rounds": [
    {
      "left": {
        "label": "Option A",
        "value": 120
      },
      "right": {
        "label": "Option B",
        "value": 240
      },
      "correct_answer": "right",
      "explanation": "Option B has the higher value.",
      "thinking_time_seconds": 8,
      "points": 1
    }
  ]
}
```

This is only conceptual.

Adapt the schema to the existing BiteBits architecture.

The important rule is:

> Game state must exist independently from narration.

The narration is generated from validated game state.

The answer is generated from validated game state.

The visuals are generated from validated game state.

The renderer must never need to guess what the correct answer is.

---

# 7. FULLY AUTOMATED EPISODE GENERATION

Episode generation should work approximately like this.

## STEP 1 — SELECT EPISODE THEME

The episode may have a light theme.

Examples:

```text
Family Game Night: Can You Beat Everyone?
```

```text
The Ultimate Mixed Challenge
```

```text
Easy to Hard Family Challenge
```

```text
Brain vs Memory Game Night
```

```text
Can Your Family Get a Perfect Score?
```

Themes should guide the selection of games.

They should not force every round into an unnatural theme.

The system should avoid repetitive episode concepts.

Use existing BiteBits rotation and recent-exclusion patterns where applicable.

---

## STEP 2 — SELECT GAME TYPES

Select a balanced sequence.

Avoid:

```text
Higher or Lower
Higher or Lower
Higher or Lower
Higher or Lower
```

unless the episode explicitly has that format.

Prefer:

```text
Observation game
        ↓
Knowledge/comparison game
        ↓
Deduction game
        ↓
Memory game
        ↓
Fast final round
```

The sequence should alternate cognitive experiences.

---

## STEP 3 — GENERATE STRUCTURED ROUND DATA

Each game module generates or receives structured data.

The LLM may help generate concepts.

However, every generated game must be validated before rendering.

The validation system should check:

- required fields
- answer exists
- answer matches clues
- no obvious contradictions
- no empty content
- difficulty within configured range
- thinking time defined
- explanation exists where needed

For deterministic visual games such as Spot the Difference:

The renderer/game generator should generate the state.

Do not ask the LLM to remember what changed.

---

## STEP 4 — VALIDATE

Validation should happen before expensive rendering.

If a round is invalid:

```text
Reject round
        ↓
Regenerate only that round
```

Do not regenerate an entire episode unless necessary.

The pipeline should avoid wasting GitHub Actions runtime.

---

## STEP 5 — BUILD EPISODE TIMELINE

The timeline must explicitly include player time.

Conceptually:

```text
00:00 Intro
00:15 Game introduction
00:30 Round presented
00:35 Player thinking time begins
00:45 Countdown
00:48 Answer reveal
00:55 Explanation
01:05 Next round
```

Do not treat narration timestamps as the entire timeline.

The timeline must include silent or low-narration gameplay periods.

---

# 8. TIMING RULES

Timing is critical.

The generator must not arbitrarily invent timing.

Create deterministic defaults.

The defaults should be configurable.

Suggested conceptual ranges:

```text
Simple question:
5–8 seconds

Moderate deduction:
8–12 seconds

Memory challenge:
8–15 seconds

Spot the difference observation:
10–20 seconds

Connection challenge:
10–15 seconds

Rapid fire:
3–6 seconds
```

These are starting points, not fixed requirements.

Different game types should define their own timing.

The timing engine should consider:

- amount of information displayed
- number of items
- difficulty
- reading time

For example:

A round with 10 words should not receive the same thinking time as a round with 2 words.

The system should be capable of estimating a minimum readable duration.

Never make the game technically possible but practically impossible to play.

---

# 9. PLAYER TIME MUST BE VISUALLY CLEAR

During player time, the viewer must understand:

```text
THE ANSWER HAS NOT BEEN REVEALED YET
```

Use visual state.

Examples:

```text
YOUR TURN
```

```text
THINK FAST
```

```text
WHAT'S YOUR ANSWER?
```

Countdown:

```text
10
9
8
7
...
```

or a visual progress indicator.

The exact style should match the channel's visual design.

The answer must not accidentally appear during this stage.

Do not display:

- highlighted answer
- answer-colored border
- explanation that gives away the answer
- narrator phrasing that reveals the solution

---

# 10. NARRATION RULES

The narrator is a host.

The narrator should not behave like an LLM reading generated text.

The narrator should sound like it is hosting a game night.

Desired qualities:

- clear
- energetic
- natural
- concise
- playful
- not overly dramatic
- not robotic
- not constantly saying generic AI phrases

Avoid repetitive phrases such as:

```text
Let's dive in
Get ready
Here's the thing
You won't believe this
And there you have it
```

The host should vary naturally.

Examples of useful host functions:

```text
Alright, first challenge.
```

```text
You've got ten seconds.
```

```text
Don't say it out loud if you're playing against someone.
```

```text
Time's up.
```

```text
If you got that, take the point.
```

```text
That one catches more people than you'd think.
```

Do not over-narrate.

During gameplay, silence is allowed.

The narrator should not talk continuously over thinking time.

---

# 11. VOICE

Continue using the existing BiteBits voice infrastructure unless a change is necessary.

The Family Game Night narrator should be:

- easy to understand
- clear at normal playback speed
- energetic without sounding rushed

Do not increase speech speed simply to make episodes shorter.

Player time should remain intact.

The narrator's speed must not make instructions difficult to understand.

The voice should have a distinct personality from:

- Programming persona
- Facts persona
- Sauce Secrets persona

Create a Family Game Night host persona.

The host should feel like:

```text
A friendly game-show host
```

not:

```text
A robotic quiz reader
```

Do not fabricate personal experiences.

Do not pretend the host has physically played with the viewer.

Avoid statements like:

```text
I played this with my family last night.
```

unless such a claim is genuinely true and manually supplied.

---

# 12. CAPTIONS

Captions are optional for this format.

Do not blindly apply the Shorts caption style.

Long-form game videos have different visual needs.

The main question is:

> Do captions help the game, or do they clutter the screen?

The initial implementation should preserve compatibility with the existing caption pipeline.

However, captions should not:

- cover clues
- cover game cards
- cover countdowns
- reveal answers
- visually overload the screen

Possible approaches:

1. Keep captions but render them in a safe lower region.
2. Use narration captions only when no game-critical text occupies that region.
3. Disable word-by-word captions for Family Game Night if they harm readability.

Do not make a large caption-system rewrite as part of this task.

Implement the Family Game format first.

If captions work cleanly, keep them.

If the existing caption system conflicts with game UI, make the format capable of disabling or adapting captions through configuration.

---

# 13. VISUAL DESIGN

The Family Game Night format should be visually distinct from Python Quiz.

Do not reuse the Python Quiz screen as-is.

The visuals should feel like a game.

Possible visual structure:

```text
TOP:
Game title / round indicator

CENTER:
Main challenge

BOTTOM:
Countdown / points / player prompt
```

But adapt based on game type.

The visual system should support:

- question cards
- comparison cards
- grids
- object scenes
- reveal animations
- countdowns
- score indicators
- round transitions

Use reusable components.

Do not manually create every scene.

The renderer should build scenes from structured data.

---

# 14. GAME UI COMPONENT SYSTEM

Build reusable rendering components where practical.

Conceptual components:

```text
render_title_card()

render_round_intro()

render_question_card()

render_option_card()

render_comparison_card()

render_grid()

render_countdown()

render_player_turn()

render_answer_reveal()

render_explanation()

render_score_prompt()

render_transition()

render_final_round()
```

Do not force every game type into identical layouts.

The components should be composable.

---

# 15. SCORE SYSTEM

Do not require the system to know each family's real score.

The video cannot track viewers directly.

Instead, players track their own points.

At the end of a successful round:

```text
GOT IT?
+1 POINT
```

For some games:

```text
Solved after clue 1?
+3

Solved after clue 2?
+2

Solved after clue 3?
+1
```

At episode checkpoints:

```text
HOW MANY POINTS DO YOU HAVE?
```

The narrator can say:

```text
Keep your score — we're halfway through.
```

Do not make the score system complicated.

The purpose is engagement.

---

# 16. EPISODE PACING

Avoid a flat experience.

An episode should have rhythm.

Conceptually:

```text
ENERGETIC INTRO
        ↓
EASY EARLY WIN
        ↓
MODERATE CHALLENGE
        ↓
OBSERVATION GAME
        ↓
PACE CHANGE
        ↓
MEMORY GAME
        ↓
HARDER CHALLENGE
        ↓
FAST FINAL ROUND
```

The player should experience:

- confidence
- challenge
- surprise
- recovery
- competition

Do not place all difficult games together.

Do not make the first challenge extremely difficult.

Early rounds should encourage the viewer to continue.

---

# 17. DIFFICULTY

Each round should have a conceptual difficulty level.

For example:

```text
easy
medium
hard
```

The episode generator should balance difficulty.

Avoid:

```text
hard
hard
hard
hard
```

A possible pattern:

```text
easy
easy-medium
medium
medium
medium-hard
hard
rapid final
```

Difficulty should be meaningful.

Do not randomly label a game hard.

Game modules should determine difficulty based on measurable properties where possible.

Examples:

Connection game difficulty may depend on:

- number of clues
- obviousness of connection
- abstraction

Memory difficulty may depend on:

- number of objects
- display duration
- similarity of objects

Spot-the-difference difficulty may depend on:

- number of changes
- size of changed object
- visual prominence

---

# 18. AUTOMATED QUALITY GATE

Add a pre-render quality gate.

This is important.

Do not spend rendering time on obviously broken games.

The quality gate should reject or flag:

- missing answer
- contradictory clues
- answer visible too early
- thinking time too short
- explanation does not match answer
- repeated game too similar to recent round
- invalid structured data
- unsupported game action
- overly long narration
- duplicate answer patterns

Where possible, validate deterministically.

Use the LLM only where semantic validation genuinely requires it.

Do not create unnecessary extra API calls.

---

# 19. ANTI-REPETITION

The format must not feel automatically generated.

Track recent episode history where the existing pipeline architecture supports it.

Avoid repeated:

- game ordering
- identical titles
- identical hooks
- same final round every episode
- same clue structure
- same narrator phrases
- same transition language

Example:

Episode A:

```text
Higher or Lower
Memory
Odd One Out
Connection
Rapid Fire
```

Episode B should not automatically be:

```text
Higher or Lower
Memory
Odd One Out
Connection
Rapid Fire
```

unless intentionally configured.

Rotate structure.

Use existing BiteBits rotation utilities where appropriate.

Do not create a separate duplicate rotation implementation if the repository already has shared utilities.

---

# 20. SHORTS PROMOTION COMPATIBILITY

Design game data so it can later be reused for Shorts.

Do not necessarily implement the Shorts format now.

But avoid architecture that prevents reuse.

A long-form game round should conceptually be extractable.

Example:

```text
Long-form round:
Guess the Connection
```

can later become:

```text
Short:
Can you solve this before time runs out?
```

The Short can contain:

```text
Hook
        ↓
Challenge
        ↓
Short countdown
        ↓
Answer
        ↓
CTA toward full game
```

The important architectural idea is:

```text
One game data model
        ↓
Long-form renderer
        +
Short-form renderer later
```

Do not duplicate game generation logic.

---

# 21. YOUTUBE RETENTION DESIGN

The format should naturally create retention.

Do not add fake clickbait.

Use the gameplay loop itself.

Every round should create:

```text
QUESTION
        ↓
UNCERTAINTY
        ↓
PLAYER THINKING
        ↓
COUNTDOWN
        ↓
REVEAL
        ↓
SATISFACTION
        ↓
NEXT CHALLENGE
```

This is the core retention loop.

The video should avoid long explanations.

The reveal should happen soon enough to satisfy curiosity.

But not so soon that the viewer cannot play.

The system must balance:

```text
Enough time to play
```

with:

```text
Not wasting the viewer's time
```

---

# 22. EXAMPLE EPISODE

This is an example of the desired experience.

Do not hardcode this exact episode.

```text
TITLE:
Can Your Family Beat This Game Night Challenge?

INTRO

HOST:
Welcome to Family Game Night.
Keep track of your own points.
We've got memory, logic, observation, and one final rapid-fire round.

GAME 1 — ODD ONE OUT

ROUND 1

Show four objects.

HOST:
Which one doesn't belong?

PLAYER TIME:
8 seconds

COUNTDOWN

REVEAL

HOST:
Time's up.
The answer is X because the other three belong to Y.

+1 POINT

GAME 2 — MEMORY

Show six objects.

HOST:
You've got ten seconds to remember these.

PLAYER TIME:
10 seconds

Hide objects.

HOST:
Which item was in the third position?

PLAYER TIME:
8 seconds

REVEAL

GAME 3 — HIGHER OR LOWER

HOST:
Which one is higher?

Show comparison.

PLAYER TIME:
8 seconds

REVEAL

GAME 4 — SPOT THE DIFFERENCE

Show scene.

HOST:
Study this carefully.

PLAYER TIME:
12 seconds

Show modified scene.

HOST:
What changed?

PLAYER TIME:
10 seconds

REVEAL

MIDPOINT SCORE CHECK

HOST:
How many points have you got?

GAME 5 — GUESS THE CONNECTION

Show clues.

PLAYER TIME:
12 seconds

REVEAL

FINAL ROUND — RAPID FIRE

HOST:
Five challenges.
Five seconds each.

Challenge
Countdown
Reveal

Challenge
Countdown
Reveal

ENDING

HOST:
That's game night.
Count your points and see who won.
```

This should feel like an actual hosted game session.

---

# 23. DO NOT MAKE THE VIDEO PLAY ITSELF

This requirement is critical.

The automated generator must not create something like:

```text
Question appears.
Narrator immediately gives answer.
Next question appears.
Narrator immediately gives answer.
```

That is not gameplay.

It is a narrated slideshow.

Every playable round must have explicit:

```text
PRESENTATION PHASE
        ↓
PLAYER THINKING PHASE
        ↓
COUNTDOWN / DEADLINE
        ↓
REVEAL PHASE
        ↓
EXPLANATION / SCORE PHASE
```

The episode generator must enforce this state machine.

Do not leave timing to arbitrary LLM prose.

The renderer should receive explicit event timing.

---

# 24. RECOMMENDED DATA MODEL

Adapt this concept to the existing codebase.

A round should conceptually contain:

```text
Round
    id
    game_type
    difficulty
    title
    instructions
    presentation_data
    answer
    explanation
    thinking_time
    reveal_data
    scoring
```

An episode should conceptually contain:

```text
Episode
    title
    theme
    intro
    games[]
    transitions[]
    outro
```

A game should conceptually contain:

```text
Game
    game_type
    rounds[]
    intro
    rules
    visual_style
```

Do not overengineer inheritance if simple typed data structures work better.

Follow the project's existing architecture and conventions.

---

# 25. RENDERING

Reuse the existing BiteBits rendering stack.

The project already uses:

- Python
- Pillow/PIL
- ffmpeg
- automated narration
- timestamps
- captions

Use these strengths.

The Family Game format should be rendered frame-by-frame or scene-by-scene according to existing best practices.

Do not introduce a completely unrelated rendering technology.

The system should generate:

```text
Scene plan
        ↓
Frames / visual segments
        ↓
Narration audio
        ↓
Timed silence/player periods
        ↓
Countdown animation
        ↓
Sound effects
        ↓
Final ffmpeg assembly
```

The countdown and player time must not depend on narration audio duration.

They must be explicit timeline events.

---

# 26. SOUND DESIGN

The format should support:

- subtle background music
- countdown sounds
- reveal sound
- correct-answer sound where appropriate
- transition sounds

Do not make the audio exhausting.

The countdown should be clear.

The reveal should feel satisfying.

Reuse existing audio loudness handling.

Narration must remain understandable.

Do not blindly add loud music.

---

# 27. MUSIC DURING THINKING TIME

Player thinking time should not feel empty.

However, continuous narration should not fill it.

Use:

- background music
- subtle ticking
- countdown audio near the end

The viewer should clearly feel time passing.

Do not use overly stressful ticking for every game.

Rotate audio treatment.

---

# 28. TITLE AND THUMBNAIL SYSTEM

Generate titles around the game experience.

Avoid generic:

```text
Family Quiz #17
```

Prefer concepts such as:

```text
Can Your Family Beat This Game Night?
```

```text
Only 1 in 10 Gets a Perfect Score
```

```text
The Ultimate Family Game Night Challenge
```

```text
Memory, Logic and Speed — Who Wins?
```

Do not make unsupported statistical claims unless validated.

For thumbnails, use:

- strong game visual
- large readable challenge
- limited text
- clear competitive framing

Do not make thumbnails overly complex.

The Family Game Night visual identity should be distinct from Python Quiz.

---

# 29. AUTHENTICITY AND INAUTHENTIC CONTENT CONSIDERATIONS

This is an automated faceless format.

Therefore, avoid creating a repetitive template farm.

The format should demonstrate genuine editorial variation through:

- different game combinations
- different mechanics
- different episode pacing
- varied host language
- varied visual challenges
- deterministic custom-generated game scenes
- unique episode structure

Do not mass-produce identical question cards with only words swapped.

The procedural games should create meaningful variation.

The goal is:

```text
A reusable game show format
```

not:

```text
The same automated video repeated forever
```

---

# 30. IMPLEMENTATION PLAN

Follow this order.

## PHASE 1 — INSPECT THE REPOSITORY

Before writing code:

Inspect:

- existing Python Quiz long-form pipeline
- state machine integration
- rendering utilities
- narration generation
- timing system
- caption system
- thumbnail generation
- metadata generation
- rotation utilities
- quality gate infrastructure
- tests

Identify the cleanest way to add a new content type.

Do not guess.

Do not rewrite existing systems.

---

## PHASE 2 — CREATE THE GAME ENGINE FOUNDATION

Create the reusable game data model.

Create a common interface or equivalent structure for game modules.

Support:

- generation
- validation
- timeline planning
- rendering data preparation

Do not implement all games before the foundation works.

---

## PHASE 3 — IMPLEMENT ONE COMPLETE GAME VERTICALLY

Start with one relatively straightforward game.

Recommended:

```text
Higher or Lower
```

Implement the full pipeline:

```text
Structured data
        ↓
Validation
        ↓
Timeline
        ↓
Narration
        ↓
Player time
        ↓
Countdown
        ↓
Reveal
        ↓
Render
```

Confirm that the system actually gives viewers time to play.

Do not proceed until the complete loop works.

---

## PHASE 4 — ADD PROCEDURAL GAME

Implement:

```text
Spot the Difference / What Changed
```

This is important because it demonstrates deterministic game generation.

The renderer should know the exact state.

Do not rely on LLM memory.

---

## PHASE 5 — ADD ADDITIONAL GAME MODULES

Add:

- Odd One Out
- Memory Challenge
- Guess the Connection
- Who / What Am I
- Rapid Fire

Each must use the same overall game lifecycle.

---

## PHASE 6 — EPISODE COMPOSER

Build the episode composition logic.

Select:

- game types
- order
- difficulty progression
- round counts
- transitions

Avoid repetition.

Use existing rotation utilities.

---

## PHASE 7 — QUALITY GATE

Validate before rendering.

Reject invalid rounds.

Regenerate only failed rounds where possible.

---

## PHASE 8 — FULL END-TO-END TEST

Generate a complete test episode.

Verify:

- all games render
- player time exists
- answers do not appear early
- countdown timing is correct
- narration does not spoil answers
- transitions work
- duration is reasonable
- captions do not block gameplay
- final ffmpeg output is valid

---

# 31. TESTING REQUIREMENTS

Add automated tests where practical.

Test:

- structured game validation
- invalid answer rejection
- missing fields
- answer not shown during player phase
- timeline includes thinking time
- countdown duration
- reveal occurs after thinking time
- score logic
- sequential episode composition
- anti-repetition logic where applicable

For procedural games:

Test that:

```text
Initial scene
```

and:

```text
Modified scene
```

actually differ according to the recorded answer.

The answer should be generated from deterministic scene state.

---

# 32. FAILURE HANDLING

If one generated round fails validation:

Do not crash the entire episode immediately.

Prefer:

```text
Round generation fails
        ↓
Reject round
        ↓
Generate replacement
        ↓
Validate replacement
```

However, prevent infinite regeneration loops.

Use bounded retries consistent with existing project patterns.

If repeated failure occurs:

- mark appropriately
- log useful diagnostics
- fail cleanly according to the existing state machine

Do not silently create broken game content.

---

# 33. PERFORMANCE AND GITHUB ACTIONS

The system runs automatically through GitHub Actions.

Therefore:

- avoid unnecessary heavy dependencies
- avoid expensive rendering experiments
- avoid external APIs for every visual detail
- reuse existing assets
- cache where the project already supports caching
- keep generation deterministic where possible

The game format should be scalable.

A new episode should not require dramatically more compute than necessary.

---

# 34. DO NOT DO THESE THINGS

Do not:

- build a manual video editor
- require human interaction
- require someone to approve every round
- make the narrator talk continuously
- reveal answers immediately
- create only quiz questions and call it a game
- hardcode one episode
- hardcode game order
- generate visuals manually
- depend on real people being filmed
- create a website requirement
- create an app requirement
- ask the viewer to interact with external software
- rewrite unrelated BiteBits templates
- rewrite the existing state machine
- replace the existing rendering stack unnecessarily
- add a massive dependency tree
- build a full 3D game engine

This is an automated YouTube game show renderer.

Keep the architecture focused.

---

# 35. FINAL SUCCESS CRITERIA

The completed system should allow the pipeline to automatically create something that feels approximately like:

```text
A hosted family game night
```

rather than:

```text
An AI reading trivia questions over slides
```

A finished episode should have:

- multiple game mechanics
- clear instructions
- explicit player thinking time
- visible countdowns
- satisfying reveals
- natural host narration
- procedural or structured visuals
- score prompts
- varied pacing
- a strong final round
- automated generation
- automated validation
- automated rendering
- automated upload compatibility

The most important behavioral requirement is this:

```text
THE VIDEO MUST WAIT FOR THE HUMAN VIEWER.
```

The game engine must understand that watching silence, thinking, discussing, remembering, and choosing are not failures in pacing.

They are the actual product.

The generator must not "play the game by itself."

The pipeline should present the challenge, give the viewer a fair chance to play, and only then reveal the result.

Build the system around this state machine:

```text
INTRODUCE
        ↓
PRESENT
        ↓
WAIT / PLAYER TIME
        ↓
COUNTDOWN
        ↓
REVEAL
        ↓
EXPLAIN
        ↓
SCORE
        ↓
NEXT ROUND
```

This state machine is the heart of Family Game Night.

Everything else — narration, visuals, animation, captions, music, thumbnails, and episode composition — should support it.

Before finishing implementation, review the result from the perspective of a real family sitting in front of a TV.

Ask:

> "Could several people actually play this together without the video rushing ahead and answering for them?"

If the answer is no, the implementation is not finished.

The final product should be fully automated after implementation and should integrate cleanly into the existing BiteBits pipeline as a new long-form content type.
