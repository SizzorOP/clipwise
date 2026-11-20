# Clipwise

**Turn long livestreams into ready-to-post shorts with Claude Code.** Give it a YouTube, Twitch or Kick
stream (a finished replay, or one that's live right now) and get vertical 1080x1920 clips: facecam on top,
gameplay below, a hook title, word-by-word captions, and a post caption with hashtags. Works for any
streamer and any game.

Clipwise reads the whole stream for you: an 11-hour stream comes back as its best moments, picked by
Claude, with every clip checked before you get it.

## What it does

1. **Downloads only the audio** of the stream (a few hundred MB, not a giant video).
2. **Transcribes it on your computer** and marks where the streamer got loud and where chat sped up.
3. **Claude reads the transcript 12 minutes at a time** and scores the moments people share: first
   reactions, hype, fails, hot takes, funny chat interactions, wholesome moments. Anything that needs
   context is thrown out.
4. **Downloads only the minutes it needs** and renders each clip: finds the facecam, stacks it over the
   gameplay, burns in the hook and word-by-word captions (curse words starred: f\*\*k, s\*\*t), keeps audio
   and video in sync, and writes the post title, caption and hashtags.

3 clips per stream by default (ask for more any time). Several streams can run at once. A live mode
records the stream as it happens and delivers clips ~5-8 minutes after each moment.

## Install

You need [Claude Code](https://claude.com/claude-code) (the desktop app or the terminal) on Windows 10/11,
macOS or Linux. In Claude Code, type:

```
/plugin marketplace add SizzorOP/clipwise
/plugin install clipwise@clipwise
```

Then say **"set up clipwise"**. It installs everything it needs (FFmpeg, Python, the speech-to-text model,
~1 GB, into `~/.clipwise`) without admin rights and tells you when it's ready.

<details>
<summary>Manual install (without the plugin system)</summary>

Download this repo (Code -> Download ZIP), then copy the two folders in `plugins/clipwise/skills/`
(`clipwise` and `clipwise-live`) into `~/.claude/skills/`. Restart Claude Code and say "set up clipwise".
</details>

To update later: `/plugin marketplace update clipwise`.

## Use it

Just talk to Claude:

- **"clip this stream https://www.youtube.com/watch?v=..."**
- **"find me today's biggest Valorant streams and clip them"**
- **"clip this stream live https://www.twitch.tv/..."**
- **"give me 5 more clips"**, **"make clip 2 start earlier"**, **"use a different hook for clip 3"**

Clips land in `~/Clipwise/<stream>/clips/`: an `.mp4` plus a `.txt` with the title, caption and hashtags.

## Modes

| Mode | When | What you get |
|---|---|---|
| **Brand-safe** (default) | always, unless you ask otherwise | Clipping-campaign rules: the streamer named in every hook, a `#StreamerName` hashtag, only moments that show them positively, no false or negative narratives, the streamer on screen the whole clip. |
| **Unhinged** | say "unhinged", "no filter" or "anything goes" | Every entertaining moment counts: trash talk, roasts, rage, crude jokes, wild donations. Hooks still stay truthful. Won't pass most campaign rules. |
| **Custom** | paste your campaign's rules | Clipwise follows your rules (e.g. "caption must mention X by name, use #X, ...") on top of brand-safe. Say "same rules but for <streamer>" to reuse them. |

Curse words in captions are always starred, in every mode, unless you explicitly ask for uncensored captions.

## Languages

- **English** (default).
- **Hinglish**: say the streamer speaks Hindi/Hinglish and captions come out as Hindi in English letters
  ("isko message kar rahi hai bro"), never translated.
- **Other Latin-script languages** (Spanish, Portuguese, French, ...): say which language. Non-Latin
  scripts aren't supported in captions yet.

## Free mode (no Claude subscription)

Install [Ollama](https://ollama.com), pull a model sized to your RAM (16 GB -> `qwen3.5:9b`,
32 GB+ -> `qwen3.5:27b`), run `ollama launch claude`, pick the model, and use the same prompts. It's slower
and the picks are rougher than Claude's, but it beats scrubbing a stream by hand.

## Good to know

- A 4-hour stream takes roughly 10-30 minutes to prepare, depending on your CPU. An NVIDIA GPU speeds up
  transcription (see the skill's notes).
- Age-restricted YouTube streams and Kick need your browser login: Clipwise will ask to use your Firefox
  cookies or a `cookies.txt` file.
- YouTube streams that are still live can't be clipped as replays yet: use live mode, or wait for the replay.
- Antivirus HTTPS scanning on Windows (Norton, Avast, ...) is handled automatically.
- Everything runs on your computer; nothing is uploaded anywhere.

## Folder layout

```
plugins/clipwise/skills/clipwise/        replay clipper: SKILL.md, picking + mode rules, scripts
  scripts/clipwise.py                    the engine (prep, status, render, discover)
  scripts/setup.ps1, scripts/setup.sh    installers (Windows / macOS + Linux)
plugins/clipwise/skills/clipwise-live/   live clipper (shares the engine)
~/.clipwise/                             installed tools, models, config (created by setup)
~/Clipwise/<run>/                        transcript, chunks, picks, clips/
```

## Responsible use

Only clip creators who allow clipping, follow each platform's rules and each campaign's terms, and watch
every clip before posting. Clipwise is a tool; what you post is up to you.

## License

MIT, see [LICENSE](LICENSE).
