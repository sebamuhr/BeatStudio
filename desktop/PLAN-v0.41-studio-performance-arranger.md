# PLAN — v0.41+: Studio = LIVE-PERFORMANCE RECORDER → CLIP ARRANGER

**Vision (user, 2026-07).** The Separator makes SAMPLES and assigns each to an APC pad column. You
**perform live** on the pads (start/stop/switch loops). The Studio **records that performance**: every loop
you trigger appears as a **CLIP** on the Studio timeline at the moment you hit it, for as long as it played.
Then the Studio is where you **arrange** — extend (loop longer), crop, move, EQ, delete clips — turning a
live take into a song base. **The Studio stops showing beats/notes; it shows CLIPS.**

This realises the v0.35 link model: a clip = a REFERENCE to a separator sample (linked content), with its
own position + length (how long you held it). Editing the sample on the separator updates all its clips.

## Data model
- `Clip`: `{track_id/column, variation, start_beat, length_beats, eq/mix overrides?}` — references a
  separator track (its instrument + beats + loop region = the sample). NOT a copy of audio.
- The Studio timeline = **lanes** (one per pad column / separator track) of clips. Replaces the current
  1:1 beat-mirror as the Studio's primary surface.

## PHASE 1 — Record the performance → clips appear + play back
- **● Record performance** (Studio). Arms capture; a beat-clock runs off the bpm.
- Pad **START** (press) opens a clip on that column's lane at the current beat; **STOP** (re-press / switch
  variation / record-end) closes it (sets length). Switching variation closes the old clip and opens a new
  one (its variation) contiguously.
- Draw clips as coloured bars on lanes (colour = track). Play the arrangement: each clip loops its sample
  over its span (reuse `Looper` / `render`), scheduled by the transport.

## PHASE 2 — Clip editing
- Drag a clip to MOVE; drag its right edge to EXTEND (loop repeats to fill); left edge to CROP; delete;
  copy/paste/duplicate. Snap to the grid/bar.

## PHASE 3 — Per-clip tweaks + linked propagation
- Per-clip EQ/volume (the 8-knob MIX, or a subset) as clip overrides. Editing a sample on the separator
  re-renders and updates every clip that references it (linked). Variations remain switchable.

## DECISIONS TO LOCK (before building)
1. **Quantize?** Snap recorded clip starts/lengths to the BAR (recommended — stays in time, loops
   phase-lock) vs. land exactly when pressed (free/human feel).
2. **Old beat-grid Studio:** retire it (Studio becomes clips only) vs. keep it as a second view. Recommend
   RETIRE (Studio = arrangement; the board is where beats/notes are drawn).
3. Later: does a clip keep playing its loop until its `length` (extend = more repeats), and does cropping
   below one loop just truncate? (Recommend yes, per v0.35.)

## Build order
Phase 1 (record → clips + playback) → Phase 2 (edit) → Phase 3 (mix/linked). Each: implement → extend
`board_check` → screenshot → keep checks green.
