"""My Sounds — the user's personal sample library (used as instruments + for matching).

Each sound is a recorded buffer plus edit params (trim, base pitch, gain, loop). Stored
in <dir>/index.json + <id>.npy so it persists across sessions.
"""
from __future__ import annotations
import os
import json
import itertools
import numpy as np

from .synth import SR
from .analysis import seg_features, onset_start

_ids = itertools.count(1)


class Sound:
    def __init__(self, id, name, buf, sr=SR, base_pitch=60, trim_start=0.0, trim_end=None,
                 gain=1.0, loop=False):
        self.id = id
        self.name = name
        self.buf = np.asarray(buf, np.float32)
        self.sr = sr
        self.base_pitch = base_pitch
        self.trim_start = trim_start
        self.trim_end = trim_end if trim_end is not None else len(self.buf) / sr
        self.gain = gain
        self.loop = loop

    @property
    def length(self):
        return len(self.buf) / self.sr

    def trimmed(self) -> np.ndarray:
        a = max(0, int(self.trim_start * self.sr))
        b = min(len(self.buf), int(self.trim_end * self.sr))
        if b <= a:
            return self.buf * self.gain
        return (self.buf[a:b] * self.gain).astype(np.float32)

    def meta(self):
        return {"id": self.id, "name": self.name, "sr": self.sr, "base_pitch": self.base_pitch,
                "trim_start": self.trim_start, "trim_end": self.trim_end, "gain": self.gain,
                "loop": self.loop}


class SoundLibrary:
    def __init__(self, directory):
        self.dir = directory
        self.sounds: list[Sound] = []
        self._feat = {}
        self._clap = {}          # id -> CLAP embedding (cached)
        self.load()

    def load(self):
        self.sounds = []
        idx = os.path.join(self.dir, "index.json")
        if not os.path.isfile(idx):
            return
        try:
            meta = json.load(open(idx, encoding="utf-8"))
        except Exception:
            return
        for m in meta.get("sounds", []):
            p = os.path.join(self.dir, m["id"] + ".npy")
            if not os.path.isfile(p):
                continue
            buf = np.load(p)
            self.sounds.append(Sound(m["id"], m.get("name", "Sound"), buf, m.get("sr", SR),
                                     m.get("base_pitch", 60), m.get("trim_start", 0.0),
                                     m.get("trim_end"), m.get("gain", 1.0), m.get("loop", False)))

    def _write_index(self):
        os.makedirs(self.dir, exist_ok=True)
        json.dump({"sounds": [s.meta() for s in self.sounds]},
                  open(os.path.join(self.dir, "index.json"), "w", encoding="utf-8"), indent=1)

    def add(self, buf, name=None, sr=SR) -> Sound:
        sid = "s%d" % next(_ids)
        while any(s.id == sid for s in self.sounds):
            sid = "s%d" % next(_ids)
        s = Sound(sid, name or f"Sound {len(self.sounds) + 1}", buf, sr)
        self.sounds.append(s)
        os.makedirs(self.dir, exist_ok=True)
        np.save(os.path.join(self.dir, sid + ".npy"), s.buf)
        self._write_index()
        self._feat.pop(sid, None)
        return s

    def save(self, sound: Sound):
        self._feat.pop(sound.id, None)
        self._clap.pop(sound.id, None)
        self._write_index()

    def delete(self, sid):
        self.sounds = [s for s in self.sounds if s.id != sid]
        try:
            os.remove(os.path.join(self.dir, sid + ".npy"))
        except OSError:
            pass
        self._write_index()

    def get(self, sid):
        return next((s for s in self.sounds if s.id == sid), None)

    def samples_dict(self):
        """{'mys:<id>': {'buf': trimmed, 'base': base_pitch}} for the renderer."""
        return {"mys:" + s.id: {"buf": s.trimmed(), "base": s.base_pitch} for s in self.sounds}

    def features(self, sid):
        if sid in self._feat:
            return self._feat[sid]
        s = self.get(sid)
        if not s:
            return None
        buf = s.trimmed()
        st = onset_start(buf, 0, len(buf))
        f = seg_features(buf, st, s.sr)
        self._feat[sid] = f
        return f

    def clap_embedding(self, sid):
        """Cached CLAP embedding for a gallery sound (None if CLAP unavailable)."""
        if sid in self._clap:
            return self._clap[sid]
        from . import ai_match
        s = self.get(sid)
        if not s:
            return None
        emb = ai_match.embed(s.trimmed(), s.sr)
        self._clap[sid] = emb
        return emb

    def invalidate(self, sid):
        self._feat.pop(sid, None)
        self._clap.pop(sid, None)
