#!/usr/bin/env python3
"""Clipwise: stream link (or nothing) -> ready-to-post vertical clips, for any streamer and any game.

  discover --game G   find today's biggest streams of a game (YouTube + Twitch)
  prep URL [URL...]   steps 1+2: audio-only download, local transcript, loud moments,
                      chat speed-ups (YouTube replays), 12-minute chunks for the AI to read
  status RUN          show what a run has and what's left
  render RUN          step 4: rank the AI's picks, download only those minutes,
                      find the facecam, stack facecam over gameplay, hook + word captions,
                      post caption + hashtags

Step 3 (picking) is done by the Claude Code session itself (no API keys); see SKILL.md.
Windows, macOS and Linux. Everything heavy (Python env, models, ffmpeg, config) lives in
~/.clipwise (or $CLIPWISE_HOME), installed by scripts/setup.ps1 (Windows) or scripts/setup.sh (macOS/Linux).
Run with that venv:  ~/.clipwise/.venv/Scripts/python.exe (Windows) or ~/.clipwise/.venv/bin/python
"""
import argparse, concurrent.futures as cf, datetime as dt, json, math, os, re, shutil
import statistics, subprocess, sys, threading, time, urllib.parse, urllib.request
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("CLIPWISE_HOME", Path.home() / ".clipwise"))  # venv, models, ffmpeg, config.json
RUNS = Path(os.environ.get("CLIPWISE_CLIPS_DIR", Path.home() / "Clipwise"))  # one folder per stream
CFG = json.loads((HOME / "config.json").read_text(encoding="utf-8-sig")) if (HOME / "config.json").exists() else {}
SETUP_HINT = (f'powershell -NoProfile -ExecutionPolicy Bypass -File "{SKILL / "scripts" / "setup.ps1"}"'
              if os.name == "nt" else f'bash "{SKILL / "scripts" / "setup.sh"}"')
# Romanized Hinglish line: with language "en" Whisper then writes Hindi in English letters instead of
# translating it ("isko message kar rahi hai bro"), so captions stay in the streamer's own words
HINGLISH_PROMPT = "Haan bhai, chalo yaar mission karte hain. Kya scene hai bro, paise kitne mile? Arre bhai yeh kya ho gaya!"
LANGS = {  # prep --lang: Whisper model / language / prompt per stream (stored in the run's stream.json)
    "en": {"model": "small.en", "language": "en", "prompt": ""},
    "hinglish": {"model": "small", "language": "en", "prompt": HINGLISH_PROMPT},
    "auto": {"model": "small", "language": "auto", "prompt": ""},  # other languages, captions in their script
}

# Print UTF-8 (stream titles have emoji), make yt-dlp child processes UTF-8 too, and put the
# tools setup installed (ffmpeg, deno) on PATH even before the terminal is restarted.
for _st in (sys.stdout, sys.stderr):
    if hasattr(_st, "reconfigure"):
        _st.reconfigure(encoding="utf-8", errors="replace")
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
_pd = CFG.get("path_dirs") or []
for _d in reversed([_pd] if isinstance(_pd, str) else _pd):
    if _d and _d not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _d + os.pathsep + os.environ.get("PATH", "")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console windows popping up for ffmpeg
CHUNK_SEC = 12 * 60
# Windows: no-certifi makes yt-dlp verify TLS against the Windows certificate store instead of certifi's
# bundle, so it works behind antivirus HTTPS scanning (Norton, Avast, Kaspersky...) whose root CA only
# lives in the Windows store. macOS/Linux keep certifi (the system store isn't always wired up there).
YTDLP = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--quiet", "--no-progress"]
if os.name == "nt":
    YTDLP += ["--compat-options", "no-certifi"]
try:  # same idea for the Whisper model download (huggingface): use the OS certificate store
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass
# common names -> Twitch's official category name (discover --game)
TWITCH_GAMES = {"gta 6": "Grand Theft Auto VI", "gta vi": "Grand Theft Auto VI", "gta 5": "Grand Theft Auto V",
                "gta v": "Grand Theft Auto V", "cod": "Call of Duty: Warzone", "warzone": "Call of Duty: Warzone",
                "cs2": "Counter-Strike", "lol": "League of Legends", "rdr2": "Red Dead Redemption 2"}


# ---------------------------------------------------------------- helpers
def log(*a):
    print(*a, flush=True)


def run(cmd, **kw):
    kw.setdefault("creationflags", NO_WINDOW)
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def cookie_args(c):
    if not c:
        return []
    return ["--cookies", c] if os.path.isfile(c) else ["--cookies-from-browser", c]


def hms(s):
    s = max(0, int(round(s)))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def parse_ts(v):
    if isinstance(v, (int, float)):
        return float(v)
    parts = [float(p) for p in str(v).strip().split(":")]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def slug(s, n=40):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s or "stream").strip("-").lower()
    return s[:n] or "stream"


def ytdlp_json(url, cookies=None, extra=()):
    r = run(YTDLP + cookie_args(cookies) + list(extra) + ["-J", url])
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "yt-dlp failed")
    return json.loads(r.stdout)


# ---------------------------------------------------------------- discover
def load_env():
    env = {}
    f = HOME / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"')
    return {**env, **os.environ}


def helix(path, cid, token):
    req = urllib.request.Request(f"https://api.twitch.tv/helix/{path}",
                                 headers={"Client-ID": cid, "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def discover_twitch(limit, game):
    """Official Twitch API. Needs a free Twitch dev app (dev.twitch.tv/console):
    TWITCH_CLIENT_ID + TWITCH_CLIENT_SECRET in ~/.clipwise/.env. Skipped without them."""
    env = load_env()
    cid, sec = env.get("TWITCH_CLIENT_ID"), env.get("TWITCH_CLIENT_SECRET")
    if not (cid and sec):
        log("  twitch: skipped (add TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET to .env to include Twitch)")
        return []
    out = []
    try:
        body = f"client_id={cid}&client_secret={sec}&grant_type=client_credentials".encode()
        with urllib.request.urlopen(urllib.request.Request("https://id.twitch.tv/oauth2/token", data=body), timeout=20) as r:
            tok = json.loads(r.read())["access_token"]
        name = TWITCH_GAMES.get(game.lower().strip(), game)
        games = helix("games?name=" + urllib.parse.quote(name), cid, tok).get("data") or []
        streams = helix(f"streams?game_id={games[0]['id']}&first=20", cid, tok).get("data", []) if games else []
        for st in streams[: limit * 2]:
            vids = helix(f"videos?user_id={st['user_id']}&type=archive&first=1", cid, tok).get("data") or []
            if vids:
                out.append({"platform": "twitch", "streamer": st["user_name"], "title": st["title"],
                            "viewers": st["viewer_count"], "live_now": True, "url": vids[0]["url"]})
    except Exception as e:
        log(f"  twitch: skipped ({e})")
    return out


def game_matcher(game):
    """Title filter for a game: every word of the name in order (GTA 6 also matches GTA VI / Grand Theft Auto VI)."""
    alts = {"6": "(?:6|vi)", "vi": "(?:6|vi)", "5": "(?:5|v)", "v": "(?:5|v)"}
    words = [alts.get(w, re.escape(w)) for w in re.findall(r"\w+", game.lower())]
    pats = [r"\b" + r"\W*".join(words) + r"\b"]
    full = TWITCH_GAMES.get(game.lower().strip())
    if full:
        pats.append(re.escape(full.lower()))
    return re.compile("|".join(pats), re.I)


def discover_youtube(limit, game):
    """Finished streams of the game from today / this week (clippable now) + what's live right now."""
    out, seen = [], set()
    q = urllib.parse.quote_plus(game)
    match = game_matcher(game)
    searches = [(q + "+stream", "EgIIAg%3D%3D"), (q + "+live", "EgIIAg%3D%3D"),
                (q + "+stream", "EgIIAw%3D%3D"), (q, "EgJAAQ%3D%3D")]
    for q, sp in searches:
        try:
            pl = ytdlp_json(f"https://www.youtube.com/results?search_query={q}&sp={sp}",
                            extra=["--flat-playlist", "--playlist-end", "40"])
        except Exception as e:
            log(f"  youtube search skipped: {e}")
            continue
        for e in pl.get("entries") or []:
            if not e or e.get("id") in seen or not match.search(e.get("title") or ""):
                continue
            live = e.get("live_status") == "is_live"
            if not live and (e.get("duration") or 0) < 40 * 60:  # regular videos aren't streams
                continue
            seen.add(e["id"])
            out.append({"platform": "youtube", "streamer": e.get("channel") or e.get("uploader") or "",
                        "title": e.get("title", ""), "live_now": live,
                        "viewers": (e.get("concurrent_view_count") or 0) * 20 if live else (e.get("view_count") or 0),
                        "length": hms(e.get("duration") or 0), "url": f"https://www.youtube.com/watch?v={e['id']}"})
    return out


def cmd_discover(a):
    log(f"Finding today's biggest {a.game} streams...")
    with cf.ThreadPoolExecutor(2) as ex:
        tw, yt = ex.submit(discover_twitch, a.limit, a.game), ex.submit(discover_youtube, a.limit, a.game)
        streams = tw.result() + yt.result()
    # clippable first (finished YouTube replays + Twitch archives), YouTube still-live last
    streams.sort(key=lambda s: (s["platform"] == "youtube" and s["live_now"], -s["viewers"]))
    seen, picked = set(), []
    for s in streams:
        k = s["streamer"].lower()
        if k not in seen:
            seen.add(k)
            picked.append(s)
    picked = picked[: a.limit]
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / f"discover-{dt.date.today()}.json").write_text(json.dumps(picked, indent=2), encoding="utf-8")
    for i, s in enumerate(picked, 1):
        tag = "LIVE NOW, clip after it ends" if s["platform"] == "youtube" and s["live_now"] else s.get("length", "archive")
        log(f"{i}. [{s['platform']}] {s['streamer']} ({tag}) {s['title'][:80]}\n   {s['url']}")
    if not picked:
        log("Nothing found. Paste stream links instead.")


# ---------------------------------------------------------------- prep (steps 1 + 2)
def loud_moments(wav):
    """Per-second RMS, flag seconds well above the local baseline (yelling / losing it)."""
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(wav), "-af",
             "asetnsamples=n=16000,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
             "-f", "null", "-"])
    vals = []
    for m in re.finditer(r"RMS_level=(-?[\d.]+|-inf)", r.stdout):
        v = m.group(1)
        vals.append(-90.0 if v == "-inf" else float(v))
    events = []
    if not vals:
        return events, vals
    W = 90
    for i, v in enumerate(vals):
        if v < -32:
            continue
        lo, hi = max(0, i - W), min(len(vals), i + W)
        base = statistics.median(vals[lo:hi])
        if v - base >= 9:
            events.append((i, round(v - base, 1)))
    # merge consecutive seconds into events
    merged = []
    for t, d in events:
        if merged and t - merged[-1]["end"] <= 2:
            merged[-1]["end"] = t
            merged[-1]["db"] = max(merged[-1]["db"], d)
        else:
            merged.append({"start": t, "end": t, "db": d})
    return merged, vals


def chat_spikes(chat_file):
    """YouTube replay chat: messages per 10 s vs the local baseline."""
    if not chat_file or not Path(chat_file).exists():
        return []
    times = []
    with open(chat_file, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                ms = json.loads(line)["replayChatItemAction"]["videoOffsetTimeMsec"]
                times.append(int(ms) / 1000)
            except Exception:
                pass
    if len(times) < 50:
        return []
    nb = int(max(times) // 10) + 1
    bins = [0] * nb
    for t in times:
        if t >= 0:
            bins[int(t // 10)] += 1
    out = []
    for i, c in enumerate(bins):
        lo, hi = max(0, i - 30), min(nb, i + 30)
        base = max(1.0, statistics.median(bins[lo:hi]))
        if c >= 8 and c / base >= 2.5:
            out.append({"start": i * 10, "end": i * 10 + 10, "x": round(c / base, 1), "msgs": c})
    return out


_FW, _FW_LOCK = None, threading.Lock()


def wcfg(key, default=None):
    """Whisper setting: env CLIPWISE_WHISPER_<KEY> (per stream, may be "" to switch it off) beats config.json."""
    env = os.environ.get(f"CLIPWISE_WHISPER_{key.upper()}")
    return env if env is not None else CFG.get(f"whisper_{key}", default)


def whisper_settings():
    return {"model": wcfg("model", "small.en"), "language": wcfg("language", "en"), "prompt": wcfg("prompt", "")}


def use_run_whisper(info):
    """Re-use the Whisper settings a run was prepped with (stored in stream.json), unless env overrides them."""
    for k, v in (info.get("whisper") or {}).items():
        os.environ.setdefault(f"CLIPWISE_WHISPER_{k.upper()}", v or "")


def whisper_model():
    """faster-whisper (CTranslate2), CPU int8. Loaded once per process, shared by threads."""
    global _FW
    with _FW_LOCK:
        if _FW is None:
            from faster_whisper import WhisperModel
            _FW = WhisperModel(wcfg("model", "small.en"), device=os.environ.get("CLIPWISE_WHISPER_DEVICE", "cpu"),
                               compute_type=os.environ.get("CLIPWISE_WHISPER_COMPUTE", "int8"), num_workers=2,
                               download_root=CFG.get("whisper_dir"))
    return _FW


def transcribe(wav, out_base=None, words=False):
    """Speech -> text on this PC. words=True returns one entry per word (for the captions)."""
    try:
        import wave
        import numpy as np
        with wave.open(str(wav), "rb") as wf:  # our wavs are always 16 kHz mono 16-bit (ffmpeg -ac 1 -ar 16000)
            pcm = np.frombuffer(wf.readframes(wf.getnframes()), np.int16).astype(np.float32) / 32768.0
        if pcm.size < 1600:
            return []
        # whisper_language: "en" (default, needs small.en) or "auto" = detect per sentence, for streamers who
        # switch languages mid-stream (Hinglish etc.; needs a multilingual model such as "small")
        lang = wcfg("language", "en")
        lang_kw = {"language": None, "multilingual": True} if lang == "auto" else {"language": lang}
        if wcfg("prompt"):  # e.g. a Romanized Hinglish line: Whisper then writes Hindi in Latin letters
            lang_kw["initial_prompt"] = wcfg("prompt")
            # initial_prompt only steers the first 30 s window; hotwords go into EVERY window, so long audio
            # stays Hinglish instead of drifting into an English translation after the first window
            lang_kw["hotwords"] = wcfg("prompt")
        it, _ = whisper_model().transcribe(pcm, beam_size=1 if not words else 5,
                                           word_timestamps=words, vad_filter=True,
                                           condition_on_previous_text=False, **lang_kw)
        segs = []
        pairs = lambda x: (lambda w: list(zip(w, w[1:])))(re.sub(r"[^\w]+", " ", x.lower()).split())
        prompt_pairs = set(pairs(lang_kw.get("initial_prompt", "")))
        for s in it:
            # Whisper sometimes "hears" its prompt during music/silence (often reshuffled): drop prompt echoes
            sp = pairs(s.text)
            if prompt_pairs and len(set(sp) & prompt_pairs) >= 4 and sum(p in prompt_pairs for p in sp) >= 0.7 * len(sp):
                continue
            if words:
                for w in s.words or []:
                    if w.word.strip():
                        segs.append({"start": w.start, "end": w.end, "text": w.word.strip()})
            elif s.text.strip():
                segs.append({"start": s.start, "end": s.end, "text": s.text.strip()})
        return segs
    except Exception as e:
        raise RuntimeError(f"whisper failed: {e}")


def prep_one(url, cookies, force=False, mode="brand-safe"):
    t0 = time.time()
    meta = ytdlp_json(url, cookies, ["--no-playlist"])
    if meta.get("live_status") == "is_live" and meta.get("extractor_key", "").lower().startswith("youtube"):
        return {"url": url, "error": "still live on YouTube: clip it once the replay is up (Twitch archives work while live)"}
    streamer = meta.get("uploader") or meta.get("channel") or "streamer"
    rid = f"{dt.date.today()}-{slug(streamer, 24)}-{slug(str(meta.get('id')), 16)}"
    rd = RUNS / rid
    (rd / "chunks").mkdir(parents=True, exist_ok=True)
    (rd / "picks").mkdir(exist_ok=True)
    info = {"url": url, "webpage_url": meta.get("webpage_url") or url, "id": meta.get("id"),
            "title": meta.get("title"), "streamer": streamer, "platform": meta.get("extractor_key"),
            "duration": meta.get("duration"), "cookies": cookies, "whisper": whisper_settings(), "mode": mode}
    (rd / "stream.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    if (rd / "transcript.json").exists() and not force:
        log(f"[{streamer}] already prepped -> {rd}")
        return {"run": str(rd), "streamer": streamer, "cached": True}

    log(f"[{streamer}] 1/2 downloading audio only ({hms(meta.get('duration') or 0)} stream)")
    is_yt = "youtube" in (meta.get("extractor_key") or "").lower()
    with cf.ThreadPoolExecutor(2) as ex:
        fa = ex.submit(run, YTDLP + cookie_args(cookies) + ["--no-playlist", "-f", "bestaudio/audio_only/worst",
                                                             "-o", str(rd / "audio.%(ext)s"), url])
        fc = ex.submit(run, YTDLP + cookie_args(cookies) + ["--no-playlist", "--skip-download", "--write-subs",
                                                             "--sub-langs", "live_chat", "-o", str(rd / "chat"), url]) if is_yt else None
        ra = fa.result()
        if fc:
            fc.result()
    src = next((p for p in rd.glob("audio.*") if p.suffix not in (".part", ".ytdl", ".wav")), None)
    if not src:  # Twitch highlights / edited VODs break yt-dlp's own HLS downloader: retry through ffmpeg
        for p in rd.glob("audio.*"):
            p.unlink(missing_ok=True)
        ra = run(YTDLP + cookie_args(cookies) + ["--no-playlist", "--downloader", "m3u8:ffmpeg", "-f",
                                                 "bestaudio/audio_only/worst", "-o", str(rd / "audio.%(ext)s"), url])
        src = next((p for p in rd.glob("audio.*") if p.suffix not in (".part", ".ytdl", ".wav")), None)
    if not src:
        raise RuntimeError(f"audio download failed: {ra.stderr[-300:]}")
    wav = rd / "audio.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", "16000", str(wav)])
    src.unlink(missing_ok=True)
    t_dl = time.time()

    log(f"[{streamer}] 2/2 transcribing on this PC + scanning for loud moments and chat spikes")
    with cf.ThreadPoolExecutor(2) as ex:
        fs = ex.submit(transcribe, wav, rd / "whisper")
        fl = ex.submit(loud_moments, wav)
        segs = fs.result()
        loud, _ = fl.result()
    chat_file = next(iter(rd.glob("chat*.live_chat.json")), None)
    chat = chat_spikes(chat_file)
    wav.unlink(missing_ok=True)
    (rd / "whisper.json").unlink(missing_ok=True)
    (rd / "transcript.json").write_text(json.dumps(segs), encoding="utf-8")
    (rd / "signals.json").write_text(json.dumps({"loud": loud, "chat": chat}, indent=1), encoding="utf-8")

    # ---- 12-minute chunks with signal markers inline
    dur = meta.get("duration") or (segs[-1]["end"] if segs else 0)
    n = max(1, math.ceil(dur / CHUNK_SEC))
    for ci in range(n):
        a, b = ci * CHUNK_SEC, (ci + 1) * CHUNK_SEC
        lines = [f"# {streamer}: {info['title']}", f"Chunk {ci + 1}/{n}  ({hms(a)} to {hms(b)})",
                 f"Mode: {mode} (pick by references/modes.md; custom mode also reads rules.md in the run folder)",
                 "Markers: LOUD(+dB over normal) = streamer got loud. CHAT xN = chat moving N times faster than normal.", ""]
        for s in segs:
            if s["end"] <= a or s["start"] >= b:
                continue
            tags = []
            for e in loud:
                if e["start"] <= s["end"] and e["end"] + 1 >= s["start"]:
                    tags.append(f"LOUD(+{e['db']:.0f}dB)")
                    break
            for e in chat:  # chat reacts a few seconds late
                if e["start"] - 15 <= s["end"] and e["end"] >= s["start"]:
                    tags.append(f"CHAT x{e['x']}")
                    break
            lines.append(f"[{hms(s['start'])}] {s['text']}" + (f"   <<{' '.join(tags)}>>" if tags else ""))
        (rd / "chunks" / f"chunk_{ci + 1:02d}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    timing = {"prep_started": t0, "download_sec": round(t_dl - t0), "analyse_sec": round(time.time() - t_dl),
              "chunks": n, "segments": len(segs), "loud_events": len(loud), "chat_spikes": len(chat)}
    (rd / "timing.json").write_text(json.dumps(timing, indent=1), encoding="utf-8")
    log(f"[{streamer}] ready: {n} chunks, {len(loud)} loud moments, {len(chat)} chat spikes "
        f"({round(time.time() - t0)}s) -> {rd}")
    return {"run": str(rd), "streamer": streamer, "chunks": n}


def cmd_prep(a):
    RUNS.mkdir(parents=True, exist_ok=True)
    for k, v in LANGS[a.lang].items():  # per-stream Whisper settings; stored in stream.json, reused by render
        os.environ.setdefault(f"CLIPWISE_WHISPER_{k.upper()}", v)
    results = []
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        futs = {ex.submit(prep_one, u, a.cookies, a.force, a.mode): u for u in a.urls}
        for f in cf.as_completed(futs):
            try:
                results.append(f.result())
            except Exception as e:
                results.append({"url": futs[f], "error": str(e)})
                log(f"FAILED {futs[f]}: {e}")
    log("\nRUNS:")
    for r in results:
        log(f"  {r.get('run') or ''}  {r.get('error') or ''}")
    if results and all(r.get("error") for r in results):
        sys.exit(1)


# ---------------------------------------------------------------- status
def cmd_status(a):
    rd = Path(a.run)
    chunks = sorted((rd / "chunks").glob("chunk_*.md"))
    picked = {p.stem for p in (rd / "picks").glob("chunk_*.json")}
    todo = [c.name for c in chunks if c.stem not in picked]
    cands = sum(len(json.loads(p.read_text(encoding="utf-8"))) for p in (rd / "picks").glob("chunk_*.json"))
    info = json.loads((rd / "stream.json").read_text(encoding="utf-8")) if (rd / "stream.json").exists() else {}
    log(json.dumps({"run": str(rd), "streamer": info.get("streamer"), "mode": info.get("mode", "brand-safe"),
                    "custom_rules": (rd / "rules.md").exists(), "chunks": len(chunks), "picked_chunks": len(picked),
                    "candidates": cands,
                    "chunks_left": todo, "clips": sorted(x.name for x in (rd / "clips").glob("*.mp4"))
                    if (rd / "clips").exists() else []}, indent=1))


# ---------------------------------------------------------------- render (step 4)
def select(rd, top, min_score):
    segs = json.loads((rd / "transcript.json").read_text(encoding="utf-8"))
    cands = []
    for p in sorted((rd / "picks").glob("chunk_*.json")):
        try:
            for c in json.loads(p.read_text(encoding="utf-8")):
                c["_s"], c["_e"] = parse_ts(c["start"]), parse_ts(c["end"])
                cands.append(c)
        except Exception as e:
            log(f"  bad pick file {p.name}: {e}")
    total = len(cands)
    ok = []
    for c in sorted(cands, key=lambda c: -float(c.get("score", 0))):
        if float(c.get("score", 0)) < min_score:
            continue
        # snap to sentence boundaries so clips don't start/end mid-word
        st = max([s["start"] for s in segs if s["start"] <= c["_s"] + 0.5] or [c["_s"]])
        en = min([s["end"] for s in segs if s["end"] >= c["_e"] - 0.5] or [c["_e"]])
        if en - st > 75:
            en = st + 75
        if en - st < 12:
            continue
        if any(not (en + 20 < o["_s"] or st > o["_e"] + 20) for o in ok):
            continue
        c["_s"], c["_e"] = max(0, st - 0.25), en + 0.4
        ok.append(c)
        if len(ok) >= top:
            break
    return ok, total


def find_facecam(video, W, H):
    """Sample frames, find a face that sits in the same small spot (a facecam overlay),
    then find the overlay box edges from static straight lines around it."""
    import cv2
    import numpy as np
    cv2.setLogLevel(0) if hasattr(cv2, "setLogLevel") else None
    cap = cv2.VideoCapture(str(video))
    nfr = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 300
    det = None
    ym = CFG.get("yunet_model")
    if ym and Path(ym).exists():
        det = cv2.FaceDetectorYN.create(ym, "", (W, H), 0.75, 0.3, 50)
    haar = None
    if det is None and hasattr(cv2, "CascadeClassifier"):
        haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces, grads = [], []
    for i in range(12):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(nfr * (i + 0.5) / 12))
        ok, fr = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        grads.append((np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0)), np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1))))
        found = []
        if det is not None:
            _, res = det.detect(fr)
            if res is not None:
                found = [tuple(map(float, r[:4])) for r in res]
        elif haar is not None:
            found = [tuple(map(float, f)) for f in haar.detectMultiScale(g, 1.1, 6, minSize=(40, 40))]
        faces.append(found)
    cap.release()
    flat = [f for fs in faces for f in fs]
    if not flat:
        return {"mode": "gameplay"}
    # cluster by centre; keep the most persistent cluster
    best, best_n = None, 0
    for f in flat:
        cx, cy = f[0] + f[2] / 2, f[1] + f[3] / 2
        members = [g for g in flat if abs(g[0] + g[2] / 2 - cx) < W * 0.06 and abs(g[1] + g[3] / 2 - cy) < H * 0.08]
        if len(members) > best_n:
            best, best_n = members, len(members)
    if best_n < max(3, len(faces) * 0.4):
        return {"mode": "gameplay"}
    fx = statistics.median(m[0] for m in best); fy = statistics.median(m[1] for m in best)
    fw = statistics.median(m[2] for m in best); fh = statistics.median(m[3] for m in best)
    if fw > W * 0.2:  # face fills the screen: it's a camera view, not an overlay
        return {"mode": "cam", "face": [fx, fy, fw, fh]}

    gx = np.median(np.stack([g[0] for g in grads]), axis=0)  # vertical edges, static over time
    gy = np.median(np.stack([g[1] for g in grads]), axis=0)  # horizontal edges

    def scan(profile, start, stop):
        rng = range(int(start), int(stop), 1 if stop > start else -1)
        vals = [(profile[i], i) for i in rng if 0 <= i < len(profile)]
        if len(vals) < 5:
            return None
        v, i = max(vals)
        return i if v > 3.5 * (statistics.median(x for x, _ in vals) + 1e-3) and v > 6 else None

    y0, y1 = int(max(0, fy - fh * 0.5)), int(min(H, fy + fh * 1.5))
    x0, x1 = int(max(0, fx - fw * 0.5)), int(min(W, fx + fw * 1.5))
    colp = gx[y0:y1].mean(axis=0)
    rowp = gy[:, x0:x1].mean(axis=1)
    L = scan(colp, fx - fw * 0.15, fx - fw * 2.6)
    R = scan(colp, fx + fw * 1.15, fx + fw * 3.6)
    T = scan(rowp, fy - fh * 0.15, fy - fh * 2.2)
    B = scan(rowp, fy + fh * 1.15, fy + fh * 3.2)
    # fallbacks: typical facecam framing around the face
    cw_guess = fw * 3.4
    ch_guess = cw_guess * 0.75
    L = L if L is not None else fx + fw / 2 - cw_guess / 2
    R = R if R is not None else fx + fw / 2 + cw_guess / 2
    T = T if T is not None else fy + fh * 0.45 - ch_guess * 0.45
    B = B if B is not None else fy + fh * 0.45 + ch_guess * 0.55
    L, R = max(0, L + 2), min(W, R - 2)
    T, B = max(0, T + 2), min(H, B - 2)
    if R - L < fw * 1.4 or B - T < fh * 1.4:
        return {"mode": "gameplay"}
    return {"mode": "facecam", "box": [int(L), int(T), int(R - L), int(B - T)], "face": [fx, fy, fw, fh]}


INDIC_RE = re.compile(r"[\u0900-\u0DFF]")  # Devanagari, Gurmukhi, Gujarati, Bengali, Tamil, Telugu, ...


def font(size, text=""):
    from PIL import ImageFont
    fonts = Path(os.environ.get("WINDIR", r"C:\\Windows")) / "Fonts"
    if INDIC_RE.search(text or "") and (fonts / "Nirmala.ttc").exists():
        return ImageFont.truetype(str(fonts / "Nirmala.ttc"), size, index=1)  # Nirmala UI Bold: Indic + Latin
    for f in (CFG.get("caption_font") or "",  # optional override in ~/.clipwise/config.json
              fonts / "ariblk.ttf", fonts / "impact.ttf", fonts / "arialbd.ttf",  # Windows
              "/System/Library/Fonts/Supplemental/Arial Black.ttf", "/Library/Fonts/Arial Black.ttf",  # macOS
              "/System/Library/Fonts/Supplemental/Impact.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/usr/share/fonts/truetype/msttcorefonts/Arial_Black.ttf",  # Linux
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
              "/usr/share/fonts/liberation-sans/LiberationSans-Bold.ttf"):
        if f and Path(f).exists():
            return ImageFont.truetype(str(f), size)
    try:  # Pillow >= 10.1 ships a scalable default font
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def wrap(draw, text, fnt, maxw):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=fnt) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def caption_frames(words, hook, seam_y, cap_y, dur, outdir):
    """Build one transparent 1080x1920 PNG per caption state + an ffconcat list."""
    from PIL import Image, ImageDraw
    outdir.mkdir(exist_ok=True)
    hf = font(50, hook or "")

    def base():
        im = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        if hook:
            lines = wrap(d, censor(hook).upper(), hf, 900)[:3]
            lh = 62
            bh = lh * len(lines) + 34
            top = seam_y - bh // 2
            bw = max(d.textlength(l, font=hf) for l in lines) + 60
            d.rounded_rectangle([540 - bw / 2, top, 540 + bw / 2, top + bh], 18, fill=(255, 255, 255, 255))
            for i, l in enumerate(lines):
                d.text((540, top + 17 + i * lh + lh / 2), l, font=hf, fill=(0, 0, 0), anchor="mm")
        return im

    # group words into 1-3 word chunks
    groups, cur = [], []
    for w in words:
        if cur and (len(cur) >= 3 or w["s"] - cur[-1]["e"] > 0.45 or re.search(r"[.?!,]$", cur[-1]["t"])):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)

    states = []  # (t0, t1, group, active_idx)
    for g in groups:
        for i, w in enumerate(g):
            t1 = g[i + 1]["s"] if i + 1 < len(g) else w["e"]
            states.append((w["s"], max(t1, w["s"] + 0.08), g, i))
    timeline, t, k = [], 0.0, 0
    blank = outdir / "blank.png"
    base().save(blank)
    for t0, t1, g, ai in states:
        if t0 > t + 0.02:
            timeline.append((blank, t0 - t))
        im = base()
        d = ImageDraw.Draw(im)
        text = [w["t"].upper() for w in g]
        cf_ = font(84, " ".join(text))
        widths = [d.textlength(x, font=cf_) for x in text]
        space = d.textlength(" ", font=cf_)
        total = sum(widths) + space * (len(text) - 1)
        scale_font = cf_
        if total > 1000:
            scale_font = font(int(84 * 1000 / total), " ".join(text))
            widths = [d.textlength(x, font=scale_font) for x in text]
            space = d.textlength(" ", font=scale_font)
            total = sum(widths) + space * (len(text) - 1)
        x = 540 - total / 2
        for j, (word, wd) in enumerate(zip(text, widths)):
            d.text((x, cap_y), word, font=scale_font, anchor="lm",
                   fill=(255, 221, 0) if j == ai else (255, 255, 255), stroke_width=7, stroke_fill=(0, 0, 0))
            x += wd + space
        p = outdir / f"c{k:04d}.png"
        im.save(p)
        k += 1
        start = max(t, t0)
        timeline.append((p, max(0.04, t1 - start)))
        t = start + max(0.04, t1 - start)
    if t < dur:
        timeline.append((blank, dur - t))
    lst = outdir / "list.ffconcat"
    body = ["ffconcat version 1.0"]
    for p, d_ in timeline:
        body += [f"file '{p.name}'", f"duration {d_:.3f}"]
    body.append(f"file '{timeline[-1][0].name}'")
    lst.write_text("\n".join(body) + "\n", encoding="utf-8")
    return lst


def av_start_gap(f):
    """Seconds the video track starts after the audio track (0 if unknown)."""
    try:
        st = json.loads(run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,start_time",
                             "-of", "json", str(f)]).stdout)["streams"]
        v = min(float(s["start_time"]) for s in st if s["codec_type"] == "video")
        a = min(float(s["start_time"]) for s in st if s["codec_type"] == "audio")
        return v - a
    except Exception:
        return 0.0


_DEV_CONS = dict(zip("कखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसहळ",
                     "k kh g gh n ch chh j jh n t th d dh n t th d dh n p f b bh m y r l v sh sh s h l".split()))
# nukta forms, precomposed (U+0958..U+095F) and base+nukta
_DEV_NUKTA = {"क़": "q", "ख़": "kh", "ग़": "gh", "ज़": "z", "ड़": "d", "ढ़": "dh",
              "फ़": "f", "य़": "y"}
_DEV_NUKTA_BASE = {"क": "q", "ख": "kh", "ग": "gh", "ज": "z", "ड": "d", "ढ": "dh", "फ": "f", "य": "y"}
_DEV_VOW = dict(zip("अआइईउऊऋएऐओऔऑऍ", "a aa i ee u oo ri e ai o au o e".split()))
_DEV_MATRA = dict(zip("ािीुूृेैोौॉॅ", "aa i ee u oo ri e ai o au o e".split()))
_NASAL = "ंँ"  # anusvara, chandrabindu
_FINAL = {"aa": "a", "ee": "i", "oo": "u"}  # word-final long vowels are written short in Hinglish (raha, rahi)


def hinglish(word):
    """Devanagari word -> casual Hinglish spelling (इसको isko, करना karna, नहीं nahin, में mein, यार yaar)."""
    w, out, i = word, [], 0
    n = len(w)
    dev = lambda c: "ऀ" <= c <= "ॿ"
    at_end = lambda j: all(c in _NASAL or not dev(c) for c in w[j:])  # nothing but nasal marks left

    def cons(j):  # consonant at j -> (latin, chars used) or None
        c = w[j] if j < n else ""
        if c in _DEV_NUKTA:
            return _DEV_NUKTA[c], 1
        if c in _DEV_CONS:
            if j + 1 < n and w[j + 1] == "़":
                return _DEV_NUKTA_BASE.get(c, _DEV_CONS[c]), 2
            return _DEV_CONS[c], 1
        return None

    while i < n:
        ch = w[i]
        cv = cons(i)
        if cv:
            out.append(cv[0])
            i += cv[1]
            nx = w[i] if i < n else ""
            if nx in _DEV_MATRA:
                v = _DEV_MATRA[nx]
                if v == "aa" and i + 1 < n and w[i + 1] in "ईइ":  # भाई -> bhai
                    v = "a"
                elif at_end(i + 1):
                    v = _FINAL.get(v, v)
                    if v == "e" and i + 1 < n and w[i + 1] in _NASAL:  # में -> mein
                        v = "ei"
                out.append(v)
                i += 1
            elif nx == "्":  # halant: no vowel
                i += 1
            else:
                # inherent 'a': dropped at the word end, and before a consonant that carries a vowel sign
                nxt = cons(i)
                after = w[i + nxt[1]] if nxt and i + nxt[1] < n else ""
                if not (at_end(i) or (len(out) > 1 and nxt and after in _DEV_MATRA)):
                    out.append("a")
            continue
        if ch in _DEV_VOW:
            v = _DEV_VOW[ch]
            out.append(_FINAL.get(v, v) if at_end(i + 1) else v)
        elif ch in _NASAL:
            out.append("n")
        elif ch == "ः":
            out.append("h")
        elif ch in "।॥":
            out.append(".")
        elif "०" <= ch <= "९":
            out.append(str(ord(ch) - 0x966))
        elif not dev(ch):
            out.append(ch)
        i += 1
    return "".join(out).replace("chchh", "chh")  # अच्छा -> achha


# Curse words in on-screen text keep their first and last letter; up to 3 letters in between become *.
# Roots matched anywhere inside a word (fucking, motherfucker, bullshit, niggas, bitches, dickhead...)
_CURSE_ANY = ["motherfuck", "fuck", "shit", "nigger", "nigga", "nigg", "bitch", "pussy", "cunt", "whore",
              "slut", "bastard", "dick", "damn", "asshole", "phuck", "fck", "sh1t"]
# short roots only matched as whole words (or with a known prefix), so class/assist/shoe/cucumber stay clean
_CURSE_WORD = re.compile(r"^(?P<pre>dumb|jack|bad|smart|lame|kick|broke|bum|punk|fat|big|wise|bitch)?"
                         r"(?P<root>ass|asses|hoe|hoes|cock|cocks|tits|titties|cum|prick|thot|thots)$", re.I)


def _mask(root):
    if len(root) <= 2:
        return root
    n = min(3, len(root) - 2)
    return root[0] + "*" * n + root[1 + n:]


CENSOR = True  # render --no-censor turns it off (only when the user explicitly asks)


def censor(text):
    """Mask curse words for on-screen captions: fuck -> f**k, shit -> s**t, nigga -> n***a, bitch -> b***h."""
    if not CENSOR:
        return text

    def word(m):
        w = m.group()
        lw = w.lower()
        mw = _CURSE_WORD.match(w)
        if mw:
            i = mw.start("root")
            root = mw.group("root")
            core = root[:-1] if root.lower() in ("asses", "hoes", "cocks", "thots") else root
            return w[:i] + _mask(core) + w[i + len(core):]
        for r in _CURSE_ANY:
            i = lw.find(r)
            if i >= 0:
                if r == "motherfuck":  # keep it readable: motherf**k...
                    i, r = i + 6, "fuck"
                return w[:i] + _mask(w[i:i + len(r)]) + censor(w[i + len(r):])
        return w
    return re.sub(r"[A-Za-z0-9]+", word, text)


def latin_caption(text):
    import unicodedata
    t = re.sub(r"[ऀ-ॿ]+", lambda m: hinglish(m.group()), text)
    t = unicodedata.normalize("NFKD", t)  # é -> e + accent mark, then the mark is dropped below
    return re.sub(r"[^\x00-\x7f]", "", t).strip()  # anything else non-Latin (other scripts, junk) is dropped


def clip_words(src, ss, dur, work):
    wav = work / "w.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{ss:.2f}", "-t", f"{dur:.2f}", "-i", str(src),
         "-ac", "1", "-ar", "16000", str(wav)])
    segs = transcribe(wav, work / "words", words=True)
    words = []
    for s in segs:
        # captions are always in English letters: Hindi in Devanagari becomes Hinglish spelling, other scripts drop
        t = censor(latin_caption(s["text"].strip()))
        if not t or re.fullmatch(r"\[.*\]|\(.*\)", t):
            continue
        if re.fullmatch(r"[^\w]+", t) and words:
            words[-1]["t"] += t
            continue
        words.append({"t": t, "s": s["start"], "e": s["end"]})
    wav.unlink(missing_ok=True)
    return words


def render_one(rd, info, c, n, cookies, keep, local_src=None, src_start=None):
    """local_src/src_start: a file already on disk that starts at stream time src_start
    (the live clipper cuts from its buffer instead of downloading)."""
    clips = rd / "clips"
    clips.mkdir(exist_ok=True)
    work = rd / f"work_{n:02d}"
    work.mkdir(exist_ok=True)
    pad = 3.0
    a, b = max(0, c["_s"] - pad), c["_e"] + 1
    if local_src is not None:
        a = src_start
    src = Path(local_src) if local_src is not None else next(work.glob("src.*"), None)
    if not src:
        r = run(YTDLP + cookie_args(cookies) + ["--no-playlist", "-f",
                "bv*[height<=1080][fps<=60]+ba/b[height<=1080]/bv*+ba/b", "--download-sections", f"*{a:.1f}-{b:.1f}",
                "--merge-output-format", "mp4", "-o", str(work / "src.%(ext)s"), info["webpage_url"]])
        src = next((p for p in work.glob("src.*") if p.suffix in (".mp4", ".mkv", ".webm")), None)
        if not src:
            raise RuntimeError("section download failed: " + r.stderr[-300:])
    if src.suffix.lower() == ".ts":
        # MPEG-TS has no keyframe index: -ss lands mid-GOP, the video can't decode until the next keyframe
        # while the audio starts at once, so the clip's video track starts 0-2 s after its audio. Phones and
        # TikTok/Shorts line both tracks up at 0, which plays as audio ~1 s late. MP4 seeks frame-accurately.
        mp4 = work / "src_seek.mp4"
        r = run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0",
                 "-c", "copy", str(mp4)])
        if r.returncode == 0 and mp4.exists():
            src = mp4
    pr = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                         "stream=width,height:format=duration", "-of", "json", str(src)]).stdout)
    W, H = pr["streams"][0]["width"], pr["streams"][0]["height"]
    sdur = float(pr["format"]["duration"])
    ss = min(c["_s"] - a, max(0, sdur - 5))
    dur = min(c["_e"] - c["_s"], sdur - ss)

    fc = find_facecam(src, W, H)
    forced = c.get("layout")  # per-pick override when the detector gets it wrong (scene switches mid-clip)
    if forced == "gameplay" or (forced == "cam" and "face" not in fc):
        fc = {"mode": "gameplay"}
    elif forced == "cam":
        fc = {"mode": "cam", "face": fc["face"]}
    if fc["mode"] == "facecam":
        L, T, cw, ch = fc["box"]
        top_h = int(min(960, max(560, 1080 * ch / cw)))
        top_h -= top_h % 2
        bot_h = 1920 - top_h
        gw, gh = H * 1080 / bot_h, H
        if gw > W:
            gw, gh = W, W * bot_h / 1080
        gx, gy = (W - gw) / 2, (H - gh) / 2
        if os.environ.get("FACECAM_FIT") == "1":  # whole cam visible (zoomed out) over a blurred fill, sharpened
            zf = float(os.environ.get("FACECAM_ZOOM", "0.9"))
            fw_, fh_ = int(1080 * zf) // 2 * 2, int(top_h * zf) // 2 * 2
            topf = (f"[a]crop={cw}:{ch}:{L}:{T},split[ca][cb];"
                    f"[ca]scale=1080:{top_h}:force_original_aspect_ratio=increase,crop=1080:{top_h},boxblur=24:2,eq=brightness=-0.12[cbg];"
                    f"[cb]scale={fw_}:{fh_}:force_original_aspect_ratio=decrease:flags=lanczos,unsharp=5:5:0.7[cfg];"
                    f"[cbg][cfg]overlay=(W-w)/2:(H-h)/2[top];")
        else:
            topf = f"[a]crop={cw}:{ch}:{L}:{T},scale=1080:{top_h}:force_original_aspect_ratio=increase,crop=1080:{top_h}[top];"
        vf = (f"[0:v]fps=30,split[a][b];" + topf +
              f"[b]crop={int(gw)}:{int(gh)}:{int(gx)}:{int(gy)},scale=1080:{bot_h}[bot];[top][bot]vstack[base]")
        seam, cap_y = top_h, top_h + int(bot_h * 0.58)
    elif fc["mode"] == "cam":
        fx, fy, fw, fh = fc["face"]
        cw = min(W, H * 9 / 16)
        cx = min(max(0, fx + fw / 2 - cw / 2), W - cw)
        vf = f"[0:v]fps=30,crop={int(cw)}:{H}:{int(cx)}:0,scale=1080:1920[base]"
        seam, cap_y = 300, 1380
    else:  # no facecam: full frame in the middle over a blurred fill
        vf = ("[0:v]fps=30,split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
              "boxblur=30:3,eq=brightness=-0.15[bg];[b]scale=1080:-2[fg];[bg][fg]overlay=0:(H-h)/2[base]")
        seam, cap_y = 560, 1420
    out = clips / f"clip_{n:02d}_{slug(c.get('title') or c.get('hook'), 40)}.mp4"
    for attempt in range(2):
        words = clip_words(src, ss, dur, work)
        lst = caption_frames(words, c.get("hook") or c.get("title"), seam, cap_y, dur, work / "cap")
        r = run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
                 "-f", "concat", "-safe", "0", "-i", str(lst), "-filter_complex",
                 vf + ";[1:v]format=rgba[ov];[base][ov]overlay=0:0:eof_action=repeat:format=auto,format=yuv420p[v];"
                 "[0:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]",
                 "-map", "[v]", "-map", "[aout]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)])
        if r.returncode != 0:
            raise RuntimeError("render failed: " + r.stderr[-500:])
        lag = av_start_gap(out)
        if lag <= 0.1:
            break
        if attempt:
            log(f"  WARNING: video still starts {lag:.2f}s after the audio in {out.name}")
            break
        # the source has no decodable video for the first `lag` s: start the clip there so both tracks begin at 0
        log(f"  video started {lag:.2f}s after the audio: moving the clip start so they line up")
        ss, dur = ss + lag, dur - lag
    tags = " ".join(c.get("hashtags") or ["#" + re.sub(r"\W", "", info.get("streamer") or "clips"), "#clips", "#gaming"])
    post = (f"TITLE: {c.get('title', '')}\n\nCAPTION:\n{c.get('caption', '')}\n\n{tags}\n\n"
            f"Source: {info['streamer']}, {info['webpage_url']} at {hms(c['_s'])}\n"
            f"Category: {c.get('category')}  Score: {c.get('score')}  Layout: {fc['mode']}\n")
    out.with_suffix(".txt").write_text(post, encoding="utf-8")
    if not keep:
        shutil.rmtree(work, ignore_errors=True)
        if local_src is not None:
            Path(local_src).unlink(missing_ok=True)
    return out, fc["mode"]


def cmd_render(a):
    global CENSOR
    rd = Path(a.run)
    info = json.loads((rd / "stream.json").read_text(encoding="utf-8"))
    use_run_whisper(info)  # captions with the same language/prompt the transcript was made with
    CENSOR = not a.no_censor
    t0 = time.time()
    picks, total = select(rd, a.top, a.min_score)
    log(f"[{info['streamer']}] {total} possible moments -> keeping best {len(picks)}")
    made = []
    for n, c in enumerate(picks, 1):
        try:
            out, mode = render_one(rd, info, c, n, a.cookies or info.get("cookies"), a.keep)
            made.append({"file": str(out), "title": c.get("title"), "score": c.get("score"), "layout": mode,
                         "at": hms(c["_s"]), "len": round(c["_e"] - c["_s"])})
            log(f"  clip {n}: {c.get('title')}  ({hms(c['_s'])}, {round(c['_e'] - c['_s'])}s, {mode}) -> {out.name}")
        except Exception as e:
            log(f"  clip {n} FAILED: {e}")
    tm = json.loads((rd / "timing.json").read_text(encoding="utf-8")) if (rd / "timing.json").exists() else {}
    tm["render_sec"] = round(time.time() - t0)
    tm["total_sec"] = round(time.time() - tm.get("prep_started", t0))
    (rd / "timing.json").write_text(json.dumps(tm, indent=1), encoding="utf-8")
    summary = {"stream": info["title"], "streamer": info["streamer"], "length": hms(info.get("duration") or 0),
               "moments_found": total, "clips": made, "total_time": hms(tm["total_sec"])}
    (rd / "clips" / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    log(f"\n{info['streamer']}: {summary['length']} stream -> {total} moments -> {len(made)} clips "
        f"(total {summary['total_time']}) -> {rd / 'clips'}")


# ---------------------------------------------------------------- main
def main():
    if not (HOME / ".ready").exists():
        sys.exit("Not set up yet. Run: " + SETUP_HINT)
    p = argparse.ArgumentParser(prog="clipwise")
    sp = p.add_subparsers(dest="cmd", required=True)
    d = sp.add_parser("discover"); d.add_argument("--limit", type=int, default=7)
    d.add_argument("--game", required=True, help='game to search for, e.g. "GTA 6", "Valorant", "Minecraft"')
    pr = sp.add_parser("prep"); pr.add_argument("urls", nargs="+")
    pr.add_argument("--cookies", help="firefox / edge / chrome / safari, or a cookies.txt path (age-restricted YouTube, Kick). On Windows firefox or cookies.txt is the reliable one")
    pr.add_argument("--jobs", type=int, default=2, help="streams processed at once (2 is safe on a 16 GB PC)")
    pr.add_argument("--force", action="store_true")
    pr.add_argument("--lang", choices=sorted(LANGS), default="en",
                    help="en (default) | hinglish: Hindi+English, captions in English letters | auto: any other language")
    pr.add_argument("--mode", choices=["brand-safe", "unhinged", "custom"], default="brand-safe",
                    help="picking rules for this stream (references/modes.md); stored in stream.json")
    s = sp.add_parser("status"); s.add_argument("run")
    r = sp.add_parser("render"); r.add_argument("run")
    r.add_argument("--top", type=int, default=3); r.add_argument("--min-score", type=float, default=7.0)
    r.add_argument("--cookies"); r.add_argument("--keep", action="store_true", help="keep downloaded source sections")
    r.add_argument("--no-censor", action="store_true", help="show curse words in full in captions (only if the user asks)")
    a = p.parse_args()
    {"discover": cmd_discover, "prep": cmd_prep, "status": cmd_status, "render": cmd_render}[a.cmd](a)


if __name__ == "__main__":
    main()
