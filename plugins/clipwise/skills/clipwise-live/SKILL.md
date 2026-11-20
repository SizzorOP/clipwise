---
name: clipwise-live
description: Clipwise LIVE clips streams WHILE they're live, for any streamer and any game - records a rolling buffer on the computer, transcribes each minute as it lands, the Claude session picks moments every 5 minutes and clips are rendered straight from the buffer, ready to post ~5-8 minutes after the moment happens. Activates on "clip this stream live", "live clip <link>", "watch <streamer> and clip as it happens", "start the live clipper", /clipwise-live, or any request to clip a stream that is live right now. Same output, modes (brand-safe default, unhinged, custom rules) and languages as the clipwise skill. For finished streams / replays use clipwise instead. Windows, macOS and Linux.
---

# Clipwise LIVE

Same engine, install and output as the `clipwise` skill (set that one up first; this skill shares its
`~/.clipwise` venv, models and render code). The difference: nothing gets downloaded twice. The live stream
is recorded into 1-minute segments on the computer, only the last `--buffer-min` minutes are kept, and
clips are cut from them.

`L` = this skill's folder, `V` = the `clipwise` skill folder next to it (`L/../clipwise`).
`PY` = `~/.clipwise/.venv/Scripts/python.exe` on Windows, `~/.clipwise/.venv/bin/python` on macOS/Linux
(or under `$CLIPWISE_HOME`). Run: `"$PY" "$L/scripts/live.py" <command>`. Quote paths.

If it says "Set up Clipwise first", run the setup command it prints (that's step 0 of the clipwise skill).

## 0. Mode, streamer, language

Exactly as in the clipwise skill: read `$V/references/modes.md` and pick `--mode brand-safe` (default),
`unhinged` (only when asked) or `custom` (user's pasted rules, saved verbatim to `<run>/rules.md` right
after start). `--lang en` (default), `hinglish` (Hindi in English letters) or `auto`.

## 1. Start

`start <url> [<url> ...] --mode <mode> --lang <lang>`: Twitch channel (`https://www.twitch.tv/<name>`),
YouTube live link, or Kick. Options: `--quality 720` (default; 1080 doubles disk), `--buffer-min 15`,
`--window-min 5`, `--cookies firefox` or a cookies.txt path (Kick, age-restricted YouTube). Each stream
gets a background recorder and a run folder. Max 2 streams on a 16 GB computer (each transcribes a minute
of audio every minute). If it says NOT LIVE, the stream is finished: use the clipwise skill.

Right after starting, run `status <run>` once a minute or two later and confirm `recorded` is growing; if
not, read `<run>/ytdlp.log` and `<run>/ffmpeg.log`.

## 2. The loop (you run this until the stream ends or the user says stop)

Read `$V/references/picking.md` and `$V/references/modes.md` once before the first window. Then repeat:

1. `next <run> [<run> ...]` blocks up to 9 minutes until a new 5-minute window is ready (from any run) and
   prints it with the path to write. Use a Bash timeout of 600000.
2. Write `picks/window_NNN.json` in THAT run folder, same format and rules as picking.md + modes.md.
   `[]` when nothing qualifies (most windows). Windows overlap by 45 s: don't pick the same moment twice.
3. If you wrote any pick with score >= 7.5, run `clip <run>` right away. It renders from the buffer,
   skips anything already clipped, and prints the new clip paths. Check the new clip's frames (streamer
   visible, hook true) exactly like the clipwise skill's step 4, then send it to the user.
4. Tell the user in ONE short line per new clip (hook + path) and go back to step 1. No line for empty windows.

`next` printing "NO NEW WINDOW YET" just means keep looping. "STREAM ENDED" means run `clip` once more,
then report. Live clip bar is 7.5 (not 7): posting fast only matters if the clip is good.

Clips are ready ~5-8 min after the moment: up to 5 min for the window to close + picking + ~1 min render.
For a faster cadence use `--window-min 3` (more reads, more tokens).

## 3. Stop / check

- `status <run>`: recorder alive, minutes recorded, windows waiting, clips made.
- `stop <run>`: stops the recorder (the last partial window still gets written: pick it and clip).
- Changing `--lang`/`--mode` mid-stream: `stop` the run and `start` again (new run folder).
- Clips live in `<run>/clips/` (mp4 + txt with title, caption, hashtags). Open the folder with
  `explorer.exe` (Windows, backslashes), `open` (macOS) or `xdg-open` (Linux).
- `clip <run> --no-censor` shows curse words in full: only if the user explicitly asks.
- The buffer deletes itself as it rolls; old runs in `~/Clipwise/live/` only get deleted if the user says so.

## Notes

- Chat speed is tracked on Twitch (read-only anonymous chat). YouTube/Kick live use loudness only.
- YouTube live serves audio and video as separate feeds; the recorder keeps their original timestamps so
  clips stay in sync. Don't remove `--downloader-args ffmpeg:-copyts` from `live.py`.
- A moment older than the buffer can't be clipped (prints "out of buffer"). Keep up with the windows.
- The recorder runs hidden in the background (no window). `stop` ends it cleanly; closing Claude Code does not.
- The Claude session must stay open while live clipping. On Ollama/local models: one stream at a time.
