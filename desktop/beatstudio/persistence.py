"""Project save/load (JSON), MIDI export (mido), and phone-sync groove loading.

from_dict is tolerant of the WEB app's groove format (type/laneId/len) so grooves the
phone records and syncs via server.py load straight into the desktop app.
"""
from __future__ import annotations
import json
import os
import mido

from .model import Project, Lane, Event

# General-MIDI percussion notes (channel 10) for our drum voices
DRUM_NOTE = {"kick": 36, "808": 35, "snare": 38, "rim": 37, "clap": 39,
             "tomL": 45, "tomM": 47, "tomH": 50, "hat": 42, "openhat": 46,
             "cowbell": 56, "shaker": 70, "congaH": 62, "congaL": 63, "cymbal": 49}


def to_dict(p: Project) -> dict:
    return {
        "bpm": p.bpm, "grid": p.grid, "start_at": p.start_at, "metronome": p.metronome,
        "loop_on": p.loop_on, "loop_start": p.loop_start, "loop_end": p.loop_end,
        "lanes": [{"id": l.id, "kind": l.kind, "sound": l.sound, "sound_b": l.sound_b, "name": l.name,
                   "muted": l.muted, "solo": l.solo, "auto": l.auto, "eq": l.eq, "src_master": l.src_master,
                   "color": l.color, "sound_params": l.sound_params, "sound_b_params": l.sound_b_params,
                   "lo_note": l.lo_note, "hi_note": l.hi_note, "vol_pts": l.vol_pts, "fx": l.fx,
                   "has_original": l.has_original, "play_original": l.play_original} for l in p.lanes],
        "events": [{"id": e.id, "lane_id": e.lane_id, "beat": e.beat, "vel": e.vel,
                    "length": e.length, "pitch": e.pitch, "tune": e.tune, "eq": e.eq,
                    "src_t": e.src_t, "src_dur": e.src_dur,
                    "morph": e.morph, "morph_end": e.morph_end, "env": e.env,
                    "src_track": e.src_track, "src_pts": e.src_pts} for e in p.events],
    }


def from_dict(d: dict) -> Project:
    d = d.get("state", d)          # web grooves wrap data under "state"
    p = Project(bpm=int(d.get("bpm", 90)), grid=int(d.get("grid", 4)),
                start_at=d.get("start_at", d.get("startAt", 0)) or 0,
                metronome=bool(d.get("metronome", False)),
                loop_on=bool(d.get("loop_on", d.get("loopOn", False))),
                loop_start=d.get("loop_start", d.get("loopStart")),
                loop_end=d.get("loop_end", d.get("loopEnd")))
    for l in d.get("lanes", []):
        p.lanes.append(Lane(id=l["id"], kind=l.get("kind") or l.get("type", "drum"),
                            sound=l.get("sound", "kick"), sound_b=l.get("sound_b", ""),
                            name=l.get("name") or l.get("soundName", "Sound"),
                            muted=bool(l.get("muted", False)), solo=bool(l.get("solo", False)),
                            auto=bool(l.get("auto", False)),
                            has_original=bool(l.get("has_original", False)),
                            play_original=bool(l.get("play_original", False)),
                            src_master=l.get("src_master"),
                            color=l.get("color", ""),
                            sound_params=l.get("sound_params") or {},
                            sound_b_params=l.get("sound_b_params") or {},
                            lo_note=int(l.get("lo_note", 48)), hi_note=int(l.get("hi_note", 72)),
                            vol_pts=l.get("vol_pts") or [],
                            fx=l.get("fx") or {},
                            eq=l.get("eq") or {"low": 0, "mid": 0, "high": 0}))
    for e in d.get("events", []):
        p.events.append(Event(id=e.get("id"), lane_id=e.get("lane_id") or e.get("laneId"),
                             beat=e.get("beat", 0), vel=e.get("vel", 0.85),
                             length=e.get("length", e.get("len", 0)) or 0,
                             pitch=e.get("pitch"), tune=e.get("tune", 0),
                             eq=e.get("eq") or {"low": 0, "mid": 0, "high": 0},
                             src_t=e.get("src_t", e.get("srcT")), src_dur=e.get("src_dur", e.get("srcDur")),
                             morph=e.get("morph"), morph_end=e.get("morph_end"), env=e.get("env"),
                             src_track=e.get("src_track"), src_pts=e.get("src_pts")))
    return p


def save_project(p: Project, path: str):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(to_dict(p), fh, indent=1)


def load_project(path: str) -> Project:
    with open(path, "r", encoding="utf-8") as fh:
        return from_dict(json.load(fh))


NOTE_DRUM = {v: k for k, v in DRUM_NOTE.items()}   # reverse map for MIDI import


def export_midi(p: Project, path: str, tpb: int = 480):
    """Standard multi-track MIDI so the groove opens cleanly in any DAW: one named track per lane,
    drums on channel 10 (GM notes), melodic/synth lanes on their own channels."""
    mid = mido.MidiFile(ticks_per_beat=tpb)
    meta = mido.MidiTrack(); mid.tracks.append(meta)
    meta.append(mido.MetaMessage("track_name", name="Tempo"))
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(p.bpm)))
    ev_by_lane = {}
    for e in p.events:
        ev_by_lane.setdefault(e.lane_id, []).append(e)
    ch_seq = 0
    for li, lane in enumerate(p.lanes):
        if lane.kind == "master":
            continue
        events = ev_by_lane.get(lane.id, [])
        if not events:
            continue
        track = mido.MidiTrack(); mid.tracks.append(track)
        track.append(mido.MetaMessage("track_name", name=(lane.name or f"Track {li + 1}")))
        drum = lane.kind == "drum"
        if drum:
            ch = 9
        else:
            ch = ch_seq if ch_seq != 9 else 10   # skip the drum channel
            ch_seq += 1
        msgs = []
        for e in events:
            if drum:
                note, length = DRUM_NOTE.get(lane.sound, 36), tpb // 8
            else:
                note = (e.pitch if e.pitch is not None else 60) + (e.tune or 0)
                length = max(1, int((e.length or 0.25) * tpb))
            note = max(0, min(127, int(note)))
            start = int(p.snap(e.beat) * tpb)
            vel = max(1, min(127, int((e.vel or 0.8) * 127)))
            msgs.append((start, 1, mido.Message("note_on", note=note, velocity=vel, channel=ch)))
            msgs.append((start + length, 0, mido.Message("note_off", note=note, velocity=0, channel=ch)))
        msgs.sort(key=lambda m: (m[0], m[1]))
        last = 0
        for tick, _, msg in msgs:
            msg.time = tick - last; last = tick
            track.append(msg)
    mid.save(path)


def import_midi(path: str) -> Project:
    """Build a Project from a standard MIDI file (for grooves made in other software). Drums (ch 10)
    become one drum lane per GM note; other channels become synth lanes. Lossy vs. .beat but portable."""
    mid = mido.MidiFile(path)
    tpb = mid.ticks_per_beat or 480
    bpm = 120.0
    for tr in mid.tracks:
        for msg in tr:
            if msg.type == "set_tempo":
                bpm = mido.tempo2bpm(msg.tempo); break
    p = Project(bpm=int(round(bpm)), grid=16)
    drum_lanes = {}     # gm note -> Lane
    for ti, tr in enumerate(mid.tracks):
        name = next((m.name for m in tr if m.type == "track_name"), f"Track {ti}")
        t = 0; on = {}; mono = None
        for msg in tr:
            t += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                on[(msg.channel, msg.note)] = (t, msg.velocity)
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                key = (msg.channel, msg.note)
                if key not in on:
                    continue
                start, vel = on.pop(key)
                beat = start / tpb
                length = max(0.05, (t - start) / tpb)
                v = max(0.05, min(1.0, vel / 127.0))
                if msg.channel == 9:
                    lane = drum_lanes.get(msg.note)
                    if lane is None:
                        snd = NOTE_DRUM.get(msg.note, "kick")
                        lane = Lane(kind="drum", sound=snd, name=snd.capitalize())
                        drum_lanes[msg.note] = lane; p.lanes.append(lane)
                    p.events.append(Event(lane_id=lane.id, beat=beat, vel=v, length=length))
                else:
                    if mono is None:
                        mono = Lane(kind="synth", sound="saw", name=name)
                        p.lanes.append(mono)
                    p.events.append(Event(lane_id=mono.id, beat=beat, vel=v,
                                          pitch=int(msg.note), length=length))
    return p


def save_song(p: Project, path: str) -> str:
    """Save for BOTH worlds: a standard .mid (opens in any DAW) PLUS a full-fidelity .beat sidecar
    (synths/FX/board/automation) next to it, so reopening here restores everything. Returns the .mid path."""
    base, ext = os.path.splitext(path)
    if ext.lower() != ".mid":
        path = base + ".mid"
    export_midi(p, path)
    with open(base + ".beat", "w", encoding="utf-8") as fh:
        json.dump(to_dict(p), fh, indent=1)
    return path


def open_song(path: str) -> Project:
    """Open a .beat/.json project (full fidelity) or a .mid. For a .mid, prefer a matching .beat
    sidecar (full fidelity) when present, otherwise import the raw MIDI notes."""
    base, ext = os.path.splitext(path); ext = ext.lower()
    if ext in (".beat", ".json"):
        return load_project(path)
    side = base + ".beat"
    if os.path.exists(side):
        return load_project(side)
    return import_midi(path)


def list_synced(sync_dir: str):
    if not os.path.isdir(sync_dir):
        return []
    out = []
    for f in sorted(os.listdir(sync_dir)):
        if f.endswith(".json"):
            path = os.path.join(sync_dir, f)
            try:
                with open(path, encoding="utf-8") as fh:
                    d = json.load(fh)
                out.append((d.get("id", f[:-5]), d.get("name", f[:-5]), path))
            except Exception:
                pass
    return out
