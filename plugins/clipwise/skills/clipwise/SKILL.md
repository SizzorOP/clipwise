---
name: clipwise
description: Clipwise turns long livestream replays (YouTube, Twitch, Kick) into ready-to-post vertical shorts for any streamer and any game - facecam on top, gameplay below, hook title, word-by-word captions with curse words starred, post caption and hashtags. Activates on "set up clipwise", "clip this stream <link>", "find me today's biggest <game> streams and clip them", "make shorts from this stream", /clipwise, or any request to clip a stream replay. Three picking modes - brand-safe (default, clipping-campaign rules), unhinged (only when asked), and custom (the user's own campaign rules). English, Hinglish (captions in English letters) and other Latin-script languages. Downloads audio only, transcribes on the computer, marks loud moments and chat spikes; the Claude session reads the transcript 12 minutes at a time and scores moments (no API keys), then downloads only the needed minutes and renders 3 clips per stream. Windows, macOS and Linux. For streams that are live right now use the clipwise-live skill.
---

# Clipwise

Stream replay link (YouTube, Twitch, Kick) or a game name -> ready-to-post 1080x1920 clips.
Everything except the picking runs on the user's computer. The picking is done by YOU (this Claude Code
session), so it runs on the user's Claude subscription, or on a local model through Ollama. No API keys.

## Paths

- `S` = this skill's folder (Claude Code shows it as "Base directory for this skill").
- Everything heavy lives in `H` = `~/.clipwise` (or `$CLIPWISE_HOME`): the Python venv, models, ffmpeg, config.
- `PY` = `H/.venv/Scripts/python.exe` on Windows, `H/.venv/bin/python` on macOS/Linux.
- Run every command as `"$PY" "$S/scripts/clipwise.py" <command>`. Quote paths (they often contain spaces).
  Forward slashes work everywhere, including Git Bash and PowerShell on Windows.
- Clips go to `~/Clipwise/<run>/clips/` (or `$CLIPWISE_CLIPS_DIR`).

## 0. "Set up clipwise"

- Windows: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$S/scripts/setup.ps1"`
- macOS / Linux: `bash "$S/scripts/setup.sh"`

Use a 600000 ms timeout; the first run downloads ~1 GB. It checks FFmpeg, Deno, uv, the Python venv
(yt-dlp, faster-whisper, OpenCV, Pillow, truststore), the Whisper model and the face detector, installs
what's missing (no admin/sudo needed) and prints READY or what is still missing. Tell the user in plain
words what was installed and that it's ready. If any command later says "Not set up yet", run setup first.
Re-run setup if YouTube downloads start failing (it updates yt-dlp).

## Before you start: mode, streamer, language

Decide these from the user's words and say them back in one line before prepping:

1. **Mode** (`--mode`, full rules in `references/modes.md`; read it every time):
   - `brand-safe` (default): clipping-campaign rules - the streamer named in every hook, `#StreamerName`
     hashtag, only moments that show them positively, no false or negative narratives, the streamer on
     screen for the whole clip.
   - `unhinged`: ONLY when the user asks for it ("unhinged", "no filter", "anything goes", "include
     everything"). Every entertaining moment counts. Tell them once that these clips won't pass most
     campaign rules.
   - `custom`: the user pasted campaign rules (e.g. "caption must mention X by name, use #X, ..."). After
     prep, save their rules verbatim to `<run>/rules.md`; they apply on top of brand-safe and win on conflicts.
2. **Streamer name** for hooks and the hashtag: use the name the user gives; otherwise the channel name.
3. **Language** (`--lang`): `en` (default); `hinglish` if the streamer speaks Hindi/Hinglish - captions
   come out as Hindi in English letters ("isko message kar rahi hai bro"), never Devanagari or a
   translation; `auto` for other Latin-script languages (Spanish, Portuguese, French, ...). Non-Latin
   scripts aren't supported in captions yet. If an `en` transcript is full of nonsense English, the
   streamer probably isn't speaking English: tell the user and re-prep with the right `--lang --force`.

## 1+2. Get the streams ready ("prep")

- Given links: `prep <url> [<url> ...] --mode <mode> --lang <lang>`
- Given a game ("find today's biggest Valorant streams"): `discover --game "<game>"` (default 7 streams,
  `--limit N`), show the list, then `prep` the URLs it printed. Don't wait for approval unless the user
  asked to choose. YouTube streams that are still live can't be prepped yet: offer clipwise-live instead.
- Age-restricted YouTube streams and Kick need the browser login: add `--cookies firefox` (macOS: `safari`
  or `chrome` work too). On Windows, Chrome/Edge cookies can't be read while the browser is open: use
  Firefox or a `cookies.txt` exported with a browser extension (`--cookies /path/cookies.txt`). If a
  download fails with "Sign in to confirm your age" / 403, retry with it.
- `--jobs 2` (default) preps 2 streams at once. Don't go higher on a 16 GB computer.
- Long streams take a while (4 h stream: a few minutes download + ~10-25 min transcript, depending on the
  CPU; 12 h: ~30 min). Run prep in the background and tell the user it's running.

Prep downloads only the audio, transcribes it locally, marks where the streamer got loud and (YouTube
replays) where chat sped up, and writes `chunks/chunk_NN.md`: 12-minute pieces with `<<LOUD(+12dB)>>` and
`<<CHAT x4.1>>` markers and the run's mode at the top. It prints the run folder for each stream.

## 3. Pick the moments (you do this)

Read `references/picking.md` and `references/modes.md` first, every time (and `<run>/rules.md` in custom
mode). Then for each run folder:

1. Read every `chunks/chunk_NN.md`, in order (several at a time is fine for long streams).
2. For each chunk write `picks/chunk_NN.json` (same NN): a JSON array of candidate moments, `[]` if
   nothing qualifies. Write the file even when it's empty: that's how progress is tracked.
3. `status <run>` shows which chunks still have no picks file. Keep going until `chunks_left` is empty.

Multiple streams: give each stream its own subagent (Agent tool, general-purpose) with the run folder path
and the instruction "read references/picking.md and references/modes.md, then do step 3 of SKILL.md for
this run folder". Up to 4 at once. On a local Ollama model, skip subagents and do the streams one by one.

## 4. Make the clips

`render <run>` (defaults: `--top 3 --min-score 7`). It ranks all picks, drops overlaps, snaps to sentence
edges, downloads only those minutes, finds the facecam, stacks facecam on top of gameplay (or blurred
full-frame if there's no facecam), burns in the hook title + word-by-word captions (curse words starred:
f**k, s**t, n***a), normalises audio, keeps audio and video in sync, and writes
`clips/clip_NN_<title>.mp4` + `clip_NN_<title>.txt` (title, post caption, hashtags) + `summary.json`.

Before rendering, preview the cuts and their lengths:
`"$PY" -c "import sys; sys.path.insert(0, r'$S/scripts'); import clipwise as g; from pathlib import Path; [print(c['score'], g.hms(c['_s']), round(c['_e']-c['_s']), c['title']) for c in g.select(Path(r'<run>'), 10, 7)[0]]"`
Anything over ~60 s, or that starts much earlier than you picked, usually means the start time sits just
before a transcript line: move it onto that line's exact timestamp.

After rendering, CHECK EVERY CLIP before reporting (this catches real problems):
- Grab a frame every ~4 s, tiled: `ffmpeg -i clip.mp4 -vf "fps=1/4,scale=160:-1,tile=8x2" -frames:v 1 check.png`
  and look at it. The streamer must be visible the whole time (brand-safe/custom). If the top panel shows
  the wrong thing (a face on a poster or in-game, a chat overlay, an extreme zoom) or the stream switches
  layouts mid-clip, add `"layout": "gameplay"` (full frame) or `"cam"` to that pick, delete the mp4, re-render.
- If the hook claims something specific ("got GTA 6 on day one"), confirm it in the frames. Fix the hook
  if the picture says otherwise - that's the "no false narrative" rule.
- If a download fails with an ffmpeg error, just re-run render (it's usually a transient YouTube error).

Other render notes:
- If fewer than 3 clips came out because scores were low, say so; offer `--min-score 6` rather than
  quietly lowering the bar. More clips: `--top 5` etc.
- `--no-censor` shows curse words in full: only if the user explicitly asks for uncensored captions.
- Pass the same `--cookies` as prep if the stream needed it (it's remembered in stream.json).

## 5. Report

Per stream: stream length -> moments found -> clips kept, and each clip's hook, timestamp, length, layout
and file path, plus the near-misses (6.5-7.0) in case they want more. Say which mode was used. Open the
clips folder: Windows `explorer.exe "<run>\clips"` (backslashes), macOS `open "<run>/clips"`, Linux
`xdg-open "<run>/clips"`. Remind the user: watch every clip before posting, and only clip streamers who
allow clipping.

## Other requests

- "Make clip 2 longer / start earlier / different hook": edit that entry in the matching `picks/*.json`,
  delete the old mp4, re-run render (it re-picks deterministically, so the same picks come back with the change).
- Render a single extra pick without re-rendering the rest: call `render_one` from Python with that pick
  (see `cmd_render` in `scripts/clipwise.py`), numbered after the existing clips.
- Speech-to-text tuning (advanced): env vars `CLIPWISE_WHISPER_MODEL` / `_LANGUAGE` / `_PROMPT` beat
  `--lang` for that command. GPU: `CLIPWISE_WHISPER_DEVICE=cuda CLIPWISE_WHISPER_COMPUTE=float16`
  (NVIDIA + CUDA 12 + cuDNN; CPU is the safe default).
- Disk: prep deletes the audio after transcribing and render deletes downloaded sections (`--keep` keeps
  them). Delete finished runs only if the user says so.

## Free mode (no subscription)

Same skill, same prompts. The user installs Ollama and pulls a model sized to their MEMORY (RAM):
16 GB -> `qwen3.5:9b`, 32 GB+ -> `qwen3.5:27b`, then runs `ollama launch claude` and picks the model.
Be honest if asked: it's slower and the picks are rougher than Claude's.

## Platform notes

- Windows: if Windows Defender / SmartScreen asks about ffmpeg, deno or uv, they're the official builds.
  Antivirus HTTPS scanning (Norton, Avast, ...) is handled: downloads trust the Windows certificate store.
- macOS: FFmpeg comes from Homebrew (`brew install ffmpeg`); setup tells the user if Homebrew is missing.
- Linux: setup downloads a static FFmpeg build into `~/.clipwise/bin` if there's no system ffmpeg; Deno's
  installer needs `unzip`; captions need a bold font (`fonts-dejavu-core` on Debian/Ubuntu).
