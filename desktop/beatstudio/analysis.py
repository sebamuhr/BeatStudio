"""Onset detection — port of the web app's _onsetsFrom (energy envelope, peak pick,
sustain length, and merge of a re-triggered sustained sound into one long note)."""
from __future__ import annotations
import numpy as np


def gate_lin(gate: float) -> float:
    return (gate / 100.0) ** 2 * 0.5 + 0.002


def zcr(buf: np.ndarray, start: int, n: int) -> float:
    seg = buf[start:start + n]
    if len(seg) < 2:
        return 0.0
    return float(np.mean(np.abs(np.diff(np.sign(seg))) > 0))


def onset_start(buf: np.ndarray, a: int, b: int) -> int:
    seg = buf[a:b]
    if len(seg) == 0:
        return a
    th = float(np.abs(seg).max()) * 0.15
    idx = np.argmax(np.abs(seg) > th)
    return a + int(idx)


_N_MFCC = 13
# weights: 5 spectral shape + 6 bands + 13 MFCCs (MFCCs carry most of the timbre identity)
MATCH_WEIGHTS = np.array([1.0, 0.7, 0.9, 0.5, 0.9] + [1.1] * 6 + [1.6] * _N_MFCC)
MATCH_THRESH = 3.2          # in the MFCC-augmented space


def _mel_filterbank(sr, n_fft, n_mels=26, fmax=None):
    fmax = fmax or sr / 2
    def hz2mel(f): return 2595 * np.log10(1 + f / 700)
    def mel2hz(m): return 700 * (10 ** (m / 2595) - 1)
    mels = np.linspace(hz2mel(0), hz2mel(fmax), n_mels + 2)
    hz = mel2hz(mels)
    bins = np.floor((n_fft + 1) * hz / sr).astype(int)
    fb = np.zeros((n_mels, n_fft // 2))
    for m in range(1, n_mels + 1):
        l, c, r = bins[m - 1], bins[m], bins[m + 1]
        for k in range(l, c):
            if 0 <= k < fb.shape[1] and c > l:
                fb[m - 1, k] = (k - l) / (c - l)
        for k in range(c, r):
            if 0 <= k < fb.shape[1] and r > c:
                fb[m - 1, k] = (r - k) / (r - c)
    return fb


_MFB_CACHE = {}


def _mfcc(mag, sr, n_fft):
    key = (sr, n_fft)
    fb = _MFB_CACHE.get(key)
    if fb is None:
        fb = _MFB_CACHE[key] = _mel_filterbank(sr, n_fft)
    melE = np.log(fb @ (mag ** 2) + 1e-9)
    # DCT-II
    n = len(melE)
    k = np.arange(_N_MFCC)[:, None]
    basis = np.cos(np.pi * k * (2 * np.arange(n)[None, :] + 1) / (2 * n))
    return (basis @ melE) / n


def seg_features(buf: np.ndarray, start: int, sr: int, N: int = 2048) -> np.ndarray:
    """Timbre descriptor: 5 spectral-shape + 6 bands + 13 MFCCs, averaged over a few frames
    from the attack so short beatbox hits are described robustly (MFCCs do the heavy lifting)."""
    hop = N // 2
    frames = []
    for f in range(3):                     # attack + short decay
        st = start + f * hop
        seg = buf[st:st + N]
        if len(seg) < 8:
            break
        if len(seg) < N:
            seg = np.pad(seg, (0, N - len(seg)))
        frames.append(seg * np.hanning(N))
    if not frames:
        return np.zeros(11 + _N_MFCC)
    mags = [np.abs(np.fft.rfft(fr))[: N // 2] for fr in frames]
    mag = np.mean(mags, axis=0)
    M = len(mag)
    s = float(mag.sum()) or 1e-9
    idx = np.arange(M)
    centroid = float((mag * idx).sum()) / s / M
    spread = float(np.sqrt((mag * (idx / M - centroid) ** 2).sum() / s))
    roll = int(np.searchsorted(np.cumsum(mag), s * 0.85)) / M
    flat = float(np.exp(np.log(mag + 1e-9).mean()) / (mag.mean() + 1e-9))
    zc = zcr(buf, start, N)
    bi = np.minimum(5, (np.sqrt(idx / M) * 6).astype(int))
    bands = np.array([mag[bi == b].sum() for b in range(6)], dtype=np.float64)
    bands /= (bands.sum() or 1e-9)
    mfcc = np.mean([_mfcc(m, sr, N) for m in mags], axis=0)
    return np.concatenate([[centroid, spread, roll, flat, zc], bands, mfcc])


def match_dist(a: np.ndarray, b: np.ndarray) -> float:
    d = (a - b) * MATCH_WEIGHTS
    return float(np.sqrt((d * d).sum()))


def onsets_from(buf: np.ndarray, sr: int, gl: float):
    """Attack-based onset detection via spectral flux — one onset per hit (pf, ts, …), with a
    short percussive length by default and a longer length only for genuinely sustained sounds.
    Returns [{t, dur, amp, bright}] (seconds / seconds / 0..1 / 0..1)."""
    hop = 256
    win = 1024
    n = len(buf)
    if n < win:
        return []
    window = np.hanning(win).astype(np.float32)
    nf = 1 + (n - win) // hop
    mags = np.empty((nf, win // 2 + 1), np.float32)
    rms = np.empty(nf, np.float32)
    for i in range(nf):
        seg = buf[i * hop:i * hop + win] * window
        mags[i] = np.abs(np.fft.rfft(seg))
        rms[i] = np.sqrt(np.mean(seg * seg)) + 1e-9

    # spectral flux = sum of positive spectral change → responds to attacks
    diff = np.diff(mags, axis=0)
    flux = np.concatenate([[0.0], np.maximum(diff, 0).sum(axis=1)])
    fmax = float(flux.max()) or 1.0
    flux = flux / fmax

    # adaptive threshold: local mean over ~0.14s + floor
    w = max(3, int(0.14 * sr / hop))
    kernel = np.ones(w) / w
    local = np.convolve(flux, kernel, mode="same")
    thr = local * 1.4 + 0.05

    refr = max(2, int(0.045 * sr / hop))     # 45ms refractory between hits
    rmax = float(rms.max()) or 1e-6
    onsets = []
    last = -10 ** 9
    for i in range(1, nf - 1):
        if (flux[i] > thr[i] and flux[i] >= flux[i - 1] and flux[i] > flux[i + 1]
                and (i - last) >= refr and rms[i] > gl):
            t = i * hop / sr
            # local peak amplitude in the ~40ms after the attack
            pk = float(rms[i:min(nf, i + int(0.04 * sr / hop) + 1)].max())
            onsets.append({"t": t, "f": i, "amp": min(1.0, 0.35 + pk / rmax * 0.65),
                           "bright": zcr(buf, i * hop, win)})
            last = i

    # length per hit: short by default; extend only while energy stays up (sustained tsss),
    # hard-capped so a hit can never bleed into a whole-bar note.
    MAX_SEC = 0.7
    for k, o in enumerate(onsets):
        sf = o["f"]
        pk = float(rms[sf:min(nf, sf + refr)].max())
        floor = max(gl * 1.5, pk * 0.4)      # note ends when it decays under 40% of its peak
        end_f = sf + 1
        f = sf + 1
        while f < nf and rms[f] > floor:
            end_f = f
            f += 1
        gap_cap = onsets[k + 1]["f"] - 1 if k < len(onsets) - 1 else nf
        end_f = min(end_f, gap_cap, sf + int(MAX_SEC * sr / hop))
        o["dur"] = max(0.05, (end_f - sf) * hop / sr)
    return onsets
