"""CLAP-based audio matching — a real neural audio embedding, run fully locally.

Loads the CLAP model once (weights cached under ~/.cache/huggingface after the first
run), embeds each sound into a 512-D vector, and matches by cosine similarity. This is
far better at telling beatbox sounds apart than the hand-crafted DSP features.

Everything runs offline after the one-time model download. If torch/transformers aren't
installed, `available()` returns False and the app falls back to the DSP matcher.
"""
from __future__ import annotations
import numpy as np

_MODEL = None
_PROC = None
_TORCH = None
_LOAD_ERR = None
CLAP_ID = "laion/clap-htsat-unfused"
CLAP_SR = 48000
# cosine-distance threshold (0 = identical). Same sound ≈ 0.0–0.25, different ≈ 0.3–0.9.
CLAP_THRESH = 0.45


def available() -> bool:
    try:
        import torch  # noqa
        import transformers  # noqa
        return True
    except Exception:
        return False


def _resample(buf: np.ndarray, sr: int, target: int) -> np.ndarray:
    if sr == target or len(buf) < 2:
        return buf.astype(np.float32)
    n = int(round(len(buf) * target / sr))
    x = np.interp(np.linspace(0, len(buf) - 1, n), np.arange(len(buf)), buf)
    return x.astype(np.float32)


def load(progress=None):
    """Load the model (slow first time: downloads ~600MB weights). Returns True on success."""
    global _MODEL, _PROC, _TORCH, _LOAD_ERR
    if _MODEL is not None:
        return True
    try:
        import torch
        from transformers import ClapModel, ClapProcessor
        _TORCH = torch
        if progress:
            progress("Loading CLAP model (first run downloads ~600MB)…")
        _MODEL = ClapModel.from_pretrained(CLAP_ID)
        _PROC = ClapProcessor.from_pretrained(CLAP_ID)
        _MODEL.eval()
        return True
    except Exception as e:
        _LOAD_ERR = str(e)
        _MODEL = None
        return False


def load_error():
    return _LOAD_ERR


def embed(buf: np.ndarray, sr: int) -> np.ndarray | None:
    """Return a unit-norm 512-D embedding for one sound, or None if unavailable."""
    if _MODEL is None and not load():
        return None
    x = _resample(np.asarray(buf, np.float32), sr, CLAP_SR)
    if len(x) < CLAP_SR // 20:                       # pad very short hits to ~50ms
        x = np.pad(x, (0, CLAP_SR // 20 - len(x)))
    mx = float(np.abs(x).max()) or 1.0
    x = x / mx
    with _TORCH.no_grad():
        try:
            inputs = _PROC(audio=x, sampling_rate=CLAP_SR, return_tensors="pt")
        except (TypeError, ValueError):
            inputs = _PROC(audios=x, sampling_rate=CLAP_SR, return_tensors="pt")
        out = _MODEL.get_audio_features(**inputs)
        emb = (out.pooler_output if hasattr(out, "pooler_output") else out)[0].cpu().numpy()
    n = np.linalg.norm(emb) or 1.0
    return (emb / n).astype(np.float32)


def cosine_dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(1.0 - np.dot(a, b))


# Zero-shot categories → the instrument we assign. Lets us split a groove WITHOUT a
# "My Sounds" gallery, and catch sounds beyond drums (vocal/bass/scratch).
LABELS = [
    ("a kick drum, deep bass boom", "kick"),
    ("an 808 sub bass drum", "808"),
    ("a snare drum", "snare"),
    ("a rimshot click", "rim"),
    ("a hand clap", "clap"),
    ("a closed hi-hat, short tss", "hat"),
    ("an open hi-hat, long tsss", "openhat"),
    ("a crash cymbal", "cymbal"),
    ("a tom drum", "tomM"),
    ("a cowbell", "cowbell"),
    ("a shaker", "shaker"),
    ("a beatbox vocal scratch", "rim"),
    ("a bass synth note, humming", "808"),
    ("a whistle or high tone", "openhat"),
]

_TEXT_EMB = None


def _text_embeddings():
    global _TEXT_EMB
    if _TEXT_EMB is not None:
        return _TEXT_EMB
    if _MODEL is None and not load():
        return None
    prompts = [p for p, _ in LABELS]
    with _TORCH.no_grad():
        inputs = _PROC(text=prompts, return_tensors="pt", padding=True)
        out = _MODEL.get_text_features(**inputs)
        emb = (out.pooler_output if hasattr(out, "pooler_output") else out).cpu().numpy()
    emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9)
    _TEXT_EMB = emb.astype(np.float32)
    return _TEXT_EMB


def classify(buf: np.ndarray, sr: int):
    """Zero-shot: return (sound_key, confidence 0..1) for the closest category, or None."""
    emb = embed(buf, sr)
    txt = _text_embeddings()
    if emb is None or txt is None:
        return None
    sims = txt @ emb                      # cosine (both unit-norm)
    i = int(np.argmax(sims))
    return LABELS[i][1], float(sims[i])


# ---- instrument reference embeddings (audio-to-audio matching) ----
# Render each built-in voice once, embed it, and match a recorded hit to the NEAREST one by
# audio similarity. This is what the user asked for: compare waveforms, pick the closest.
# (kind, sound_key) — the instrument each reference maps to.
INSTRUMENTS = [
    ("drum", "kick"), ("drum", "808"), ("drum", "snare"), ("drum", "rim"),
    ("drum", "clap"), ("drum", "hat"), ("drum", "openhat"), ("drum", "cymbal"),
    ("drum", "tomL"), ("drum", "tomM"), ("drum", "tomH"), ("drum", "cowbell"),
    ("drum", "shaker"), ("drum", "congaH"), ("drum", "congaL"),
    ("synth", "bass"), ("synth", "square"), ("synth", "saw"),
]
_INSTR_REFS = None


def instrument_refs():
    """[(kind, sound_key, embedding)] for all built-in voices, embedded with CLAP (cached)."""
    global _INSTR_REFS
    if _INSTR_REFS is not None:
        return _INSTR_REFS
    if _MODEL is None and not load():
        return None
    from . import synth
    refs = []
    for kind, key in INSTRUMENTS:
        if kind == "drum":
            wav = synth.drum(key, 1.0)
        else:
            wav = synth.synth(key, synth.midi_to_hz(48), 0.35, 0.9)   # low note = beatbox-ish
        e = embed(wav, synth.SR)
        if e is not None:
            refs.append((kind, key, e))
    _INSTR_REFS = refs
    return refs


def nearest_instrument(emb):
    """Return (kind, sound_key, distance) for the closest built-in instrument to `emb`."""
    refs = instrument_refs()
    if not refs or emb is None:
        return None
    best, bd = None, 9.9
    for kind, key, e in refs:
        d = cosine_dist(emb, e)
        if d < bd:
            bd, best = d, (kind, key)
    return (best[0], best[1], bd) if best else None
