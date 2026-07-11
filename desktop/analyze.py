#!/usr/bin/env python3
"""Analyze a real beatbox recording through the actual Beat Studio pipeline and print what it
detects — tempo, hits, clusters, instruments, pitches — plus save a spectrogram PNG so we can
debug/tune on YOUR sound instead of synthetic tests.

Usage:  ./.venv/bin/python analyze.py samples/mybeat.wav
"""
import sys
import numpy as np
import soundfile as sf
import librosa

from beatstudio import ai_match
from beatstudio.synth import SR
from beatstudio.groove import onsets_from, gate_lin, detect_tempo, quantize
from beatstudio.extract import smart_extract


def _read_audio(path):
    """Read in blocks so files with a missing/streamed length header still load."""
    with sf.SoundFile(path) as f:
        sr = f.samplerate
        blocks = []
        while True:
            b = f.read(1 << 20, dtype="float32")
            if len(b) == 0:
                break
            blocks.append(b)
    y = np.concatenate(blocks) if blocks else np.zeros(1, np.float32)
    return y, sr


def main(path):
    y, sr = _read_audio(path)
    if y.ndim > 1:
        y = y.mean(axis=1)
    if sr != SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=SR)
        sr = SR
    print(f"file: {path}")
    print(f"length: {len(y)/sr:.2f}s  sr: {sr}  peak: {np.abs(y).max():.3f}")

    ons = onsets_from(y, sr, gate_lin(10))
    print(f"\nonsets detected: {len(ons)}")
    for o in ons[:40]:
        print(f"  t={o['t']:.3f}s  dur={o['dur']:.3f}s  amp={o['amp']:.2f}")

    times = [o["t"] for o in ons]
    bpm = detect_tempo(y, sr, times)
    print(f"\ndetected tempo: {bpm} BPM")

    print("\nloading CLAP…")
    ai_match.load()
    bpm2, lanes, events = smart_extract(y, sr, 0.0, None)
    print(f"\n=== INTERPRETATION ({bpm2} BPM, {len(lanes)} tracks, {len(events)} notes) ===")
    for l in lanes:
        ev = [e for e in events if e.lane_id == l.id]
        beats = ", ".join(f"{e.beat:.2f}" for e in ev[:16])
        pit = sorted({e.pitch for e in ev if e.pitch is not None})
        tag = "PLAYS-YOUR-AUDIO" if l.play_original else l.kind
        print(f"  ● {l.name:10s} [{tag}] {len(ev)} hits  pitches={pit}")
        print(f"      beats: {beats}")

    # spectrogram image for a visual
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        S = librosa.amplitude_to_db(np.abs(librosa.stft(y, n_fft=1024, hop_length=256)), ref=np.max)
        plt.figure(figsize=(12, 4))
        librosa.display.specshow(S, sr=sr, hop_length=256, x_axis="time", y_axis="log")
        for o in ons:
            plt.axvline(o["t"], color="cyan", alpha=0.4, lw=0.8)
        plt.title(f"{path}  ·  {bpm2} BPM  ·  {len(ons)} onsets")
        out = path.rsplit(".", 1)[0] + "_spectrogram.png"
        plt.tight_layout(); plt.savefig(out, dpi=90)
        print(f"\nspectrogram saved: {out}")
    except Exception as e:
        print(f"(spectrogram skipped: {e})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: analyze.py <audiofile>")
        sys.exit(1)
    main(sys.argv[1])
