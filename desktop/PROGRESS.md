# Beat Studio (native desktop) — PROGRESS

**This is the living status doc for the NATIVE desktop app. Read this first when
continuing in a new chat.** Current version: **v0.34.0** (shown in the window title bar as
`Beat Studio · v0.34.0`).

## ★ ROADMAP (user, 2026-07-17) — do in order, CONFIRM the big ones first

### ▶▶ START HERE (next chat: "please continue the progress.md file")
The whole v0.34 plan is now BUILT (v0.34.0): #3 notes line, #4 instrument restructure, #5 navigator unify,
per-soundwave controls, and the global full-screen fix all landed together and pass `board_check` (27
checks). Plan doc: `PLAN-v0.34-notes-instruments-navigator.md`. The v0.34.0 changelog below has the detail.

**Open follow-ups the USER should verify / decide next (I can't hear audio):**
- **Sound quality pass:** the 12 hum voices and 32 instrument recipes are synthesized and UNHEARD by me —
  the user should audition them and tell me which to retune (they all have knob stacks to tweak). Same for
  the notes-line glide (drum/hum/inst gliding along a pitch track).
- **Per-wave Volume/Notes = phase 1** (each wave REMEMBERS its last view and restores it on select). True
  simultaneous mixed-mode (wave A shows Notes while wave B shows Volume in the same paint) is deferred —
  confirm phase-1 is enough.
- **Two-screen full screen** currently full-screens BOTH windows; confirm that's what "global" should do
  (vs only the focused window).
- **Held-note last-pitch duration:** a HELD run's final note rings out at its natural length; fine for now,
  revisit if it feels short. Curve SHAPE of a glide is linear (portamento) — bending via a real handle is a
  later refinement.
- Legacy web-app deletion at the repo root is still pending (user-approved back in v0.28).

**STABILITY RULE (overarching):** the app is ONE track/data model edited from many views — every edit
must propagate to the volume view, notes view, Studio grid, playback AND undo. Don't add parallel data;
wire through the shared point/lane/take model + `tracks_changed`/`take_audio_changed`/`_board_fp`.

Roadmap status (all items done):
1. [x] **Finer notes grid** (v0.32.2) — `NOTE_SNAP_DIV=48`.
2. [x] **Remove the "⊞ Separator" button** (v0.32.2).
3. [x] **A LINE between points in the NOTES view** (v0.34.0) — held bars + glides; see below.
4. [x] **Instrument picker restructure** (v0.34.0) — Original·Hum·Synth·Instrument; 12 hums, 32 instruments.
5. [x] **Unify the navigator/zoom** (v0.34.0) — Studio minimap is now the board's box-drag style.
6. [x] **Select WHICH soundwave you're editing** (v0.33.0) — checkbox per take.
7. [x] **Board track list moved to the LEFT** (v0.33.0).

## v0.34.0 — Notes line (held + glide) · Original·Hum·Synth·Instrument · per-wave controls · box navigator · global full screen
Five things built together (the user wanted the whole UI change at once, then to test it):
- **#3 NOTES LINE (ties).** A line between note points means the note SUSTAINS. Same pen gesture as the
  volume line: **click = a HELD note** (a piano-roll bar lasting until the next point), **click-and-hold
  while placing = a GLIDE** (pitch slide); **right-click a line removes just that tie**. Only PITCHED
  instruments auto-connect successive clicks (`_is_pitched`); drums stay separate hits. **No line = the
  sound plays its natural length** (kick decays, piano rings). Model: shared point `tie`/`glide`
  (horizontal → shows in BOTH views); `Event.pitch_track` (per-step MIDI). A tied run → piano-roll bars for
  held segments + ONE sliding note (pitch_track) per glide chain, the last note ringing out. `render.
  _voice_for` glides drum/sample/synth via `glide_voice`, hum via `hum_voice`, inst via `inst_voice`. The
  volume view only connects tied instrument points, so both views show the same gaps.
- **#4 INSTRUMENT RESTRUCTURE.** The board picker is a top-level **Original · Hum · Synth · Instrument**
  selector (`TrackRow._on_group`/`_refresh_group_ui`, `GROUPS`/`_group_items`). Hum = **12 synthesized
  VOWEL voices** (formant synthesis: `synth.hum_voice`/`HUM_SPECS`/`HUM_KNOBS`) with their own knob stack;
  glides for free (oscillator). Instrument = **47 sounds** in categories (Drum + Mallets/Keys/Strings/
  Winds/Brass/Bass/Bells) via `synth.inst_voice`/`INST_SPECS`/`INST_CATEGORIES` (parametric partials+
  envelope, pitched + glide-capable). Synth keeps the Base+Modulator designer. Hum knobs live in
  `track["hum_params"]` (separate from synth `params`). Old projects still load.
- **#6 PER-SOUNDWAVE CONTROLS.** Each take row has **Solo (S) / Mute (M)** buttons + the select checkbox +
  a ✕; double-click the name to **rename**. Solo/Mute a wave → every track bound to it inherits it at render
  (authoritative for the wave's auto lanes via the upsert). Add-track binds under the selected wave. Each
  wave **remembers its Volume/Notes view** and restores it on select (`_restore_take_mode`; phase 1).
- **#5 NAVIGATOR UNIFY.** The Studio minimap is now the same **box-drag viewport navigator** as the board
  (a translucent cyan box you drag to pan, no on-grid "mirror" marker) — `minimap._view_box`.
- **#7 GLOBAL FULL SCREEN.** A full-screen button on the Studio toolbar (F11) covers BOTH windows in
  two-screen mode (was board-only). The screens button REOPENS a separator that was closed in two-screen
  mode instead of stranding it.
- Verified headless: `board_check` grew FULLSCREEN, NOTES LINE, WAVE CONTROLS, INSTRUMENTS, NAVIGATOR
  checks — **27 checks, all green**. Screenshots in `scratchpad/` (notes_line, instruments, navigator,
  take_volume/notes). NOTE: audio is UNHEARD by the assistant — the user should audition the voices/glides.

## v0.33.0 — pick the soundwave you're working on (checkbox per take) · track list moved left
User: recording a secondary gave two stacked waves with no way to say "I'm editing THIS one" — clicking
**Notes** always showed the Main wave's pitches, so a secondary's melody was unreachable.
- **Root cause:** `_active_band()` (the "row I'm working on") was *derived* from the ACTIVE TRACK's take
  binding and **fell back to take 0 whenever no track was picked** — so Notes drew Main's pitch no matter
  which wave you meant. There was no way to express the selection at all: `_active_take` (board) only
  decided which take a NEW track binds to, and nothing showed it.
- **Now `CurveCanvas.sel_take` is authoritative** and `_active_band()` just returns it. A **checkbox +
  name** sits at the left of each take row (volume mode) and, when there's more than one wave, as a row of
  **chips in a strip at the top of the piano-roll** (`TAKE_BAR=24`, `_notes_plot()` reserves it). The
  selected wave is tinted in its own colour with a coloured side bar; `set_sel_take` re-centres the piano
  on that take's pitches (`_fit_note_range`).
- **Scoping (the actual ask):** the Notes view draws the SELECTED take's pitch fill AND only that take's
  tracks' note points (it used to draw every track's notes onto whatever roll was open); `_notes_press`
  picks the first track **on this wave** (was `set_active(0)` = possibly another wave's track); new tracks
  bind to it (`_active_take`); clicking another wave's row in Volume **selects that wave** instead of
  silently dropping the point on the one you were on.
- **INVARIANT (stability rule):** the active track always belongs to the selected wave, and the two can't
  disagree — `set_active` sets `sel_take` from the track's band, `_on_take_selected`/`_sync_sel_take` →
  `_reconcile_active()` picks a track on the newly selected wave (or -1). `set_active` assigns `active`
  BEFORE calling `set_sel_take`, because the board reconciles against `active` and a stale value there
  bounced the selection to another track. `_sync_sel_take` sets the index WITHOUT the signal, so
  restore/delete/add_take paths can't re-enter. `_hit`/`_hit_handle` now hit-test in the track's OWN band
  (`_track_band`) instead of `_active_band()`, so hit-testing can't diverge from painting.
- Track rows for another wave **fade back** (`TrackRow.set_on_take` → `QGraphicsOpacityEffect` 0.42), so
  the list reads as "the tracks on the wave I'm editing".
- Round-trips through undo/save: `_active_take` was already in `snapshot()`; `restore`/`set_take`/
  `add_take`/`_delete_take` all call `_sync_sel_take()`.
- **Board track list + "＋ Add track" moved to the LEFT** of the canvas (was right) — every menu in the app
  is left-side now (user: consistency).
- Verified headless: new `board_check` **TAKE SELECT** check (ticking a wave scopes the notes view, the
  active track and new tracks to it; both checkboxes hit-test) + all 21 prior checks green. Screenshots
  `scratchpad/take_volume.png` (checkbox + tinted row, left sidebar) and `scratchpad/take_notes.png`
  (Notes shows *Secondary 1's* sung A3→C4→E4→D4, not Main's).
- STILL OPEN (user's wording "then they all play together but I should be able to isolate them"): all
  takes' tracks already render together, and per-lane **Solo/Mute** already exist in the Studio header —
  confirm whether "isolate" meant that (audio) or just the editing scope built here (visual).

## v0.32.2 — finer notes grid + removed the Separator button
- **Notes snap is now super-fine:** `_snap_t` uses `NOTE_SNAP_DIV=48` (1/48 of a beat) instead of the
  1/16-note grid, so notes place accurately (the drawn beat lines stay at 1/16 for readability).
- **Removed the `⊞ Separator` toolbar button** (`toolbar.sep_btn`) — the board is always present now
  (one-screen default); the launch/record flow still opens it. `open_separator` signal kept (unused by UI).

## v0.32.1 — Fit stretches the ACTUAL sound · Grid = left-stretch/right-move · undo covers audio
Three bugs the user hit:
- **Fit now stretches the real audio, not just the picture.** Root: `_apply_fit` resampled the take
  buffer but `_orig_rec` (what play-original/render actually use) was never updated. New board signal
  `take_audio_changed` (emitted by `_apply_fit` + `_delete_take`) → `MainWindow._on_take_audio_changed`
  syncs `self._orig_rec = self._board.buf` + re-renders. Verified: Fit shrinks take 88200→66150 AND
  orig_rec 88200→66150.
- **Undo/redo now covers audio/grid changes (was project-only).** Root: `_commit` deduped on the Studio
  project dict alone, so an audio-only change (Fit on a track with no beats, grid move, take delete)
  created NO undo entry. Added `_board_fp()` = (take-ids+lengths, grid_off, bpm); `_commit` fires when
  that fingerprint OR the project changed. `_restore` now also restores `_orig_rec` from the board take.
  Verified: Fit undo/redo restores take+orig_rec (88200↔66150); grid move undoable (off 0.30→0.00).
- **Grid tool remapped: LEFT-drag = stretch/shrink tempo, RIGHT-drag = move the grid sideways** (was
  plain=move / Shift=stretch, which felt broken). `mousePressEvent` routes button→`_grid_press(stretch=
  left)`; `mouseMoveEvent` accepts either button. Tooltip updated. `board_check` GRID tests updated
  (stretch=left-drag, move=right-drag).

## v0.32.0 — delete a soundwave (✕) + MOVE the grid sideways (phase offset)
- **Delete a soundwave.** A small **✕** at the top-right of each take (top-right of the piano-roll in
  Notes mode) removes that take **and every track on it** (beats/notes/volume + Studio lanes), after a
  confirm dialog. Canvas `delete_take=Signal(int)` (hit-tested first in `mousePressEvent`) →
  `SeparationBoard._delete_take`: confirms, drops bound tracks via `_delete_track`, pops the take,
  keeps a silent Main if you delete the last one, fixes the active take + `self.buf`, resyncs. Verified:
  deleting a secondary removes its bound track; deleting the last leaves an empty Main, no crash.
- **Move the grid (phase offset).** The Grid tool could stretch tempo but not slide sideways, so a grid
  line couldn't land on the first onset. New `canvas.grid_off` (seconds): **plain drag = MOVE** the grid
  sideways, **Shift-drag = stretch tempo** (was plain drag). The offset shifts the drawn grid (volume
  bars + beats, notes subdivisions) and the beat math (`_beat_of`, `_snap_t`) so points re-time to the
  moved grid; it's board-only (the Studio is the musical view, beat 0 at t=0 — no offset needed there).
  `grid_moved=Signal()` → board resyncs; round-trips in snapshot/restore (undo). Verified: move sets a
  nonzero offset + re-times a point, tempo unchanged; Shift-drag still stretches; grid lines land on the
  peaks (`scratchpad/grid_off1.png`). `board_check` updated (GRID stretch now Shift-drag + new GRID MOVE).
- NOTE: `_beat_of` reads `self.canvas.grid_off` (grid_off lives on the CANVAS, not the board).
- **Reverted the v0.31.0 horizontal-lock.** Notes-created points are NO LONGER time-locked in the
  Volume tab — the user decided Notes just sets the notes, and the Volume tab should let you move points
  freely (adapt to the grid, slide around) in BOTH time and volume. Dropped the `from_notes` flag and
  the lock in the volume anchor-drag; all points move freely in either tab now.
- **One-screen is now the DEFAULT.** `MainWindow._one_screen=True` at init (+ `toolbar.set_layout_mode(True)`);
  `showEvent` opens the separator docked on first launch (`_shown_once` guard, `QTimer.singleShot(0,
  _open_separator)`). So the app opens as one window (separator docked above the studio); the toolbar
  toggle still flips to two windows. `board_check` LIFECYCLE test now floats the board first (its window
  `w` is never shown, so a docked board isn't "visible").

## v0.31.0 — NOTES: vertical scroll (whole piano) + notes-created points are time-locked
- **Scroll the piano up/down.** The NOTES view now shows a **NOTE_SPAN=30**-semitone window that
  **scrolls the full piano** (`PIANO_MIN..PIANO_MAX` = A0..C8) with the mouse wheel (plain wheel =
  vertical scroll; **Ctrl+wheel** = horizontal zoom). `_fit_note_range` centres the window on the
  take's detected notes; `_scroll_notes(ds)` shifts + clamps it. So higher/lower notes that used to be
  off-screen are reachable. Verified: window 42–72 on entry, scrolls, clamps to 21/108.
- **Notes-created points have a LOCKED horizontal position.** A point placed in NOTES carries
  `from_notes=True`; in the VOLUME tab its **time is locked** and dragging changes **only its volume**
  (v). Verified: a from_notes point dragged in Volume keeps t (0.375) and only v changes (0.80→0.30).
  Volume-created points still move freely in time. (Time is owned by the Notes tab.)

## v0.30.1 — NOTES fill: amplitude decides WHERE, pitch decides HEIGHT (one breath = one fill)
User: singing "paaaaaummm" (one continuous sound) was chopped into "paa aaa aa au mmm" — pYIN drops
pitch on the consonants (p/m) and breath dips, and the old bridge needed detected pitch on BOTH sides
of a gap. Rewrote the `_paint_notes` fill: a **smoothed amplitude envelope** marks contiguous runs of
SOUND (`sm > 0.04`), and within each run the pitch is **interpolated across the dropouts**
(`np.interp` over the run's detected frames) — so one continuous vocalisation is ONE continuous fill
(stepping/ gliding through its pitches), while a real silence between notes still splits it. Verified:
a tone→noise→tone→noise→tone "word" renders as one unbroken fill climbing A3→B3→C4
(`scratchpad/paum.png`). Display-only change; `board_check` still green.

## v0.30.0 — Volume & Notes are ONE set of points (pitch + volume) · notes drive pitched playback
Big model correction from the user: **Volume and Notes are two VIEWS of the SAME points**, not two
separate lists. Each point (a beat) now carries a **time**, a **volume** (its height in Volume), and a
**pitch/`midi`** (its height in Notes). Add a point in Notes → it's the same beat in Volume, where you
drag it up/down for loudness only; its time is shared.
- **Merged** the old separate `tr["notes"]` back into `tr["points"]` with a `midi` field
  (`DEF_MIDI=60`=C4 default, so existing drums stay natural). `_notes_press/_notes_move/_notes_hit/
  _notes_release` + the notes-mode draw all operate on `points` now; Volume-mode point creation seeds
  `midi=DEF_MIDI`. Placing in NOTES seeds `v=0.8`. Verified: a point placed in NOTES shows in BOTH
  tabs (`scratchpad/u_notes.png` + `u_volume.png`, same 4 points).
- **Notes now PLAY at their pitch** (Phase 2 core): `_lane_events` sets `Event.pitch=pt.midi`;
  `render._voice_for` **resamples a drum** to that note (`synth.sample_voice`, natural at
  `_DRUM_REF=60`) so a **tom really toms up/down** (verified: tom @60 len 10584 → @72 len 5292, exactly
  an octave). Synth/sample already used `Event.pitch`. `_preview_note` (gutter audition) uses the same
  C4=natural reference.
- **Fill continuity:** pYIN keeps lower-confidence frames now (`vprob>0.2`, was 0.5) and the gap-bridge
  tolerates quieter gaps (amp≥0.02) with a higher alpha floor, so a held sung note reads as one
  continuous fill instead of spots/gaps.
- STILL OPEN (user asked): the board **Play Mix/Original/Both** buttons should "play what I see" — the
  recording. Play Original already plays `_orig_rec`; Mix plays the placed points (now pitched). Confirm
  this matches the ask or make all three prefer the raw take.

## v0.29.3 — NOTES: continuous fill (no cuts) · placing notes works · piano-key audition
Real-take feedback on NOTES mode, three fixes:
- **Continuous fill for a sustained note.** pYIN drops a few voiced frames mid-note, so constant
  singing showed as separate blocks. `_paint_notes` now bridges a pitch dropout **only while the
  sound keeps going through it** (`amp.min() >= 0.05` across the gap) — one held note = one
  continuous fill, but two notes with a dip between stay separate. Verified: a vibrato'd A3 hum
  renders as ONE hill (`scratchpad/notes3.png`).
- **Placing notes works now.** In NOTES mode there's no per-track lane to click, so notes go to the
  ACTIVE track — and if none was active, clicks did nothing. `_notes_press` now auto-selects the
  first track (`set_active(0)`) and shows an "Add a track" hint when there are none. Placed notes
  render as a bright white dot + a coloured block on the lane (clearly visible on the fill).
- **Piano-key audition (start of Phase 2).** Clicking a key in the gutter plays the ACTIVE track's
  instrument AT THAT NOTE: canvas `key_pressed=Signal(int)` (emitted for a gutter click) →
  `SeparationBoard._on_key_pressed` → `MainWindow._preview_note(kind, sound, params, midi)`. Synth
  plays `synth.voice` at that freq; a **drum/sample is RESAMPLED** (`synth.sample_voice`, drums
  around C3=48) so a **tom really toms up/down**. Verified: gutter click emits the right MIDI; drum
  + synth previews render.
- NEXT (rest of Phase 2): make the PLACED notes drive playback/render (each note → an `Event` with
  `pitch`, instrument resampled/oscillated), so the drawn melody actually plays back in the Studio.

## v0.29.2 — VOLUME mode: 0 baseline moved to the BOTTOM (half-wave up) + ribbon strip retired
User: the mirrored bottom half of the volume wave was wasted; move 0 to the bottom and draw a
half-wave going up (more room to draw). Done: `_band` now returns the baseline near the row bottom
(`top + bh - 8`) with usable height `bh - 26`, so `_to_px`/`_from_px` map v=0→bottom, v=1→top with
no other call-site changes. The waveform + live-record envelope draw from the baseline UPWARD only
(`cy → cy-a`, was `cy±a`). The 0–10 scale now reads 0 at the bottom, 10 at the top. Verified: points
at v=0.9/0.3/0.7 land at ~9/3/7 and the wave is a half-wave from the bottom (`scratchpad/volume.png`);
full `board_check` still green. Also **removed the v0.28 note-ribbon strip** from volume mode (it's
superseded by NOTES mode and would overlap the taller half-wave); `groove.pitch_ribbon` + `_pitch_color`
+ the hover label stay (used by NOTES). `_draw_ribbon` is now unused (left in place, harmless).

## v0.29.1 — NOTES mode: pitch drawn as a FILLED silhouette (not spots) + shorter piano black keys
User feedback on v0.29.0: the pitch showed as isolated "spots" (amplitude dabs centred on the note),
so you couldn't read the melody's flow. Fixed: `_paint_notes` now draws each column **filled from the
BOTTOM of the grid up to the note** — a coloured silhouette whose **top edge traces your singing** (go
up to C4 → the whole column under C4 fills, so C4 is the readable top). Tiny pitch dropouts are
**bridged** (linear interp across gaps ≤ ~2% of view width) so sparse detection still reads as a
continuous contour; fill alpha scales with amplitude (louder = more solid); a bright top-edge line
marks the note. Verified: a C4→G4→D4 glide renders as one continuous red→green→blue mountain
(`scratchpad/notes2.png`). Black keys in the gutter made shorter/narrower (`KB*0.55`, `lh*0.7`).
- STILL OPEN (user asked, NOT done yet): in **Volume** mode move the 0 baseline to the BOTTOM and draw
  a half-wave going up (the mirrored bottom half is wasted) — same "baseline at bottom" idea as Notes.
- Phase 2 (unchanged): wire placed notes into playback so any instrument pitches to them.

## v0.29.0 — NOTES mode: a piano-roll where the waveform rides the grid AT ITS PITCH (Phase 1)
The board now has a **Volume ↔ Notes** toggle (top bar, next to Pen/Grid/Fit). Same take, two ways
to draw it:
- **Volume** = exactly as before (waveform mirrored around centre, draw hits/loudness).
- **Notes** = a **piano-roll**: a piano keyboard gutter on the left (C2…C6 with black/white key
  lanes + C labels), horizontal note lanes, vertical tempo grid, and — the key idea — the take's
  **waveform is drawn INSIDE the grid at its detected pitch height**, riding up/down and **coloured
  by note**, so you *see the melody you hummed on the staff*. You then place **note points** on it
  with the pen (click = a note snapped to the semitone lane + 16th-note grid, drag to move,
  right-click to delete). Hovering shows the note name for the lane under the cursor.
- **Works for ANY instrument, not just hums** (user's requirement): a note point is just (time,
  pitch); Phase 2 will make the track's instrument (tom/clap/kick/synth/…) play at that pitch, so a
  line of ascending points "toms up". Phase 1 is the **authoring/visual** surface only — NO audio
  change yet, and nothing is automatic (extraction only draws the guide).

Implementation (all in `separationboard.py`, engine reused from v0.28's `groove.pitch_ribbon`):
- `CurveCanvas.mode` ("volume"|"notes"); `set_mode` + `_fit_note_range` (auto-fits the visible pitch
  range to the take's detected notes, else C2..C6). Notes-mode geometry: `_note_y`/`_midi_at_y`
  (pitch↔y), `_to_px_t`/`_t_at_x` (time↔x), `_snap_t` (16th-note snap), `_lane_h`, `_notes_hit`.
  `_xspan` widens the left margin to `KB=46` for the keyboard in notes mode.
- `_paint_notes` draws lanes + keyboard + tempo grid + the **pitch-positioned waveform** (per column:
  pitch from the ribbon → y, amplitude → bar height, colour by pitch-class) + placed note dots +
  playhead + hover label. `paintEvent` branches to it when `mode=="notes"`.
- Interaction: `_notes_press`/`_notes_move`/`_notes_hover` + release; notes live in a per-track
  `notes` list (`[{id,t,midi}]`), separate from `points`, so the two views don't collide. Rides
  undo automatically (board `snapshot`/`restore` deep-copy all track keys).
- Top bar: `_mode_btns` + `_set_mode`. Verified: a C4→E4→G4→E4 hum renders as red→green→blue→green
  blocks climbing the grid (`scratchpad/notes.png`); clicks place notes at the right lane/time; full
  `board_check` still green.
- **Phase 2 (next):** wire the placed notes into playback so the track's instrument pitches to each
  note (drum/sample = resample; synth = oscillator freq) → `Event.pitch`.

## v0.28.0 — NOTE RIBBON on the waveform (see the pitches you hummed) · one-screen toolbar fix · My Sounds removed
- **Note ribbon (the headline feature).** A thin colour strip drawn just under each take's name on
  the Separation Board waveform, showing **what note is sounding at each moment** — hue = pitch-class
  (C=red … around the wheel), a touch brighter per octave, and **blank over drums/ts** (no pitch).
  It's a **VISUAL REFERENCE ONLY**: it never edits beats, never assigns a note, never makes a track.
  The user builds every track by hand as before; the ribbon just lets them *see* the melody in the
  take (e.g. "there's a C4 hum here") so they can draw a synth/hum track and set its note themselves.
  **Hover** the ribbon → a small label shows the exact note (e.g. `C#4`) so they can read it before
  setting a Low/High note by hand.
  - Engine: `groove.pitch_ribbon(buf, sr)` runs **pYIN on the HPSS-harmonic layer** (so a kick/ts
    over a hum doesn't fake a pitch — a mouth can only hum one pitch at a time, so monophonic tracking
    on the harmonic layer is exactly right) → `(t_frac, midi, voiced)` arrays. `groove.note_name(midi)`
    → `"C#4"`. Both DISPLAY-ONLY.
  - Canvas (`separationboard.CurveCanvas`): `set_takes` computes the ribbon per take, **cached by
    `id(buf)`** (`_ribbon_for`) so pYIN runs once per take, not on every resync. `_pitch_color(midi)`
    (pitch-class→HSL hue), `_draw_ribbon` (thin strip, ~700 cols), `_pitch_at` (note at a fraction),
    `_update_hover`/`leaveEvent` + a painted hover label. Drawn per take row, skipped while recording.
  - Verified: a synthetic C4→E4→G4 hum + kicks → ribbon reads A4/C5 exactly on pure tones, colours
    the three thirds red/green/blue, kicks stay blank (`scratchpad/ribbon.png`). All `board_check`
    checks still green.
  - NOTE (assistant can't hear/see live audio): the user should sanity-check the ribbon on a REAL
    beatbox take (hum + percussion) — pYIN thresholds may need tuning on real mic input.
  - Possible follow-ups (not built): a toggle to hide the ribbon; note letters inline (not just on
    hover); ribbon position (currently top of each row) if they want it hugging the wave.

### one-screen keeps the toolbar with the Studio · My Sounds gone from the pickers (was v0.27.1)
- **One-screen layout fix.** In one-screen mode the Studio toolbar was stranded at the WINDOW top
  with the board wedged between it and the grid (only `grid_host` was in the splitter; the toolbar
  lived above it in `root`). Now the toolbar + grid are one **`_studio_pane`** widget that IS the
  splitter's studio pane, so the board docks ABOVE the whole pane — the toolbar stays glued to the
  Studio grid, exactly like the separate window does in two-screen mode. Verified: board = top pane,
  `_studio_pane` (toolbar+grid) = bottom pane; toolbar stays parented to the studio pane across
  dock/float.
- **My Sounds removed from the instrument selectors.** `_collapse_items` (board picker) no longer
  appends the `sample` entries; `SettingsPanel.set_my_sounds` deleted and its call dropped from
  `mainwindow` (picker is now drums + a single Synth + Original). Old projects with `sample` lanes
  still load/render. Verified: no `sample` kind reaches either picker.
- **TODO (deferred, user-approved):** delete the **legacy web app** at the repo root (`Beatbox to
  MIDI.dc.html`, `support.js`, `sw.js`, `server.py`, `vendor/`, `manifest.webmanifest`, PWA icons,
  `make-cert.sh`, root `PROGRESS.md`, etc.) — the app is native-only now; the HTML is dead weight.

## v0.27.0 — save-ALL (separator too) · 1/2-screen layout · "?" help · removed Save/Grooves/My Sounds + AI
Four things:
- **Save now stores the WHOLE Separation Board too** (was Studio-only). The `.beat` sidecar is now
  `{"project": to_dict(p), "board": <serialized board>}`. `persistence.serialize_board()` base64-encodes
  the take **audio buffers** (JSON-safe) alongside the track dicts (drawn points, params, FX, colour-hex);
  `deserialize_board()` inverts it. `save_song(p, path, board=snapshot)`; `open_song()`/`load_full()` now
  return **(Project, board_blob)**. `MainWindow._save_project` passes `self._board.snapshot()`;
  `_load_fresh(p, board_blob)` recreates+`restore()`s the board and sets `_orig_rec` from the main take so
  play-original works. Old flat `.beat`/`.json` still load. Verified: waves + lines + FX survive a
  save→open into a fresh window.
- **1-screen / 2-screen layout toggle** (toolbar button, replaces the old text buttons). Two-screen =
  today (board is a separate window). One-screen = the board **docks ABOVE the Studio in a vertical
  `QSplitter`** (separator top, studio bottom, one window) — each pane is independently resizable and
  scrolls on its own. `MainWindow._toggle_layout/_dock_board/_float_board` reparent the board (strip/add
  `Qt.Window`); `SeparationBoard.set_docked()` hides the Full-screen/Close chrome + guards Escape when
  docked. `_make_board`/`_show_board` dock automatically when in one-screen mode.
- **"?" help popover** on the board: the old always-on how-to sentence is now a small `?` button
  (`separationboard`, `QToolTip.showText` on click).
- **Removed**: the toolbar **Save / ● Grooves / My Sounds** buttons (Save stays on File ▸ Save / Ctrl+S),
  the **File ▸ Grooves** item, and the entire **AI** feature (menu, arrange, CLAP preload, AI title tag,
  `ai_match`/`config`/`arrange`/`aidialog` imports, `_open_grooves`/`_open_my_sounds`). `requirements.txt`
  had already dropped torch/transformers to opt-in. `calc_done`/master-record path kept (not AI).

## ⚙️ REPO & INSTALL (as of this session — 2026-07-11)
- **Beat is now its OWN git repo** at `~/Documents/APPS/Beat`, remote
  **`github.com/sebamuhr/BeatStudio`** (branch `master`). It was split out of the old
  DeamonCLI monorepo. The `~/Documents/APPS` folder is **no longer a git repo** (that was the
  bug — it was DeamonCLI's repo rooted too high, sweeping in sibling apps). DeamonCLI now lives
  at `~/Documents/APPS/DeamonCLI` as its own repo. So: `git add/commit/push` from inside
  `Beat/` goes to BeatStudio and nothing else.
- **One-command install** (Linux only): `install.sh` at the repo root + a root `README.md`.
  `curl -fsSL https://raw.githubusercontent.com/sebamuhr/BeatStudio/master/install.sh | bash`
  (or `./install.sh` from a clone; `--with-ai` adds CLAP torch/transformers). It makes the
  venv at `desktop/.venv`, installs `desktop/requirements.txt` (now CORE-only; AI is opt-in),
  installs PortAudio, and adds an apps-menu launcher + a `beatstudio` command.
- Run locally for dev: `bash desktop/run.sh` (execs `desktop/.venv/bin/python app.py`).
- Headless tests still: `cd desktop && QT_QPA_PLATFORM=offscreen BEAT_NO_GL=1 ./.venv/bin/python board_check.py`.

## v0.26.2 — Delete track (gear ▸ Delete) now confirms + removes it from the Separation Board too
`MainWindow._delete_track` used to silently drop only the Studio lane. Now it shows a confirmation
(`QMessageBox`, matching the Clear-all style) naming the track, and on Yes also removes the matching
board track via `self._board._delete_track(board_tr)` (found by `lane_id`), which reverse-syncs the lane
away as well. Cancel is the default button and does nothing. The dialog text adapts to whether a board
track exists. Verified headless: confirmed delete drops the track from BOTH windows (+ its events);
Cancel keeps it.

## v0.26.1 — board buttons truly keep their shape · "Original" acts on the whole soundwave (no points)
- **Stop button shape fix (for real):** the `■` stop style used a hard-coded `_STOP_CSS` that dropped the
  green buttons' `padding:8px 14px;font-weight:600`, so a preview button (Mix/Original/Both) visibly
  shrank when playing. Now `_stop_css_from(css)` derives the red style from each button's OWN play style
  (only the colour hexes change → identical geometry), and the three preview buttons are pinned to a
  fixed width that fits BOTH the ▶ and ■ label, so the flip never resizes them (verified play==stop width
  for all three).
- **"Original" no longer needs points:** selecting Original now plays your WHOLE recording through the FX
  rack from the start — `_lane_events` emits a single whole-take event (`beat=0`, `src_dur=take length`,
  `play_original=True`, `fx`) regardless of drawn points, sitting on top of the soundwave. The empty-row
  hint for an Original track now says so instead of "click to place points".

## v0.26.0 — Save/Open as MIDI (portable) + full-fidelity .beat sidecar
The Save button used to write JSON only. Now **Save → MIDI so the groove opens in any DAW**, without
losing the parts MIDI can't hold:
- **`persistence.save_song(p, path)`** writes a standard **`.mid`** AND a full-fidelity **`.beat`** sidecar
  (JSON `to_dict`, i.e. synths/FX/volume automation/board provenance) next to it. Returns the .mid path.
- **`persistence.open_song(path)`** opens `.beat`/`.json` directly; for a `.mid` it prefers a matching
  `.beat` sidecar (full fidelity) and otherwise **imports the raw MIDI** (`import_midi`).
- **`export_midi`** rewritten to **multi-track**: a named track per lane, drums on channel 10 (GM notes),
  melodic/synth lanes on their own channels — opens cleanly in other software.
- **`import_midi`** builds a Project from any `.mid`: channel-10 notes → one drum lane per GM note
  (reverse `DRUM_NOTE`), other channels → synth lanes with pitch/velocity/length.
- Studio wiring: the toolbar **Save** + File ▸ *Save (MIDI + project)* (Ctrl+S) call `save_song`; File ▸
  *Open (MIDI / project)* (Ctrl+O) accepts `*.mid *.beat *.json` via `open_song`; File ▸ *Export MIDI
  (notes only)* (Ctrl+E) stays a plain notes-only export (no sidecar).
Verified: round-trip test (save → reopen via sidecar keeps fx/vol_pts/bpm; delete sidecar → raw MIDI
import rebuilds drum+synth lanes with correct pitches; the .mid re-reads in mido as Tempo+per-lane
tracks) and a Studio-level save→open smoke test.

## v0.25.0 — Phase 3 (Grid + Fit timing tools) & Phase 4 (Original instrument + FX rack)
The last two plan phases landed together.

**Phase 3 — Pen / Grid / Fit tool selector in the board toolbar** (`separationboard.py`):
- `CurveCanvas.tool` ∈ {pen, grid, fit} gates the mouse; a segmented control (✎ Pen · ⇋ Grid · ⤢ Fit) in
  the top bar switches it (`_set_tool`, lit purple when active).
- **Grid stretch (uniform tempo)** — in Grid mode a horizontal drag grabs the beat under the cursor and
  keeps it there, so `beat_len` (hence bpm) scales the WHOLE grid uniformly, like dragging Excel column
  borders. Emits `grid_scaled(bpm)` → `_on_grid_scaled` → mirrors the box + `bpm_changed` → the Studio
  rescales all beats. Tempo changes are now undoable (`_set_bpm` schedules a debounced commit).
- **Fit tool (two-point tape-style audio stretch)** — click A, click B → a shaded region with edge
  handles; drag the B handle and release to **resample that slice** (`np.interp`, tape-style so pitch
  shifts) to its new length, splicing `before + stretched + after` into a NEW take buffer; a dashed
  marker + `×N.NN` label preview the amount. `_apply_fit` remaps every drawn point on that take through a
  piecewise time map (before = unchanged · inside = scaled · after = shifted), drops beat-locks in/after
  the region, re-pads other takes to the new length, and emits `tracks_changed("")` → resync + undo.

**Phase 4 — "Original" instrument + per-track FX rack** (`synth.py`, `separationboard.py`, `render.py`,
`model.py`, `persistence.py`, `mainwindow.py`):
- The board instrument picker gains **"Original"** (`_collapse_items`). Choosing it sets
  `tr["kind"]="original"`, unfolds an **FX RACK** under the picker (built from `synth.FX_KNOBS` with the
  existing `_knob_row`), and makes `_lane_events` emit per-anchor hits on a `play_original=True` lane
  carrying `fx` — so each drawn dot plays YOUR recorded slice, transformed.
- New `synth.apply_fx(buf, fx)` chain (order: **Drive → Bass → Lowpass → Crush → Chorus → Delay →
  Reverb → Punch**), each an amount slider 0..1 (0 = bypass). May lengthen the buffer (reverb/delay
  tail); `synth.fx_tail()` sizes it. `default_fx()`/`FX_KNOBS` mirror the synth-knob pattern.
- **Per-lane render** now applies `apply_fx(lane_buf, lane.fx)` before the volume envelope and grows the
  master tail by the largest FX tail. `Lane.fx` round-trips in `persistence` and rides the board→Studio
  upsert (`play_original` + `fx` carried alongside `sound_params`/`lo_note`).
Verified headless (`board_check.py`, v0.25.0): GRID (drag rescales tempo + syncs), FIT (region resample
shortens the take + remaps points), plus a standalone FX check (each effect changes the buffer; reverb
adds a tail) and an Original-lane render. Screenshot `scratchpad/board_p34.png` shows all of it.

## v0.24.0 — Phase 2: per-track VOLUME automation line + V button + per-lane render
The Studio now has editable per-track **volume automation** (Plan Phase 2):
- **V button** — a 5th right-side header button (REC · S · **V** · M · ⚙), lit cyan when that lane's
  volume line is shown (`headers.py`, recomputed `bx` for 5 buttons; emits `action(lane_id, "vol")`).
- **The line** (`timeline.py`) — `self.vol_lanes: set` of lanes showing their line. Drawn in
  `drawForeground` in the lane colour: a polyline across the row (top = 1.5× gain, unity 1.0 marked by a
  dashed reference line, bottom = silent), holding flat before the first / after the last node, with
  draggable dots. **Click empty** = add a node (beat snapped), **drag** a dot = move (beat+gain),
  **right-click / double-click** a dot = delete. Editing is gated to lanes with V on, so it never
  collides with event editing. Gestures emit `edited` (live re-render) then `committed` (undo snapshot).
- **Per-lane render** (`render.py`, the backbone refactor) — `render_project` now renders **each lane
  into its own buffer**, multiplies by that lane's volume envelope (`_vol_gain` samples `vol_pts` over
  time via `np.interp`, unity when empty), then sums into the master. This is also the home for Phase 4
  FX. `vol_pts` already round-trips in `persistence` and is captured by the undo snapshot.
- Wiring: `mainwindow._on_header_action` handles `"vol"` (toggle `timeline.vol_lanes`).
Verified headless (`board_check.py`, v0.24.0): new VOLUME check (V toggles the line; a `vol_pts` dip
renders measurably quieter) + a screenshot (`scratchpad/vol_line.png`) showing the curve + nodes.

## v0.23.0 — Phase 1: real synth length · undo both windows · play/pause/stop transport · board buttons keep shape
Four things landed:
1. **Synth note length fix** (Plan Phase 1a) — `board._lane_events` computed a synth Event's `length`
   from the take-**fraction** span instead of **seconds** (`(t1-t0)*dur/beat_len`, `dur=len(buf)/sr`), so
   a full-take synth line rendered as a ~2-frame block on the Studio grid. Now it spans the whole grid.
   Verified `length=3.73 beats` for a full-width siren.
2. **Undo/redo affects BOTH windows** (Plan Phase 1b) — the undo entry is now a blob
   `{"project": to_dict(project), "board": board.snapshot()}`. New `SeparationBoard.snapshot()/restore()`
   serialise tracks (points/params, colours as hex) + takes (buffers by reference) + bpm/active-take;
   `MainWindow._commit/_undo/_redo` restore both sides under the `_syncing` guard. `board_check` UNDO test
   rewritten to draw an anchor, commit, undo → asserts BOTH the board points AND the project revert.
3. **Studio transport is now Play → Pause → Stop** — the ▶ button becomes **⏸ while playing**; pressing it
   **pauses in place** (remembers `_paused_beat`, resumes from there). The separate **■ Stop** button
   rewinds to the start. Reaching the end resets to ▶ from the top. (`toolbar.set_playing`,
   `mainwindow._toggle_play/_play_from/_stop/_tick`.)
4. **Board play buttons keep their shape** — flipping to Stop now swaps only the ▶ glyph for ■ and keeps
   the same label/width (`"▶ Mix"→"■ Mix"`, not `"■ Stop"`); removed the bold weight that widened them.
Verified headless (`board_check.py`, v0.23.0, all checks green + a transport pause/resume/stop smoke test).

## v0.22.2 — pen tool: click = straight, click-and-hold = curve, right-click = delete (the original feel)
User clarified the wanted behaviour: **one click = straight point, click-and-drag = curved point,
right-click = remove** (not auto-smoothed). Reverted v0.22.1's Catmull-Rom auto-smoothing. `seg_ctrls`
is now handle-only (controls sit on the anchors → straight; a hand-pulled handle bends that end), shared
by the canvas paint and `_sample_curve`. Verified: plain clicks → straight zig-zag (`ref/autosmooth.png`),
click-drag still pulls a curve handle (`board_check` curve-handle check green), right-click deletes.

## v0.22.0 — SYNTH = a SIREN (Phase A of the morph redesign): line drives pitch+timbre, one sustained note
User's redesign of the synth track (Q&A-locked). The drawn line on a **synth** track is no longer a
volume envelope — it's a **morph + pitch curve** like a police siren:
- **One continuous sustained morphing note** across the whole drawn line (not per-point hits, no SILENCE
  split). Bottom of the line = **Base** sound at the **Low note**; top = **Modulator** sound at the
  **High note**. The curve glides BOTH pitch and timbre → `kiiiiicktooooomkiiiick`. Even a one-shot drum
  used as a synth sound is held as a sustained tone.
- **New engine `synth.morph_glide(base, mod, lo_note, hi_note, dur, morph, …)`** — per-sample pitch from
  the curve (`note = lo + m*(hi-lo)`), timbre crossfade base→mod by the same curve, de-clicked edges,
  constant amplitude. `synth.glide_voice()` sustains ANY sound: tonal drums→fundamental oscillator, noisy
  drums→filtered noise, waves→their oscillator (`_GLIDE_WAVE`/`_GLIDE_NOISE`). `render._voice_for` routes
  a synth Event's `env` (the morph curve) through `morph_glide` with the lane's note range.
- **Low/High note pickers** added to the synth panel (per track, default C3→C5). `separationboard._lane_events`
  now emits ONE synth Event spanning first→last point, `env` = the drawn height sampled (0..1), `pitch=None`.
- Model: `Lane.lo_note`/`hi_note` (+ `vol_pts` reserved for Phase B); round-tripped in persistence and the
  Studio upsert.
Verified headless (`board_check.py`, v0.22.0, 18 checks incl. SIREN: pitch rises with the line, one
sustained morph note). Screenshot `ref/synth-designer.png` (BASE▁low / MOD▔high / Pitch low→high).
**NOTE this is audio the assistant can't hear — the user should test the siren sound before Phase B/C.**
NEXT: **Phase B** = a per-track editable VOLUME automation line on the Studio (all tracks; loudness moved
here off the synth line) + a new **V** button in the track header (next to Solo) to show/hide it. **Phase C**
= draw the rendered synth morph WAVEFORM behind the beats on synth lanes.

## v0.21.0 — per-button play/stop · secondary = its own take ROW · playhead live in both · fine grain · grid-add makes a point
Follow-up fixes on v0.20.0's four features:
- **Per-button play/stop (not global).** Only the button you pressed shows **■**; pressing another stops
  it and starts the new one; pressing the playing one stops. Board now tracks a single `_play_btn`
  (`_set_play_btn`/`_toggle_preview`/`clear_playing`) instead of flipping every button. `TrackRow.preview_sound`
  carries its own button so Base/Morph toggle independently.
- **Record secondary = a NEW take ROW** (own colour) under the main, not mixed on top. The canvas is now
  **multi-take**: `CurveCanvas.set_takes()` + per-row band geometry (`_band(i)`, band-aware `_to_px`/
  `_from_px`/`_apx`, `_track_band`/`_active_band`); each take draws its own waveform + name + 0–10 scale,
  bar lines span all rows. A track binds to a take (`tr["take"]`); new tracks draw over the active take.
  `SeparationBoard.add_take()` (replaces overdub); `set_take` rebuilds the take list. The secondary audio
  is also mixed into `_orig_rec` so ▶ Original / Both play it back (fixes "recorded it, pressed play, gone").
- **Red playhead live in BOTH windows.** Board `playhead_moved` signal → `MainWindow._on_board_playhead`
  drives the Studio grid line during board previews; the transport `_tick` drives the board canvas line.
- **Finer grain.** The board dot's exact x now drives its beat (`_beat_of` drawn-position, no onset snap —
  `src_t`/audio stays onset-refined), and the grid is finer (`project.grid=16`, 1/16-of-a-beat) so even a
  ~2 ms nudge on the board moves the Studio beat while staying in tempo.
- **Grid-add makes a board point.** Adding a beat on a synced grid row now creates a matching board anchor
  in `_sync_grid_to_board` — x = its snapped time, y = **interpolated between the neighbouring points**
  (`_interp_v`) — instead of being dropped on the next regenerate.
Verified headless (`board_check.py`, v0.21.0, 17 checks): PLAY/STOP (per-button), RECORD SECONDARY (new
take row + binding), GRAIN (tiny nudge moves the beat), GRID-ADD (new grid beat → board point), plus all
prior. Screenshots `ref/multitake.png`, `ref/board-playstop.png`.

## v0.20.0 — global play/stop · BPM always synced · Record secondary (overdub) · linked beat selection
Four cross-window fixes so the two screens feel like one instrument:
- **Global play/stop.** Every play button on the board (Mix / Original / Both, per-track ▶, and the
  Base/Morph ▶) flips to **■** while anything is previewing, and clicking ANY of them stops everything.
  Board owns `_playing` + `set_playing(on)` (flips all buttons via `_mark_play`/`_flip_play`); handlers
  toggle; `stop_cb` → `MainWindow._stop_preview` (stops one-shot AND the transport stream, new
  `AudioEngine.stop_one_shot()` = `sd.stop()`). Board previews `engine.stop()` first (no overlap);
  starting/stopping the Studio transport resets the board buttons. Short sound previews auto-reset via a
  1 s single-shot timer; pattern previews reset when the playhead finishes.
- **BPM always matches.** On a new take the detected tempo is now authoritative for BOTH windows
  (`_on_calc_done` sets `project.bpm` + toolbar spinbox), on top of the existing two-way `bpm_changed`/
  `set_bpm_external` mirroring.
- **Record secondary (overdub).** Renamed board "Record master" → **● Record main**; added **＋ Record
  secondary**. Secondary plays the MAIN take in the background (`engine.play(orig_rec)`) while the mic
  records at the same tempo, then mixes the new sound INTO the board wave without disturbing any track
  (`SeparationBoard.overdub()` — same length so all drawn points stay valid; `_toggle_secondary_record`/
  `_stop_secondary_record`, `_rec_lane="__secondary__"`). This is the "extra drum/soundwave on top" layer.
- **Linked beat selection.** Picking an anchor on the board rings it AND selects the matching beat on the
  Studio grid; selecting a beat on the grid rings the drawn anchor. `CurveCanvas.point_selected` +
  `sel_pts`/`set_selected_pts`; `MainWindow._on_board_point_selected` / `_on_grid_selection` map via
  `Event.src_pts`, guarded by `_sel_syncing`; `timeline.selection_changed` now wired.
Verified headless (`board_check.py`, v0.20.0): PLAY/STOP (all buttons toggle together, any click stops),
LINKED SELECTION (both ways), RECORD SECONDARY (overdub keeps length+tracks), plus all prior checks.
Screenshots `ref/board-playstop.png`, `ref/synth-designer.png`.

## v0.19.0 — stable track colours · empty Studio start · big Synth designer (Base+Morph knobs) · fix track selection
Round of user fixes on the Separation Board:
- **Track colours are now STABLE.** Removing the top track no longer recolours the others. Each board
  track mints a colour from a monotonic `_color_seq` (never re-assigned on delete) and carries it as
  `Lane.color` (hex). The Studio paints via new `theme.lane_color_of(lane, i)` (lane's own colour, else
  index). `_delete_track` stopped renumbering colours; `set_take` resets the sequence. Round-trips in
  persistence.
- **The Studio starts EMPTY.** `model.empty_project()` returns zero lanes (was Kick/Snare/Hat/Square) —
  tracks only appear as you create them on the separator, one by one (verified `lanes 0->1`).
- **Track selection fixed.** You couldn't reliably re-select a row (child widgets — name field, combos,
  sliders — swallowed the click). `TrackRow` now installs an event filter on all its children so a press
  ANYWHERE on the row selects it. And the **canvas only edits the ACTIVE track**: `CurveCanvas._hit`
  searches just the selected track, so other tracks' dots are inert — you pick a track from the list
  first, then draw/grab its dots (no accidental cross-grab).
- **Synth designer is now big.** Synth = ONE 'Synth' entry, but Base AND Modulator each get their own
  waveform selector, a small ▶ play button (hear that sound alone), and a full knob stack:
  **Octave · Cutoff · Reso · Attack · Release · Drive · Level** (`synth.SYNTH_KNOBS`, identity defaults so
  an untouched synth sounds exactly like before). New `synth.voice(preset, freq, dur, vel, params)`
  applies the knobs (octave pitch, `_shape` = level→drive(tanh)→resonant LP `_rlp`→attack/release
  envelope); `morph_env` renders Base and Modulator each through `voice()` with `base_params`/`mod_params`
  and crossfades by the drawn line. Model: `Lane.sound_params`/`sound_b_params` (+ board `tr["params"]`/
  `params_b`, `Event` unchanged). Board ▶ per sound via new `preview_sound_cb` → `_preview_synth_sound`.
Verified headless (`board_check.py`, v0.19.0): COLOURS (stable across delete + on the lane), SELECTION
(non-active tracks inert), SYNTH KNOBS (params on the lane + audibly change the voice — cutoff/drive),
empty-start (`lanes 0->1`), colour reaches the Studio lane, PLUS all prior live-sync checks. Screenshot
`ref/synth-designer.png`.

## v0.18.1 — LIVE BIDIRECTIONAL SYNC between the Separator and the Studio ("mix both screens")
The two windows are now **fully live and bidirectional** — no more one-shot "Create these tracks"
button. Create/draw on the separator and it appears on the Studio grid instantly; move/quantize/delete
a note on the grid and the drawn line follows; tempo is synced both ways; **closing the Studio closes
the separator**. Plan: `partitioned-singing-galaxy.md`.
- **Ownership rule:** the board's drawn `points` own **shape + volume**; the Studio grid owns **timing**
  ("here is the grid what rules"). New sounds are created only on the separator. There is exactly ONE
  event generator — `board._lane_events` — so the reverse path never edits Events directly; it edits
  board points then regenerates that lane's events, making shape/volume preservation automatic (`env`
  is always re-sampled from the curve).
- **Shared identity:** a board track and its Studio lane share a stable id (`tr["lane_id"] == Lane.id
  == Lane.src_master`, minted in `add_track`). Each point gets `"id": uid("p")` (`_ensure_pt_ids`
  backfills). `Event` gained `src_track` + `src_pts` (provenance: which anchor(s) an event came from).
  All three round-trip through `persistence`. Points may carry `pt["beat"]` = grid-authoritative snapped
  beat; when present `_lane_events` uses it and **skips onset-refine** (kills the "refine jump").
- **Board → Studio (live upsert):** `SeparationBoard.tracks_changed=Signal(str)` (affected lane_id, ""
  = structural) fires from add/delete track, row changes, and `CurveCanvas.edited` (release + right-click
  delete, throttled during drag). `MainWindow._on_board_track_changed` upserts **only that lane**:
  mutates the existing lane in place (keeps mute/solo/eq/order), replaces just its events, keeps lane
  order == board track order. Guarded by `self._syncing`; debounced `_commit` (400 ms) = one undo entry
  per gesture.
- **Studio → Board (reverse map):** `timeline.committed → _sync_grid_to_board()`. Instrument events map
  1:1 to anchors (`pt["beat"]=snap(e.beat)`, `pt["t"]`, `pt["v"]=vel`; `hx/hy` shape kept); synth regions
  shift member anchors by the beat delta; grid-deleted events remove their anchor(s); then re-`_lane_events`.
- **Tempo both ways:** `bpm_changed`/`set_bpm_external` mirror the spinboxes (blockSignals), rescaling beats.
- **Lifecycle:** `MainWindow.closeEvent` closes + `deleteLater()` the parentless board window.
- **Undo coherence (Risk #1):** `_undo`/`_redo` call `_sync_grid_to_board()` after restoring the project
  so drawn anchors realign to the restored grid without divergence.
- **Record master** now lives only on the separator (removed from the main toolbar).
Verified headless (`board_check.py`, v0.18.1): FORWARD add_track→lane + draw→events; REVERSE move
(beat-lock + shape preserved) & delete; TEMPO both ways; LOOP-GUARD bounded (2 calls); UNDO realign;
LIFECYCLE close. `LIVE SYNC WORKS ✓`.
KNOWN / next: Phase 2 "record an extra beatbox on top" (layering — board points → absolute seconds,
`set_take` appends) is deferred; synth designer knobs (filter/ADSR/LFO/drive/glide/pitch) still pending.

## v0.17.1 — the line FOLLOWS (env) + 0–10 volume scale + per-anchor beats + fullscreen-on-stop fix
Round of user fixes on the modulation model:
- **Full screen no longer exits on Stop.** Root cause: `_on_calc_done`/`_open_separator` called
  `board.showNormal()` which forces the window out of full screen. New `MainWindow._show_board()`
  shows/raises WITHOUT changing window state (verified: fullscreen True → still True after a
  record→calc_done cycle).
- **The line is now a continuous VOLUME + MORPH envelope the sound FOLLOWS** (was flat / endpoint-only
  morph). `separationboard._lane_events` samples the Bézier and, for a **synth**, each run of the line
  above `SILENCE`(0.03) becomes ONE held note carrying `Event.env` = the curve sampled over the note
  (0..1). `render._voice_for` → new `synth.morph_env(base, mod, freq, dur, env)` which follows env
  **sample-by-sample**: amplitude = env (swell/fade like the drawing) AND morph = env (0 → base,
  1 → modulator). So a line that fades in to 9, dips to 0, rises to 5, long-fades to 10 sounds exactly
  like that, morphing as it rises. (This replaces the endpoint m0→m1 ramp / known-limitation.)
- **Each point is a beat / makes a sound.** For **instruments** (drums/samples) every anchor above
  `SILENCE` = a discrete HIT whose velocity = the point's height (per-anchor, not region). Dips to 0
  separate synth notes. `HIT_THRESH`/`_regions`/`_hits_of` removed.
- **0–10 volume scale** drawn down the left gutter (0 = centre/silent, 10 = top/loudest); left margin
  `LM=30`. Height on this scale = the note's volume (and, for synth, its morph amount).
Model/persistence: `Event.env` added (JSON-serialized, rounded). Verified `board_check.py`: synth
line → 1 held note, 78-pt env that rises>0.7 & starts<0.3; drums per-anchor (3 anchors→3 hits);
render 4.5 s; Create lands 3 tracks/9 events. Screenshot `ref/board-vol.png`.
KNOWN: synth held note pitch is fixed 60 (per-hit pitch + the D knobs are next); amplitude=morph are
coupled to one line (a separate morph line could decouple them later).

## v0.17.0 — SYNTH MORPH + curve-as-modulator (plan items B & C) + compare previews (A)
- **A (v0.16.4): compare previews** — separator bottom bar has **▶ Mix / ▶ Original / ▶ Both**
  (`_render_pattern` splits render from play; `_preview_original` plays `_orig_rec`; `_preview_both`
  mixes drawn+original with soft-clip). All sweep the red playhead.
- **B: Synth is ONE instrument, two fields.** Board picker `_collapse_items` = drums + a single
  **"Synth"** + My Sounds (no per-waveform synth entries). A synth row reveals **Base → morph →
  Modulator** WAVES pickers. `model.Lane.sound_b` added (+ persistence + `Event.morph/morph_end`).
- **C: the curve now MODULATES (region-based, not flat).** `separationboard._sample_curve` samples
  the Bézier ~10 ms; `_regions` = runs above `HIT_THRESH`; each region → ONE note with `vel=peak`
  (volume/intensity) and `length=width` (so a synth line that never drops to 0 = one HELD note;
  a drum region >0.14 s → `synth.drum_roll` buzz = the "tsssss", else a single hit). Synth notes
  carry `morph=v_start, morph_end=v_end` → `render._voice_for` calls `synth.morph_synth` to glide
  base→modulator across the note. Engine fns `synth.morph_synth` + `synth.drum_roll` (added v0.16.1)
  now wired. Verified headlessly (`board_check.py`): one Synth picker entry; synth sustained line →
  1 held morph note (len 0.85 beat); render exercises morph+roll (2.15 s); Create lands 3 tracks.
  Screenshot `ref/board-synth.png`.
  NOTE semantic change: hits are now REGION-based (a run above threshold = one note), not one-per-
  anchor — draw a dip to 0 to separate notes. `_hits_of` removed.


## ★ PLAN — "make the wave useful": synth engine + previews (user's checklist, do in order)
Locked requirements (user, repeated — DO NOT drop any):
**A. Compare previews (separator bottom bar):**
- [x] ▶ Preview mix — play what you DREW (exists).
- [ ] ▶ Original — play the raw recorded take.
- [ ] ▶ Both — play drawn + original together to compare.
- [ ] all three sweep the red playhead.
**B. Synth = ONE instrument with TWO sound fields (NOT many synth entries):** ✅ v0.17.0
- [x] Instrument picker shows a single "Synth" option (+ each drum + My Sounds). `_collapse_items` drops the per-waveform synth entries.
- [x] Synth track row reveals TWO fields: **Base** + **→ morph** **Modulator** (WAVES pickers). Model: `Lane.sound_b`.
**C. The curve MODULATES (region-based notes):** ✅ v0.17.0
- [x] `_sample_curve` samples the Bézier to ~10 ms; `_regions` = contiguous runs above `HIT_THRESH`.
- [x] Each region = ONE note: `vel = peak` (volume/intensity), `length = width/beat_len`. Synth held note keeps sounding until the line drops to 0.
- [x] Instruments: `render._voice_for` → `drum_roll` when length>0.14 s (the "tsssss"), else one hit.
- [x] Synth MORPH: `Event.morph/morph_end = curve value at region start/end` → `synth.morph_synth` glides base→modulator across the note.
- KNOWN LIMITATION (refine later): morph/volume follow only the region ENDPOINTS (m0→m1 linear ramp) + the synth ADSR, NOT the exact intra-note curve shape (a rise-then-fall peaks aren't captured). True per-sample curve-follow = a later pass.
**D. Synth knobs (a synth-designer section on the track / a panel):** ← NEXT
- [ ] filter cutoff + resonance, ADSR (attack/decay/sustain/release), LFO (rate/depth), drive, glide, octave/pitch, morph depth. Knobs/sliders, live preview. ("seed from my sound" optional.)
**E. intensity for instruments** ✅ (folded into C: velocity from height + roll from width).
Order: A ✅ → B ✅ → C ✅ → **D next**.

## v0.16.3 — Bézier CURVE points (pen-tool handles) + Record master only on the separator
- **Curved lines with control handles** (user's reference = classic vector pen tool: square anchor +
  two round tangent handles). Each board point is now a dict `{t, v, hx, hy}` (was a bare `(t,v)`);
  the line is drawn as a **cubic Bézier** through the anchors (`QPainterPath.cubicTo`, outgoing
  control = anchor+h, incoming = next anchor−h, symmetric handles). Interaction: **click the wave to
  add an anchor, and DRAG while placing to pull out a curve handle** (pen-tool style); grab the round
  **handle circles** (shown for the active track) to reshape; drag the **square anchor** to move it;
  right-click deletes. Handles clamped (|hx|≤0.35, |hy|≤1). `_hit_handle` tests handle circles before
  anchors. Hits still come from anchors above `HIT_THRESH` (curve shape will drive the synth morph +
  per-hit dynamics when that lands). Verified headlessly: place→drag pulls a non-zero handle; anchor
  drag/delete still work; build/apply unchanged (`ref/board-curve.png` shows a smooth S-curve with
  handles).
- **Record master removed from the MAIN screen** (user): the toolbar `rec_master` button is now
  hidden (`setParent(self); hide()` — kept only so `set_master_recording()` state calls stay valid).
  Recording is exclusively the separator's **● Record master** button now. The `⊞ Separator` button
  stays on the main toolbar to open/show the board.

## v0.16.2 — Separator is a REAL independent window (fullscreen finally works) + Record IN the board
User (very frustrated): it's a TWO-SCREEN app; the separator kept behaving as "one inside the other"
and **would not full-screen no matter how many buttons**. ROOT CAUSE (finally): `SeparationBoard`
was a **`QDialog`** — Qt gives dialogs the `_NET_WM_WINDOW_TYPE_DIALOG` hint and GNOME/most WMs
**refuse to maximise/full-screen a dialog**, even parentless+`Qt.Window`. FIX: `SeparationBoard` is
now a plain top-level **`QWidget`** (`super().__init__()`, no parent). Verified headlessly:
`isinstance QWidget and not QDialog`, `isWindow()`, `parent() is None`, and **`showFullScreen()` →
`isFullScreen()==True`**. It's a normal independent window (own taskbar entry) you can throw on the
2nd monitor and F11/maximise. (No QDialog API was used anymore — `create_requested`/`hide`/
`showFullScreen` all work on QWidget.)
- **Record master MOVED into the separator:** a red **● Record master / ■ Stop** button in the
  board top-left (`record_requested` Signal → `MainWindow._toggle_master_record`). While recording,
  the board canvas shows a **live cyan RMS waveform + "● RECORDING…"** (main window pushes
  `recorder.live_env` to `board.canvas.set_live()` each `_tick`; `set_recording(on)` toggles the
  button + canvas state). Take then loads into the same board (existing flow). The toolbar's Record
  master + `⊞ Separator` buttons remain on the main window too.
- Still persistent: open/close via `⊞ Separator` keeps all work (same `self._board` instance).


## v0.16.1 — Separator is a real separate window w/ a button (two-screen) + synth-morph engine started
User (urgent): it's a TWO-SCREEN app. Recording happens "in place" on the main window and the
separator only pops at the END — wrong. Wants a **button to open the "master track"/separator on a
separate screen**, openable/closable **without losing work**; separation happens on the separator
screen, the main screen shows each created track on its own row.
- **New `⊞ Separator` toolbar button** (`toolbar.open_separator` Signal → `MainWindow._open_separator`)
  opens/shows the Separation Board **even before any recording** (fills with silence until a take
  arrives) so you can park it on your 2nd monitor. It re-shows the SAME persistent `self._board`
  instance, so **close + reopen never loses drawn tracks/lines** (verified headlessly: draw → hide →
  reopen → tracks still there). Board creation refactored into `_make_board`; `_on_calc_done` now just
  loads the take (`set_take`) into the existing board and shows it (no more modal-feeling pop).
- Main screen already shows created tracks as rows (after "Create these tracks"); separator is the
  drawing surface. (Still TODO if wanted: show the LIVE mic-capture waveform inside the separator
  during recording instead of on the main timeline.)
- **Synth-morph ENGINE started** in `synth.py` (wiring next): `morph_synth(a,b,freq,dur,vel,m0,m1)`
  = wavetable-style interpolation of two synth waveshapes (m glides m0→m1: 0=all A, 1=all B, 0.5=new
  hybrid — a MORPH, not two notes layered) and `drum_roll(inst,vel,dur,vel_end)` = re-triggered buzz
  so an intensity line turns a 'ts' into a 'tssss' (the jazz snare). NOT yet wired into model/render/
  board rows — that's the immediate next step (see DEFERRED #1).


## v0.16.0 — board is now a PERSISTENT top-level window (fixes full screen) + playhead/tempo/zoom
User reframe (THE GOLDEN RULE): *"the Separation Board should ALWAYS be visible"* — it's the main
surface; they want to keep it up, record on top, add more tracks over time. Also reported: full
screen did nothing, zoom did nothing, and wanted a playhead + on-board tempo.
- **Full screen fixed by making the board a real window.** It was a `QDialog` parented to the
  MainWindow and run with `exec()` (application-modal) — the WM treated it as a modal dialog and
  refused maximise / full screen / moving to another monitor (the user's screenshot showed it stuck
  at dialog size with "Exit full screen" active but no effect). Now it is created with **no parent +
  `Qt.Window`** and shown **non-modally** (`show()`), so it maximises, full-screens (verified
  `isFullScreen()` toggles True/False), and can be dragged to a 2nd monitor. `⛶ Full screen` button
  + **F11** (Esc exits full screen, else hides).
- **Persistent / non-modal (golden rule).** MainWindow keeps `self._board`; `_on_calc_done` creates
  it once and thereafter calls `board.set_take(hp, bpm)` and re-shows it. **"Create these tracks" no
  longer closes it** — the OK button emits `create_requested` (Signal) → `_apply_board_result`, board
  stays open so you keep working. "Close" just hides it. (TRUE record-on-top LAYERING is the next
  step; today `set_take` REPLACES the wave + clears tracks on a new recording.)
- **Red playhead** sweeps during preview: `preview_pattern_cb` now RETURNS the preview duration;
  board runs a `QTimer`+`QElapsedTimer` and draws a red vertical line (`canvas.set_playhead(frac)`).
- **On-board tempo:** a **BPM** `QSpinBox` in the top bar drives `canvas.bpm` (grid redraws) and the
  bpm used for build/preview.
- **Zoom fixed + buttons:** plain **scroll now zooms** around the cursor (no Ctrl needed; also reads
  `pixelDelta` so ThinkPad touchpads work), plus **－ / 100% / ＋** zoom buttons in the top bar
  (`zoom_at(factor)`), label shows the level. Corner navigator unchanged.
Headless `board_check.py` verifies scroll-zoom + zoom buttons + tempo wiring (bpm→140) + playhead
sweep + build + `_apply_board_result` (lanes 4→6, "CREATE WORKS ✓"). App boots v0.16.0; fullscreen
state verified to toggle.

### DEFERRED — the user asked for these; NOT built yet (do next, in this order)
1. **SYNTH morph = two lines (user's detailed idea).** When a track is **synth**, give it TWO
   instrument pickers + TWO lines: a **base** line aligned to the wave CENTRE (sound A) and a **top**
   line at the top of the grid (sound B). The drawn curve height at each moment is the **mixer knob**
   crossfading A→B (centre = 100% A, top = 100% B). Render = blend/morph the two voices by that
   per-time amount. This is the concrete version of the long-deferred "morphing sounds."
2. **Curved (smooth) lines** option (spline through the dots instead of straight segments), tied to
   the synth morph feel.
3. **Record ON TOP / layering (golden rule, full version):** keep existing tracks + drawn lines and
   record additional takes that extend/overlay the wave, instead of replacing it.
4. Solo-hear a single layer on the board; length control per track.

## v0.15.2 — board: real full-screen, drawn-pattern preview, zoom+navigator, busy states, Create fixed
Round of fixes on the Separation Board (`separationboard.py` + `mainwindow.py`):
- **Full screen actually works now.** The board is a `QDialog` but was treated as a plain dialog
  by the WM (couldn't maximise / go full screen / move to a 2nd monitor). Fix: `setWindowFlag(
  Qt.Window, True)` + Maximize/Minimize hints. `⛶ Full screen` button + **F11** toggle
  (Esc exits). Now draggable onto a second screen and full-screenable there.
- **Preview of what you DREW** (not just the instrument): per-track ▶ now plays that track's drawn
  hits with its instrument (`SeparationBoard._lane_events` → `preview_pattern_cb`), and a new
  **▶ Preview mix** (bottom-left) plays all visible tracks together. Falls back to a single
  instrument one-shot if a track has no dots yet. Wired to `MainWindow._preview_pattern` which
  renders a temp `Project` via `render_project` and plays it through `engine.one_shot`.
- **Zoom + pan + bottom-right NAVIGATOR** on the canvas (like the main timeline's minimap):
  `Ctrl+scroll` zooms around the cursor (down to `MIN_SPAN=1%` of the take), plain scroll pans;
  a corner navigator shows the whole take + a cyan viewport rect you drag to move around. Canvas
  keeps points in whole-take fractions but maps through a `(view0,view1)` window; the waveform is
  re-peaked over the visible slice each paint so zooming reveals true detail.
- **Busy / loading states** so nothing looks frozen: after a master recording, tempo + clean-up
  now run **OFF the UI thread** (`calc_done` Signal → `_on_calc_done`) behind a `QProgressDialog`
  spinner ("Calculating your take…"), and **"Creating your tracks…"** shows while building. Also
  **dropped the CLAP `analyze_clusters` call from the record path** — the board is manual, so we
  only need `groove.highpass` + `groove.detect_tempo`. Much faster, no server/LLM/CLAP in this flow.
- **"Create these tracks" now verifiably works.** Split the apply into
  `MainWindow._apply_board_result(board, bpm)` (removes old `auto` lanes, adds the new lanes+events,
  `timeline.set_project`, headers/toolbar refresh, `_commit`, title "created N tracks"). If nothing
  was drawn it says so instead of silently doing nothing. Headless `board_check.py` drives the whole
  path: add tracks → place/drag/delete dots → zoom/pan/navigator → build → `_apply_board_result` on a
  real `MainWindow`: **lanes 4→6, timeline rows=6, 8 events → "CREATE WORKS ✓"**. App boots v0.15.2.

NEXT (still the roadmap): per-track **length** control + the **SYNTH DESIGNER panel**
(osc/filter/ADSR/LFO/FX knobs+sliders+switches, "seed from my sound", live preview); solo-hear a
single layer while drawing; curve→audio by envelope-multiply for true sustained layers.

## v0.15.1 — SEPARATION BOARD is now MANUAL + full-screen (the app's main feature)
User feedback on v0.15.0: the four auto-curves all looked the same and weren't useful. The whole
point is to separate by **instrument / intention** by hand (a "ts" the user hears as a different
instrument). So the board no longer auto-creates layers. Now:
- Starts **empty** (just the waveform). **＋ Add track** (purple, top of the right panel) adds a
  track with its own row: colour swatch, editable name, **instrument dropdown** (`settings.ITEMS`
  = unified Drum/Synth/My-Sounds list, passed in via `instrument_items`), **▶ preview** (plays a
  one-shot via new `MainWindow._preview_instrument(kind, sound)` → `_voice_for` → `engine.one_shot`),
  👁 show/hide, ✕ delete. Active track = coloured border; click a row or a dot to activate.
- **Pen tool** rewritten for manual drawing: **single left-click on the wave places a dot** on the
  active track (and you can drag while held); **drag** a dot to move (dots stay x-ordered);
  **right-click** a dot to delete. Empty active track shows a "click to place points" hint.
- **Full screen:** `⛶ Full screen` button + **F11** toggle (Esc exits full screen); dialog also has
  Maximize/Minimize window buttons (`Qt.WindowMaximizeButtonHint`). Layout is canvas (stretch) +
  300px track panel (`QScrollArea`) so it scales to the whole screen.
- `SeparationBoard.build()` → one lane per visible track using **that track's chosen instrument**
  (kind/sound, `has_original=True` so Original toggle still available, `play_original=False`).
  `_hits_of` = every raised dot (v ≥ `HIT_THRESH` 0.14) is a hit, de-duped < 40 ms; each snapped to
  the real attack (`analysis.onset_start`) and placed on the tempo grid. Synth tracks get pitch 60
  (per-hit pitch + the synth-designer knobs are the NEXT feature).

Files: `separationboard.py` fully rewritten (CurveCanvas + TrackRow + SeparationBoard); wired in
`mainwindow._stop_master_record` (passes `self.settings.items` + `self._preview_instrument`).
Headless: `board_check.py` adds 2 tracks, places/drag/deletes dots, builds lanes → `ref/board-01.png`
(verified: rows render 296×80, build gives 2 kick lanes with 4 & 3 hits). App boots at v0.15.1.

NEXT (user's stated roadmap): per-track **Instrument vs Synth** is half-there (instrument picker);
still want **length** control per track + the **SYNTH DESIGNER panel** (osc/filter/ADSR/LFO/FX knobs
+ sliders + switches, "seed from my sound", live preview) so a synth track can be sculpted to match
what they hear. Also: solo-hear a single layer on the board; curve→audio by envelope-multiply for
true sustained layers.

## v0.15.0 — SEPARATION BOARD (pen-tool layer curves) — the first post-record surface
**Strategic pivot the user asked for:** stop auto-guessing (onset→CLAP→questionnaire) and let the
USER draw the sounds apart. After Record master, `SeparationBoard` (`separationboard.py`) opens
instead of `ReviewDialog`: the take's waveform (red, mirrored around centre) with several **layer
curves** laid on top — **Hits** (blue, transient novelty = HW-rectified diff of the energy env),
**Body** (green, overall RMS env), **Low**/**High** (band-limited envs, hidden by default). Each
curve is a **PEN TOOL**: every control point is a draggable **dot** — drag to move (dots stay
x-ordered so the curve is a function), **double-click** to add a dot to the active layer,
**right-click** a dot to delete. Legend swatches toggle a layer's visibility / set the active
(editable) one. Curves are amplitude envelopes: 0 at the centre line, 1 at the top (matches the
user's own mock-ups exactly). `initial_layers()` auto-computes the starting curves (scipy butter
band-envelopes → `_resample_points` to `N_POINTS=48`, spiky=peak-per-bin for transients else mean)
so you refine, not draw from scratch.

On **"Use these layers →"** `SeparationBoard.build()` turns each VISIBLE curve into its own
**play-original lane**: local maxima of the curve above a threshold become hits, each snapped to
the real attack via `analysis.onset_start` and placed on the tempo grid (`beat = src_t/beat_len`),
slicing the user's real take. This is the FIRST-PASS result — honest time-domain separation (works
for hits apart in time; simultaneous overlaps still lean on the auto band/HPSS split).

NEXT (not built yet): per-layer **Instrument vs Synth** choice + length + the **synth-designer
panel** (osc/filter/ADSR/LFO/FX knobs, "seed from my sound"); curve→audio by envelope-multiply for
true sustained layers; solo-hear each layer on the board. Qwen/arrange path is being retired per
user ("no big LLM on a server, only CLAP-type local AI"). `ReviewDialog`/`build_from_review` are
still imported in `mainwindow.py` but no longer on the record path (kept for reference).

Headless check: `desktop/board_check.py` (offscreen) builds a synthetic take, exercises
drag/add/delete on a dot, builds lanes, saves `ref/board-01.png`. Verified: drag moves a dot,
add 48→49, delete 49→48, curves build 2 lanes with hits. App boots at v0.15.0.

## v0.14.2 — thinking OFF app-wide (user directive)
User: "any model used on this app should ALWAYS be think=false." Enforced centrally in
`llm.chat`: every request gets payload `think:false` AND `_no_think_messages` appends `/no_think`
to the system message (Qwen3 template reads it), and replies are stripped of any `<think>…</think>`
via `_THINK_RE`. Applies to arrange AND the Test ping. Result on the a3b model: arrange 178s→139s
(richer 9-track output). Still server-throughput-bound (35B MoE) — if snappier is ever wanted,
`qwen2.5-coder:14b` would likely be faster, but a3b-no-think is the user's chosen default.

## v0.14.1 — AI arrange VERIFIED LIVE + model-dropdown + freeze fix
**The whole arrange pipeline works end-to-end against the user's REAL home server** (Ollama at
`192.168.2.200:11434`). Test: a 3-track sketch (kick+snare + hummed melody D4/F4) → the model
returned a full 6-track arrangement (Kick/Snare/Hat cleaned + a NEW Bass D2/F2 + Pad D3/F3 + Lead
keeping the melody) with coherent D/F harmony across three octaves. This is the "beatbox a seed →
full track" vision proven. Config saved: `desktop/config.json` = `http://192.168.2.200:11434/v1`,
model **`qwen3.5:35b-a3b`** (fast MoE, ~3B active). NOTE: even warmed, generation took ~178s for
88 notes — usable (off-thread, title shows progress) but SLOW; next optimization = disable qwen3
"thinking" (/no_think) or try `qwen2.5-coder:14b` (9GB, fast, good at JSON). The plain
`qwen2.5:32b-instruct-q4_K_M` TIMED OUT cold at 180s.

Three bugs/UX fixes this patch:
- **Test-connection FREEZE (user hit it):** a bare IP like `192.168.2.200` made `urllib` raise a
  `ValueError` DURING request construction (before the try), and `ping()` only caught `LLMError`,
  so the worker thread died silently → "Testing…" forever. Fixed: `llm.normalize_base_url` (bare
  IP → `http://…:11434/v1`, keeps explicit scheme/port/path), request built INSIDE the try, `ping`
  catches everything, dialog worker double-guards + a live "⏳ Testing … Ns" counter so you always
  know it's alive. Ping timeout 90s (big models load slowly), arrange 300s.
- **Model DROPDOWN (user's idea):** `llm.list_models` hits `/v1/models`; the dialog auto-loads the
  server's models on URL entry / open and shows them in an editable combo + ↻ reload — so you pick
  the exact tag instead of mistyping it (which is what broke it: `qwen2.5:32b-instruct` vs the real
  `…-q4_K_M`). Verified live: lists all 7 of the user's models.

## v0.14.0 — AI ARRANGE LAYER + HPSS ("stop working double") — the strategic pivot
User's insight (correct, restated over several sessions): don't make a model *hear* audio —
turn the beatbox into NUMBERS (our DSP+CLAP already do), then hand that symbolic sketch to a big
reasoning LLM on their **home server**. It reasons over the WHOLE track at once and expands the
sketch into a **full musical arrangement** (long melody behind the ts/pf, bassline, harmony,
cleaned drums), which we render with our own synth engine → user just tweaks. This ends the
"beatbox AND then build the whole track by hand" double-work. Philosophy locked: **musical, not
exact** — `ps ps ps` heard as `psssst ps` is fine if it sounds good; go with the flow like a DAW.

New files: **`config.py`** (desktop/config.json: `ai_base_url`/`ai_model`/`ai_api_key`/`ai_enabled`;
default local Ollama), **`llm.py`** (stdlib-only OpenAI-compatible `/chat/completions` client —
works with Ollama/vLLM/LM Studio/llama.cpp; `chat()`, `ping()`, `LLMError`), **`arrange.py`**
(`project_to_sketch` → compact symbolic JSON; `_SYSTEM` producer prompt constrained to our
`synth.DRUMS`/`WAVES` vocab; `_extract_json` tolerant of fences/prose; `arrangement_to_project`
coerces bad kind/sound → playable; `arrange()` = full round-trip → new `Project`), **`aidialog.py`**
(AI Settings dialog: editable **URL + model name** + optional key + **Test** (threaded ping) —
user can swap servers/models anytime).

Wiring (`mainwindow.py`): **AI menu** → "✨ Arrange into a full track" (**Ctrl+R**) + "AI Server
Settings…". `_arrange_with_ai` runs the LLM call OFF the UI thread (daemon thread → `arrange_done`
Signal → `_on_arrange_done` swaps the project via `_set_project` + `_commit` so **Ctrl+Z restores
the pre-arrange groove**). If unconfigured it opens Settings first. Errors (dead server, bad JSON)
surface in the title bar, never crash/hang (short timeouts).

**HPSS (`groove.hpss`)** = the "don't cut the background tone" fix (librosa `effects.hpss`, falls
back to (buf,buf)). **`groove.melody_line`** tracks the harmonic layer's continuous pitch and
MERGES contiguous same-pitch frames into HELD notes (allows a few unvoiced frames so a pop over
the tone doesn't split it) → a held tone becomes ONE long note, not one-note-per-hit. Wired into
`extract.analyze_clusters`: computes hpss, and appends a synthetic **melody cluster** (`suggest=
"melody"`, `is_melody=True`, pre-built held-note hits) that flows through the existing review
dialog + `build_from_review` melody path unchanged. VERIFIED headlessly: held A4→C5 tones → 2 clean
held notes (MIDI 69/72, full length); arrange serialize/parse + bad-vocab coercion + dead-server
LLMError all pass; window builds, title shows v0.14.0.

STILL TODO / next: (1) test arrange against the user's REAL home server (need URL + model tag —
they likely run Ollama; `Ollama-Test` folder exists). (2) percussion onsets still run on the full
hp buffer, not the percussive layer — could move them to `perc` to stop the tone spawning drum
onsets (needs real-audio tuning). (3) melody cluster can double-count if a tonal attack also makes
onset clusters — review dialog lets the user "ignore" those for now. (4) still want a real MELODIC
beatbox sample to tune `melody_line` thresholds.


> ⚠️ VERSION GOTCHA: bump `beatstudio/__init__.py __version__` by EDITING the string directly
> (not `sed` find-replace — a lost bump once left every later `sed` searching for a number that
> wasn't there, so the title silently stayed stale while the code advanced). Verify after: the
> title bar must show the new number.

---

## HOW THE APP WORKS NOW (the core loop, as of v0.13.0)

The philosophy pivoted (user's insight): **"My Sounds" pre-registration is BACKWARDS.** The right
flow is beatbox anything → software finds the distinct sounds → **asks you what each is** → builds
with REAL instruments → and **learns your kit** so it recognises them next time ("train along, not
beforehand"). When you press **Record master**:
1. `extract.analyze_clusters()` — high-pass (kills DC rumble) → onsets (spectral flux) → tempo
   (librosa) → quantize to 1/16 grid → cluster by CLAP embedding. Per cluster: a 0.5s preview +
   a SUGGESTED category (from `usermodel` if learnt, else acoustic guess, else pitch→melody) +
   per-hit melody note (`groove.note_of`) + a matched clean synth `preset` (`groove.pick_preset`).
2. `reviewdialog.ReviewDialog` — the QUESTIONNAIRE ("What did you just beatbox?"): one row per
   sound with ▶ (hear YOUR sound), 🔊 (hear the CHOSEN instrument), and a category dropdown
   (kick/snare/hat/…/bass/melody/keep-my-sound/ignore). Shows "(learned)" vs "(guess)".
3. `extract.build_from_review()` — builds tracks with real instruments AND
   `usermodel.add(embedding, category)` for each → learns. Melody category uses the matched synth
   preset + real per-note pitches.
4. `usermodel.UserModel` (`desktop/usermodel/labels.npz`) — CLAP-embedding k-NN. Verified:
   label once → re-analysis auto-recognises the same sounds (conf>0.5).

New files since the earlier changelog: **`usermodel.py`, `reviewdialog.py`**; new funcs in
`groove.py` (`highpass`, `classify_acoustic`, `detect_pitch`, `note_of`, `pick_preset`) and
`extract.py` (`analyze_clusters`, `build_from_review`; old `smart_extract` still there).

## HONEST OPEN ISSUES (priority order for next session)
1. **Tempo unstable** — same file read 92 vs 167 BPM depending on high-pass. Add a confirm/
   tap-tempo step in the questionnaire, or a better beat tracker. This is the shakiest part.
2. **Onset over-detection** — ~56–76 hits on a 30s take; some are breaths, and SUSTAINED melodic
   notes get chopped into many notes. For melody: merge consecutive same-pitch contiguous hits
   into one held note (but keep redobles = re-articulated repeats separate).
3. **Cold-start suggestions rough** — first-time acoustic guesses are often wrong (that's OK by
   design; user corrects once, model learns). Could improve the initial guess.
4. **pick_preset** timbre match is approximate (e.g. low sine → 'bass'). Fine for now.
5. Need a **real MELODIC beatbox sample** from the user to tune note-tracking + timbre. Also want
   Recording 1/2 style drum samples to keep tuning onsets/clustering.

## READING/DEBUGGING REAL AUDIO
- `desktop/analyze.py <file>` runs a recording through the full pipeline + prints tempo/onsets/
  clusters/suggestions + saves a spectrogram PNG. Use it to tune on the user's real audio.
- User's FLACs have BROKEN/STREAMED headers (frames=int64max → libsndfile `psf_fseek` fails,
  soundfile can't read). Decode first with GStreamer (ffmpeg NOT installed):
  `gst-launch-1.0 -q filesrc location=IN.flac ! decodebin ! audioconvert ! audioresample !
   audio/x-raw,format=S16LE,channels=1,rate=44100 ! wavenc ! filesink location=OUT.wav`
- Put user beatbox recordings in `desktop/samples/`.

---

## What this is / the pivot

`Documents/APPS/Beat` began as a **web app** ("Beatbox to MIDI", `Beatbox to MIDI.dc.html`,
last at web-v0.7.6) that kept **stuttering** (full-canvas repaints in the browser). On
2026-07-01 the user decided to go **native**: a real Linux desktop app, NOT Electron/Tauri
(those are still browser engines). The native app lives in **`desktop/`** and is the primary
product now. The **web app stays as the phone capture companion** (record on the phone
offline → sync to the desktop via `server.py` → open under File ▸ Grooves). Nothing from the
web app was thrown away — its features were ported.

Goal the user keeps restating: **feature parity with the web version**, good recording, and
**AI sound matching** (now shipped).

---

## How to run

```bash
bash ~/Documents/APPS/Beat/desktop/run.sh          # or double-click the "Beat Studio" desktop icon
```
- Desktop icon installed via `desktop/install-launcher.sh` (icon `desktop/icon.png`,
  `desktop/BeatStudio.desktop`).
- System deps the user already installed: `libxcb-cursor0` (to launch), **`libportaudio2`**
  (REQUIRED for sound + mic).
- Python venv at `desktop/.venv` (created `--system-site-packages`). Key deps:
  PySide6 6.11, numpy, scipy, sounddevice, mido, **torch 2.12 (CPU), transformers 5.12,
  soundfile** (for CLAP AI).
- Controls: **Ctrl+scroll** zoom, **Space** play/stop, **Ctrl+Z / Ctrl+Shift+Z** undo/redo,
  **Ctrl+N** new, **Ctrl+Backspace** clear beats.
- Headless verify pattern (used for all testing):
  `QT_QPA_PLATFORM=offscreen BEAT_NO_GL=1 ./.venv/bin/python <script>` and `w.grab().save('ref/x.png')`.
  Reference screenshots (web + native) are in `desktop/ref/`.

**Versioning:** bump `beatstudio/__init__.py` `__version__` on EVERY change — it's shown in
the title bar so the user can confirm a relaunch picked up the new build.

---

## Architecture / files (`desktop/beatstudio/`)

- **`mainwindow.py`** — assembles everything; transport; recording flow; undo/redo; menu;
  wires all signals. Starts with `empty_project()` (4 empty tracks Kick/Snare/Hat/Square).
- **`timeline.py`** — `QGraphicsView` + OpenGL viewport. Custom-paints ONLY the exposed rect
  in `drawBackground`/`drawForeground` (this is the anti-stutter fix). `setAlignment(Left|Top)`
  so rows line up with headers. Handles beat editing (click-add / drag-move / dbl-click delete /
  snap), marquee select, right-click → per-beat EQ, live record waveform + markers, minimap
  mirror circle.
- **`headers.py`** — left track column (colour chip, name, subtitle, REC/S/M/⚙ buttons,
  Extract/Original toggle for `has_original` lanes, + New track). Custom-painted with hit-testing.
- **`ruler.py`** — top bar-number ruler; drag to set loop region.
- **`toolbar.py`** — ▶ ■ ↺(undo) ↻(redo) 🗑(clear+confirm) 🎤 ♩(metro) BPM · level meter ·
  notes/tracks · Save/Grooves/My Sounds. `_LevelMeter` shows input volume while recording.
- **`settings.py`** — bottom track-settings panel (⚙): instrument picker (unified drum/synth/
  My-Sounds list; KEEPS beats on change), Bass/Mid/Treble EQ, Test, per-track Record,
  Play-Original checkbox, Delete, Close.
- **`synth.py`** — numpy voices: drums, synth presets, sampler (`sample_voice` = resample +
  sustain-loop), 3-band RBJ EQ, metronome click. `SR=44100`.
- **`render.py`** — `render_project(project, samples, orig)` → mono buffer (mute/solo, EQ,
  velocity, note length, metronome, play-original slices). `_voice_for` builds one voice.
- **`audio.py`** — `AudioEngine`: sounddevice OutputStream, loop, live cursor, `one_shot`
  preview; virtual-clock fallback if no PortAudio.
- **`recorder.py`** — `Recorder`: sounddevice InputStream; `live_env` (per-block RMS for the
  live waveform), `live_onsets`, `peak` (clip warn).
- **`analysis.py`** — `onsets_from` (spectral-flux attack detection — see below),
  `seg_features` (24-D: 5 spectral + 6 bands + 13 MFCC), `match_dist`, `onset_start`.
- **`extract.py`** — `multi_extract` = try CLAP → DSP gallery-match → brightness band-split.
  `clap_extract` embeds each hit, matches gallery by cosine or zero-shot classifies.
- **`ai_match.py`** — **CLAP** (`laion/clap-htsat-unfused`): `load()`, `embed()` (512-D, uses
  `out.pooler_output`, resample to 48000, processor kwarg `audio=`), `cosine_dist`, `classify()`
  zero-shot vs text LABELS. Fully local/offline after one-time ~600MB weight download to
  `~/.cache/huggingface`.
- **`sounds.py`** — `SoundLibrary` (`desktop/mysounds/` = index.json + <id>.npy); DSP features +
  CLAP embeddings cached per sound.
- **`soundsdialog.py`** — My Sounds window: list w/ per-sound ▶ buttons, record (live waveform),
  waveform editor (trim/base-pitch/gain/loop), looping Preview.
- **`minimap.py`** — bottom-right hover corner: exact scaled miniature, draggable dot (reaches
  every corner), mirror circle on real grid. `zoombar.py` = −/100%/+ pill stacked ABOVE it.
- **`beateq.py`** — per-beat EQ popover (Tune/Bass/Mid/Treble/Volume on the selection).
- **`persistence.py`** — JSON save/load, `mido` MIDI export, `from_dict` tolerant of the WEB
  groove format (phone sync via `server.py` → `Beat/synced/`).
- **`model.py`** — `Project` / `Lane` / `Event` dataclasses. `empty_project()`, `demo_project()`.

---

## DONE (feature parity with web, verified headlessly)

Audio playback · transport (play/pause/stop/space, metronome, BPM, loop) · grid editing
(add/move/delete/snap, marquee) · track settings panel (instrument switch keeps beats, EQ,
Test, Delete) · header buttons (REC/solo/mute/gear/+track) · mic recording + onset detection +
live markers + live waveform (per-track AND master full-height) + metronome-while-recording ·
**Record master → auto-split** into instrument tracks · **My Sounds** sampler gallery + waveform
editor + per-sound play + looping preview · **AI matching (CLAP)** with zero-shot fallback (works
WITH or WITHOUT a gallery) · **Extract/Original toggle** per track (header + gear) · per-beat EQ
popover + marquee · minimap (exact miniature + dot + mirror) · zoom controls · MIDI export ·
save/load · phone-sync groove loading · undo/redo (buttons + shortcuts) · clear-all (confirm) ·
starts with a clean empty grid.

### Two hard bugs fixed recently
- **v0.9.1 — onset detection rewrite** (the "giant green note / no rhythm" bug). Old detector was
  level-based and let one hit's note run until energy fell <25% of peak → a single hit became a
  whole-bar note (plus an over-aggressive timbre merge). Now **spectral-flux attack detection**
  (hop 256 / win 1024, positive spectral-change novelty, adaptive-mean threshold ×1.4 + floor,
  45 ms refractory) → ONE onset per hit; note length SHORT by default (decays under 40% of its
  own peak, hard-capped 0.7 s and by the gap to the next onset), NO merge. Verified:
  "pf ts pf ts pf pf" → 6 distinct ~0.05 s hits; a sustained "tsssss" → ~0.47 s.
- **v0.8.2 — vertical misalignment**: `QGraphicsView` centres content smaller than the viewport,
  so rows drifted below the headers. Fixed with `setAlignment(Qt.AlignLeft|Qt.AlignTop)`.
- **v0.9.3 — row misalignment (second cause)**: the track-header column had an internal
  `_HEADER_BAND` (=RULER_H) caption strip that pushed its rows down 26px while the timeline rows
  started at y=0. Fixed: `_HEADER_BAND = 0` (rows start at 0, aligned to the grid) and the
  "TRACK · REC · SOLO · MUTE" caption moved into the `CornerBox` (grid row 0, col 0). Verified
  header row 0 and timeline row 0 share the same global top (0px diff).
- **v0.9.2/0.9.3 — undo/redo buttons**: always present in the toolbar (↺ ↻), GREYED (disabled
  `:disabled` style) when the stack is empty — never hidden, never shift the layout (per user
  request). Enable on first edit / after undo.

---

## v0.12.0 — REVIEW QUESTIONNAIRE + "TRAIN ALONG" (the right architecture)

Reframed per the user: "My Sounds" (pre-registering sounds) is BACKWARDS. Correct flow =
beatbox anything → software finds the distinct sounds → **ask the user what each one is** →
build with REAL instruments → and LEARN so it recognises them next time. No pre-registration;
labelling happens AFTER, and doubles as training data.

Flow now (`_stop_master_record`):
1. `extract.analyze_clusters(buf, sr, start, usermodel)` → high-pass, onsets, tempo, quantize,
   cluster (CLAP), and per cluster: a representative 0.5s preview + a SUGGESTED category
   (from `usermodel` if learnt, else acoustic guess `groove.classify_acoustic`, else pitch→melody).
2. `reviewdialog.ReviewDialog` — a per-sound questionnaire: ▶ play example, pick instrument from
   `usermodel.CATEGORIES` (kick/snare/hat/…/bass/melody/keep-my-sound/ignore), shows "(learned)"
   vs "(guess)".
3. `extract.build_from_review(clusters, decisions, usermodel)` → tracks with real instruments,
   AND `usermodel.add(embedding, category)` for each → **learns your kit** (persisted).
4. `usermodel.UserModel` (`desktop/usermodel/labels.npz`): CLAP-embedding k-NN classifier;
   `predict()` = nearest-fingerprint vote. Verified: after labelling once, re-analysis
   auto-recognises 9/9 sounds (conf>0.5). This IS "train along, not beforehand."

NOTE: "My Sounds" gallery still exists but is now secondary; the review flow is the main path.
Acoustic suggestions are rough (cold start) but the user corrects them once and the model learns.
Tempo detection still unstable (Recording 2: 92 pre-HP, 167 post-HP) — needs work/confirm-in-UI.

## v0.10.0 — MUSICAL PIPELINE (the "random rhythm" fix)

The big fix for "the result is random as fuck." Master record now runs a real MIR pipeline
(`groove.py` + `extract.smart_extract`), replacing the raw-onset placement:
1. **Onsets** (spectral flux, `analysis.onsets_from`).
2. **Tempo** — `groove.detect_tempo` (librosa `feature.rhythm.tempo`, IOI-median fallback);
   sets `project.bpm`. Verified: recovers 120 BPM from a humanized take.
3. **Quantize** — `groove.quantize` snaps every hit to the nearest 1/16 with a circular-mean
   phase, anchored so the earliest hit = beat 0 → clean 0.25 multiples (verified maxGridErr 0.0).
4. **Cluster** — `groove.cluster` (sklearn AgglomerativeClustering cosine / numpy fallback)
   groups hits by CLAP embedding so the SAME sound → ONE track; each cluster centroid matched to
   nearest instrument / My Sound (`extract._label_centroid`).

Deps added: **librosa, scikit-learn** (in `.venv`). Also: **beat LED** in the toolbar
(`toolbar.pulse_beat`) blinks every beat while recording (green, red on the downbeat); the
metronome click now plays during record only if enabled, but the LED ALWAYS blinks
(`_start_beat_clock` / `_metro_click`) — fixes "metronome does nothing on record."

Cluster threshold (`groove.cluster thresh=0.35`) may merge similar synth sounds (test gave 2
tracks for kick/snare/hat) — tune on real beatbox.

## KNOWN GAPS / TODO (still not at web parity)

1. **Per-lane volume-automation curves** (draggable gain points along a lane) — not ported.
2. **Quantize + sensitivity controls** — web had global quantize + onset-sensitivity; not ported.
3. **Record countdown** (3-2-1 before capture) — not ported.
4. **AI matching** — v0.9.4 switched to AUDIO-TO-AUDIO: `ai_match.instrument_refs()` renders each
   built-in voice, embeds it with CLAP, and `nearest_instrument(emb)` returns the closest; a My
   Sound only wins if it's closer (`clap_extract`). Verified built-in voices self-match 7/7 (~0
   dist). Real-beatbox→synth-reference has a domain gap; the BEST results come from the user
   recording their own kick/snare/hat into My Sounds (real→real). Could bundle real one-shot
   samples as references later. Text zero-shot `classify()` still exists but is no longer the
   primary path. `instrument_refs()` is prebuilt in the AI preload thread.
5. **Undo/redo buttons looked "missing"** — they ARE present (↺ ↻ in the toolbar) but start
   DISABLED (nothing to undo yet); v0.9.2 added a visible `:disabled` style so they're dim-but-
   clearly-there. If the user still says they're missing, double-check the relaunch picked up the
   new version (title bar).
6. Live-monitor (🎤) and phone-sync (📡) toolbar buttons are placeholders/partial.

---

## NOTES for whoever continues

- The user is a beatboxer, non-developer, and gets frustrated when asked to confirm instead of
  acting — **just build, don't over-ask**. Bump the version each change so they can see it landed.
- CLAP is **local/offline** after the first weight download — this was a point of confusion;
  reassure if asked. **Ollama can NOT do this** (text/vision LLM only, no audio embeddings).
- The user's real test phrase is "pf ts pf ts pf pf" (kick/hat pattern). Recording quality +
  rhythm is what they judge on. After the v0.9.1 onset fix, ask them to re-test.
- Memory file: `~/.claude/projects/-home-sebastian-Documents-APPS/memory/beat_project.md`.
- Web app changelog/status: `Beat/PROGRESS.md` (the OTHER progress file, for the web build).
