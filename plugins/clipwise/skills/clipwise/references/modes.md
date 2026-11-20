# Picking modes

Every run has a mode (`prep --mode ...`, shown on line 3 of each chunk). Apply it together with
`references/picking.md`. If the user changes their mind ("actually make it unhinged"), re-score the
chunks you already read; you don't need to re-prep.

## brand-safe (default)

The rules most clipping campaigns use. A clip that breaks them gets rejected, and repeat "hate farming"
can get the poster's account banned, so follow them strictly.

1. **Name the streamer.** The hook (on-screen text) names the streamer, e.g. "<STREAMER> CAN'T BELIEVE ...".
2. **Hashtag.** `#StreamerName` (no spaces) in every post's hashtags, plus the game's tag.
3. **Positive light only.** The clip shows the streamer positively or as fun: hype, jokes, skill,
   reactions, wholesome moments, self-aware humour. Skip:
   - rage at chat, teammates or viewers; toxic arguments; insulting someone
   - moments framed to mock or embarrass them (a fail is fine when they laugh at it themselves)
   - anything sexual, slurs as the point of the clip, crude donation messages
   - gossip about real people's private lives, stereotypes about places or groups
4. **No false or negative narratives.** The hook and caption describe what really happens. Don't invent
   drama, don't cut a moment so it means something it didn't. If the hook claims something visible
   ("shows off his GTA 6 copy"), confirm it in the rendered frames and fix it if wrong.
5. **The streamer is in the clip.** Visible (facecam or camera) for the whole clip, not just the start.
   Skip moments where the cam is hidden; after rendering, check frames and switch the layout if needed.
6. **Captions are censored** (automatic): f**k, s**t, n***a, b***h.

## unhinged

Only when the user asks for it ("unhinged", "no filter", "anything goes", "include everything", "don't
skip anything"). Tell them once that these clips won't pass most campaign rules.

- Every entertaining moment counts: trash talk, roasts, rage, crude jokes, wild donation messages and
  the streamer's reaction, chaotic chat interactions, arguments, cursing.
- Score purely on entertainment and shareability; the same harsh scale.
- Still required: hooks stay TRUE (no fabricated claims), the streamer stays visible, captions stay
  censored unless the user explicitly asks for uncensored (`render --no-censor`), and never clip personal
  information (phone numbers, addresses, private people's names).
- Usually yields more clips per stream than brand-safe; offer `--top 5` or more.

## custom

The user pasted their own campaign rules (e.g. "Your caption or text overlay must mention <name> by name;
captions must use #<name>; videos can't show <name> in a negative light; ...").

- After prep, save the rules verbatim to `<run>/rules.md`, with the streamer's name filled in where the
  rules name someone else ("same rules but name changes to X").
- Apply them on top of brand-safe. When the user's rules and brand-safe disagree, the user's rules win.
- Read `<run>/rules.md` again before rendering and check every clip against each rule in your report.
