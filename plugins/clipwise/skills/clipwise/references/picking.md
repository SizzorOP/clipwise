# Picking moments (step 3)

You're the editor of a clipping page with millions of followers. You're reading a 12-minute piece of a
stream transcript (any game, or just chatting). Find the moments people actually SHARE, score them, and be
harsh. The run's mode is on line 3 of every chunk: apply `references/modes.md` for that mode (and
`<run>/rules.md` in custom mode) on top of everything here.

## What to look for

| category | what it looks like |
|---|---|
| `first_reaction` | first time seeing something: a new area, map, character, feature, item, cutscene, ending |
| `discovery` | finding something crazy / secret / unexpected in the game |
| `freakout` | full-on losing it: screaming, hype, clutch plays, disbelief |
| `fail` | funny fails, deaths, getting wrecked, plans going wrong |
| `hot_take` | a strong opinion people will argue about in the comments ("this game is overrated", "best game ever") |
| `funny` | a joke, a bit, an impression, a chat or donation interaction that lands without setup |
| `wholesome` | a genuine moment: thanking a fan, giving advice, a gift, a milestone |

Talking to chat and reacting to chat/donations COUNTS when the moment itself is funny or memorable (a
wild donation message and the streamer's reaction, a fan's edit, a running bit with chat). Plain chat
reading, sponsor reads and "subscribe / membership" pitches do not.

Signals help, they don't decide: `<<LOUD(+NdB)>>` = the streamer got loud. `<<CHAT xN>>` = chat moved N
times faster than normal (chat reacts a few seconds after the moment, so the moment is usually just before
the marker). A loud line with nothing interesting said is not a clip. A great line with no marker can be.
Some streamers are loud all the time: then loudness means little, read the words.

Game cutscene dialogue is in the transcript too. A cutscene alone is not a clip; the streamer's reaction
to it can be.

## Throw out (score 0, don't include) - in every mode

- Anything that needs context to make sense (references to something earlier, inside jokes, "like I said").
- Starts with filler: "uh so yeah", "anyway", "okay so", "um". Move the start to the first real sentence
  instead, and if there isn't one, drop it.
- Dead air, waiting screens, settings menus, sponsor reads, membership pitches.
- Speech-to-text junk: repeated lines, "[Music]", "Thank you." over and over, text that doesn't fit the stream.
- Personal information read out on stream (phone numbers, addresses, real names of private people).

The mode adds more (brand-safe throws out a lot more; unhinged throws out less).

## Scoring (0-10, harsh)

- 9-10: anyone scrolling would stop and share it. Instant payoff, no context needed, strong emotion.
- 7-8: solid clip, clear hook in the first 3 seconds, lands on its own.
- 5-6: fine, but nobody shares it. Include only if the chunk has nothing better (render skips < 7 by default).
- below 5: don't include.

Most chunks have 0-2 real candidates. Many have none. That's normal: write `[]`.

## Boundaries

- 20-60 seconds. Start ON the hook (the first line must grab), not on the build-up 30 seconds earlier.
- End right after the payoff (the punchline, the reaction peaks, the take lands). Don't trail off.
- Use the `[HH:MM:SS]` timestamps from the chunk. `start` = the exact timestamp of the first line of the
  moment (render snaps to the line that starts at or just before it, so a start a second too early jumps to
  the previous line and can add a long silent lead-in). `end` = start of the first line AFTER the moment.
- If the payoff is something on screen (a fan edit playing, an item being shown), the clip must run long
  enough to include it - the transcript can't tell you, so check the frames after rendering.

## Output: `picks/chunk_NN.json`

```json
[
  {
    "start": "01:23:41",
    "end": "01:24:19",
    "category": "first_reaction",
    "score": 8.5,
    "hook": "STREAMERNAME SEES THE CITY FOR THE FIRST TIME",
    "title": "StreamerName can't believe how the city looks",
    "caption": "He wasn't ready for this 😭 Would you play this on day one?",
    "hashtags": ["#StreamerName", "#GameName", "#gaming", "#clips"],
    "why": "pure disbelief, chat x5, no context needed"
  }
]
```

- `hook`: on-screen title over the clip. Max ~8 words, names the streamer, says what's happening, makes
  you need to see it. Must be TRUE: describe what actually happens, never a claim the clip doesn't show.
- `title`: post title (YouTube Shorts / TikTok), sentence case, under 70 characters.
- `caption`: 1-2 short lines + a question that gets comments. No links.
- `hashtags`: 4-6. Always `#StreamerName` (no spaces) and the game's tag.
- Optional `"layout": "gameplay"` (full frame) or `"cam"` (crop around the face) when you already know the
  facecam detection will struggle (full-screen camera segments, faces on posters or in the game).
