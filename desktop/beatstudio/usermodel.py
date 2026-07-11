"""Personal sound model — learns YOUR beatbox kit from the labels you give in the review
questionnaire. No pre-registration: every time you label a sound ("this is a kick"), we store
its CLAP fingerprint + label. Next time, we recognise it by nearest-fingerprint match, so the
suggestions get better every session. This is the "train along, not beforehand" approach.

Storage: <dir>/labels.npz  (embeddings + category strings). Grows over time.
"""
from __future__ import annotations
import os
import numpy as np

# The instrument categories offered in the questionnaire.
# (id, human label, lane kind, sound key, play_original)
CATEGORIES = [
    ("kick",    "Kick / Boom",      "drum",  "kick",    False),
    ("808",     "Sub / 808",        "drum",  "808",     False),
    ("snare",   "Snare",            "drum",  "snare",   False),
    ("rim",     "Rimshot / Click",  "drum",  "rim",     False),
    ("clap",    "Clap",             "drum",  "clap",    False),
    ("hat",     "Hi-hat (closed)",  "drum",  "hat",     False),
    ("openhat", "Hi-hat (open)",    "drum",  "openhat", False),
    ("cymbal",  "Cymbal / Crash",   "drum",  "cymbal",  False),
    ("tom",     "Tom",              "drum",  "tomM",    False),
    ("cowbell", "Cowbell / Perc",   "drum",  "cowbell", False),
    ("shaker",  "Shaker",           "drum",  "shaker",  False),
    ("bass",    "Bass (synth)",     "synth", "bass",    False),
    ("melody",  "Melody / Lead",    "synth", "saw",     False),
    ("keep",    "Keep my sound",    "sample", "orig",   True),
    ("skip",    "Ignore this",      None,    None,      False),
]
CAT_BY_ID = {c[0]: c for c in CATEGORIES}


class UserModel:
    def __init__(self, directory):
        self.dir = directory
        self.embs = np.zeros((0, 512), np.float32)
        self.labels: list[str] = []
        self.load()

    def load(self):
        p = os.path.join(self.dir, "labels.npz")
        if os.path.isfile(p):
            try:
                d = np.load(p, allow_pickle=True)
                self.embs = d["embs"].astype(np.float32)
                self.labels = list(d["labels"])
            except Exception:
                self.embs = np.zeros((0, 512), np.float32); self.labels = []

    def save(self):
        os.makedirs(self.dir, exist_ok=True)
        np.savez(os.path.join(self.dir, "labels.npz"),
                 embs=self.embs, labels=np.array(self.labels, dtype=object))

    @property
    def n(self):
        return len(self.labels)

    def add(self, emb, category):
        """Record one labeled example (a sound you told us the name of)."""
        if emb is None or category in (None, "skip"):
            return
        e = np.asarray(emb, np.float32).reshape(1, -1)
        e = e / (np.linalg.norm(e) + 1e-9)
        self.embs = np.vstack([self.embs, e]) if self.n else e
        self.labels.append(category)

    def predict(self, emb, k=5):
        """Nearest-fingerprint vote → (category, confidence 0..1) or (None, 0) if nothing learnt."""
        if self.n == 0 or emb is None:
            return None, 0.0
        e = np.asarray(emb, np.float32)
        e = e / (np.linalg.norm(e) + 1e-9)
        sims = self.embs @ e                       # cosine (both unit-norm)
        idx = np.argsort(-sims)[:min(k, self.n)]
        votes = {}
        for i in idx:
            votes[self.labels[i]] = votes.get(self.labels[i], 0.0) + max(0.0, float(sims[i]))
        best = max(votes, key=votes.get)
        conf = votes[best] / (sum(votes.values()) + 1e-9)
        return best, float(conf)
