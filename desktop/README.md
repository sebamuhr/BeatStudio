# Beat Studio — native desktop (Linux)

Native rewrite of the Beatbox-to-MIDI studio, moved off the browser so the timeline
renders on the GPU and doesn't stutter with many tracks / deep zoom. The phone stays a
capture companion that syncs over the existing `server.py`.

## Why native
The browser stutter was a rendering problem: it repainted the entire timeline canvas on
every change. Here the timeline is a `QGraphicsView` with an OpenGL viewport that paints
**only the visible region** (`drawBackground`/`drawForeground`), so scroll and zoom are
cheap no matter how big the project gets.

## Stack
- **PySide6 (Qt 6)** — GUI + GPU timeline.
- **numpy / scipy** — DSP (onset detection, features, EQ, sampler) ported from the web app.
- **sounddevice (PortAudio)** — audio playback/scheduling *(next milestone)*.
- **mido** — MIDI export.
- Local AI models plug straight into the Python side for sound matching.

## Run
```bash
cd desktop
python3 -m venv --system-site-packages .venv
./.venv/bin/pip install -r requirements.txt
sudo apt install libportaudio2        # only needed once audio lands
./.venv/bin/python app.py
```

Zoom: **Ctrl + mouse wheel**. Scroll: wheel / scrollbars. Space: play/stop.
Starts with a **clean grid** (4 empty tracks). File ▸ New (Ctrl+N) resets; File ▸ Clear all
beats (Ctrl+Backspace) empties the grid. Record: click a track's red **●** (click again to stop);
the row glows red and the title shows RECORDING while it captures.

## Status
- [x] Window, toolbar, ruler, track headers (REC/S/M/gear), timeline rendering — matches the
      web look; GPU-culled painting (no full-canvas repaints).
- [x] Audio engine — numpy voices (drums/synths/sampler + 3-band EQ, `synth.py`), pre-render
      the timeline (`render.py`) and stream it (`audio.py`); Play/Space/Stop; playhead follows
      the audio cursor; loop; graceful silent fallback if PortAudio missing. **Needs
      `sudo apt install libportaudio2` to actually make sound.**
- [x] Grid editing — click empty grid to add a beat (snapped), drag to move (across lanes),
      double-click to delete; cyan selection ring; live re-render while playing.
- [x] Track settings panel (⚙) — instrument picker that KEEPS the beats, Bass/Mid/Treble EQ,
      Test, Delete track, Close. Header buttons wired: REC(opens panel), Solo, Mute (affect the
      mix), ⚙, + New track.
- [x] Transport polish — metronome toggle (♩, renders a click track), BPM stepper, drag the
      ruler to set a **loop** region (click to clear).
- [x] Mic recording — per-track REC / "Record beatbox" captures the mic (`recorder.py`), runs
      onset detection (`analysis.py`, ported `_onsetsFrom` with sustain + merge → extended notes),
      lays down the beats, and stores the take; metronome clicks while recording. *(Needs
      libportaudio2 + a mic. Real-time live markers during record still TODO.)*
- [x] Master auto-split — **Record master** captures the whole groove and splits it into
      instrument tracks by brightness bands (`extract.py`), with extended notes; replaces the
      previous auto-split (no pile-up); keeps the take. (Gallery matching = task 9.)
- [x] Minimap (`minimap.py`) — hover the bottom-right corner to expand an EXACT miniature of the
      whole grid; drag the location dot (reaches every corner) to move; translucent mirror circle
      on the real grid.
- [x] Per-beat EQ popover — right-click a beat (or a marquee selection) for Tune + Bass/Mid/Treble
      + Volume; drag on an empty lane to marquee-select many beats (`beateq.py`, `timeline.py`).
- [x] MIDI export (`mido`), project save/load (JSON), and **phone sync** — File menu / Save /
      Grooves; loads grooves the phone synced via `server.py` (tolerant of the web format).
- [x] My Sounds sampler gallery + waveform editor (`sounds.py`, `soundsdialog.py`) — record your own
      sounds, trim/pitch/gain/loop, preview; they become instruments (in the picker) and match targets.
- [x] Sound matching (`analysis.seg_features` + `extract.multi_extract`) — master extract maps each hit
      to the nearest My Sound; **listen-original** per-track toggle plays the real take. *(A local-AI
      embedding can drop in by swapping seg_features — hook ready; pick a model and we wire it.)*

- [x] Undo/redo (Ctrl+Z / Ctrl+Shift+Z / toolbar ↺) — snapshots on gesture end + discrete actions.
- [x] Zoom controls (−/100%/+ pill, bottom-right above the minimap) + Ctrl+scroll.
- [x] Real-time live markers + record playhead while recording.

**Feature parity with the web app reached.** Minor gaps left vs web: per-lane volume automation
curves, quantize/sensitivity settings, record countdown — small, easy to add.
The optional local-AI embedding for matching is a hook (swap `analysis.seg_features`); note that
**Ollama can't do this** (it serves text/vision LLMs, not audio) — use a Python audio embedding
(CLAP / PANNs) instead.

`render_check.py` grabs the window offscreen to `ref/native-01.png` for visual diffing
against the web reference shots in `ref/`.
