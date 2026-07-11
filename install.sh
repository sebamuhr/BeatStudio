#!/usr/bin/env bash
# Beat Studio — one-command installer (Linux only, for now).
#
#   From a clone:   ./install.sh [--with-ai]
#   One-liner:      curl -fsSL https://raw.githubusercontent.com/sebamuhr/BeatStudio/master/install.sh | bash
#
# It sets up a self-contained Python virtualenv, installs the audio library,
# and adds a "Beat Studio" launcher to your apps menu. Nothing touches system Python.
set -euo pipefail

REPO_URL="https://github.com/sebamuhr/BeatStudio.git"
WITH_AI=0
for a in "$@"; do [ "$a" = "--with-ai" ] && WITH_AI=1; done

say()  { printf '\033[1;36m▸ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Linux" ] || die "Beat Studio installs on Linux only for now."

# ---- locate the repo, or clone it if we were piped from curl ----
SELF="${BASH_SOURCE[0]:-}"
if [ -n "$SELF" ] && [ -f "$(dirname "$SELF")/desktop/app.py" ]; then
  REPO="$(cd "$(dirname "$SELF")" && pwd)"
else
  command -v git >/dev/null || die "git is required (sudo apt install git), then re-run."
  REPO="${BEATSTUDIO_DIR:-$HOME/BeatStudio}"
  if [ -d "$REPO/.git" ]; then
    say "Updating existing install at $REPO"
    git -C "$REPO" pull --ff-only || warn "couldn't fast-forward; using what's already there"
  else
    say "Cloning Beat Studio into $REPO"
    git clone --depth 1 "$REPO_URL" "$REPO"
  fi
fi
DESK="$REPO/desktop"
[ -f "$DESK/app.py" ] || die "couldn't find the app at $DESK"

# ---- python ----
PY="$(command -v python3 || true)"
[ -n "$PY" ] || die "python3 is required (3.10+)."
say "Using $("$PY" --version 2>&1)"

# ---- system audio library (PortAudio) for sound output ----
have_portaudio() {
  ldconfig -p 2>/dev/null | grep -qi portaudio && return 0
  /sbin/ldconfig -p 2>/dev/null | grep -qi portaudio && return 0
  ls /usr/lib/*/libportaudio.so* /lib/*/libportaudio.so* /usr/lib/libportaudio.so* 2>/dev/null | grep -q . && return 0
  return 1
}
if ! have_portaudio; then
  say "Installing PortAudio (system audio library)…"
  if   command -v apt-get >/dev/null; then sudo apt-get update -qq && sudo apt-get install -y libportaudio2 || warn "apt install failed"
  elif command -v dnf     >/dev/null; then sudo dnf install -y portaudio || warn "dnf install failed"
  elif command -v pacman  >/dev/null; then sudo pacman -S --noconfirm portaudio || warn "pacman install failed"
  elif command -v zypper  >/dev/null; then sudo zypper install -y libportaudio2 || warn "zypper install failed"
  else warn "Couldn't detect your package manager — install 'portaudio' (a.k.a. libportaudio2) manually for sound."
  fi
fi

# ---- virtualenv + Python dependencies ----
if [ ! -x "$DESK/.venv/bin/python" ]; then
  say "Creating a self-contained Python environment…"
  "$PY" -m venv "$DESK/.venv" \
    || die "venv failed. On Debian/Ubuntu run: sudo apt install python3-venv  — then re-run."
fi
VPY="$DESK/.venv/bin/python"
say "Installing Python dependencies (this can take a minute)…"
"$VPY" -m pip install --upgrade pip -q
"$VPY" -m pip install -q -r "$DESK/requirements.txt"

if [ "$WITH_AI" = "1" ]; then
  say "Installing optional AI sound-matching (CPU torch + transformers) — this is large…"
  "$VPY" -m pip install -q --index-url https://download.pytorch.org/whl/cpu torch || warn "torch install failed (AI matching stays off)"
  "$VPY" -m pip install -q transformers || warn "transformers install failed (AI matching stays off)"
fi

# ---- launcher: apps menu + a `beatstudio` command ----
chmod +x "$DESK/run.sh"
APPS="$HOME/.local/share/applications"; mkdir -p "$APPS"
cat > "$APPS/BeatStudio.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Beat Studio
Comment=Beatbox to MIDI — native studio
Exec=$DESK/run.sh
Icon=$DESK/icon.png
Terminal=false
Categories=AudioVideo;Audio;Music;
StartupNotify=true
EOF
update-desktop-database "$APPS" 2>/dev/null || true

mkdir -p "$HOME/.local/bin"
ln -sf "$DESK/run.sh" "$HOME/.local/bin/beatstudio"

say "Beat Studio is installed. 🥁"
echo
echo "  • From your apps menu:  search for “Beat Studio”"
echo "  • From a terminal:      $DESK/run.sh"
case ":$PATH:" in *":$HOME/.local/bin:"*) echo "  • Or simply:            beatstudio" ;;
  *) echo "  • (add ~/.local/bin to PATH to use the 'beatstudio' command)" ;;
esac
