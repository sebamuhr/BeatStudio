"""AI arrangement layer — the "stop working double" feature.

Idea (the user's): don't ask a model to *hear* audio. Turn the beatbox into NUMBERS (our DSP +
CLAP already do this: onsets, tempo, pitches, timbre clusters), then hand that symbolic sketch to
a big reasoning model on the home server. It reasons over the WHOLE track at once and expands the
sketch into a full, musical arrangement — the long melody behind the ts/pf, a bassline, harmony,
cleaned-up drums — which we render with our own synth engine. The user then just tweaks.

Philosophy: musical, not exact. We don't chase transcription accuracy; we hand the model a rough
sketch and let it make something that *sounds good*.
"""
from __future__ import annotations
import json
import re

from .model import Project, Lane, Event
from .synth import DRUMS, WAVES
from . import llm

_ALLOWED_DRUM = set(DRUMS)
_ALLOWED_SYNTH = set(WAVES)


# ---------------- serialize the current groove → compact symbolic sketch ----------------
def project_to_sketch(project: Project) -> dict:
    """A small, LLM-friendly description of what was beatboxed. Notes are [beat, pitch|null, len]
    rounded to keep the payload tiny and readable."""
    tracks = []
    for lane in project.lanes:
        evs = sorted(project.events_for(lane.id), key=lambda e: e.beat)
        if not evs:
            continue
        role = "melody" if lane.kind == "synth" else "drum"
        notes = [[round(e.beat, 3),
                  (int(e.pitch) if (role == "melody" and e.pitch) else None),
                  round(e.length or 0, 3)] for e in evs]
        tracks.append({"name": lane.name, "role": role, "sound": lane.sound, "notes": notes})
    return {"bpm": int(project.bpm), "beats_per_bar": 4, "tracks": tracks}


# ---------------- prompt ----------------
_SYSTEM = (
    "You are a music producer/arranger. You are given a ROUGH beatbox sketch as symbolic data "
    "(tempo + tracks of notes; beats are in quarter-note units, pitch is MIDI note number or null "
    "for unpitched percussion). Your job: turn the sketch into a FULL, MUSICAL arrangement that a "
    "synth engine will play back. Be musical, not literal — it's fine to reinterpret, clean up "
    "timing, and fill in what the beatboxer implied.\n\n"
    "Do:\n"
    "- Keep the same tempo and overall groove/feel.\n"
    "- Clean the drums into a tight pattern; keep the kick/snare/hat feel.\n"
    "- If there is a melodic/tonal track, treat it as a CONTINUOUS melody line — keep held notes "
    "held; do not chop a sustained note into many. Harmonise it.\n"
    "- ADD what makes it a song: a bassline that follows the harmony, optional pad/chords, tasteful "
    "fills. This is the point — the user beatboxed a seed, you build the track.\n"
    "- Use a musical key/scale consistently.\n\n"
    "Output STRICT JSON only (no prose, no markdown fences), shape:\n"
    '{"bpm": <int>, "tracks": [{"name": <str>, "kind": "drum"|"synth", "sound": <str>, '
    '"notes": [{"beat": <float>, "len": <float>, "vel": <float 0..1>, "pitch": <MIDI int or null>}]}]}\n'
    "For kind=drum, sound MUST be one of: " + ", ".join(DRUMS) + " (pitch=null).\n"
    "For kind=synth, sound MUST be one of: " + ", ".join(WAVES) + " (pitch REQUIRED, MIDI 24-96).\n"
    "beat is in quarter notes from 0. Keep it to a few bars unless the sketch is longer."
)


def build_messages(sketch: dict) -> list[dict]:
    user = ("Here is the beatbox sketch. Arrange it into a full track.\n\n"
            + json.dumps(sketch, separators=(",", ":")))
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]


# ---------------- parse the model's answer → Project ----------------
def _extract_json(text: str) -> dict:
    """Models sometimes wrap JSON in prose or ``` fences. Pull out the first {...} block."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise llm.LLMError("The AI reply wasn't valid JSON.")
    return json.loads(m.group(0))


def _coerce_sound(kind: str, sound: str) -> tuple[str, str]:
    """Force kind/sound onto something our engine can actually play."""
    s = (sound or "").strip().lower()
    if kind == "drum":
        return "drum", (s if s in _ALLOWED_DRUM else "kick")
    if kind == "synth":
        return "synth", (s if s in _ALLOWED_SYNTH else "saw")
    # unknown kind → guess from the sound name
    if s in _ALLOWED_DRUM:
        return "drum", s
    if s in _ALLOWED_SYNTH:
        return "synth", s
    return "drum", "kick"


def arrangement_to_project(arr: dict, base: Project) -> Project:
    """Build a fresh Project from the model's arrangement, inheriting transport from `base`."""
    p = Project(bpm=int(arr.get("bpm") or base.bpm), grid=base.grid, start_at=base.start_at,
                metronome=base.metronome)
    for t in (arr.get("tracks") or []):
        kind, sound = _coerce_sound(t.get("kind", ""), t.get("sound", ""))
        name = str(t.get("name") or (sound.capitalize()))[:40]
        lane = Lane(kind=kind, sound=sound, name=name, auto=True)
        p.lanes.append(lane)
        for n in (t.get("notes") or []):
            try:
                beat = float(n.get("beat"))
            except Exception:
                continue
            if beat < 0:
                continue
            length = max(0.0, float(n.get("len", 0) or 0))
            vel = min(1.0, max(0.1, float(n.get("vel", 0.85) or 0.85)))
            pitch = n.get("pitch")
            if kind == "synth":
                try:
                    pitch = int(pitch) if pitch is not None else 60
                except Exception:
                    pitch = 60
                pitch = min(96, max(24, pitch))
            else:
                pitch = None
            p.events.append(Event(lane_id=lane.id, beat=round(beat, 4), vel=vel,
                                  length=length, pitch=pitch))
    if not p.lanes or not p.events:
        raise llm.LLMError("The AI returned an empty arrangement.")
    return p


def arrange(project: Project, cfg: dict) -> Project:
    """Full round-trip: serialize → call the server → parse → new Project. Raises LLMError."""
    sketch = project_to_sketch(project)
    if not sketch["tracks"]:
        raise llm.LLMError("Nothing to arrange yet — record or add some beats first.")
    text = llm.chat(cfg.get("ai_base_url", ""), cfg.get("ai_model", ""),
                    build_messages(sketch), api_key=cfg.get("ai_api_key", ""),
                    temperature=0.7, timeout=300.0)
    arr = _extract_json(text)
    return arrangement_to_project(arr, project)
