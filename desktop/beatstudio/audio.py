"""Audio output engine: streams a pre-rendered buffer via sounddevice, with loop and
a live play cursor (so the playhead stays tight to the audio). Degrades gracefully to a
silent 'virtual' clock if PortAudio/sounddevice isn't available yet."""
from __future__ import annotations
import time
import numpy as np
from .synth import SR

try:
    import sounddevice as sd
    _SD_ERR = None
except Exception as e:            # missing libportaudio2, etc.
    sd = None
    _SD_ERR = str(e)


class AudioEngine:
    def __init__(self):
        self.available = sd is not None
        self.err = _SD_ERR
        self._buf = np.zeros(1, np.float32)
        self._stream = None
        self._cursor = 0
        self._loop = False
        self._loop_a = 0
        self._loop_b = 0
        self._playing = False
        self._virt_start = 0.0        # wall-clock fallback when no audio device
        self._virt_from = 0

    # ---- buffer ----
    def set_buffer(self, buf: np.ndarray):
        self._buf = np.ascontiguousarray(buf, dtype=np.float32)

    # ---- transport ----
    def play(self, start_frame=0, loop=False, loop_a=0, loop_b=0):
        self.stop()
        self._cursor = int(start_frame)
        self._loop = bool(loop) and loop_b > loop_a
        self._loop_a, self._loop_b = int(loop_a), int(loop_b)
        self._playing = True
        self._virt_start = time.monotonic()
        self._virt_from = self._cursor
        if not self.available:
            return
        self._stream = sd.OutputStream(samplerate=SR, channels=1, dtype="float32",
                                       blocksize=512, callback=self._cb)
        self._stream.start()

    def _cb(self, outdata, frames, time_info, status):
        buf = self._buf
        out = outdata[:, 0]
        c = self._cursor
        i = 0
        while i < frames:
            end = self._loop_b if self._loop else len(buf)
            take = min(frames - i, end - c)
            if take <= 0:
                if self._loop:
                    c = self._loop_a
                    continue
                out[i:] = 0.0
                self._playing = False
                self._cursor = len(buf)
                raise sd.CallbackStop()
            out[i:i + take] = buf[c:c + take]
            c += take
            i += take
        self._cursor = c

    def one_shot(self, buf: np.ndarray):
        """Fire-and-forget preview (Test button); independent of the main stream."""
        if self.available:
            try:
                sd.play(np.ascontiguousarray(buf, dtype="float32"), SR)
            except Exception:
                pass

    def stop_one_shot(self):
        """Stop a fire-and-forget preview started with one_shot()."""
        if self.available:
            try:
                sd.stop()
            except Exception:
                pass

    def stop(self):
        self._playing = False
        if self._stream is not None:
            try:
                self._stream.stop(); self._stream.close()
            except Exception:
                pass
            self._stream = None

    # ---- state ----
    @property
    def playing(self):
        return self._playing

    def position_frames(self):
        if self.available:
            return self._cursor
        # virtual clock
        if not self._playing:
            return self._cursor
        elapsed = time.monotonic() - self._virt_start
        pos = self._virt_from + int(elapsed * SR)
        if self._loop and pos >= self._loop_b:
            span = self._loop_b - self._loop_a
            pos = self._loop_a + ((pos - self._loop_a) % max(1, span))
        elif pos >= len(self._buf):
            self._playing = False
            pos = len(self._buf)
        self._cursor = pos
        return pos


class Looper:
    """A live multi-voice STEREO looper for the pad grid: several sample loops play together, each
    looping seamlessly. Each 'voice' is one grid column (a track). Per-voice **gain** (Volume) and
    **pan** (Balance) are applied LIVE in the callback, so those knobs respond instantly; the baked
    buffer carries the rest of the mix (EQ/reverb/…) and swaps at the loop boundary."""
    def __init__(self):
        self.available = sd is not None
        self._voices = {}          # id -> {buf, pos, next, gain, pan}
        self._stream = None

    def _ensure_stream(self):
        if not self.available or self._stream is not None:
            return
        try:
            self._stream = sd.OutputStream(samplerate=SR, channels=2, dtype="float32",
                                           blocksize=512, callback=self._cb)
            self._stream.start()
        except Exception:
            self._stream = None

    def _cb(self, outdata, frames, time_info, status):
        left = outdata[:, 0]; right = outdata[:, 1]; left[:] = 0.0; right[:] = 0.0
        for v in list(self._voices.values()):
            buf = v["buf"]; n = len(buf)
            if n < 1:
                continue
            g = v.get("gain", 1.0); pan = v.get("pan", 0.0)
            lg = g * min(1.0, 1.0 - pan); rg = g * min(1.0, 1.0 + pan)   # -1 = left, +1 = right
            pos = v["pos"]; i = 0
            while i < frames:
                take = min(frames - i, n - pos)
                seg = buf[pos:pos + take]
                left[i:i + take] += seg * lg; right[i:i + take] += seg * rg
                pos += take; i += take
                if pos >= n:                      # loop boundary — swap a pending buffer HERE, so any
                    nxt = v.get("next")           # variation/mix change lands on the beat, never off
                    if nxt is not None:
                        v["buf"] = nxt; v["next"] = None; buf = nxt; n = len(buf)
                    pos = 0
            v["pos"] = pos
        np.tanh(left, out=left); np.tanh(right, out=right)              # soft-clip each channel

    def set_voice(self, vid, buf, quantized=False, gain=1.0, pan=0.0):
        """Start/replace a looping voice. quantized=True swaps the BUFFER at the next loop boundary
        (stays on beat); gain/pan are applied live and update immediately either way."""
        if buf is None or not len(buf):
            self.stop_voice(vid); return
        buf = np.ascontiguousarray(buf, np.float32)
        if quantized and vid in self._voices:
            self._voices[vid]["next"] = buf       # swap at the end of the current loop
            self._voices[vid]["gain"] = float(gain); self._voices[vid]["pan"] = float(pan)
        else:
            self._voices[vid] = {"buf": buf, "pos": 0, "next": None,
                                 "gain": float(gain), "pan": float(pan)}
        self._ensure_stream()

    def set_gain(self, vid, gain):
        """Volume knob → instant per-voice gain (no re-render)."""
        if vid in self._voices:
            self._voices[vid]["gain"] = float(gain)

    def set_pan(self, vid, pan):
        """Balance knob → instant per-voice pan (−1 left … +1 right)."""
        if vid in self._voices:
            self._voices[vid]["pan"] = max(-1.0, min(1.0, float(pan)))

    def stop_voice(self, vid):
        self._voices.pop(vid, None)
        if not self._voices:
            self.stop_all()

    def is_on(self, vid):
        return vid in self._voices

    def active(self):
        return set(self._voices.keys())

    def stop_all(self):
        self._voices.clear()
        if self._stream is not None:
            try:
                self._stream.stop(); self._stream.close()
            except Exception:
                pass
            self._stream = None
