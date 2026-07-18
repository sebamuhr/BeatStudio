# PLAN — v0.35: Separator = SAMPLE FACTORY · Studio = SONG ARRANGER

**Vision (user, 2026-07-18).** A clean split of the two windows:
- **The Separator makes SAMPLES.** Each track is its own little sound you craft: record a **guide**
  (hum / beatbox) into it, see its pitch, pick the matching instrument/hum/synth, draw its beats/notes.
  The recording is a **guide, not usually the output** — it helps you choose the instrument and notes.
- **The Studio arranges the SONG.** You take a **selected region** of a finished sample over to the Studio
  and arrange the whole track there — place / copy / paste / drag the samples on the song timeline.

## Locked decisions (user Q&A)
1. **1 track = 1 soundwave** (confirmed). Each track row IS a soundwave: its own recording + beats/notes +
   instrument + its own Record / Solo / Mute / Volume-Notes controls.
2. **"Add track" is the only creation button** on the separator. Remove **Record main**, **Record
   secondary**, and the **global Volume/Notes toggle**.
3. **Add track when others exist → a dialog:** **New**, or **Duplicate ‹which track›** — and the duplicate
   dialog also asks **"duplicate the beats too?"** (so you can reuse the same beats on another instrument,
   or start the beats fresh on a copy of the audio).
4. **Record on every track** — the guide recording belongs on each track (you record a hum/beatbox to pick
   the right hum/synth/instrument and to see the notes). It's a guide layer per track.
5. **NEW — "select area" tool** at the **top-right of each soundwave card.** Once a sample is finished, this
   tool lets you **select a region** of the soundwave; **only that selected region is reflected to the
   Studio** as a clip/sample.
6. **Studio = the whole song**, built from those selected clips: **copy / paste / drag** samples on the
   song timeline. Separator = the samples; Studio = the arrangement.

**STABILITY RULE:** one shared point/lane/take model; every edit propagates to volume view, notes view,
Studio, playback, undo. Wire through the existing signals — no parallel data.

---

## PHASE 1 — Separator restructure: 1 track = 1 soundwave, per-track controls
Make each track own its soundwave, and move all per-wave controls into the sidebar track rows.

- **Model:** enforce **1 track ↔ 1 take** (each `add_track` also mints a dedicated take and binds it;
  `tr["take"]` is unique per track). Keeps the existing take-drives-canvas-rows machinery (each track now
  has its own waveform row) — a smaller, safer change than merging the two lists outright.
- **Sidebar track row gets the Studio-style cluster** (REC · S · V/N · M) — reuse the visuals:
  - **Record** → records a guide into THIS track's take (per-track record; see recording rewire).
  - **Solo / Mute** → the take's solo/muted (already built in v0.34 as per-wave flags; now per-track since 1:1).
  - **Volume/Notes toggle** → this track's view (already have per-take mode memory from v0.34).
- **Remove** from the toolbar: `Record main`, `Record secondary`, the global `▁ Volume / ♪ Notes` toggle.
- **Recording rewire (`mainwindow`):** a new `board.record_track=Signal(str)` (lane_id). The handler records
  into that track's take (replace/overdub its buf), like `_toggle_secondary_record` but targeting an
  existing take instead of appending. `_toggle_master_record`/`_toggle_secondary_record` retired from the UI.
- **Add-track dialog:** when tracks exist, `add_track` opens New / Duplicate‹which› (+ "also beats?").
  Duplicate copies the source take's buf (+ optionally the points) into a new track/take.
- The canvas per-take checkbox/✕ stays (selection + delete a wave); selecting a track selects its take.
- `board_check`: RECORD SECONDARY / TAKE SELECT tests rewritten to the 1:1 model; new ADD-TRACK-DUP test.

## PHASE 2 — "Select area" → the clip region per sample
- A **select-area tool** button at the **top-right of each soundwave card** (next to ✕). Drag on the wave to
  mark a region `[a,b]` (store `clip_a`/`clip_b` on the take, in take-fractions).
- **Only that region syncs to the Studio.** The board→Studio upsert emits events **clipped to `[a,b]`** and
  offset so the region starts at the clip origin. No selection = the whole take (back-compat).
- Visual: shade the selected region on the card; handles to resize; a small "→ Studio" affordance.

## PHASE 3 — Studio = song arranger (clips: place / copy / paste / drag)
- The Studio timeline becomes an **arrangement of CLIPS** (each = a sample region sent from the separator),
  not a 1:1 mirror of board lanes. A clip carries its lane/voice + events, placed at a song position.
- **Interactions:** drag a clip along the timeline, **copy/paste/duplicate**, delete; multiple copies of the
  same sample at different positions. Snap to grid.
- This is the biggest change — it replaces today's live 1:1 board→lane mirror with a clip model. Needs its
  own detailed sub-plan before building (data model for clips, how edits to a source sample propagate to its
  placed copies — link vs. independent, TBD with the user).

## Open questions to confirm before Phase 2/3
- When a sample is edited on the separator AFTER being placed in the Studio, do its placed copies update
  (linked) or stay as they were (independent snapshots)?
- Can one sample be placed many times (instances), and does per-instance editing detach it?
- Does the Studio still show per-track volume automation / the notes view, or is it purely arrangement?

## Build order
Phase 1 (this cycle) → Phase 2 → Phase 3 (after a sub-plan). Each phase: implement → extend `board_check`
→ screenshot → keep all checks green.
