"""Mic capture via sounddevice InputStream, with a running level for live feedback."""
from __future__ import annotations
import numpy as np
from .synth import SR

try:
    import sounddevice as sd
except Exception:
    sd = None


class Recorder:
    def __init__(self):
        self.available = sd is not None
        self.recording = False
        self.level = 0.0
        self.frames = 0
        self.live_onsets = []          # onset times (s) detected in real time
        self.live_env = []             # per-block RMS, for the live waveform display
        self.peak = 0.0                # running peak (for the level meter / clip warning)
        self._noise = 1e-4
        self._armed = True
        self._chunks = []
        self._stream = None

    def start(self) -> bool:
        if not self.available or self.recording:
            return False
        self._chunks = []
        self.level = 0.0
        self.frames = 0
        self.live_onsets = []
        self.live_env = []
        self.peak = 0.0
        self._noise = 1e-4
        self._armed = True
        try:
            self._stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                                          blocksize=1024, callback=self._cb)
            self._stream.start()
        except Exception:
            self._stream = None
            return False
        self.recording = True
        return True

    def _cb(self, indata, frames, time_info, status):
        x = indata[:, 0].copy()
        self._chunks.append(x)
        self.frames += len(x)
        rms = float(np.sqrt(np.mean(x ** 2)))
        self.level = rms
        self.live_env.append(rms)
        self.peak = max(self.peak * 0.999, float(np.abs(x).max()))
        # cheap real-time onset detection for live markers
        self._noise = self._noise * 0.995 + rms * 0.005
        trig = max(0.02, self._noise * 2.5)
        if self._armed and rms > trig:
            self._armed = False
            self.live_onsets.append(self.frames / SR)
        elif rms < trig * 0.6:
            self._armed = True

    def stop(self) -> np.ndarray:
        self.recording = False
        if self._stream is not None:
            try:
                self._stream.stop(); self._stream.close()
            except Exception:
                pass
            self._stream = None
        if not self._chunks:
            return np.zeros(1, np.float32)
        return np.concatenate(self._chunks).astype(np.float32)
