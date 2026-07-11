# Beat Studio 🥁

**Turn your beatbox into music.** Record a beat with your mouth, then pull it apart
into separate instrument tracks by drawing over the waveform — and build it out into a
full arrangement on a live-synced studio grid.

Native Linux desktop app (Python + PySide6). No account, no cloud — it runs on your machine.

---

## Install (Linux)

One command — it sets up everything in a self-contained environment and adds a
**Beat Studio** launcher to your apps menu:

```bash
curl -fsSL https://raw.githubusercontent.com/sebamuhr/BeatStudio/master/install.sh | bash
```

Prefer to see the code first? Clone, then run the installer:

```bash
git clone https://github.com/sebamuhr/BeatStudio.git
cd BeatStudio
./install.sh
```

That's it. The installer:

- creates a private Python virtualenv (your system Python is left untouched),
- installs the app's dependencies,
- installs the **PortAudio** system library for sound (asks for your password once, via `sudo`),
- adds a **Beat Studio** entry to your applications menu and a `beatstudio` command.

> **Optional AI sound-matching** (CLAP — suggests which real instrument each of your
> beats sounds like). It's a large download and not needed to make music:
> ```bash
> ./install.sh --with-ai
> ```

---

## Launch

- Open your apps menu and search for **Beat Studio**, or
- run `beatstudio` in a terminal, or
- run `desktop/run.sh` from the repo.

---

## Requirements

- **Linux** (only platform supported for now — Windows/macOS not yet).
- **Python 3.10+** (`python3`).
- Internet access on first install (to fetch the Python packages).

The installer handles the PortAudio system library automatically on Debian/Ubuntu,
Fedora, Arch, and openSUSE. On anything else, install `portaudio` (a.k.a. `libportaudio2`)
yourself and re-run.

---

## How it works

- **Separation Board** — record a take, then draw a line over the waveform for each
  sound (pen tool). Every drawn peak becomes a hit on the tempo grid, played with that
  track's instrument. Tools: **Pen** (draw), **Grid** (stretch the tempo to match your
  beat), **Fit** (stretch a slice of audio onto the beat). Pick **Original** to play
  your own recorded sound back through an **FX rack** (drive, bass, reverb, delay…).
- **Studio** — the grid of notes, live-synced to the board. Per-track **volume
  automation**, play / pause / stop transport, undo/redo across both windows.
- **Save / Open** — saves a standard **`.mid`** (opens in any DAW) plus a full-fidelity
  `.beat` sidecar so reopening here restores your synths, FX, and drawings.

---

## Update

```bash
cd BeatStudio && git pull && ./install.sh
```

## Uninstall

```bash
rm -rf ~/BeatStudio                                  # or wherever you cloned it
rm -f  ~/.local/share/applications/BeatStudio.desktop
rm -f  ~/.local/bin/beatstudio
```

---

## Also in this repo

A small **web capture companion** (`Beatbox to MIDI.dc.html`, `server.py`) — a
phone/browser PWA for recording beatbox takes and syncing them over your LAN. Optional;
the desktop app stands alone.
