"""Turn a raw beatbox take into a MUSICAL groove:

  1. detect onsets (each hit),
  2. estimate the tempo (BPM) from the rhythm,
  3. quantize every hit onto that tempo's 16th-note grid (so a slightly-off human take
     still lands musically — this is what stops the "random" placement),
  4. cluster the hits by timbre (CLAP embedding) so the SAME sound groups into one track.

Uses librosa for beat tracking + scikit-learn for clustering when available, with numpy
fallbacks so the app still runs without them.
"""
from __future__ import annotations
import numpy as np
from scipy import signal

from .analysis import onsets_from, gate_lin
from .synth import SR


def highpass(buf, sr, fc=70.0):
    """Remove DC offset / subsonic rumble that otherwise makes every sound look bass-heavy
    (and creates spurious onsets). Real recordings often carry this junk below ~70 Hz."""
    if len(buf) < 16:
        return buf
    b, a = signal.butter(2, fc / (sr / 2), "high")
    return signal.filtfilt(b, a, buf).astype(np.float32)

try:
    import librosa
    _HAS_LIBROSA = True
except Exception:
    _HAS_LIBROSA = False

try:
    from sklearn.cluster import AgglomerativeClustering
    _HAS_SK = True
except Exception:
    _HAS_SK = False


# ---------------- tempo ----------------
def detect_tempo(buf, sr, onset_times):
    """Return BPM (clamped to a sane musical range)."""
    bpm = None
    if _HAS_LIBROSA:
        try:
            fn = getattr(librosa.feature.rhythm, "tempo", None) or librosa.beat.tempo
            t = fn(y=buf.astype(np.float32), sr=sr)
            bpm = float(np.median(t)) if np.size(t) else None
        except Exception:
            bpm = None
    if bpm is None and len(onset_times) >= 3:
        # fallback: median inter-onset interval → bpm
        iois = np.diff(np.sort(onset_times))
        iois = iois[iois > 0.05]
        if len(iois):
            m = float(np.median(iois))
            bpm = 60.0 / m
    if not bpm or bpm <= 0:
        return 90
    while bpm < 70:
        bpm *= 2
    while bpm > 180:
        bpm /= 2
    return int(round(bpm))


# ---------------- quantize ----------------
def quantize(onset_times, bpm, grid=4):
    """Snap onset times to the nearest 1/grid-of-a-beat, with a phase that best fits the take.
    Returns a list of beat positions (float, e.g. 0.0, 0.25, 1.5)."""
    if not len(onset_times):
        return []
    beat_len = 60.0 / bpm
    sub = beat_len / grid                       # 16th-note in seconds (grid=4)
    # circular-mean phase so the grid lines up with where the hits actually are
    ph = np.array(onset_times) % sub
    ang = 2 * np.pi * ph / sub
    mean_ang = np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())
    phase = (mean_ang / (2 * np.pi)) * sub
    if phase < 0:
        phase += sub
    # grid step index per onset; anchor the earliest hit to beat 0 so positions are clean
    # multiples of 1/grid (0, 0.25, 0.5, …) — a musically-aligned downbeat.
    ks = [round((t - phase) / sub) for t in onset_times]
    k0 = min(ks)
    return [max(0.0, (k - k0) / grid) for k in ks]


# ---------------- acoustic instrument guess ----------------
def classify_acoustic(seg, sr):
    """Guess a drum instrument from a hit's frequency profile (works on high-passed audio).
    Beatbox sounds mimic drums by spectral character: kick=low, snare=mid burst, hat=high hiss.
    Returns a DRUMS key."""
    n = min(len(seg), 4096)
    if n < 256:
        return "kick"
    s = seg[:n] * np.hanning(n)
    mag = np.abs(np.fft.rfft(s))
    freqs = np.fft.rfftfreq(n, 1 / sr)
    e = mag ** 2
    tot = e.sum() + 1e-9
    cen = float((freqs * e).sum() / tot)
    low = float(e[freqs < 250].sum() / tot)
    high = float(e[freqs >= 6000].sum() / tot)
    flat = float(np.exp(np.log(mag + 1e-9).mean()) / (mag.mean() + 1e-9))   # noisiness
    if cen < 900 and low > 0.35:
        return "kick"
    if cen > 6500:
        return "hat" if flat > 0.35 else "openhat"
    if cen > 3500:
        return "openhat" if high > 0.3 else "snare"
    if flat > 0.4:
        return "snare"        # noisy mid burst
    return "tomM"             # tonal mid → tom-ish


# ---------------- pitch ----------------
def detect_pitch(seg, sr):
    """Return (midi_note or None, is_pitched). Melodic beatbox sounds (hums, basslines) have a
    stable f0; percussion doesn't. Uses librosa YIN with a stability check."""
    if not _HAS_LIBROSA or len(seg) < 2048:
        return None, False
    try:
        f0, voiced, vprob = librosa.pyin(seg.astype(np.float32), fmin=65, fmax=1000, sr=sr,
                                         frame_length=2048)
        good = np.isfinite(f0) & voiced
        if good.sum() < 3 or float(np.mean(vprob[voiced])) < 0.5:
            return None, False
        f0v = f0[good]
        med = float(np.median(f0v))
        rel_var = float(np.std(f0v)) / (med + 1e-9)     # stable f0 = a real pitch
        # voiced for a good part of the sound AND stable pitch = melodic
        pitched = (good.mean() > 0.4) and rel_var < 0.18 and 65 <= med <= 1000
        midi = int(round(69 + 12 * np.log2(med / 440.0)))
        return max(24, min(96, midi)), pitched
    except Exception:
        return None, False


# ---------------- melody: note + clean synth timbre ----------------
def note_of(seg, sr):
    """Robust MIDI note for a melodic sound (median of the voiced f0 over the note). None if
    it isn't clearly pitched."""
    if not _HAS_LIBROSA or len(seg) < 2048:
        return None
    try:
        f0, voiced, vprob = librosa.pyin(seg.astype(np.float32), fmin=65, fmax=1200, sr=sr,
                                         frame_length=2048)
        good = np.isfinite(f0) & voiced
        if good.sum() < 3:
            return None
        med = float(np.median(f0[good]))
        return max(24, min(96, int(round(69 + 12 * np.log2(med / 440.0)))))
    except Exception:
        return None


def pick_preset(seg, sr):
    """Choose a CLEAN synth timbre resembling the real sound: bright/buzzy→saw/lead,
    round→sine/triangle, hollow→square, low→bass."""
    n = min(len(seg), 4096)
    if n < 256:
        return "saw"
    s = seg[:n] * np.hanning(n)
    mag = np.abs(np.fft.rfft(s))
    freqs = np.fft.rfftfreq(n, 1 / sr)
    e = mag ** 2
    tot = e.sum() + 1e-9
    cen = float((freqs * e).sum() / tot)
    # harmonicity: peaky spectrum = tonal/round; flat = buzzy/bright
    flat = float(np.exp(np.log(mag + 1e-9).mean()) / (mag.mean() + 1e-9))
    if cen < 220:
        return "bass"
    if cen > 2600:
        return "lead" if flat > 0.25 else "saw"
    if flat < 0.12:
        return "sine"        # very pure/round
    if flat < 0.22:
        return "triangle"
    return "square"          # hollow/reedy


# ---------------- harmonic / percussive layers ----------------
def hpss(buf, sr):
    """Split a take into (harmonic, percussive) layers. This is what lets a sustained BACKGROUND
    TONE stay one continuous sound while ts/pf pops are read as separate percussion — instead of
    the tone being chopped at every hit. Falls back to (buf, buf) without librosa."""
    if not _HAS_LIBROSA or len(buf) < 2048:
        return buf, buf
    try:
        h, p = librosa.effects.hpss(buf.astype(np.float32))
        return h.astype(np.float32), p.astype(np.float32)
    except Exception:
        return buf, buf


# ---------------- pitch ribbon (VISUAL reference only) ----------------
_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(midi):
    """MIDI number → e.g. 'C#4' (MIDI 60 = C4)."""
    m = int(round(float(midi)))
    return f"{_NOTE_NAMES[m % 12]}{m // 12 - 1}"


def pitch_ribbon(buf, sr, hop=512):
    """Per-frame pitch of the WHOLE take, for the visual 'note ribbon' on the waveform. DISPLAY
    ONLY — this never edits beats, assigns notes, or creates tracks; it just lets you SEE what note
    you hummed so you can build the tracks by hand. Runs pYIN on the HARMONIC layer (so ts/kick
    don't fake a pitch). Returns (t_frac, midi, voiced): arrays aligned in time, t_frac 0..1 over
    the take, midi the float MIDI note, voiced a bool mask of where a real pitch was found. Empty
    arrays if librosa is missing or the take is too short/silent."""
    empty = (np.zeros(0, np.float32), np.zeros(0, np.float32), np.zeros(0, bool))
    if not _HAS_LIBROSA or buf is None or len(buf) < 2048 or float(np.abs(buf).max()) < 1e-4:
        return empty
    h, _ = hpss(buf, sr)
    try:
        f0, voiced, vprob = librosa.pyin(h.astype(np.float32), fmin=65, fmax=1200, sr=sr,
                                         frame_length=2048, hop_length=hop)
    except Exception:
        return empty
    n = len(f0)
    if n == 0:
        return empty
    dur = len(buf) / float(sr)
    times = librosa.times_like(f0, sr=sr, hop_length=hop)
    tfrac = (times / dur).astype(np.float32) if dur > 0 else times.astype(np.float32)
    ok = np.isfinite(f0) & voiced & (vprob > 0.2)   # keep low-confidence frames so a held note doesn't gap
    midi = np.full(n, np.nan, np.float32)
    good = ok & (f0 > 0)
    midi[good] = (69.0 + 12.0 * np.log2(f0[good] / 440.0)).astype(np.float32)
    return tfrac, midi, ok.astype(bool)


def melody_line(harmonic, sr, bpm, start_beat=0.0, min_note_beats=0.2):
    """Track the CONTINUOUS pitch of the harmonic layer and merge contiguous same-pitch frames
    into HELD notes — so a tone you hold behind the percussion becomes one long note (or a few
    clean notes if you move the pitch), never one-note-per-drum-hit. Returns a list of hit dicts
    (beat/pitch/len in beats/amp/src_t/src_dur) ready for a melody lane, or [] if not pitched."""
    if not _HAS_LIBROSA or len(harmonic) < 4096:
        return []
    try:
        hop = 512
        f0, voiced, vprob = librosa.pyin(harmonic.astype(np.float32), fmin=65, fmax=1200,
                                         sr=sr, frame_length=2048, hop_length=hop)
    except Exception:
        return []
    times = librosa.times_like(f0, sr=sr, hop_length=hop)
    beat_len = 60.0 / max(1, bpm)
    # RMS envelope (same hop) so we can set velocity and drop near-silent frames
    rms = librosa.feature.rms(y=harmonic.astype(np.float32), frame_length=2048,
                              hop_length=hop)[0]
    rpeak = float(rms.max()) + 1e-9

    notes = []
    cur = None                 # {"midi", "t0", "t1", "amp"}
    gap_frames = 0
    MAX_GAP = 3                # allow a few unvoiced frames (a pop over the tone) without splitting
    for i, f in enumerate(f0):
        ok = np.isfinite(f) and voiced[i] and (rms[i] / rpeak) > 0.08
        midi = int(round(69 + 12 * np.log2(f / 440.0))) if ok else None
        if midi is not None:
            midi = max(24, min(96, midi))
        if cur is not None and midi is not None and midi == cur["midi"]:
            cur["t1"] = times[i]; cur["amp"] = max(cur["amp"], rms[i] / rpeak); gap_frames = 0
        elif cur is not None and midi is None and gap_frames < MAX_GAP:
            gap_frames += 1                    # brief dropout — keep the note held through it
        else:
            if cur is not None:
                notes.append(cur)
            cur = {"midi": midi, "t0": times[i], "t1": times[i],
                   "amp": float(rms[i] / rpeak)} if midi is not None else None
            gap_frames = 0
    if cur is not None:
        notes.append(cur)

    hits = []
    for nb in notes:
        if nb["midi"] is None:
            continue
        dur_s = max(0.0, nb["t1"] - nb["t0"]) + hop / sr
        if dur_s < min_note_beats * beat_len:
            continue                            # drop blips shorter than ~a 32nd note
        hits.append({"beat": start_beat + nb["t0"] / beat_len,
                     "amp": max(0.4, min(1.0, nb["amp"])),
                     "len": round((dur_s / beat_len) * 4) / 4,
                     "src_t": nb["t0"], "src_dur": min(4.0, dur_s),
                     "pitch": nb["midi"]})
    return hits


# ---------------- cluster ----------------
def cluster(embeddings, thresh=0.35):
    """Group hit embeddings so the same sound → one cluster. Returns an int label per hit."""
    n = len(embeddings)
    if n == 0:
        return []
    if n == 1:
        return [0]
    X = np.asarray(embeddings, np.float32)
    X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    if _HAS_SK:
        try:
            cl = AgglomerativeClustering(n_clusters=None, distance_threshold=thresh,
                                         metric="cosine", linkage="average")
            return list(cl.fit_predict(X))
        except Exception:
            pass
    # numpy fallback: greedy single-pass clustering by cosine distance
    labels = [-1] * n
    centroids = []
    for i in range(n):
        best, bd = -1, 9.9
        for c, cen in enumerate(centroids):
            d = 1.0 - float(np.dot(X[i], cen))
            if d < bd:
                bd, best = d, c
        if best >= 0 and bd <= thresh:
            labels[i] = best
            m = X[labels[i] == np.array(labels)].mean(axis=0)
            centroids[best] = m / (np.linalg.norm(m) + 1e-9)
        else:
            labels[i] = len(centroids)
            centroids.append(X[i])
    return labels
