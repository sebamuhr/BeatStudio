"""Render a Project to a mono float32 buffer by summing scheduled voices.

We pre-render the whole timeline (glitch-free), then stream it. Live edits during
playback just re-render. Mirrors the web app's offline scheduling.
"""
from __future__ import annotations
import numpy as np
from . import synth
from .synth import SR

# When a sample-lane has no loaded sample yet, fall back to a distinct percussion
# voice per track so the groove is audible.
_FALLBACK = ["kick", "snare", "hat", "clap", "tomM", "rim", "cowbell", "shaker", "congaH", "openhat"]
_DRUM_REF = 60   # a drum note at this MIDI plays NATURAL; above/below resamples it up/down (tom up/down)


def _pitch_track_hz(e, spb, tune):
    """Per-sample frequency array for a TIED note (NOTES-view line). `pitch_track` is a coarse MIDI
    curve (held = repeated steps, glide = a slide); resample it to the note's sample length."""
    pt = np.asarray(e.pitch_track, np.float32).ravel()
    if len(pt) < 1:
        return None
    n = max(2, int((e.length or 0) * spb * SR))
    midi = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(pt)), pt) if len(pt) >= 2 \
        else np.full(n, float(pt[0]), np.float32)
    return (440.0 * (2.0 ** ((midi + tune - 69.0) / 12.0))).astype(np.float32)


def _voice_for(lane, e, spb, li, samples):
    kind = lane.kind
    tune = e.tune or 0
    # A TIED note (a line in the NOTES view) → ONE sustained voice that GLIDES along the pitch track.
    # Held segments repeat a step (staircase), glide segments slide — both live in e.pitch_track.
    if e.pitch_track and kind in ("drum", "hum", "inst", "sample", "synth"):
        freq = _pitch_track_hz(e, spb, tune)
        if freq is not None and len(freq) >= 2:
            bp = getattr(lane, "sound_params", None)
            snd = lane.sound
            if kind == "hum":
                x = synth.hum_voice(snd, freq, params=bp)
            elif kind == "inst":
                x = synth.inst_voice(snd, freq, params=bp)
            else:                                    # drum / sample / synth: filtered-osc glide voice
                x = synth.glide_voice(snd if kind != "synth" else (snd or "sine"), freq, bp)
            x = (x * max(0.2, min(1.2, e.vel or 0.85))).astype(np.float32)
            eq = e.eq or {}
            return synth.apply_eq(x, eq.get("low", 0), eq.get("mid", 0), eq.get("high", 0))
    if kind == "drum":
        dur = (e.length or 0) * spb
        # a long drawn region → a buzz-ROLL (the "tsssss"); a short one → a single hit
        x = synth.drum_roll(lane.sound, e.vel, dur) if dur > 0.14 else synth.drum(lane.sound, e.vel)
        if e.pitch is not None and int(e.pitch) + tune != _DRUM_REF:   # NOTES pitch → resample (tom up/down)
            x = synth.sample_voice(x, _DRUM_REF, int(e.pitch) + tune, 0.0, 1.0, loop=False)
    elif kind == "synth":
        freq = synth.midi_to_hz((e.pitch if e.pitch is not None else 60) + tune)
        dur = max(0.15, (e.length or 0) * spb) if e.length else 0.3
        bp = getattr(lane, "sound_params", None); mp = getattr(lane, "sound_b_params", None)
        if e.env:
            # the SIREN: one sustained voice gliding pitch+timbre along the drawn morph curve
            lo = getattr(lane, "lo_note", 48); hi = getattr(lane, "hi_note", 72)
            x = synth.morph_glide(lane.sound or "sine", lane.sound_b, lo, hi, dur, e.env,
                                  base_params=bp, mod_params=mp, vel=e.vel)
        elif lane.sound_b and e.morph is not None:
            m1 = e.morph_end if e.morph_end is not None else e.morph
            x = synth.morph_synth(lane.sound or "sine", lane.sound_b, freq, dur, e.vel, e.morph, m1)
        else:
            x = synth.voice(lane.sound or "square", freq, dur, e.vel, bp)
    elif kind == "sample":
        samp = (samples or {}).get(lane.sound)
        if samp is not None:
            dur = (e.length or 0) * spb
            x = synth.sample_voice(samp["buf"], samp.get("base", 60),
                                   (e.pitch if e.pitch is not None else 60) + tune, dur, e.vel)
        else:
            x = synth.drum(_FALLBACK[li % len(_FALLBACK)], e.vel)
    else:
        return None
    eq = e.eq or {}
    return synth.apply_eq(x, eq.get("low", 0), eq.get("mid", 0), eq.get("high", 0))


def _orig_slice(orig, e):
    a = max(0, int((e.src_t or 0) * SR))
    b = min(len(orig), a + int((e.src_dur or 0.28) * SR))
    if b <= a:
        return None
    seg = (orig[a:b] * max(0.05, min(1.4, e.vel or 0.85))).astype(np.float32)
    rel = min(len(seg), int(0.02 * SR))
    if rel > 1:
        seg = seg.copy(); seg[-rel:] *= np.linspace(1, 0, rel, dtype=np.float32)
    return seg


def _vol_gain(lane, spb, n):
    """Per-sample gain array (len n) from lane.vol_pts [{beat,v}]; 1.0 (unity) when empty."""
    pts = sorted((getattr(lane, "vol_pts", None) or []), key=lambda q: q["beat"])
    if not pts:
        return None                       # None → unity, skip the multiply
    t = np.arange(n, dtype=np.float32) / SR / max(1e-6, spb)   # beat at each sample
    bx = np.array([p["beat"] for p in pts], np.float32)
    by = np.array([max(0.0, min(1.5, float(p["v"]))) for p in pts], np.float32)
    return np.interp(t, bx, by, left=by[0], right=by[-1]).astype(np.float32)


def render_project(project, samples=None, tail=0.6, orig=None):
    """Return (buffer float32 mono, seconds_per_beat). `orig` = master take for play_original.

    Renders each lane into its OWN buffer, applies that lane's volume envelope, then sums —
    this per-lane path is the home for volume automation (and, later, per-lane FX).
    """
    spb = 60.0 / max(1, project.bpm)
    max_beat = project.max_beat()
    # reverb/delay FX add a tail — grow the buffer so they aren't cut off
    fx_extra = max((synth.fx_tail(getattr(l, "fx", None)) for l in project.lanes), default=0.0)
    total = int((max_beat * spb + tail + fx_extra) * SR) + SR // 4
    buf = np.zeros(total + SR, np.float32)

    solos = [l for l in project.lanes if l.solo]
    pool = solos if solos else project.lanes
    active = {l.id for l in pool if not l.muted}
    lanes_by_id = {l.id: (i, l) for i, l in enumerate(project.lanes)}

    # group events per lane so each lane can be shaped by its own volume envelope
    by_lane = {}
    for e in project.events:
        by_lane.setdefault(e.lane_id, []).append(e)

    for lane_id, events in by_lane.items():
        li_lane = lanes_by_id.get(lane_id)
        if not li_lane:
            continue
        li, lane = li_lane
        if lane.id not in active or lane.kind == "master":
            continue
        lane_buf = np.zeros(len(buf), np.float32)
        for e in events:
            if lane.play_original and orig is not None and e.src_t is not None:
                v = _orig_slice(orig, e)
            else:
                v = _voice_for(lane, e, spb, li, samples)
            if v is None:
                continue
            start = int(project.snap(e.beat) * spb * SR)
            if start >= len(lane_buf):
                continue
            end = min(len(lane_buf), start + len(v))
            lane_buf[start:end] += v[:end - start]
        fx = getattr(lane, "fx", None)
        if fx and any(v > 0 for v in fx.values()):
            lane_buf = synth.apply_fx(lane_buf, fx)          # may return a longer buffer (tail)
            if len(lane_buf) < len(buf):
                lane_buf = np.concatenate([lane_buf, np.zeros(len(buf) - len(lane_buf), np.float32)])
            else:
                lane_buf = lane_buf[:len(buf)]
        gain = _vol_gain(lane, spb, len(lane_buf))
        if gain is not None:
            lane_buf *= gain
        buf += lane_buf

    if getattr(project, "metronome", False):
        b = 0
        while b * spb * SR < len(buf):
            c = synth.click(accent=(b % 4 == 0))
            s = int(b * spb * SR); e = min(len(buf), s + len(c))
            buf[s:e] += c[:e - s]
            b += 1

    np.tanh(buf * 0.9, out=buf)        # soft clip
    buf *= 0.9
    return buf[:total].astype(np.float32), spb
