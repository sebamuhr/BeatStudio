"""Voice synthesis in numpy — ports the web app's drum/synth/sampler voices.

Every generator returns a mono float32 numpy array at sample-rate SR. These are summed
into the render buffer by render.py.
"""
from __future__ import annotations
import numpy as np
from scipy import signal

SR = 44100

DRUMS = ["kick", "snare", "hat", "openhat", "clap", "tomL", "tomM", "tomH",
         "rim", "cowbell", "808", "shaker", "congaH", "congaL", "cymbal"]
WAVES = ["sine", "saw", "square", "triangle", "pad", "pluck", "bass", "lead", "bell", "organ"]

# Per-sound synth knobs (the Separation Board draws one slider per row for Base AND Modulator).
# (key, label, min, max, default, scale)  →  real value = slider / scale.  The defaults are the
# IDENTITY set, so a synth with no knobs touched sounds exactly like the bare preset.
SYNTH_KNOBS = [
    ("octave",  "Octave",  -2,   2, 0,     1.0),
    ("cutoff",  "Cutoff",   0, 100, 100, 100.0),   # 0 = dark, 1 = open (log 180 Hz → 14 kHz)
    ("reso",    "Reso",     0, 100, 0,   100.0),   # filter resonance / Q
    ("attack",  "Attack",   0, 100, 0,   100.0),   # extra fade-in (→ 0..0.4 s)
    ("release", "Release",  0, 100, 0,   100.0),   # extra fade-out (→ 0..0.8 s)
    ("drive",   "Drive",    0, 100, 0,   100.0),   # waveshaping grit
    ("level",   "Level",    0, 150, 100, 100.0),   # gain (1.0 = unchanged)
]


def default_params() -> dict:
    """The identity knob set (Cutoff open, everything else neutral, Level 1.0)."""
    out = {}
    for key, _, _, _, dflt, sc in SYNTH_KNOBS:
        out[key] = int(dflt) if key == "octave" else dflt / sc
    return out


def _t(n):
    return np.arange(n) / SR


def _env_exp(n, decay):
    """Exponential decay from 1 to ~0 over `decay` seconds."""
    return np.exp(-_t(n) / max(1e-4, decay / 4.0)).astype(np.float32)


def _noise(n):
    return (np.random.random(n).astype(np.float32) * 2 - 1)


def _hp(x, fc):
    b, a = signal.butter(2, min(0.99, fc / (SR / 2)), btype="high")
    return signal.lfilter(b, a, x).astype(np.float32)


def _lp(x, fc):
    b, a = signal.butter(2, min(0.99, fc / (SR / 2)), btype="low")
    return signal.lfilter(b, a, x).astype(np.float32)


def _bp(x, fc, q=4.0):
    bw = fc / q
    lo = max(20.0, fc - bw / 2) / (SR / 2)
    hi = min(0.99, (fc + bw / 2) / (SR / 2))
    b, a = signal.butter(2, [lo, hi], btype="band")
    return signal.lfilter(b, a, x).astype(np.float32)


def _sine_sweep(f0, f1, n, k=0.12):
    """Sine whose frequency glides f0->f1 (exp) over ~k seconds."""
    t = _t(n)
    f = f1 + (f0 - f1) * np.exp(-t / max(1e-4, k / 4))
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph).astype(np.float32)


# ---------------- drums ----------------
def drum(inst: str, vel: float = 1.0) -> np.ndarray:
    v = float(vel)
    if inst == "kick":
        n = int(SR * 0.26); return _sine_sweep(165, 45, n, 0.12) * _env_exp(n, 0.22) * v
    if inst == "808":
        n = int(SR * 0.62); return _sine_sweep(120, 38, n, 0.18) * _env_exp(n, 0.6) * v
    if inst == "snare":
        n = int(SR * 0.16)
        body = np.sin(2 * np.pi * 185 * _t(n)) * _env_exp(n, 0.1) * 0.5
        nz = _hp(_noise(n), 1300) * _env_exp(n, 0.14) * 0.8
        return ((body + nz) * v).astype(np.float32)
    if inst in ("hat", "openhat"):
        dec = 0.32 if inst == "openhat" else 0.05
        n = int(SR * (dec + 0.02))
        return (_hp(_noise(n), 6500) * _env_exp(n, dec) * (0.4 if inst == "openhat" else 0.5) * v).astype(np.float32)
    if inst == "clap":
        n = int(SR * 0.12); out = np.zeros(n, np.float32)
        for i in range(3):
            off = int(SR * 0.012 * i)
            seg = _bp(_noise(n - off), 1500) * _env_exp(n - off, 0.07) * 0.55
            out[off:] += seg
        return out * v
    if inst in ("tomL", "tomM", "tomH"):
        f = {"tomL": 150, "tomM": 210, "tomH": 285}[inst]
        n = int(SR * 0.24); return _sine_sweep(f, f * 0.5, n, 0.18) * _env_exp(n, 0.22) * 0.9 * v
    if inst in ("congaH", "congaL"):
        f = 330 if inst == "congaH" else 220
        n = int(SR * 0.2); return _sine_sweep(f, f * 0.85, n, 0.12) * _env_exp(n, 0.18) * 0.8 * v
    if inst == "rim":
        n = int(SR * 0.05); return (signal.square(2 * np.pi * 1700 * _t(n)).astype(np.float32) * _env_exp(n, 0.04) * 0.4 * v)
    if inst == "cowbell":
        n = int(SR * 0.26); s = (signal.square(2 * np.pi * 540 * _t(n)) + signal.square(2 * np.pi * 800 * _t(n)))
        return (s.astype(np.float32) * _env_exp(n, 0.25) * 0.25 * v)
    if inst == "shaker":
        n = int(SR * 0.1); return (_hp(_noise(n), 5000) * _env_exp(n, 0.09) * 0.32 * v).astype(np.float32)
    if inst == "cymbal":
        n = int(SR * 0.62); return (_hp(_noise(n), 8000) * _env_exp(n, 0.6) * 0.3 * v).astype(np.float32)
    # default -> kick
    n = int(SR * 0.26); return _sine_sweep(165, 45, n) * _env_exp(n, 0.22) * v


# ---------------- synths ----------------
def _osc(kind, freq, n):
    t = _t(n); ph = 2 * np.pi * freq * t
    if kind == "sine": return np.sin(ph).astype(np.float32)
    if kind == "square": return signal.square(ph).astype(np.float32)
    if kind == "saw" or kind == "sawtooth": return signal.sawtooth(ph).astype(np.float32)
    if kind == "triangle": return signal.sawtooth(ph, 0.5).astype(np.float32)
    return np.sin(ph).astype(np.float32)


def _adsr(n, atk, rel):
    e = np.ones(n, np.float32)
    a = max(1, int(atk * SR)); r = max(1, int(rel * SR))
    e[:a] = np.linspace(0, 1, a, dtype=np.float32)
    if r < n:
        e[n - r:] = np.linspace(1, 0, r, dtype=np.float32)
    return e


def synth(preset: str, freq: float, dur: float, vel: float = 0.8) -> np.ndarray:
    v = max(0.2, min(1.0, vel))
    n = int(SR * (dur + 0.25))
    if preset == "pad":
        s = _osc("saw", freq, n) + _osc("saw", freq * 1.005, n) + _osc("sine", freq / 2, n)
        s = _lp(s / 3, 900 + 2000 * v)
        return (s * _adsr(n, min(0.25, dur * 0.4), min(0.5, dur * 0.6 + 0.1)) * 0.3 * v).astype(np.float32)
    if preset == "pluck":
        s = _osc("triangle", freq, n) + _osc("saw", freq, n) * 0.6
        return (_lp(s, 2500) * np.exp(-_t(n) / max(1e-3, (dur + 0.12) / 4)) * 0.5 * v).astype(np.float32)
    if preset == "bass":
        s = _osc("square", freq, n) + _osc("sine", freq / 2, n)
        return (_lp(s / 2, 600 + 900 * v) * _adsr(n, 0.01, min(0.12, dur * 0.4)) * 0.5 * v).astype(np.float32)
    if preset == "lead":
        s = _osc("saw", freq, n) + _osc("square", freq * 1.003, n)
        return (_lp(s / 2, 2200 + 2600 * v) * _adsr(n, 0.015, min(0.15, dur * 0.4)) * 0.34 * v).astype(np.float32)
    if preset == "bell":
        s = (_osc("sine", freq, n) * 0.5 + _osc("sine", freq * 2.76, n) * 0.3 + _osc("sine", freq * 5.4, n) * 0.16)
        return (s * np.exp(-_t(n) / max(1e-3, max(0.45, dur + 0.35) / 4)) * 0.5 * v).astype(np.float32)
    if preset == "organ":
        s = sum(_osc("sine", freq * h, n) * g for h, g in zip((1, 2, 3, 4), (0.5, 0.25, 0.15, 0.1)))
        return (s * _adsr(n, 0.02, min(0.12, dur * 0.3)) * 0.32 * v).astype(np.float32)
    # plain waveforms
    s = _osc(preset, freq, n)
    return (s * _adsr(n, 0.012, min(0.1, dur * 0.4)) * 0.42 * v).astype(np.float32)


def _rlp(x, fc, q):
    """Resonant low-pass (RBJ biquad) — Cutoff + Reso knobs."""
    w0 = 2 * np.pi * max(30.0, min(SR * 0.45, fc)) / SR
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / (2 * max(0.3, q))
    b0 = (1 - cw) / 2; b1 = 1 - cw; b2 = (1 - cw) / 2
    a0 = 1 + alpha; a1 = -2 * cw; a2 = 1 - alpha
    return signal.lfilter([b0 / a0, b1 / a0, b2 / a0], [1, a1 / a0, a2 / a0], x).astype(np.float32)


def _shape(x, p, dur):
    """Apply the per-sound knobs (drive / filter / attack / release / level) to a voice."""
    lvl = float(p.get("level", 1.0))
    if lvl != 1.0:
        x = x * lvl
    drive = float(p.get("drive", 0.0))
    if drive > 1e-3:
        x = np.tanh(x * (1.0 + 6.0 * drive)).astype(np.float32)
    cutoff = float(p.get("cutoff", 1.0)); reso = float(p.get("reso", 0.0))
    if cutoff < 0.995 or reso > 1e-3:
        fc = 180.0 * (14000.0 / 180.0) ** max(0.0, min(1.0, cutoff))
        x = _rlp(x, fc, 0.707 + 7.0 * max(0.0, min(1.0, reso)))
    atk = float(p.get("attack", 0.0)); rel = float(p.get("release", 0.0))
    if atk > 1e-3 or rel > 1e-3:
        n = len(x); env = np.ones(n, np.float32)
        a = int(atk * 0.4 * SR); r = int(rel * 0.8 * SR)
        if a > 1:
            env[:min(a, n)] = np.linspace(0, 1, min(a, n), dtype=np.float32)
        if 1 < r < n:
            env[n - r:] = np.linspace(1, 0, r, dtype=np.float32)
        x = x * env
    return x.astype(np.float32)


def voice(preset: str, freq: float, dur: float, vel: float = 0.8, params=None) -> np.ndarray:
    """A synth voice with its per-sound knobs applied. `params=None`/empty → identical to synth()."""
    if not params:
        return synth(preset, freq, dur, vel)
    octv = int(params.get("octave", 0))
    return _shape(synth(preset, freq * (2.0 ** octv), dur, vel), params, dur)


def morph_synth(preset_a: str, preset_b: str, freq: float, dur: float, vel: float = 0.8,
                m0: float = 0.0, m1: float | None = None) -> np.ndarray:
    """MORPH one synth into another — not two notes layered, but a single voice whose WAVESHAPE
    is interpolated between A and B (wavetable-style). `m` glides from m0 (start) to m1 (end):
    m=0 → all A, m=1 → all B, 0.5 → a new hybrid timbre. Drawing a rising line makes the note
    evolve A→B across its length."""
    if m1 is None:
        m1 = m0
    xa = synth(preset_a, freq, dur, vel)
    xb = synth(preset_b or preset_a, freq, dur, vel)
    n = min(len(xa), len(xb))
    m = np.clip(np.linspace(m0, m1, n), 0.0, 1.0).astype(np.float32)
    return ((1.0 - m) * xa[:n] + m * xb[:n]).astype(np.float32)


def morph_env(base: str, mod: str, freq: float, dur: float, env, vel: float = 0.95,
              base_params=None, mod_params=None) -> np.ndarray:
    """A synth voice that FOLLOWS the drawn line sample-by-sample: `env` (0..1) is both the
    AMPLITUDE (volume) and the MORPH amount — env=0 → silent/base, env=1 → full/modulator. So the
    sound swells and fades and morphs base→mod exactly as the line moves. Base and Modulator each
    carry their OWN knobs (base_params / mod_params)."""
    xa = voice(base or "sine", freq, dur, vel, base_params)
    xb = voice(mod, freq, dur, vel, mod_params) if mod else xa
    n = min(len(xa), len(xb))
    if n < 2:
        return np.zeros(1, np.float32)
    e = np.asarray(env, np.float32).ravel()
    if e.size < 2:
        e = np.full(n, float(e[0]) if e.size else 0.0, np.float32)
    else:
        e = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, e.size), e).astype(np.float32)
    e = np.clip(e, 0.0, 1.0)
    out = (1.0 - e) * xa[:n] + e * xb[:n]      # morph base→modulator by height
    return (out * e).astype(np.float32)         # and the amplitude follows height too


# a sustainable oscillator/noise identity for every sound, so ANY sound (even a kick) can be held
# and morphed as a continuous synth voice (the "kiiiiiick" the siren needs).
_GLIDE_WAVE = {"sine": "sine", "saw": "saw", "sawtooth": "saw", "square": "square", "triangle": "triangle",
               "pad": "saw", "pluck": "triangle", "bass": "square", "lead": "saw", "bell": "sine", "organ": "sine"}
_GLIDE_NOISE = {"snare": 1400, "clap": 1200, "hat": 6500, "openhat": 6000, "shaker": 5000, "cymbal": 8000, "rim": 1700}


def _wave_shape(shape, phase):
    if shape == "square":
        return signal.square(phase)
    if shape == "saw":
        return signal.sawtooth(phase)
    if shape == "triangle":
        return signal.sawtooth(phase, 0.5)
    return np.sin(phase)


def glide_voice(sound: str, freq: np.ndarray, params=None) -> np.ndarray:
    """A SUSTAINED voice for `sound` whose pitch follows the per-sample `freq` array — a tonal drum
    (kick/tom…) is held as its fundamental; a noisy drum (snare/hat…) is held as filtered noise;
    a synth wave is its oscillator. This is what lets a drum become a long morphing 'kiiiiick'."""
    freq = np.asarray(freq, np.float32); n = len(freq)
    if n < 2:
        return np.zeros(1, np.float32)
    if sound in _GLIDE_NOISE:
        x = _hp(_noise(n), _GLIDE_NOISE[sound] * 0.6) * 0.5
    else:
        phase = np.cumsum(2 * np.pi * np.maximum(20.0, freq) / SR).astype(np.float32)
        x = _wave_shape(_GLIDE_WAVE.get(sound, "sine"), phase).astype(np.float32) * 0.5
    if params:
        x = _shape(x, {**params, "octave": 0}, n / SR)   # octave already applied via the note range
    return x.astype(np.float32)


def morph_glide(base: str, mod: str, lo_note: float, hi_note: float, dur: float, morph,
                base_params=None, mod_params=None, vel: float = 0.9) -> np.ndarray:
    """The SIREN voice: one continuous, sustained tone that follows the drawn curve `morph` (0..1).
    morph=0 → Base sound at `lo_note`; morph=1 → Modulator sound at `hi_note`; in between it glides
    BOTH pitch and timbre. Volume is constant here (loudness lives on the Studio volume line)."""
    n = int(SR * max(0.05, dur))
    m = np.asarray(morph, np.float32).ravel()
    m = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(m)), m).astype(np.float32) if len(m) >= 2 \
        else np.full(n, float(m[0]) if len(m) else 0.0, np.float32)
    m = np.clip(m, 0.0, 1.0)
    note = lo_note + m * (hi_note - lo_note)                 # pitch glides low→high with the curve
    freq = 440.0 * (2.0 ** ((note - 69.0) / 12.0))
    xa = glide_voice(base or "sine", freq, base_params)
    xb = glide_voice(mod or base or "sine", freq, mod_params) if mod else xa
    k = min(len(xa), len(xb), n)
    out = (1.0 - m[:k]) * xa[:k] + m[:k] * xb[:k]            # timbre crossfades base→modulator
    env = np.ones(k, np.float32); r = min(k, int(0.006 * SR))
    if r > 1:
        env[:r] = np.linspace(0, 1, r); env[-r:] = np.linspace(1, 0, r)   # de-click edges
    return (out * env * max(0.2, min(1.2, vel))).astype(np.float32)


def drum_roll(inst: str, vel: float, dur: float, vel_end: float | None = None) -> np.ndarray:
    """Sustain a drum as a buzz-ROLL for `dur` seconds (re-triggering fast) so the intensity line
    can turn a 'ts' into a 'tsssss' — the jazz snare. Velocity glides vel→vel_end across the roll."""
    total = int(SR * max(0.02, dur))
    if total <= int(SR * 0.12):
        return drum(inst, vel)                     # short → a single hit
    if vel_end is None:
        vel_end = vel
    step = int(SR * 0.033)                          # ~30 re-triggers / second
    out = np.zeros(total + int(SR * 0.3), np.float32)
    i = 0
    while i < total:
        f = i / max(1, total)
        d = drum(inst, vel + (vel_end - vel) * f)
        out[i:i + len(d)] += d * 0.6
        i += step
    env = np.ones(len(out), np.float32)
    rel = min(len(out), int(0.05 * SR))
    env[-rel:] = np.linspace(1, 0, rel, dtype=np.float32)
    return (out * env)[:total + int(SR * 0.12)].astype(np.float32)


def midi_to_hz(m: float) -> float:
    return 440.0 * (2 ** ((m - 69) / 12.0))


def click(accent: bool = False) -> np.ndarray:
    n = int(SR * 0.045)
    f = 1600 if accent else 1000
    return (signal.square(2 * np.pi * f * _t(n)).astype(np.float32)
            * np.exp(-_t(n) / 0.006) * (0.3 if accent else 0.18))


# ---------------- HUM voices (formant / vowel synthesis) ----------------
# A hum = a glottal source (rich harmonics) shaped by 2-3 fixed FORMANT resonances (a vowel). The
# source pitch moves but the formants stay put, so it "sings" the vowel at any pitch — and being an
# oscillator it glides for free (needed by the NOTES-view pitch line). Sliders live in HUM_KNOBS.
HUM_SPECS = {
    "aah":     {"f": (730, 1090, 2440), "src": "saw",    "breath": 0.03, "label": "Aah"},
    "eee":     {"f": (270, 2290, 3010), "src": "saw",    "breath": 0.03, "label": "Eee"},
    "ooh":     {"f": (300, 870, 2240),  "src": "saw",    "breath": 0.02, "label": "Ooh"},
    "ohh":     {"f": (450, 800, 2830),  "src": "saw",    "breath": 0.02, "label": "Ohh"},
    "eh":      {"f": (530, 1840, 2480), "src": "saw",    "breath": 0.03, "label": "Eh"},
    "ih":      {"f": (390, 1990, 2550), "src": "saw",    "breath": 0.03, "label": "Ih"},
    "uh":      {"f": (640, 1190, 2390), "src": "saw",    "breath": 0.03, "label": "Uh"},
    "mmm":     {"f": (250, 1100, 2000), "src": "square", "breath": 0.0,  "label": "Mmm (hum)"},
    "nng":     {"f": (280, 1700, 2600), "src": "square", "breath": 0.0,  "label": "Nng"},
    "breathy": {"f": (320, 900, 2200),  "src": "saw",    "breath": 0.14, "label": "Breathy Ooo"},
    "choir":   {"f": (660, 1120, 2600), "src": "saw",    "breath": 0.05, "label": "Choir Aah", "detune": True},
    "falsetto":{"f": (400, 1700, 2800), "src": "sine",   "breath": 0.06, "label": "Falsetto"},
}
HUMS = list(HUM_SPECS.keys())

HUM_KNOBS = [
    ("bright",   "Bright",  0, 100, 50,  100.0),   # formant tilt / air
    ("breath",   "Breath",  0, 100, 25,  100.0),   # breath-noise mix
    ("vibrate",  "Vib",     0, 100, 30,  100.0),   # vibrato RATE
    ("vibdepth", "VibDep",  0, 100, 25,  100.0),   # vibrato DEPTH
    ("attack",   "Attack",  0, 100, 15,  100.0),
    ("release",  "Release", 0, 100, 20,  100.0),
    ("level",    "Level",   0, 150, 100, 100.0),
]


def default_hum_params() -> dict:
    return {k: (v / sc) for k, _, _, _, v, sc in HUM_KNOBS}


def _freq_array(freq, dur):
    """Normalise a scalar-freq(+dur) OR a per-sample freq array into a freq array (glide-ready)."""
    if np.isscalar(freq):
        n = int(SR * max(0.08, (dur if dur else 0.6)))
        return np.full(n, float(freq), np.float32)
    f = np.asarray(freq, np.float32).ravel()
    return np.maximum(30.0, f)


def hum_voice(preset: str, freq, dur: float = None, vel: float = 0.9, params=None) -> np.ndarray:
    """A sung vowel. `freq` may be a scalar (with `dur`) or a per-sample array (a glide)."""
    spec = HUM_SPECS.get(preset, HUM_SPECS["aah"])
    p = params or default_hum_params()
    f = _freq_array(freq, dur); n = len(f)
    if n < 2:
        return np.zeros(1, np.float32)
    t = _t(n)
    vib = 0.6 + 7.0 * float(p.get("vibrate", 0.3))        # 0.6..7.6 Hz
    depth = 0.03 * float(p.get("vibdepth", 0.25))          # up to ~3% pitch wobble
    fmod = f * (1.0 + depth * np.sin(2 * np.pi * vib * t).astype(np.float32))
    phase = np.cumsum(2 * np.pi * fmod / SR).astype(np.float32)
    src = _wave_shape("saw" if spec["src"] == "saw" else spec["src"], phase)
    if spec.get("detune"):                                 # choir = a couple of detuned voices
        src = 0.6 * src + 0.4 * _wave_shape("saw", phase * 1.006)
    out = np.zeros(n, np.float32)
    for i, fc in enumerate(spec["f"]):
        out += _bp(src, float(fc), q=9.0) * (0.9 ** i)
    breath = float(p.get("breath", 0.25)) * spec["breath"] * 4.0
    if breath > 1e-3:
        out += breath * _hp(_noise(n), 2500) * 0.4
    bright = float(p.get("bright", 0.5))                    # brighten = let more highs through
    out = _lp(out, 1500 + 6000 * bright)
    mx = float(np.abs(out).max()) + 1e-6
    out = out / mx
    atk = 0.005 + 0.35 * float(p.get("attack", 0.15)); rel = 0.02 + 0.5 * float(p.get("release", 0.2))
    out = out * _adsr(n, min(atk, n / SR * 0.5), min(rel, n / SR * 0.6))
    return (out * 0.5 * float(p.get("level", 1.0)) * max(0.2, min(1.2, vel))).astype(np.float32)


# ---------------- pitched INSTRUMENTS (categories) ----------------
# Each instrument is a family recipe (partials + envelope + brightness + vibrato) with a per-instrument
# octave shift. Additive/oscillator based, so everything pitches and GLIDES. Not studio-accurate, but
# distinct and tweakable — the point is a big, usable palette. Grouped into categories for the picker.
INST_CATEGORIES = [
    ("Mallets", ["marimba", "xylophone", "vibraphone", "glockenspiel", "kalimba", "musicbox"]),
    ("Keys",    ["piano", "epiano", "clav", "harpsichord"]),
    ("Strings", ["violin", "viola", "cello", "contrabass", "pizzicato", "harp"]),
    ("Winds",   ["flute", "clarinet", "oboe", "panflute", "recorder"]),
    ("Brass",   ["trumpet", "trombone", "frenchhorn", "tuba"]),
    ("Bass",    ["subbass", "fingerbass", "pickbass", "synthbass"]),
    ("Bells",   ["tubularbell", "chime", "celesta"]),
]
# name: (family, semitone_shift, brightness 0..1, vibrato 0..1)
INST_SPECS = {
    "marimba": ("mallet", 0, 0.6, 0.0),   "xylophone": ("mallet", 12, 0.85, 0.0),
    "vibraphone": ("mallet", 0, 0.5, 0.35), "glockenspiel": ("mallet", 24, 0.95, 0.0),
    "kalimba": ("mallet", 0, 0.55, 0.0),  "musicbox": ("mallet", 12, 0.75, 0.0),
    "piano": ("key", 0, 0.55, 0.0),       "epiano": ("key", 0, 0.4, 0.0),
    "clav": ("key", 0, 0.75, 0.0),        "harpsichord": ("key", 0, 0.8, 0.0),
    "violin": ("string", 12, 0.6, 0.5),   "viola": ("string", 5, 0.5, 0.5),
    "cello": ("string", -12, 0.4, 0.4),   "contrabass": ("string", -24, 0.3, 0.3),
    "pizzicato": ("pluckstring", 0, 0.5, 0.0), "harp": ("pluckstring", 0, 0.55, 0.0),
    "flute": ("wind", 12, 0.35, 0.25),    "clarinet": ("windodd", 0, 0.4, 0.2),
    "oboe": ("wind", 5, 0.65, 0.3),       "panflute": ("wind", 12, 0.3, 0.15),
    "recorder": ("wind", 12, 0.4, 0.1),
    "trumpet": ("brass", 5, 0.7, 0.25),   "trombone": ("brass", -7, 0.6, 0.2),
    "frenchhorn": ("brass", -2, 0.5, 0.2), "tuba": ("brass", -19, 0.4, 0.15),
    "subbass": ("sub", -12, 0.2, 0.0),    "fingerbass": ("pluckstring", -12, 0.35, 0.0),
    "pickbass": ("pluckstring", -12, 0.55, 0.0), "synthbass": ("sub", -12, 0.5, 0.0),
    "tubularbell": ("bell", 0, 0.6, 0.0), "chime": ("bell", 12, 0.7, 0.0),
    "celesta": ("bell", 12, 0.6, 0.0),
}
INSTS = list(INST_SPECS.keys())

# family → (partials as (ratio, gain), envelope kind)
_FAMILY_PARTIALS = {
    "mallet":      [(1, 1.0), (3.9, 0.5), (9.2, 0.15)],
    "key":         [(1, 1.0), (2, 0.5), (3, 0.3), (4, 0.16), (5, 0.08)],
    "string":      [(1, 1.0), (2, 0.6), (3, 0.45), (4, 0.3), (5, 0.2), (6, 0.12)],
    "pluckstring": [(1, 1.0), (2, 0.55), (3, 0.4), (4, 0.25), (5, 0.15)],
    "wind":        [(1, 1.0), (2, 0.5), (3, 0.22), (4, 0.1)],
    "windodd":     [(1, 1.0), (3, 0.6), (5, 0.35), (7, 0.18)],
    "brass":       [(1, 1.0), (2, 0.7), (3, 0.5), (4, 0.36), (5, 0.22), (6, 0.12)],
    "sub":         [(1, 1.0), (2, 0.3)],
    "bell":        [(1, 1.0), (2.76, 0.5), (5.4, 0.25), (8.9, 0.12)],
}
_SUSTAIN_FAMILIES = {"string", "wind", "windodd", "brass", "sub"}


def inst_voice(preset: str, freq, dur: float = None, vel: float = 0.85, params=None) -> np.ndarray:
    """A pitched instrument voice. `freq` may be scalar (+dur) or a per-sample array (a glide)."""
    fam, shift, bright, vib = INST_SPECS.get(preset, ("key", 0, 0.5, 0.0))
    f = _freq_array(freq, dur) * (2.0 ** (shift / 12.0)); n = len(f)
    if n < 2:
        return np.zeros(1, np.float32)
    t = _t(n)
    if vib > 1e-3:
        f = f * (1.0 + 0.02 * vib * np.sin(2 * np.pi * 5.5 * t).astype(np.float32))
    sustain = fam in _SUSTAIN_FAMILIES
    out = np.zeros(n, np.float32)
    for ratio, gain in _FAMILY_PARTIALS[fam]:
        ph = np.cumsum(2 * np.pi * f * ratio / SR).astype(np.float32)
        wav = signal.sawtooth(ph) if (fam == "brass" and ratio == 1) else np.sin(ph)
        out += gain * wav.astype(np.float32)
    if fam in ("wind", "windodd"):
        out += 0.06 * _hp(_noise(n), 3000)              # breath
    out = _lp(out, 500 + 8000 * bright)
    out /= (float(np.abs(out).max()) + 1e-6)
    if sustain:
        env = _adsr(n, min(0.06, n / SR * 0.4), min(0.12, n / SR * 0.4))
    else:                                                # struck/plucked: exponential decay
        dk = {"bell": 2.2, "mallet": 0.6, "key": 0.9, "pluckstring": 0.5}.get(fam, 0.8)
        env = np.exp(-t / max(1e-3, dk)).astype(np.float32)
    p = params or {}
    return (out * env * 0.5 * float(p.get("level", 1.0)) * max(0.2, min(1.2, vel))).astype(np.float32)


# ---------------- sampler ----------------
def sample_voice(buf: np.ndarray, base_pitch: int, pitch: int, dur: float,
                 vel: float = 0.85, loop: bool = True) -> np.ndarray:
    """Resample `buf` for pitch (playbackRate) and loop its body to fill `dur`."""
    rate = 2 ** ((pitch - base_pitch) / 12.0)
    if rate <= 0:
        rate = 1.0
    # resample by rate via linear interpolation
    idx = np.arange(0, len(buf), rate)
    res = np.interp(idx, np.arange(len(buf)), buf).astype(np.float32)
    natural = len(res) / SR
    want = int(SR * dur) if dur and dur > 0.02 else len(res)
    if want <= len(res) or not loop:
        out = res[:want] if want < len(res) else res
    else:
        atk = int(min(0.045, natural * 0.2) * SR)
        body = res[atk:max(atk + 1, int(len(res) * 0.92))]
        reps = int(np.ceil((want - atk) / max(1, len(body))))
        out = np.concatenate([res[:atk]] + [body] * reps)[:want]
    rel = min(len(out), int(0.02 * SR))
    if rel > 1:
        out = out.copy(); out[-rel:] *= np.linspace(1, 0, rel, dtype=np.float32)
    return (out * max(0.05, min(1.4, vel))).astype(np.float32)


# ---------------- 3-band EQ (RBJ biquads) ----------------
def _biquad(kind, f0, gain_db, q=0.9):
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * f0 / SR
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / (2 * q)
    if kind == "lowshelf":
        b0 = A * ((A + 1) - (A - 1) * cw + 2 * np.sqrt(A) * alpha)
        b1 = 2 * A * ((A - 1) - (A + 1) * cw)
        b2 = A * ((A + 1) - (A - 1) * cw - 2 * np.sqrt(A) * alpha)
        a0 = (A + 1) + (A - 1) * cw + 2 * np.sqrt(A) * alpha
        a1 = -2 * ((A - 1) + (A + 1) * cw)
        a2 = (A + 1) + (A - 1) * cw - 2 * np.sqrt(A) * alpha
    elif kind == "highshelf":
        b0 = A * ((A + 1) + (A - 1) * cw + 2 * np.sqrt(A) * alpha)
        b1 = -2 * A * ((A - 1) + (A + 1) * cw)
        b2 = A * ((A + 1) + (A - 1) * cw - 2 * np.sqrt(A) * alpha)
        a0 = (A + 1) - (A - 1) * cw + 2 * np.sqrt(A) * alpha
        a1 = 2 * ((A - 1) - (A + 1) * cw)
        a2 = (A + 1) - (A - 1) * cw - 2 * np.sqrt(A) * alpha
    else:  # peaking
        b0 = 1 + alpha * A; b1 = -2 * cw; b2 = 1 - alpha * A
        a0 = 1 + alpha / A; a1 = -2 * cw; a2 = 1 - alpha / A
    return np.array([b0, b1, b2]) / a0, np.array([1, a1 / a0, a2 / a0])


def apply_eq(x: np.ndarray, low_db=0, mid_db=0, high_db=0) -> np.ndarray:
    if not (low_db or mid_db or high_db):
        return x
    out = x
    if low_db:
        b, a = _biquad("lowshelf", 200, low_db); out = signal.lfilter(b, a, out)
    if mid_db:
        b, a = _biquad("peaking", 1200, mid_db); out = signal.lfilter(b, a, out)
    if high_db:
        b, a = _biquad("highshelf", 4200, high_db); out = signal.lfilter(b, a, out)
    return out.astype(np.float32)


# ----------------------------------------------------------------- the FX rack
# Transform a recorded sound ("Original") — one amount slider per effect, 0 = OFF.
# (key, label, min, max, default, scale) → amount = slider/scale in 0..1 (0 = bypass).
# Order matters: drive → bass → tone → crush → chorus → delay → reverb → compress.
FX_KNOBS = [
    ("drive",   "Drive",    0, 100, 0, 100.0),   # tanh waveshaper grit / distortion
    ("bass",    "Bass",     0, 100, 0, 100.0),   # massive sub: octave-down sine + low shelf
    ("lowpass", "Lowpass",  0, 100, 0, 100.0),   # close a resonant low-pass (tone / warmth)
    ("crush",   "Crush",    0, 100, 0, 100.0),   # bitcrush: bit + sample-rate decimation (lo-fi)
    ("chorus",  "Chorus",   0, 100, 0, 100.0),   # modulated short delay for width / thickness
    ("delay",   "Delay",    0, 100, 0, 100.0),   # feedback echo
    ("reverb",  "Reverb",   0, 100, 0, 100.0),   # small room/space (adds a tail)
    ("comp",    "Punch",    0, 100, 0, 100.0),   # compressor: even out + punch
]


def default_fx() -> dict:
    return {k: 0.0 for k, *_ in FX_KNOBS}


def fx_tail(fx) -> float:
    """Extra seconds a chain needs so delay/reverb tails aren't cut off."""
    if not fx:
        return 0.0
    return 0.5 * float(fx.get("reverb", 0)) + 0.6 * float(fx.get("delay", 0))


def _sub_octave(x):
    """A rough octave-down: flip polarity on every other zero-crossing of the low band → an
    octave-lower square-ish tone that follows the fundamental. Low-passed for weight."""
    low = _lp(x, 200)
    flip = np.ones(len(low), np.float32)
    s = 1.0
    zc = np.where(np.diff(np.signbit(low)))[0]
    last = 0
    for j, idx in enumerate(zc):
        flip[last:idx + 1] = s
        if j % 2 == 1:
            s = -s
        last = idx + 1
    flip[last:] = s
    return (np.abs(low) * flip).astype(np.float32)


def _chorus(x, amt):
    n = len(x); t = np.arange(n)
    base = 0.011 * SR                     # ~11 ms
    depth = 0.004 * SR * amt
    lfo = base + depth * np.sin(2 * np.pi * 0.8 * t / SR)
    idx = np.clip(t - lfo, 0, n - 1)     # clamp BEFORE splitting so frac stays in 0..1
    i0 = idx.astype(int)
    frac = idx - i0
    i1 = np.clip(i0 + 1, 0, n - 1)
    wet = x[i0] * (1 - frac) + x[i1] * frac
    return (x * (1 - 0.5 * amt) + wet * 0.5 * amt * 1.1).astype(np.float32)


def _delay(x, amt, time_s=0.28):
    d = int(time_s * SR)
    fb = 0.55 * amt
    out = x.astype(np.float32).copy()
    tap = out.copy()
    for _ in range(6):                    # a few feedback repeats
        tap = np.concatenate([np.zeros(d, np.float32), tap[:-d] if len(tap) > d else np.zeros(0, np.float32)])
        if len(tap) < len(out):
            tap = np.concatenate([tap, np.zeros(len(out) - len(tap), np.float32)])
        tap = tap[:len(out)] * fb
        if np.max(np.abs(tap)) < 1e-4:
            break
        out += tap * amt
    return out.astype(np.float32)


def _reverb(x, amt):
    """Freeverb-lite: parallel comb filters + series all-passes."""
    combs = [(0.0297, 0.805), (0.0371, 0.827), (0.0411, 0.783), (0.0437, 0.764)]
    out = np.zeros(len(x), np.float32)
    for dt, g in combs:
        d = max(1, int(dt * SR))
        buf = x.astype(np.float32).copy()
        acc = buf.copy()
        for _ in range(int(6 + amt * 8)):
            acc = np.concatenate([np.zeros(d, np.float32), acc[:-d]]) * (g * (0.6 + 0.4 * amt))
            if np.max(np.abs(acc)) < 1e-4:
                break
            buf = buf + acc
        out += buf / len(combs)
    for dt, g in ((0.005, 0.7), (0.0017, 0.7)):
        d = max(1, int(dt * SR))
        delayed = np.concatenate([np.zeros(d, np.float32), out[:-d]])
        out = (-g * out + delayed + g * np.concatenate([np.zeros(d, np.float32), (-g * out + delayed)[:-d]])).astype(np.float32)
    return (x * (1 - 0.5 * amt) + out * 0.6 * amt).astype(np.float32)


def _compress(x, amt):
    """Simple RMS compressor + makeup — evens dynamics and adds punch."""
    if np.max(np.abs(x)) < 1e-6:
        return x
    win = max(1, int(0.005 * SR))
    env = np.sqrt(np.convolve(x.astype(np.float64) ** 2, np.ones(win) / win, mode="same")) + 1e-6
    thr = 0.15
    ratio = 1 + 7 * amt
    gain = np.where(env > thr, (thr + (env - thr) / ratio) / env, 1.0)
    makeup = 1.0 + 1.4 * amt
    return (x * gain.astype(np.float32) * makeup).astype(np.float32)


def apply_fx(x: np.ndarray, fx: dict) -> np.ndarray:
    """Run the FX rack over a buffer. `fx` maps FX_KNOBS keys → amount 0..1 (0 = bypass).
    May RETURN A LONGER buffer (delay/reverb tails) — callers should size the render tail."""
    if not fx or not any(v > 0 for v in fx.values()):
        return x.astype(np.float32)
    out = x.astype(np.float32).copy()
    tail = int(fx_tail(fx) * SR)
    if tail > 0:
        out = np.concatenate([out, np.zeros(tail, np.float32)])

    drive = float(fx.get("drive", 0))
    if drive > 0:
        k = 1 + drive * 12
        out = (np.tanh(out * k) / np.tanh(k)).astype(np.float32)

    bass = float(fx.get("bass", 0))
    if bass > 0:
        out = out + _sub_octave(out) * (0.6 * bass)
        b, a = _biquad("lowshelf", 110, 6 * bass); out = signal.lfilter(b, a, out).astype(np.float32)

    lp = float(fx.get("lowpass", 0))
    if lp > 0:
        cutoff = 14000 * (1 - lp) + 350          # more = darker
        out = _rlp(out, cutoff, 0.5 + lp * 3.0)

    crush = float(fx.get("crush", 0))
    if crush > 0:
        bits = max(2, int(round(16 - crush * 13)))
        step = 2 ** bits
        out = np.round(out * step) / step
        ds = 1 + int(crush * 24)
        if ds > 1:
            idx = (np.arange(len(out)) // ds) * ds
            out = out[np.clip(idx, 0, len(out) - 1)]
        out = out.astype(np.float32)

    chorus = float(fx.get("chorus", 0))
    if chorus > 0:
        out = _chorus(out, chorus)

    delay = float(fx.get("delay", 0))
    if delay > 0:
        out = _delay(out, delay)

    reverb = float(fx.get("reverb", 0))
    if reverb > 0:
        out = _reverb(out, reverb)

    comp = float(fx.get("comp", 0))
    if comp > 0:
        out = _compress(out, comp)

    return out.astype(np.float32)
