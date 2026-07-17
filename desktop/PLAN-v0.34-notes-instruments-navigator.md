# PLAN — v0.34: Notes line · Instrument restructure · Navigator unify · Soundwave controls · Global full screen

**Status:** APPROVED-IN-PRINCIPLE, decisions locked below (user, 2026-07-17). Build all of it, then test
as one — the user does NOT want to keep working against the old UI piece by piece.

**Overarching STABILITY RULE (do not violate):** the app is ONE track/data model edited from many views.
Every edit must propagate to the Volume view, the Notes view, the Studio grid, playback AND undo. No
parallel data — wire through the shared point/lane/take model + `tracks_changed` / `take_audio_changed` /
`_board_fp` / `snapshot`/`restore`.

---

## THE MENTAL MODEL (locked with the user — read this first)

One horizontal axis, two vertical axes:

- **Horizontal = TIME (the grid).** Shared by both views. A beat/point has exactly one time.
- **Volume view = the LOUDNESS vertical.** Adjust per-beat volume + the grid.
- **Notes view = the PITCH vertical.** Adjust per-beat note + slide it on the grid.
- The two are **the same points** (v0.30.0). Moving a point in time shows in both; its loudness is owned by
  Volume, its pitch by Notes.

**Consequence for the "line" (item #3):** a line spans a TIME segment → it is a **horizontal property → it
is SHARED**. Break a line in Notes and the Volume view shows the same gap. BUT the **curve handles are
per-view**: a curve in Volume is a loudness swell, a curve in Notes is a pitch bend — same two points,
different vertical, so they cannot share handle values.

### Point model (target)
```
{
  id, t,                     # SHARED: identity + time (horizontal)
  tie: bool,                 # SHARED: True = a line runs from THIS point to the next (sustain)
  v,   hx, hy,               # VOLUME view: loudness + its Bézier handle (already exist)
  midi, nhx, nhy,            # NOTES view: pitch (exists) + its OWN Bézier handle (nhx/nhy NEW)
}
```
`tie` is the whole line concept. `nhx/nhy` are new; default 0 (straight). Everything round-trips through
`persistence`, board `snapshot`/`restore`, and the Studio upsert. Backfill on load (`_ensure_pt_ids`-style).

---

## ITEM #3 — a LINE between note points (sustained notes + glides)

### Gesture vocabulary (SAME as the volume pen, v0.22.2 — this is the point, one tool everywhere)
- **Click, click, click** → straight lines between successive points (a HELD/step note between them).
- **Click-and-hold (drag while placing)** → pulls out Bézier handles = a CURVE (a pitch GLIDE in Notes,
  a loudness swell in Volume).
- **Right-click ON a point** → delete the point (already works).
- **Right-click ON a line segment** → remove just that line (the `tie` on the left point). NEW hit-test:
  `_hit_segment(pos)` → point index whose outgoing segment is under the cursor.

### What a line MEANS (locked)
- **Straight line = held/step note** (pitch holds, jumps at the next point).
- **Curved line (handle pulled) = glide/portamento** (pitch slides between the two points along the curve).
- **NO line between two points = the sound just ends at its NATURAL length.** i.e. a piano note rings and
  ends, a kick decays and ends — the instrument's own sample/envelope length. This is the default and needs
  no UI: an untied point plays exactly like today's one-shot hit.

### Which instruments auto-connect (locked — the drum correction)
- **Pitched instruments only** (Hum, Synth, and any pitched Instrument/sample) auto-connect successive
  clicks with a `tie`.
- **Drums / one-shots do NOT auto-connect** — three clicks = three separate hits, exactly as today.
- Rule follows the instrument kind, so it is invisible until it helps. A helper `_is_pitched(tr)` gates
  whether a new point sets `tie=True` on the previous point.

### Engine (how a tie actually sounds)
A run of tied points → ONE sustained `Event` spanning first→last, carrying:
- `pitch_track`: the per-sample MIDI curve sampled from the tied points' `midi` + `nhx/nhy` handles
  (straight = step/hold, curved = glide). Reuse `_sample_curve` / `seg_ctrls` from the volume Bézier,
  applied on the pitch axis.
- `env`: loudness over the run from `v` + `hx/hy` (already how synth notes carry `env`).
- Routing in `render._voice_for`:
  - **Synth** → already has `morph_glide` / `glide_voice` (per-sample pitch). Feed `pitch_track`.
  - **Drum/sample pitched** → `synth.sample_voice(..., loop=True)` resampled along `pitch_track`
    (drums natural at `_DRUM_REF=60`, as v0.30.0's tom-toms-up already does for single notes).
  - **Hum** → new hum voice (see #4) is oscillator-based, so it glides for free.
- An UNtied point → today's discrete `Event` (one hit, natural length). No behavior change for drums.

### Files
- `separationboard.py`: `_notes_press` sets `tie` on the previous point for pitched tracks; drag pulls
  `nhx/nhy`; `_hit_segment` + right-click-removes-tie; `_paint_notes` draws the tie lines (Bézier through
  `midi` using `nhx/nhy`) and the glide fill; `_lane_events` groups tied runs into sustained Events with
  `pitch_track`. Volume paint reads the SAME `tie` to show the shared gap.
- `render.py`: `_voice_for` consumes `pitch_track` for synth/drum/sample/hum.
- `synth.py`: ensure `sample_voice` can take a pitch array (glide) not just a scalar; hum glide via the
  new voices.
- `model.py` / `persistence.py`: `Event.pitch_track`; point `tie`/`nhx`/`nhy`.
- `board_check.py`: NOTES LINE check — 3 tied pitched points → 1 sustained Event whose pitch_track steps
  (straight) then glides (curved); a drum stays 3 hits; right-click a segment splits the run back into two.

### Open sub-question (decide during build, not blocking)
Volume view already draws a Bézier through ALL points as the loudness envelope. Once `tie` exists, the
volume line should only connect TIED points (an untied gap = envelope returns to baseline / note off).
Verify this reads well; it's the honest interpretation of "no line = no sustain".

---

## ITEM #4 — Instrument picker restructure (BIG)

### Top-level selector (replaces the single dropdown)
`Original · Hum · Synth · Instrument` as a segmented control at the top of each track row (board side).
- **Original** = your recorded take through the FX rack (`kind="original"`, exists).
- **Hum** = pick from **≥10 hum voices** (NEW, see below).
- **Synth** = **≥10 synth presets** (WAVES already has 10: sine/saw/square/triangle/pad/pluck/bass/lead/
  bell/organ — expand + keep the Base+Modulator morph designer). Full `SYNTH_KNOBS` slider stack stays.
- **Instrument** = **categories** with many sounds each (drum today = 15 in `synth.DRUMS`).

### "Hum" = SYNTHESIZED VOICES (locked)
No sample files, no gallery. Built-in **formant/vowel synthesis** — an oscillator (glottal-ish source) +
2–3 formant band-pass filters tuned to a vowel. Ships as code, works offline forever, and **glides for
free** (it's an oscillator), which is exactly what #3's pitch_track needs.
- New `synth.hum_voice(preset, freq|freq_array, dur, vel, params)` and a `HUMS` preset table.
- Presets = vowels × character: e.g. `aah, ooh, eee, mmm, ohh, uhh, nasal, bright, breathy, throat,
  choir, falsetto` (≥10; final list below for approval).
- **Same knob philosophy as Synth**: a `HUM_KNOBS` slider stack (the user explicitly wants "all those
  sliders to modify the sound") — vowel/formant shift, brightness, breath, vibrato rate/depth, attack,
  release, drive, level.

### Instrument CATEGORIES (locked: "add a lot")
Categories with real sounds. The user has no strong preference on exact content — **I propose the full
list below; user approves/edits before I build.** Existing `synth.DRUMS` becomes the Drum category.
Proposed categories + engines (all synthesized, offline, glide-capable where pitched):
- **Drum** (percussion, unpitched-ish): the current 15.
- **Mallets** (pitched): marimba, xylophone, vibraphone, glockenspiel, kalimba, music box.
- **Keys** (pitched): piano, e-piano, clavi, harpsichord, organ.
- **Strings** (pitched): violin, viola, cello, pizzicato, plucked/harp, ensemble pad.
- **Winds** (pitched): flute, clarinet, sax, oboe, pan flute.
- **Brass** (pitched): trumpet, trombone, horn, tuba.
- **Bass** (pitched): sub, finger, pick, synth bass.
- **Bells/FX** (pitched): bell, chime, pluck, blip.

Each pitched instrument = a small additive/FM/filtered-osc recipe in `synth.py` (a table of partials +
envelope per instrument) so it pitches and glides. This is the bulk of the engine work.

### Data / UI
- `settings.ITEMS` becomes a **nested** structure: `{group: [(kind, key, label), …]}` for Original/Hum/
  Synth/Instrument, and Instrument itself grouped by category. `_collapse_items` reworked.
- Board `TrackRow`: the segmented top selector → reveals the right sub-picker (hum list / synth designer /
  category+sound). `Lane.kind` gains `hum`; `Lane.sound` namespaced (e.g. `hum:aah`, `inst:violin`).
- `render._voice_for` routes `hum`/`inst:*` to the new voices.
- Persistence: old projects (`drum`/`synth`/`original`/`sample`) still load.

### Files
`synth.py` (hum_voice + HUMS + HUM_KNOBS + instrument recipes + INSTRUMENTS table), `settings.py`
(nested ITEMS), `separationboard.py` (TrackRow selector + sub-pickers), `render.py`, `model.py`,
`persistence.py`, `board_check.py` (each group produces sound; hum glides; a category instrument pitches).

### ⚠️ CONTENT TO APPROVE BEFORE BUILDING
The exact HUMS list, the expanded synth preset list, and the category→instrument lists above. User said
"just add a lot" — I'll finalize the concrete names in a short follow-up for a thumbs-up, THEN build.

---

## ITEM #5 — Navigator unify (copy the SEPARATOR's to the Studio)

Locked: the Separation Board's navigator is the reference; rebuild the Studio's minimap to match it.
- Board navigator today (`separationboard._paint_navigator` / `_mm_rect` / `_center_on`): a **mini
  waveform strip** bottom-right with a **translucent viewport box** you drag to pan (horizontal).
- Studio today (`minimap.py`): a 2-D pad (grid miniature + location dot), plus a separate `zoombar.py`.
- **Task:** give the Studio the same **box-drag viewport** navigator visual/behaviour as the board.
  NOTE — the Studio scrolls in BOTH axes (tracks stack vertically), the board is horizontal-only. So the
  unify is: same **look + box-drag interaction model**, extended to 2-D on the Studio (drag the box in x
  AND y). Confirm with a screenshot during build that they read as the same component.
- Consider extracting a shared `NavigatorBox` widget used by both, so they can't drift again.

### Files
`minimap.py` (reshape to the board's box-drag style), `separationboard.py` (maybe extract shared code),
`mainwindow.py` (wiring). Keep `zoombar.py` or fold the zoom into the navigator to match the board.

---

## ITEM #6 — Per-SOUNDWAVE controls (extends v0.33.0 take-select)

The user wants to "work with just one soundwave, e.g. detailed work on a hum, then add the others". On top
of v0.33.0's checkbox selection, each take/soundwave row gets a **control cluster matching the Studio's
`REC · S · V · M · ⚙` header style** (see the user's screenshot):
- **Solo** — solos every track bound to this soundwave (hear it alone). Maps to `Lane.solo` on all its
  lanes, OR a board-level `_solo_take` that mutes other takes' lanes at render.
- **Mute** — silences every track bound to this soundwave (`Lane.muted` on its lanes).
- **Volume/Notes switch PER WAVE** (user: "we could move the volume/notes switch here"). Today `mode` is
  one global canvas switch. Target: each take remembers its own mode so one wave shows Notes while another
  shows Volume. This is a real refactor — `mode` moves from a single canvas field to per-take state, and
  `paintEvent` renders each band in its OWN mode. **Flag as the riskiest sub-item;** may phase: first a
  per-wave switch that changes the GLOBAL mode + selects that wave (easy), then true per-band mixed modes.
- **Rename** the wave inline (edit "Main"/"Secondary 1").
- **Add track adds under the SELECTED soundwave** (already true after v0.33.0 — `_active_take`; just
  confirm + keep it wired as waves are added/removed).

### Files
`separationboard.py` (take-row control cluster in volume mode + the notes take-chips; per-take `mode`;
solo/mute plumbing to lanes), `render.py` (respect take solo/mute), `board_check.py`.

---

## ITEM #7 — GLOBAL full screen + reopen the separator (user bug report)

Today `⛶ Full screen` lives on the **board's** top bar → only exists when the board is open, and in
two-screen mode it's the separator window only. Also: closing the separator in two-screen mode strands it.
- **Move a full-screen control to the STUDIO toolbar** (`toolbar.py`) so it's always reachable, for BOTH
  windows. Decide during build (ask user): in two-screen mode, does it full-screen BOTH windows or the
  focused one? Default proposal: full-screen the Studio; keep the board's own button too for the board.
- **The screens/layout button must REOPEN the separator** if it was closed: `_toggle_layout` / a dedicated
  "show separator" path should re-create+show the board when it's None or hidden (the machinery exists:
  `_open_separator` already re-makes it — wire the layout button to guarantee it reappears).
- `MainWindow.closeEvent` already closes the board with the Studio; make sure a manually-closed board in
  two-screen mode is recoverable, not gone.

### Files
`toolbar.py` (full-screen button + signal), `mainwindow.py` (global full-screen handler; layout button
re-shows the separator), `separationboard.py` (keep/adjust its own button for two-screen).

---

## BUILD ORDER
1. **#7 full screen + reopen** (small, unblocks testing the two-window flow) 
2. **#3 notes line** (the headline; establishes the shared `tie` model)
3. **#6 per-soundwave controls** (builds on #3's per-view awareness + v0.33.0)
4. **#4 instrument restructure** (biggest; needs the content-approval round first)
5. **#5 navigator unify** (self-contained; last)

Each item: implement → extend `board_check.py` → screenshot to `scratchpad/` → keep all prior checks
green. Version bumps per item or one v0.34.0 at the end (decide with user). PROGRESS.md changelog entry
for each.

## STILL TO CONFIRM WITH USER BEFORE/DURING BUILD
- [ ] Final HUMS list, expanded synth presets, category→instrument lists (#4) — I propose, user approves.
- [ ] #7 two-screen full-screen = both windows or focused one?
- [ ] #6 per-wave Volume/Notes: true mixed modes, or switch-global-and-select (phase 1)?
- [ ] #5 confirm 2-D box-drag on the Studio reads as "the same" as the board's horizontal one.
- [ ] Volume view with ties: untied gap = envelope to baseline (note off) — confirm it reads well.
