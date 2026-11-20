#!/usr/bin/env bash
# Clipwise setup (macOS + Linux): checks what this computer needs, installs what's missing, says when it's ready.
# Safe to re-run any time (it also updates yt-dlp, which fixes most download errors).
# Everything goes into ~/.clipwise (or $CLIPWISE_HOME), outside the skill/plugin folder, so updating the
# plugin never deletes the ~1 GB of models. No sudo needed (on macOS, FFmpeg comes from Homebrew if you have it).
# Run:  bash setup.sh
set -u

HOME2="${CLIPWISE_HOME:-$HOME/.clipwise}"
VENV="$HOME2/.venv"
MODELS="$HOME2/models"
BIN="$HOME2/bin"
mkdir -p "$MODELS" "$BIN"
FAILED=0
ok()   { echo "  [ok]      $1"; }
inst() { echo "  [install] $1"; }
fail() { echo "  [MISSING] $1"; FAILED=1; }
warn() { echo "  [warn]    $1"; }
have() { command -v "$1" >/dev/null 2>&1; }
dl()   { # dl URL FILE
  if have curl; then curl -fsSL --retry 3 -o "$2" "$1"; elif have wget; then wget -q -O "$2" "$1"; else return 1; fi
}

OS="$(uname -s)"; ARCH="$(uname -m)"
echo "Clipwise setup ($OS $ARCH) -> $HOME2"
case "$OS" in Darwin|Linux) ;; *) echo "This script is for macOS and Linux. On Windows run scripts/setup.ps1."; exit 1 ;; esac
if ! have curl && ! have wget; then echo "Needs curl or wget. Install one and re-run."; exit 1; fi
export PATH="$BIN:$BIN/ffmpeg:$HOME/.deno/bin:$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# 1. FFmpeg + FFprobe (cutting, encoding, loudness)
FF="$(command -v ffmpeg || true)"; FP="$(command -v ffprobe || true)"
if [ -z "$FF" ] || [ -z "$FP" ]; then
  if [ "$OS" = "Darwin" ]; then
    if have brew; then inst "FFmpeg (Homebrew, a few minutes)"; brew install ffmpeg >/dev/null 2>&1 || true
    else warn "Homebrew not found. Install it from https://brew.sh, then re-run (or: install FFmpeg yourself)."; fi
  else
    # BtbN static builds (same family as the Windows setup). Not johnvansickle's: those segfault on HTTPS input.
    case "$ARCH" in x86_64|amd64) FA="linux64" ;; aarch64|arm64) FA="linuxarm64" ;; *) FA="" ;; esac
    if [ -n "$FA" ]; then
      inst "FFmpeg (static build, ~100 MB)"
      TMP="$(mktemp -d)"
      if dl "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-$FA-gpl.tar.xz" "$TMP/ff.tar.xz" \
         && tar -xf "$TMP/ff.tar.xz" -C "$TMP"; then
        D="$(find "$TMP" -maxdepth 1 -type d -name 'ffmpeg-*' | head -1)"
        [ -n "$D" ] && cp "$D/bin/ffmpeg" "$D/bin/ffprobe" "$BIN/" && chmod +x "$BIN/ffmpeg" "$BIN/ffprobe"
      fi
      rm -rf "$TMP"
    else warn "No prebuilt FFmpeg for $ARCH: install it with your package manager (e.g. sudo apt install ffmpeg)."; fi
  fi
  FF="$(command -v ffmpeg || true)"; FP="$(command -v ffprobe || true)"
fi
if [ -n "$FF" ] && [ -n "$FP" ]; then ok "FFmpeg ($FF)"
else fail "FFmpeg (macOS: brew install ffmpeg; Linux: sudo apt install ffmpeg, then re-run)"; fi

# 2. Deno (yt-dlp needs a JavaScript runtime for YouTube)
if ! have deno; then
  inst "Deno"
  if ! have unzip && [ "$OS" = "Linux" ]; then warn "Deno's installer needs 'unzip' (sudo apt install unzip)"; fi
  (curl -fsSL https://deno.land/install.sh | sh -s -- -y >/dev/null 2>&1) || true
fi
DENO="$(command -v deno || true)"
if [ -n "$DENO" ]; then ok "Deno"; else fail "Deno (https://deno.com, then re-run)"; fi

# 3. uv (fast Python + venv manager; also brings Python 3.12, no system Python needed)
if ! have uv; then
  inst "uv"
  (curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1) || true
fi
UV="$(command -v uv || true)"
if [ -n "$UV" ]; then ok "uv"; else fail "uv (https://docs.astral.sh/uv/, then re-run)"; fi

# 4. Python environment: yt-dlp (always latest), faster-whisper (speech to text), OpenCV (facecam), Pillow (captions)
# --native-tls: uv trusts the OS certificate store, so antivirus HTTPS scanning (Norton, Avast...) does not break it
PY="$VENV/bin/python"
if [ -n "$UV" ]; then
  if [ ! -x "$PY" ]; then inst "Python 3.12 environment"; "$UV" venv -q --native-tls --python 3.12 "$VENV" || true; fi
  inst "Python packages (first run downloads ~150 MB)"
  if "$UV" pip install -q --native-tls --python "$PY" -U "yt-dlp[default]" faster-whisper opencv-python-headless pillow numpy truststore; then
    ok "Python packages (yt-dlp, faster-whisper, opencv, pillow, numpy, truststore)"
  else fail "Python packages"; fi
fi

# 5. Whisper model (speech -> text, runs on this computer). Downloaded once (~480 MB).
# English model by default; Hinglish/other languages download the multilingual "small" model on first use.
WHISPER_DIR="$MODELS/whisper"
WMODEL="small.en"
if [ -x "$PY" ] && [ -f "$HOME2/config.json" ]; then
  WMODEL="$("$PY" -c "import json;print(json.load(open('$HOME2/config.json')).get('whisper_model') or 'small.en')" 2>/dev/null || echo small.en)"
fi
if [ -x "$PY" ]; then
  inst "Whisper $WMODEL model (skips if already downloaded)"
  if "$PY" - "$WMODEL" "$WHISPER_DIR" <<'EOF'
import sys
try:
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass
from faster_whisper import WhisperModel
WhisperModel(sys.argv[1], device="cpu", compute_type="int8", download_root=sys.argv[2])
EOF
  then ok "Whisper model"; else fail "Whisper model (check your internet and re-run)"; fi
fi

# 6. Face detector (YuNet, ~230 KB) used to find the facecam box
YUNET="$MODELS/face_detection_yunet_2023mar.onnx"
size_of() { wc -c <"$1" 2>/dev/null | tr -d ' ' || echo 0; }
if [ ! -f "$YUNET" ] || [ "$(size_of "$YUNET")" -lt 100000 ]; then
  inst "YuNet face detector"
  dl "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx" "$YUNET" || true
fi
if [ -f "$YUNET" ] && [ "$(size_of "$YUNET")" -gt 100000 ]; then ok "Face detector"; else fail "Face detector"; fi

# 7. Caption font (bold sans: Arial Black on macOS, DejaVu/Liberation on Linux)
FONT=""
for f in "/System/Library/Fonts/Supplemental/Arial Black.ttf" "/Library/Fonts/Arial Black.ttf" \
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf" \
         /usr/share/fonts/truetype/msttcorefonts/Arial_Black.ttf \
         /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf /usr/share/fonts/dejavu/DejaVuSans-Bold.ttf \
         /usr/share/fonts/TTF/DejaVuSans-Bold.ttf /usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf \
         /usr/share/fonts/liberation-sans/LiberationSans-Bold.ttf; do
  [ -f "$f" ] && { FONT="$f"; break; }
done
if [ -n "$FONT" ]; then ok "Caption font ($(basename "$FONT"))"
else warn "No bold caption font found (Linux: sudo apt install fonts-dejavu-core). Captions use a fallback font."; fi

# 8. Free space
FREE_GB="$(df -Pk "$HOME2" | awk 'NR==2 {print int($4/1024/1024)}')"
if [ "${FREE_GB:-0}" -lt 3 ]; then warn "Only ${FREE_GB} GB free. Each stream needs ~0.5-1 GB while it runs."; else ok "Disk space (${FREE_GB} GB free)"; fi

# config.json: absolute tool folders so it works before the terminal is restarted (keeps earlier whisper settings)
if [ -x "$PY" ]; then
  DIRS=""
  for x in "$FF" "$DENO"; do [ -n "$x" ] && DIRS="$DIRS$(dirname "$x")
"; done
  "$PY" - "$HOME2/config.json" "$WHISPER_DIR" "$YUNET" "$FONT" "$DIRS" <<'EOF'
import json, os, sys
path, wdir, yunet, font, dirs = sys.argv[1:6]
cfg = {}
if os.path.exists(path):
    try:
        cfg = json.load(open(path, encoding="utf-8-sig"))
    except Exception:
        cfg = {}
cfg.setdefault("whisper_model", "small.en")
cfg.setdefault("whisper_language", "en")
cfg.update({"whisper_dir": wdir, "yunet_model": yunet, "path_dirs": [d for d in dirs.splitlines() if d]})
if font:
    cfg["caption_font"] = font
json.dump(cfg, open(path, "w", encoding="utf-8"))
EOF
fi

if [ "$FAILED" -eq 0 ]; then
  date -u +%Y-%m-%dT%H:%M:%S > "$HOME2/.ready"
  echo ""; echo "READY. Python: $PY"
  echo "Say: clip this stream <link>   or   find me today's biggest <game> streams and clip them"
  exit 0
else
  rm -f "$HOME2/.ready"
  echo ""; echo "NOT READY: fix the [MISSING] items above and re-run setup."
  exit 1
fi
