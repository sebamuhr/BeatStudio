"""The Separation Board — the golden surface of the app.

Your recorded take becomes a drawing board. You add a track, pick an instrument for it, and
then draw its line by hand with the PEN TOOL — placing a dot everywhere that sound happens.
This separates the take by INSTRUMENT and by INTENTION, not by an automatic guess.

  • + Add track       → a new empty line + its own instrument picker + preview
  • click on the wave → place a dot on the active track
  • drag a dot        → move it · right-click a dot → delete it
  • ▶ (on a track)    → preview what you've DRAWN for that track
  • ▶ Preview mix     → hear everything together (a red playhead sweeps as it plays)
  • scroll            → zoom (or the − / + buttons) · drag the corner navigator to move around
  • BPM box           → set the tempo right here · Full screen / F11 for the whole screen

A line is an amplitude shape over time (0 at the centre line, 1 at the top). Every raised dot
on a visible track becomes a hit on the tempo grid, played with that track's instrument.
"""
from __future__ import annotations
import copy
import numpy as np
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QWidget, QComboBox, QScrollArea, QFrame, QLineEdit, QSizePolicy,
                               QSpinBox, QSlider, QToolTip, QGraphicsOpacityEffect, QSplitter)
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QTimer, QElapsedTimer, QEvent
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath

from . import theme, groove
from .synth import (SR, WAVES, SYNTH_KNOBS, default_params, FX_KNOBS, default_fx,
                    HUM_SPECS, HUMS, HUM_KNOBS, default_hum_params,
                    INST_CATEGORIES, INST_SPECS, DRUMS, MIX_KNOBS, default_mix)
from .model import Lane, Event, uid
from .analysis import onset_start
from .settings import ITEMS as INSTRUMENT_ITEMS


def _collapse_items(raw):
    """Kept for back-compat (old callers). The picker is now grouped — see GROUPS / _group_items."""
    raw = list(raw)
    drums = [it for it in raw if it[0] == "drum"]
    return drums + [("synth", WAVES[0], "Synth"), ("original", "", "Original")]


# The instrument picker is a TOP-LEVEL selector: Original · Hum · Synth · Instrument. Each opens its
# own sub-picker (a combo of that group's sounds; Synth opens the Base/Modulator designer; Original
# just the FX rack). "Instrument" lists real categories (Drum + pitched families).
GROUPS = ["Original", "Hum", "Synth", "Instrument"]


def _instrument_items():
    """(kind, sound, 'Category — Name') for every Instrument-group sound: Drums + pitched families."""
    items = [("drum", k, "Drum — " + k.title()) for k in DRUMS]
    for cat, names in INST_CATEGORIES:
        for nm in names:
            items.append(("inst", nm, f"{cat} — {nm.title()}"))
    return items


def _group_items(group):
    """The (kind, sound, label) list shown in a group's sub-combo (empty for Original/Synth, which
    use the FX rack / synth designer instead of a plain combo)."""
    if group == "Hum":
        return [("hum", h, HUM_SPECS[h].get("label", h.title())) for h in HUMS]
    if group == "Instrument":
        return _instrument_items()
    return []


def _group_of(track):
    """Which top-level group a track's kind belongs to."""
    k = track.get("kind")
    if k == "original":
        return "Original"
    if k == "hum":
        return "Hum"
    if k == "synth":
        return "Synth"
    return "Instrument"        # drum / inst

DOT_R = 5.5
HIT_R = 12.0
SILENCE = 0.03           # at/under this the line is silent; anything above makes sound
MIN_SPAN = 0.01          # deepest zoom = 1% of the take across the screen
MM_H = 46                # navigator height
LM = 30                  # left margin (room for the 0–10 volume scale)
KB = 46                  # left margin in NOTES mode (room for the piano keyboard gutter)
RM = 12                  # right margin
_BLACK_KEYS = {1, 3, 6, 8, 10}   # pitch-classes that are black keys on the piano
DEF_MIDI = 60                    # default pitch (C4 = natural) for a point until you set it in NOTES
PIANO_MIN, PIANO_MAX = 21, 108   # full piano (A0..C8) — scroll the NOTES view anywhere in here
NOTE_SPAN = 30                   # semitones visible at once in NOTES mode (scroll for the rest)
NOTE_SNAP_DIV = 48               # notes snap to 1/48 of a beat (super fine — accurate placement)
TAKE_BAR = 24                    # height of the take-picker strip at the top of NOTES mode
TAKE_ROW_H = 132                 # a soundwave row ≈ a track card's height (1 track = 1 soundwave)
# each take (main + overdubs) gets its own row + waveform colour
TAKE_HEX = ["#ff6b6b", "#c0a8ff", "#5cd6c0", "#ffd24d", "#ff8c5c", "#6ecbff"]


def take_color(i):
    return QColor(TAKE_HEX[i % len(TAKE_HEX)])


def _is_pitched(tr):
    """Pitched instruments AUTO-connect successive note clicks (a melody line). Drums/original do
    NOT — three clicks stay three hits. (A drum can still be TIED by hand; this only gates the
    automatic tie-on-click.)"""
    return tr.get("kind") in ("synth", "hum", "inst", "sample")


def _seg_dist(px, py, ax, ay, bx, by):
    """Distance from point (px,py) to the segment (ax,ay)-(bx,by), in pixels."""
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 <= 1e-6:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    tt = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return ((px - (ax + tt * dx)) ** 2 + (py - (ay + tt * dy)) ** 2) ** 0.5


# ---------------------------------------------------------------- the canvas
class CurveCanvas(QWidget):
    """Waveform + hand-drawn pen-tool lines with draggable dots, zoom/pan, navigator, playhead."""
    active_changed = Signal(int)
    edited = Signal(int)          # a point gesture finished on track index (for live sync)
    point_selected = Signal(str)  # an anchor was picked → highlight the matching Studio beat
    grid_scaled = Signal(float)   # Grid tool dragged → a new bpm (uniform tempo stretch)
    grid_moved = Signal()         # Grid tool moved sideways → grid offset changed (re-time the beats)
    fit_applied = Signal(float, float, float)   # Fit tool: (a_frac, b0_frac, new_b_frac) → resample
    key_pressed = Signal(int)     # a piano key in the notes gutter was clicked → audition this MIDI note
    delete_take = Signal(int)     # the ✕ on a take (soundwave) was clicked → remove it + everything on it
    take_selected = Signal(int)   # a soundwave's checkbox was ticked → scope everything to that take
    take_flag = Signal(int, str)  # a soundwave's Solo/Mute button was toggled (index, "solo"|"mute")
    take_rename = Signal(int)     # double-clicked a soundwave's name → rename it
    loop_changed = Signal(int)    # the Loop tool set a soundwave's loop region (take index)

    def __init__(self, buf, sr, bpm, tracks, parent=None):
        super().__init__(parent)
        self.sr = sr
        self.bpm = bpm or 90
        self.tracks = tracks
        self.active = -1
        self.sel_pts = set()      # ids of anchors currently highlighted (linked selection)
        self.view0, self.view1 = 0.0, 1.0
        self.playhead = None                      # take-fraction 0..1, or None
        self.tool = "pen"                          # pen | grid (tempo) | fit (audio) | loop (sample region)
        self._loop_drag = None                     # take-fraction where a Loop drag started
        self._grid_grab = None                     # (grabbed beat number) while STRETCHING the grid
        self.grid_off = 0.0                        # grid phase offset in SECONDS (moves the grid sideways)
        self._grid_pan = None                      # (start-x, start-offset) while MOVING the grid
        self.fit_a = None; self.fit_b = None       # Fit region endpoints (fractions of the active take)
        self._fit_b0 = None; self._fit_drag = False; self._fit_hover = None
        self.recording = False
        self.live_env = []                        # live RMS envelope while recording
        self.rec_clip = False
        self._drag = None
        self._pan_mm = False
        self._emit_clock = QElapsedTimer(); self._emit_clock.start()
        self._pitch_cache = {}     # id(buf) -> (len, (tfrac, midi, voiced)); pYIN runs once per take
        self._hover = None         # (x, y, note-name) for the ribbon's hover label, or None
        self.mode = "volume"       # "volume" (hits/loudness, as always) | "notes" (piano-roll)
        self.note_lo, self.note_hi = 36, 84   # visible pitch range in notes mode (C2..C6)
        self._note_drag = None     # (track_idx, note_idx) while dragging a note in the piano-roll
        self._tie_left = None       # while placing a tied note: the LEFT point of the new segment
        self._place_pos = None      # press position, to tell a plain click (held) from a drag (glide)
        self.takes = []
        # WHICH soundwave you are working on. Authoritative: the notes view, point placement and new
        # tracks all scope to it, and the active track is always one of THIS take's tracks.
        self.sel_take = 0
        self.set_takes([{"id": "T0", "buf": buf, "color": take_color(0), "name": "Main"}])
        self.setMinimumHeight(340)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_takes(self, takes):
        """Replace the stacked take rows (main + overdubs). Each take draws its own waveform row."""
        self.takes = []
        for tk in takes:
            b = tk.get("buf")
            b = b.astype(np.float32) if b is not None else np.zeros(self.sr, np.float32)
            self.takes.append({"id": tk["id"], "buf": b, "color": tk.get("color", take_color(len(self.takes))),
                               "name": tk.get("name", f"Take {len(self.takes)+1}"),
                               "solo": bool(tk.get("solo", False)), "muted": bool(tk.get("muted", False)),
                               "mode": tk.get("mode", "volume"),
                               "loop_a": tk.get("loop_a"), "loop_b": tk.get("loop_b"),   # sample loop region (0..1)
                               "gpeak": float(np.abs(b).max()) + 1e-9,
                               "pitch": self._ribbon_for(b),
                               "peaks": self._peaks_over(b, 0.0, 1.0, 1400)})
        self.buf = self.takes[0]["buf"]      # the MAIN take drives tempo/duration
        self.sel_take = max(0, min(self.sel_take, len(self.takes) - 1))
        self.update()

    def _ribbon_for(self, buf):
        """(tfrac, midi, voiced) pitch ribbon for a take buffer, computed once per buffer. set_takes
        is called a lot during sync with the SAME buffers, so cache by identity to avoid re-running
        pYIN on every resync."""
        key = id(buf); entry = self._pitch_cache.get(key)
        if entry is None or entry[0] != len(buf):
            entry = (len(buf), groove.pitch_ribbon(buf, self.sr))
            self._pitch_cache[key] = entry
        return entry[1]

    @staticmethod
    def _pitch_color(midi):
        """Pitch-class → hue around the colour wheel (C=red…); octave nudges the lightness so higher
        notes read a touch brighter. Distinct per note, works in the dark theme."""
        m = float(midi); pc = int(round(m)) % 12
        octv = int(round(m)) // 12 - 1                 # ~ musical octave (MIDI 60 = C4)
        light = 0.40 + 0.05 * max(-2, min(3, octv - 4))
        return QColor.fromHslF(pc / 12.0, 0.80, max(0.30, min(0.72, light)))

    def set_buf(self, buf):                  # back-compat: replace just the main take
        self.set_takes([{"id": "T0", "buf": buf, "color": take_color(0), "name": "Main"}])
        self.view0, self.view1 = 0.0, 1.0

    def _peaks_over(self, buf, a_frac, b_frac, n):
        x = np.abs(buf); N = len(x)
        a, b = int(a_frac * N), max(int(a_frac * N) + 1, int(b_frac * N))
        seg = x[a:b]
        if len(seg) < 2:
            return np.zeros(n, np.float32)
        edges = np.linspace(0, len(seg), n + 1).astype(int)
        return np.array([seg[edges[i]:max(edges[i] + 1, edges[i + 1])].max() for i in range(n)], np.float32)

    # --- take-row geometry ---
    def _track_band(self, tr):
        tid = tr.get("take")
        for i, tk in enumerate(self.takes):
            if tk["id"] == tid:
                return i
        return 0

    def _active_band(self):
        """The take row you're working on = the SELECTED soundwave (not a guess from the active
        track, which used to fall back to take 0 whenever no track was picked)."""
        return max(0, min(self.sel_take, len(self.takes) - 1))

    def _band(self, i=0):
        """Vertical layout → (top, height, baseline-y, usable-height). ONLY the SELECTED soundwave is
        shown now (the others were confusing stacked together), so every band is the full plot area —
        the selected wave fills the canvas. The baseline (v=0) is near the bottom, v=1 the top."""
        y0 = 6.0; y1 = self.height() - MM_H - 18
        bh = y1 - y0
        return y0, bh, y0 + bh - 8, bh - 26

    def _take_del_rect(self, i):
        """The ✕ (delete-soundwave) button rect at the top-right of take-row i (volume mode)."""
        top, _, _, _ = self._band(i); _, x1 = self._xspan()
        return QRectF(x1 - 24, top + 5, 17, 17)

    def _take_sm_rects(self, i):
        """Solo / Mute button rects for take-row i (volume mode), left of the ✕."""
        top, _, _, _ = self._band(i); _, x1 = self._xspan()
        m = QRectF(x1 - 48, top + 5, 17, 17)
        s = QRectF(x1 - 70, top + 5, 17, 17)
        return s, m

    def _hit_take_sm(self, pos):
        """Solo/Mute moved to the track cards — no longer on the soundwave (kept as a no-op hook)."""
        return None

    def _take_name_rect(self, i):
        """The soundwave's name label (double-click to rename). Volume mode."""
        top, _, _, _ = self._band(i); x0, _ = self._xspan()
        return QRectF(x0 + 24, top + 2, 160, 14)

    def mouseDoubleClickEvent(self, ev):
        """Double-click a soundwave's name → rename it (both views)."""
        pos = ev.position()
        if self.mode == "notes":
            if self._take_bar():
                for i in range(len(self.takes)):
                    if self._take_chip_rect(i).contains(pos):
                        self.take_rename.emit(i); return
        else:
            for i in range(len(self.takes)):
                if self._take_name_rect(i).contains(pos):
                    self.take_rename.emit(i); return
        super().mouseDoubleClickEvent(ev)

    def _take_bar(self):
        """The NOTES-mode take-picker strip: shown only when there's more than one soundwave."""
        return TAKE_BAR if len(self.takes) > 1 else 0.0

    def _take_chk_rect(self, i):
        """The soundwave checkbox, left of the take's name (volume mode)."""
        top, _, _, _ = self._band(i); x0, _ = self._xspan()
        return QRectF(x0 + 6, top + 3, 13, 13)

    def _take_chip_rect(self, i):
        """A take's chip in the NOTES-mode picker strip (checkbox + name), left to right."""
        x0, _ = self._xspan()
        w = 104.0
        return QRectF(x0 + 6 + i * (w + 6), 5, w, TAKE_BAR - 8)

    def _band_at(self, y):
        """Which take row the cursor is over — only the SELECTED wave is shown, so it's that one."""
        top, bh, _, _ = self._band()
        return self._active_band() if top <= y <= top + bh else None

    def _first_track_on(self, band):
        """The first track bound to take-row `band`, or None — so we never draw on another wave."""
        for i, tr in enumerate(self.tracks):
            if self._track_band(tr) == band:
                return i
        return None

    def _hit_take_sel(self, pos):
        """Which soundwave's selector was clicked (index), or None."""
        if self.mode == "notes":
            if self._take_bar():
                for i in range(len(self.takes)):
                    if self._take_chip_rect(i).contains(pos):
                        return i
            return None
        i = self._active_band()                          # only the selected wave is shown/hittable
        if self._take_chk_rect(i).united(QRectF(self._take_chk_rect(i).right(),
                                                self._take_chk_rect(i).top(), 130, 13)).contains(pos):
            return i
        return None

    def _notes_del_rect(self):
        """The ✕ for the take shown in notes mode (deletes the active take)."""
        _, x1 = self._xspan(); y0, _ = self._notes_plot()
        return QRectF(x1 - 24, y0 + 5, 17, 17)

    def _hit_take_del(self, pos):
        """Which take's ✕ was clicked (index), or None."""
        if self.mode == "notes":
            return self._active_band() if self._notes_del_rect().contains(pos) else None
        i = self._active_band()                          # only the selected wave is shown/hittable
        return i if self._take_del_rect(i).contains(pos) else None

    def _draw_del_x(self, p, r):
        p.setBrush(QBrush(QColor(28, 20, 24, 205))); p.setPen(QPen(QColor(255, 90, 90, 130), 1))
        p.drawRoundedRect(r, 4, 4)
        p.setPen(QPen(QColor("#ff8a8a"), 1.8)); m = 5.0
        p.drawLine(QPointF(r.left() + m, r.top() + m), QPointF(r.right() - m, r.bottom() - m))
        p.drawLine(QPointF(r.right() - m, r.top() + m), QPointF(r.left() + m, r.bottom() - m))

    def _draw_sm(self, p, r, letter, on, col):
        """A small Solo/Mute pill (lit in `col` when on) for a soundwave row."""
        p.setBrush(QBrush(col if on else QColor(20, 20, 28, 220)))
        p.setPen(QPen(col if on else QColor(255, 255, 255, 45), 1.2))
        p.drawRoundedRect(r, 4, 4)
        p.setFont(theme.sans(9, 700))
        p.setPen(QPen(QColor("#12121a") if on else QColor(180, 180, 190), 1))
        p.drawText(r, Qt.AlignCenter, letter)

    def _draw_take_chk(self, p, r, col, on):
        """A small checkbox in the take's own colour — ticked = this is the soundwave you're editing."""
        p.setBrush(QBrush(col if on else QColor(20, 20, 28, 220)))
        p.setPen(QPen(col if on else QColor(255, 255, 255, 55), 1.3))
        p.drawRoundedRect(r, 3, 3)
        if on:
            p.setPen(QPen(QColor("#12121a"), 1.9))
            p.drawLine(QPointF(r.left() + 3, r.center().y()), QPointF(r.center().x() - 0.5, r.bottom() - 3.2))
            p.drawLine(QPointF(r.center().x() - 0.5, r.bottom() - 3.2), QPointF(r.right() - 2.8, r.top() + 3.2))

    def set_sel_take(self, i):
        """Pick the soundwave to work on. Everything (notes view, new points, new tracks) follows it."""
        i = max(0, min(int(i), len(self.takes) - 1))
        if i == self.sel_take:
            return
        self.sel_take = i
        if self.mode == "notes":
            self._fit_note_range()          # re-centre the piano on THIS take's pitches
        self.take_selected.emit(i); self.update()

    def set_active(self, i):
        # Picking a track also moves you to ITS soundwave, so the two can never disagree. Assign
        # `active` FIRST: set_sel_take emits, and the board reconciles against `active` — a stale
        # value there would bounce the selection to another track.
        self.active = i
        if 0 <= i < len(self.tracks):
            self.set_sel_take(self._track_band(self.tracks[i]))
        self.active_changed.emit(i); self.update()

    def _select_point(self, pid):
        self.sel_pts = {pid} if pid else set()
        self.point_selected.emit(pid or ""); self.update()

    def set_selected_pts(self, ids):
        """The Studio grid selected some beats — highlight the drawn anchors behind them."""
        self.sel_pts = set(i for i in (ids or []) if i); self.update()

    def set_playhead(self, frac):
        self.playhead = frac; self.update()

    def set_live(self, env, clip=False):
        self.live_env = env or []; self.rec_clip = clip; self.update()

    # --- geometry ---
    def _xspan(self):
        return (KB if self.mode == "notes" else LM), self.width() - RM

    def _span(self):
        return max(1e-6, self.view1 - self.view0)

    def _to_px(self, t, v, i=0):
        x0, x1 = self._xspan(); _, _, cy, half = self._band(i)
        return QPointF(x0 + (t - self.view0) / self._span() * (x1 - x0), cy - v * half)

    def _from_px(self, x, y, i=0):
        x0, x1 = self._xspan(); _, _, cy, half = self._band(i)
        t = self.view0 + (x - x0) / max(1.0, (x1 - x0)) * self._span()
        v = (cy - y) / max(1.0, half)
        return max(0.0, min(1.0, t)), max(0.0, min(1.0, v))

    def _apx(self, pt, i=0):                   # anchor pixel (in take-row i)
        return self._to_px(pt["t"], pt["v"], i)

    def _pitch_at(self, pr, tf):
        """Note (midi) at take-fraction tf from a ribbon triple, or None where unpitched."""
        if not pr or len(pr[0]) < 2:
            return None
        tfr, midi_arr, voiced = pr
        j = min(len(tfr) - 1, max(0, int(np.searchsorted(tfr, tf))))
        return float(midi_arr[j]) if (voiced[j] and np.isfinite(midi_arr[j])) else None

    def _draw_ribbon(self, p, pr, x0, x1, ry, rh):
        if not pr or len(pr[0]) < 2:
            return
        ncols = int(min(700, max(2, (x1 - x0) / 2)))
        cw = (x1 - x0) / ncols + 1.0
        for k in range(ncols):
            tf = self.view0 + (k / (ncols - 1)) * self._span()
            m = self._pitch_at(pr, tf)
            if m is not None:
                x = x0 + (k / (ncols - 1)) * (x1 - x0)
                p.fillRect(QRectF(x, ry, cw, rh), self._pitch_color(m))

    # --- notes-mode (piano-roll) geometry ---
    def set_mode(self, name):
        """Switch the canvas between 'volume' (hits/loudness) and 'notes' (piano-roll)."""
        self.mode = "notes" if name == "notes" else "volume"
        if self.mode == "notes":
            self._fit_note_range()
        self.update()

    def _fit_note_range(self):
        """Centre the (scrollable) NOTE_SPAN-semitone window on the active take's detected notes, so
        the singing lands in the middle of the grid. Falls back to C3..-ish when there's no pitch."""
        centre = 63                                       # ~D#4 default centre
        pr = self.takes[self._active_band()].get("pitch") if self.takes else None
        if pr and len(pr[0]) > 1:
            good = pr[1][pr[2] & np.isfinite(pr[1])]
            if len(good):
                centre = int(round((float(good.min()) + float(good.max())) / 2))
        lo = max(PIANO_MIN, min(PIANO_MAX - NOTE_SPAN, centre - NOTE_SPAN // 2))
        self.note_lo, self.note_hi = lo, lo + NOTE_SPAN

    def _scroll_notes(self, ds):
        """Shift the visible piano window by ds semitones (mouse-wheel in NOTES mode), clamped."""
        span = self.note_hi - self.note_lo
        lo = max(PIANO_MIN, min(PIANO_MAX - span, self.note_lo + int(ds)))
        if lo != self.note_lo:
            self.note_lo, self.note_hi = lo, lo + span; self.update()

    def _notes_plot(self):
        return 6.0 + self._take_bar(), self.height() - MM_H - 18

    def _note_y(self, m):
        y0, y1 = self._notes_plot()
        frac = (m - self.note_lo) / max(1, (self.note_hi - self.note_lo))
        return y1 - frac * (y1 - y0)

    def _midi_at_y(self, y):
        y0, y1 = self._notes_plot()
        frac = (y1 - y) / max(1.0, (y1 - y0))
        return self.note_lo + frac * (self.note_hi - self.note_lo)

    def _to_px_t(self, t):
        x0, x1 = self._xspan()
        return x0 + (t - self.view0) / self._span() * (x1 - x0)

    def _t_at_x(self, x):
        x0, x1 = self._xspan()
        return max(0.0, min(1.0, self.view0 + (x - x0) / max(1.0, (x1 - x0)) * self._span()))

    def _snap_t(self, t):
        """Snap a take-fraction to the FINE notes grid (1/NOTE_SNAP_DIV of a beat) so pitch placement
        is accurate — much finer than the 16th-note beat lines that are drawn."""
        dur = len(self.buf) / self.sr
        if dur <= 0:
            return t
        sub = (60.0 / self.bpm) / NOTE_SNAP_DIV
        sec = round((t * dur - self.grid_off) / sub) * sub + self.grid_off
        return min(1.0, max(0.0, sec / dur))

    def _lane_h(self):
        y0, y1 = self._notes_plot()
        return (y1 - y0) / max(1, (self.note_hi - self.note_lo))

    def _notes_hit(self, pos):
        """A point of the active track near the cursor (by time+pitch) → index, else None."""
        if not (0 <= self.active < len(self.tracks)):
            return None
        pts = self.tracks[self.active].get("points") or []
        for i, pt in enumerate(pts):
            dx = self._to_px_t(pt["t"]) - pos.x(); dy = self._note_y(pt.get("midi", DEF_MIDI)) - pos.y()
            if dx * dx + dy * dy <= (HIT_R * 0.9) ** 2:
                return i
        return None


    def _hit_segment(self, pos):
        """A TIE line of the active track near the cursor → the LEFT point of that segment, else None.
        Held segments are a horizontal bar at the left pitch; glide segments are the a→b line."""
        if not (0 <= self.active < len(self.tracks)):
            return None
        pts = sorted(self.tracks[self.active].get("points") or [], key=lambda p: p["t"])
        for k in range(len(pts) - 1):
            a, b = pts[k], pts[k + 1]
            if not a.get("tie"):
                continue
            ax, ay = self._to_px_t(a["t"]), self._note_y(a.get("midi", DEF_MIDI))
            bx = self._to_px_t(b["t"])
            by = self._note_y(b.get("midi", DEF_MIDI)) if a.get("glide") else ay
            if _seg_dist(pos.x(), pos.y(), ax, ay, bx, by) < 6.0:
                return a
        return None

    # --- painting ---
    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing, True)
        x0, x1 = self._xspan()
        p.fillRect(self.rect(), QColor("#0c0c14"))
        if self.mode == "notes":
            self._paint_notes(p, x0, x1)
            ny0, ny1 = self._notes_plot(); self._paint_loop(p, ny0, ny1)
            self._paint_navigator(p); p.end(); return
        dur = len(self.buf) / self.sr; beat_len = 60.0 / self.bpm
        y_top = self._band(0)[0]; y_bot = self._band(len(self.takes) - 1)[0] + self._band(len(self.takes) - 1)[1]
        active_band = self._active_band()

        # ONLY the selected soundwave is shown (fills the canvas) — the others were confusing.
        for i, tk in enumerate(self.takes):
            if i != active_band:
                continue
            top, bh, cy, half = self._band(i)
            base = tk["color"]
            if i == active_band:      # the soundwave you're editing: tinted in its own colour + a side bar
                p.fillRect(QRectF(0, top, self.width(), bh), QColor(base.red(), base.green(), base.blue(), 15))
                p.fillRect(QRectF(0, top, 3, bh), base)
                p.setPen(QPen(QColor(base.red(), base.green(), base.blue(), 60), 1)); p.setBrush(Qt.NoBrush)
                p.drawLine(int(x0), int(top), int(x1), int(top))
            for lvl in range(0, 11, 5):            # compact volume scale per row
                yv = cy - (lvl / 10.0) * half
                p.setPen(QPen(QColor("#4a4a56"), 1))
                p.drawText(QRectF(0, yv - 7, x0 - 5, 14), Qt.AlignRight | Qt.AlignVCenter, str(lvl))
                p.setPen(QPen(QColor(255, 255, 255, 10), 1)); p.drawLine(int(x0), int(yv), int(x1), int(yv))
            p.setPen(QPen(QColor(255, 255, 255, 22), 1)); p.drawLine(int(x0), int(cy), int(x1), int(cy))
            # waveform (this take's colour), or the live envelope if we're recording into it
            if self.recording and i == active_band:
                env = np.asarray(self.live_env, np.float32)
                col = theme.REC if self.rec_clip else QColor(61, 214, 255)
                p.setPen(QPen(col, 1))
                if len(env) >= 2:
                    pk = float(env.max()) + 1e-9
                    for k in range(len(env)):
                        x = x0 + (k / (len(env) - 1)) * (x1 - x0) * 0.75; a = float(env[k]) / pk * half
                        p.drawLine(QPointF(x, cy), QPointF(x, cy - a))
            else:
                ncols = int(min(1400, max(2, x1 - x0)))
                a0, b0 = int(self.view0 * len(tk["buf"])), int(self.view1 * len(tk["buf"]))
                seg = np.abs(tk["buf"][a0:max(a0 + 1, b0)])
                if len(seg) >= 2:
                    edges = np.linspace(0, len(seg), ncols + 1).astype(int)
                    vpeaks = np.array([seg[edges[k]:max(edges[k] + 1, edges[k + 1])].max() for k in range(ncols)]) / tk["gpeak"]
                    p.setPen(QPen(QColor(base.red(), base.green(), base.blue(), 130), 1))
                    for k in range(ncols):
                        x = x0 + (k / (ncols - 1)) * (x1 - x0); a = float(vpeaks[k]) * half
                        p.drawLine(QPointF(x, cy), QPointF(x, cy - a))
            # checkbox + name: tick a soundwave to make it the one you're editing
            sel = (i == active_band)
            self._draw_take_chk(p, self._take_chk_rect(i), base, sel)
            p.setFont(theme.sans(9, 700 if sel else 600))
            p.setPen(QPen(QColor(base.red(), base.green(), base.blue(), 235 if sel else 150), 1))
            p.drawText(QRectF(x0 + 24, top + 2, 200, 14), Qt.AlignLeft | Qt.AlignVCenter, tk["name"])
            # (Solo / Mute live on the TRACK CARD now, not on the soundwave — removed from here.)
            self._draw_del_x(p, self._take_del_rect(i))    # ✕ delete this whole soundwave (+ its tracks)

        # bar + beat lines span every row (shifted by the grid offset)
        if dur:
            step = beat_len * 4
            bar = int((self.view0 * dur - self.grid_off) / step) - 1
            while True:
                tf = (bar * step + self.grid_off) / dur
                if tf > self.view1:
                    break
                if self.view0 <= tf and tf >= 0:
                    x = self._to_px(tf, 0, 0).x()
                    p.setPen(QPen(QColor("#2c2c3a"), 1)); p.drawLine(int(x), int(y_top), int(x), int(y_bot))
                bar += 1
            beat = int((self.view0 * dur - self.grid_off) / beat_len) - 1        # fainter beat lines
            while True:
                tf = (beat * beat_len + self.grid_off) / dur
                if tf > self.view1:
                    break
                if self.view0 <= tf and tf >= 0 and beat % 4 != 0:
                    x = self._to_px(tf, 0, 0).x()
                    p.setPen(QPen(QColor(255, 255, 255, 12), 1)); p.drawLine(int(x), int(y_top), int(x), int(y_bot))
                beat += 1

        if self.recording:
            p.setFont(theme.sans(14, 600)); p.setPen(QPen(theme.REC, 1))
            p.drawText(self.rect().adjusted(0, 8, -14, 0), Qt.AlignHCenter | Qt.AlignTop, "●  RECORDING…")

        for ti, tr in enumerate(self.tracks):
            if not tr["visible"] or self._track_band(tr) != active_band:   # only the selected wave's tracks
                continue
            bi = self._track_band(tr)
            col = tr["color"]; active = (ti == self.active); pts = tr["points"]
            # A SYNTH line is one continuous envelope (always connect). An INSTRUMENT connects only
            # TIED points — an untied gap = a hit that ends at its natural length (the same break the
            # NOTES view shows), so the two views agree.
            always = tr.get("kind") in ("synth", "original")
            if len(pts) >= 2:                          # smooth cubic-Bézier through the anchors
                p.setPen(QPen(col, 2.6 if active else 1.4)); p.setBrush(Qt.NoBrush)
                for i in range(len(pts) - 1):
                    if not (always or pts[i].get("tie")):
                        continue
                    c0, c1 = seg_ctrls(pts, i)
                    seg = QPainterPath(); seg.moveTo(self._apx(pts[i], bi))
                    seg.cubicTo(self._to_px(c0[0], c0[1], bi), self._to_px(c1[0], c1[1], bi), self._apx(pts[i + 1], bi))
                    p.drawPath(seg)
            if active:                                 # tangent handles (circles) like a pen tool
                for pt in pts:
                    if not (pt["hx"] or pt["hy"]):
                        continue
                    ho = self._to_px(pt["t"] + pt["hx"], pt["v"] + pt["hy"], bi)
                    hi = self._to_px(pt["t"] - pt["hx"], pt["v"] - pt["hy"], bi)
                    p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 160), 1)); p.drawLine(hi, ho)
                    p.setBrush(QBrush(QColor("#e8e8f0"))); p.setPen(QPen(col, 1.2))
                    p.drawEllipse(ho, 4.2, 4.2); p.drawEllipse(hi, 4.2, 4.2)
            for pt in pts:                             # anchors: square (active) / dot (inactive)
                q = self._apx(pt, bi)
                if active:
                    p.setBrush(QBrush(col)); p.setPen(QPen(QColor("#0c0c14"), 1.5))
                    p.drawRect(QRectF(q.x() - DOT_R, q.y() - DOT_R, 2 * DOT_R, 2 * DOT_R))
                else:
                    p.setBrush(QBrush(QColor(col.red(), col.green(), col.blue(), 95))); p.setPen(Qt.NoPen)
                    p.drawEllipse(q, DOT_R - 1.8, DOT_R - 1.8)
                if pt.get("id") in self.sel_pts:       # linked-selection ring (matches the Studio beat)
                    p.setBrush(Qt.NoBrush); p.setPen(QPen(theme.ACCENT_CY, 2))
                    p.drawEllipse(q, DOT_R + 3, DOT_R + 3)

        if self.playhead is not None and self.view0 <= self.playhead <= self.view1:
            x = self._to_px(self.playhead, 0, 0).x()
            p.setPen(QPen(theme.REC, 2)); p.drawLine(QPointF(x, y_top), QPointF(x, y_bot))

        # Fit tool: shade the selected region and show its A / B edge handles
        if self.tool == "fit" and self.fit_a is not None:
            cyan = QColor(61, 214, 255)
            xa = self._to_px(self.fit_a, 0, 0).x()
            b = self.fit_b if self.fit_b is not None else self._fit_hover
            if b is not None:
                xb = self._to_px(b, 0, 0).x()
                p.fillRect(QRectF(min(xa, xb), y_top, abs(xb - xa), y_bot - y_top), QColor(61, 214, 255, 34))
                # the ORIGINAL right edge (dashed) while dragging, so the stretch amount is visible
                if self._fit_b0 is not None and abs(b - self._fit_b0) > 1e-4:
                    x0 = self._to_px(self._fit_b0, 0, 0).x()
                    dp = QPen(QColor(255, 255, 255, 90), 1); dp.setStyle(Qt.DashLine)
                    p.setPen(dp); p.drawLine(QPointF(x0, y_top), QPointF(x0, y_bot))
                    old = self._fit_b0 - self.fit_a; new = b - self.fit_a
                    if old > 1e-6:
                        p.setPen(QPen(cyan, 1)); p.setFont(theme.sans(11, 600))
                        p.drawText(QRectF(min(xa, xb), y_top + 2, abs(xb - xa), 16),
                                   Qt.AlignCenter, f"×{new / old:.2f}")
                p.setPen(QPen(cyan, 2)); p.drawLine(QPointF(xb, y_top), QPointF(xb, y_bot))
                p.setBrush(QBrush(cyan)); p.setPen(Qt.NoPen)
                p.drawRect(QRectF(xb - 4, (y_top + y_bot) / 2 - 10, 8, 20))    # grab handle at B
            p.setPen(QPen(cyan, 2)); p.drawLine(QPointF(xa, y_top), QPointF(xa, y_bot))

        if 0 <= self.active < len(self.tracks) and len(self.tracks[self.active]["points"]) == 0:
            top, bh, cy, half = self._band(active_band)
            p.setPen(QPen(QColor("#5a5a6a"), 1)); p.setFont(theme.sans(12))
            if self.tracks[self.active].get("kind") == "original":
                hint = "“Original” plays your whole recording — just dial the FX rack (no points needed)"
            else:
                hint = f"Click this row to place points for “{self.tracks[self.active]['name']}”"
            p.drawText(QRectF(x0, top, x1 - x0, bh), Qt.AlignCenter, hint)
        elif not self.tracks:
            p.setPen(QPen(QColor("#5a5a6a"), 1)); p.setFont(theme.sans(13))
            p.drawText(self.rect(), Qt.AlignCenter, "Add a track → then draw its sound with your mouse")

        # hover label: the note under the cursor on the ribbon (read it to set a synth/hum note by hand)
        if self._hover is not None:
            hx, hy, txt = self._hover
            p.setFont(theme.sans(11, 700))
            tw = p.fontMetrics().horizontalAdvance(txt) + 14
            bx = min(max(hx + 12, x0), self.width() - tw); by = max(2.0, hy - 26)
            p.setBrush(QBrush(QColor(18, 18, 28, 235))); p.setPen(QPen(QColor(255, 255, 255, 40), 1))
            p.drawRoundedRect(QRectF(bx, by, tw, 20), 5, 5)
            p.setPen(QPen(QColor("#ffffff"), 1)); p.drawText(QRectF(bx, by, tw, 20), Qt.AlignCenter, txt)

        self._paint_loop(p, y_top, y_bot)
        self._paint_navigator(p); p.end()

    def _paint_notes(self, p, x0, x1):
        """Piano-roll: keyboard gutter + note lanes + the take's waveform drawn AT ITS PITCH HEIGHT
        (riding up/down the grid, coloured by note), and the hand-placed note points on top."""
        y0, y1 = self._notes_plot(); lh = self._lane_h()
        dur = len(self.buf) / self.sr; beat_len = 60.0 / self.bpm
        ab = self._active_band()
        # note lanes: black-key shading (background)
        for m in range(self.note_lo, self.note_hi + 1):
            if (m % 12) in _BLACK_KEYS:
                p.fillRect(QRectF(x0, self._note_y(m) - lh / 2, x1 - x0, lh), QColor(0, 0, 0, 60))
        # the take's pitch drawn as a FILLED silhouette: each column filled from the BOTTOM up to the
        # note (so the TOP EDGE traces your singing and you can read the whole flow, not just spots).
        pr = self.takes[ab].get("pitch") if self.takes else None
        buf = self.takes[ab]["buf"] if self.takes else self.buf
        gpk = self.takes[ab]["gpeak"] if self.takes else (float(np.abs(buf).max()) + 1e-9)
        if pr and len(pr[0]) > 1 and len(buf) > 1:
            nc = int(min(1100, max(2, x1 - x0))); N = len(buf)
            cw = (x1 - x0) / nc + 1.0
            mid = np.full(nc, np.nan, np.float32); amp = np.zeros(nc, np.float32)
            for kk in range(nc):
                tf0 = self.view0 + (kk / nc) * self._span(); tf1 = self.view0 + ((kk + 1) / nc) * self._span()
                mm = self._pitch_at(pr, (tf0 + tf1) / 2)
                if mm is not None:
                    mid[kk] = mm
                a = int(tf0 * N); b = max(a + 1, int(tf1 * N)); amp[kk] = float(np.abs(buf[a:b]).max()) / gpk
            # AMPLITUDE decides WHERE to draw (a continuous run of sound = one vocalisation), PITCH
            # decides the height — interpolated across pYIN dropouts (the p/m consonants) so one breath
            # ("paaaaaummm") is ONE continuous fill; a real silence between notes still breaks it.
            w = max(1, nc // 120)
            sm = np.convolve(amp, np.ones(2 * w + 1, np.float32) / (2 * w + 1), mode="same") if nc >= 5 else amp
            sound = sm > 0.04
            fillmid = np.full(nc, np.nan, np.float32)
            kk = 0
            while kk < nc:
                if not sound[kk]:
                    kk += 1; continue
                j = kk
                while j < nc and sound[j]:
                    j += 1
                seg = np.arange(kk, j); gd = seg[np.isfinite(mid[seg])]
                if len(gd) >= 1:
                    fillmid[seg] = np.interp(seg, gd, mid[gd]).astype(np.float32)   # hold/ramp pitch across the run
                kk = j
            for kk in range(nc):
                if not np.isfinite(fillmid[kk]):
                    continue
                x = self._to_px_t(self.view0 + (kk / nc) * self._span()); yc = self._note_y(float(fillmid[kk]))
                col = self._pitch_color(float(fillmid[kk])); col.setAlpha(int(90 + 130 * min(1.0, amp[kk] * 2.0)))
                p.fillRect(QRectF(x, yc, cw, y1 - yc), col)        # fill down to the baseline
                edge = self._pitch_color(float(fillmid[kk]))       # bright top edge = the note
                p.setPen(QPen(edge, 1.6)); p.drawLine(QPointF(x, yc), QPointF(x + cw, yc))
        # horizontal lane separators + vertical tempo grid ON TOP of the fill (kept readable)
        for m in range(self.note_lo, self.note_hi + 1):
            top = self._note_y(m) - lh / 2
            p.setPen(QPen(QColor(255, 255, 255, 16), 1)); p.drawLine(int(x0), int(top), int(x1), int(top))
        if dur:
            sub = beat_len / 4.0; k = int((self.view0 * dur - self.grid_off) / sub) - 1
            while True:
                tf = (k * sub + self.grid_off) / dur
                if tf > self.view1:
                    break
                if self.view0 <= tf and tf >= 0:
                    x = self._to_px_t(tf)
                    a = 55 if (k % 16 == 0) else (30 if (k % 4 == 0) else 12)
                    p.setPen(QPen(QColor(255, 255, 255, a), 1)); p.drawLine(int(x), int(y0), int(x), int(y1))
                k += 1
        # placed note points (active track bright, others faint) — a short bar on the lane + a dot.
        # ONLY this soundwave's tracks: another take's notes belong to another wave, not this piano-roll.
        for ti, tr in enumerate(self.tracks):
            if not tr.get("visible", True) or self._track_band(tr) != ab:
                continue
            active = (ti == self.active)
            spts = sorted(tr.get("points") or [], key=lambda q: q["t"])
            # TIE LINES first (behind the note blocks): HELD = a horizontal bar at the left pitch
            # spanning to the next point; GLIDE = a sloped line connecting the two pitches.
            for k in range(len(spts) - 1):
                a, b = spts[k], spts[k + 1]
                if not a.get("tie"):
                    continue
                ax = self._to_px_t(a["t"]); ay = self._note_y(a.get("midi", DEF_MIDI))
                bx = self._to_px_t(b["t"]); by = self._note_y(b.get("midi", DEF_MIDI))
                if bx < x0 - 8 or ax > x1 + 8:
                    continue
                col = self._pitch_color(a.get("midi", DEF_MIDI))
                col.setAlpha(230 if active else 110)
                if a.get("glide"):
                    p.setPen(QPen(col, 3.2 if active else 2)); p.drawLine(QPointF(ax, ay), QPointF(bx, by))
                else:                                       # held: a fat horizontal bar (piano-roll note)
                    p.setPen(Qt.NoPen); p.setBrush(QBrush(col))
                    p.drawRoundedRect(QRectF(ax, ay - lh * 0.22, bx - ax, lh * 0.44), 3, 3)
            for nt in spts:
                mm = nt.get("midi", DEF_MIDI)
                x = self._to_px_t(nt["t"]); yc = self._note_y(mm)
                if not (x0 - 8 <= x <= x1 + 8):
                    continue
                col = self._pitch_color(mm)
                bar = col if active else QColor(col.red(), col.green(), col.blue(), 110)
                p.setPen(Qt.NoPen); p.setBrush(QBrush(bar))
                p.drawRoundedRect(QRectF(x - 9, yc - lh * 0.34, 18, lh * 0.68), 3, 3)   # note block on its lane
                p.setBrush(QBrush(QColor("#ffffff") if active else QColor(255, 255, 255, 150)))
                p.setPen(QPen(QColor("#0c0c14"), 1.4) if active else Qt.NoPen)
                p.drawEllipse(QPointF(x, yc), DOT_R, DOT_R)
        # keyboard gutter (drawn last, left of the plot)
        for m in range(self.note_lo, self.note_hi + 1):
            yc = self._note_y(m); top = yc - lh / 2
            if (m % 12) in _BLACK_KEYS:
                p.fillRect(QRectF(0, top + lh * 0.15, KB * 0.55, lh * 0.7), QColor("#15151c"))
            else:
                p.fillRect(QRectF(0, top, KB, lh), QColor("#e6e6ec"))
                p.setPen(QPen(QColor("#aeaeb8"), 1)); p.drawLine(0, int(top), int(KB), int(top))
                if m % 12 == 0:
                    p.setPen(QPen(QColor("#30303a"), 1)); p.setFont(theme.sans(8, 700))
                    p.drawText(QRectF(3, yc - 6, KB - 6, 12), Qt.AlignLeft | Qt.AlignVCenter, groove.note_name(m))
        # playhead
        if self.playhead is not None and self.view0 <= self.playhead <= self.view1:
            x = self._to_px_t(self.playhead)
            p.setPen(QPen(theme.REC, 2)); p.drawLine(QPointF(x, y0), QPointF(x, y1))
        if self.takes:
            self._draw_del_x(p, self._notes_del_rect())    # ✕ delete this soundwave (+ its tracks)
        # take picker: which soundwave's notes am I looking at? (only worth showing with >1 wave)
        if self._take_bar():
            for i, tk in enumerate(self.takes):
                r = self._take_chip_rect(i)
                if r.right() > x1:
                    break
                sel = (i == ab); col = tk["color"]
                p.setBrush(QBrush(QColor(col.red(), col.green(), col.blue(), 30) if sel else QColor(18, 18, 26, 200)))
                p.setPen(QPen(col if sel else QColor(255, 255, 255, 30), 1.4 if sel else 1))
                p.drawRoundedRect(r, 5, 5)
                cr = QRectF(r.left() + 6, r.center().y() - 6.5, 13, 13)
                self._draw_take_chk(p, cr, col, sel)
                p.setFont(theme.sans(9, 700 if sel else 600))
                p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 235 if sel else 150), 1))
                p.drawText(QRectF(cr.right() + 5, r.top(), r.width() - 26, r.height()),
                           Qt.AlignLeft | Qt.AlignVCenter, tk["name"])
        # hint / hover
        if self._first_track_on(ab) is None:
            name = self.takes[ab]["name"] if self.takes else "this soundwave"
            p.setPen(QPen(QColor("#5a5a6a"), 1)); p.setFont(theme.sans(12))
            p.drawText(QRectF(x0, y0, x1 - x0, 24), Qt.AlignHCenter | Qt.AlignTop,
                       f"Add a track → it lands on “{name}” → then click the wave to place notes")
        elif not (self.tracks[max(0, self.active)].get("points")):
            p.setPen(QPen(QColor("#5a5a6a"), 1)); p.setFont(theme.sans(12))
            p.drawText(QRectF(x0, y0, x1 - x0, 24), Qt.AlignHCenter | Qt.AlignTop,
                       "Trace the coloured wave — click to place notes")
        if self._hover is not None:
            hx, hy, txt = self._hover
            p.setFont(theme.sans(11, 700)); tw = p.fontMetrics().horizontalAdvance(txt) + 14
            bx = min(max(hx + 12, x0), self.width() - tw); by = max(2.0, hy - 26)
            p.setBrush(QBrush(QColor(18, 18, 28, 235))); p.setPen(QPen(QColor(255, 255, 255, 40), 1))
            p.drawRoundedRect(QRectF(bx, by, tw, 20), 5, 5)
            p.setPen(QPen(QColor("#ffffff"), 1)); p.drawText(QRectF(bx, by, tw, 20), Qt.AlignCenter, txt)

    def _mm_rect(self):
        w, h = self.width(), self.height(); pad = 12; mw = min(300, w * 0.34)
        return QRectF(w - mw - pad, h - MM_H - pad, mw, MM_H)

    def _paint_navigator(self, p):
        r = self._mm_rect()
        p.setPen(QPen(QColor("#2a2a36"), 1)); p.setBrush(QBrush(QColor(10, 10, 16, 235))); p.drawRoundedRect(r, 6, 6)
        peaks = self.takes[0]["peaks"]; gpk = self.takes[0]["gpeak"]
        n = len(peaks); mid = r.center().y(); hh = r.height() * 0.42
        p.setPen(QPen(QColor(255, 93, 93, 120), 1))
        for i in range(n):
            x = r.left() + (i / (n - 1)) * r.width(); a = float(peaks[i]) / gpk * hh
            p.drawLine(QPointF(x, mid - a), QPointF(x, mid + a))
        vx0 = r.left() + self.view0 * r.width(); vx1 = r.left() + self.view1 * r.width()
        vp = QRectF(vx0, r.top() + 1, max(3.0, vx1 - vx0), r.height() - 2)
        p.setPen(QPen(theme.ACCENT_CY, 1.4)); p.setBrush(QBrush(QColor(61, 214, 255, 45))); p.drawRoundedRect(vp, 3, 3)

    # --- zoom / pan ---
    def zoom_at(self, factor, fx=0.5):
        anchor = self.view0 + fx * self._span()
        span = min(1.0, max(MIN_SPAN, self._span() * factor))
        self.view0 = anchor - fx * span; self.view1 = self.view0 + span
        self._clamp_view(); self.update()

    def wheelEvent(self, ev):
        d = ev.angleDelta().y() or ev.pixelDelta().y()      # touchpads use pixelDelta
        if d == 0:
            return
        if self.mode == "notes" and not (ev.modifiers() & Qt.ControlModifier):
            self._scroll_notes(2 if d > 0 else -2)          # NOTES: plain scroll = up/down the piano
            return
        x0, x1 = self._xspan()
        fx = min(1.0, max(0.0, (ev.position().x() - x0) / max(1.0, (x1 - x0))))
        self.zoom_at(0.82 if d > 0 else 1 / 0.82, fx)       # plain scroll zooms (Ctrl+scroll in notes)

    def _clamp_view(self):
        span = min(1.0, self.view1 - self.view0)
        if self.view0 < 0:
            self.view0, self.view1 = 0.0, span
        if self.view1 > 1:
            self.view1, self.view0 = 1.0, 1.0 - span
        self.view0 = max(0.0, self.view0); self.view1 = min(1.0, self.view1)

    def _center_on(self, cf):
        span = self._span(); self.view0 = cf - span / 2; self.view1 = self.view0 + span; self._clamp_view()

    # --- mouse (pen tool with Bézier handles) ---
    def _hit(self, pos):
        # Only the ACTIVE track is editable on the canvas — you pick a track from the list first,
        # then draw/grab ITS dots. Other tracks' dots are inert here (no accidental cross-grab).
        ti = self.active
        if not (0 <= ti < len(self.tracks)) or not self.tracks[ti]["visible"]:
            return None
        bi = self._track_band(self.tracks[ti])     # hit-test in the row it's PAINTED in
        best, bd = None, HIT_R ** 2
        for pi, pt in enumerate(self.tracks[ti]["points"]):
            if not (self.view0 - 1e-3 <= pt["t"] <= self.view1 + 1e-3):
                continue
            q = self._apx(pt, bi); d = (q.x() - pos.x()) ** 2 + (q.y() - pos.y()) ** 2
            if d < bd:
                bd, best = d, (ti, pi)
        return best

    def _hit_handle(self, pos):
        if not (0 <= self.active < len(self.tracks)):
            return None
        bi = self._track_band(self.tracks[self.active])     # same row it's painted in
        for pi, pt in enumerate(self.tracks[self.active]["points"]):
            if not (pt["hx"] or pt["hy"]):
                continue
            for side, sx in (("out", 1), ("in", -1)):
                q = self._to_px(pt["t"] + sx * pt["hx"], pt["v"] + sx * pt["hy"], bi)
                if (q.x() - pos.x()) ** 2 + (q.y() - pos.y()) ** 2 < HIT_R ** 2:
                    return ("handle_" + side, self.active, pi)
        return None

    # --- Grid tool: LEFT-drag = stretch/shrink tempo · RIGHT-drag = move the grid sideways (phase) ---
    def _grid_press(self, pos, stretch=False):
        dur = len(self.buf) / self.sr; beat_len = 60.0 / self.bpm
        t, _ = self._from_px(pos.x(), pos.y(), 0)
        if stretch:                                           # left-drag: grab a beat and scale tempo
            beat = (t * dur - self.grid_off) / beat_len
            self._grid_grab = beat if beat > 0.25 else None
            self._grid_pan = None
        else:                                                 # plain drag: slide the whole grid sideways
            self._grid_grab = None
            self._grid_pan = (pos.x(), self.grid_off)

    def _grid_move(self, pos):
        dur = len(self.buf) / self.sr; beat_len = 60.0 / self.bpm
        if self._grid_grab:                                   # STRETCH (tempo)
            t, _ = self._from_px(pos.x(), pos.y(), 0)
            time = max(1e-3, t * dur - self.grid_off)
            bpm = max(40.0, min(300.0, 60.0 / (time / self._grid_grab)))
            self.bpm = bpm; self.update()
            if self._emit_clock.elapsed() > 80:
                self._emit_clock.restart(); self.grid_scaled.emit(float(bpm))
        elif self._grid_pan is not None:                      # MOVE (phase offset)
            x0, off0 = self._grid_pan; xa, xb = self._xspan()
            dt = (pos.x() - x0) / max(1.0, (xb - xa)) * self._span() * dur
            off = off0 + dt
            off = ((off % beat_len) + beat_len) % beat_len    # one bar-beat of range is enough (grid repeats)
            self.grid_off = off; self.update()
            if self._emit_clock.elapsed() > 80:
                self._emit_clock.restart(); self.grid_moved.emit()

    # --- Fit tool: pick A, pick B, then drag the B edge to stretch/shrink that slice of audio ---
    def _fit_press(self, ev, pos):
        if ev.button() != Qt.LeftButton:
            if ev.button() == Qt.RightButton:                 # right-click clears the selection
                self.fit_a = self.fit_b = self._fit_b0 = None; self.update()
            return
        t, _ = self._from_px(pos.x(), pos.y(), self._active_band())
        if self.fit_b is not None:                            # a region exists → grab its B edge, else restart
            xb = self._to_px(self.fit_b, 0, 0).x()
            if abs(pos.x() - xb) <= HIT_R:
                self._fit_drag = True; return
            self.fit_a = t; self.fit_b = self._fit_b0 = None; self.update(); return
        if self.fit_a is None:
            self.fit_a = t; self._fit_hover = t
        else:
            self.fit_b = max(self.fit_a + 0.002, t); self._fit_b0 = self.fit_b
        self.update()

    def _fit_move(self, pos):
        t, _ = self._from_px(pos.x(), pos.y(), self._active_band())
        if self._fit_drag:
            self.fit_b = max(self.fit_a + 0.002, min(1.0, t)); self.update()
        elif self.fit_a is not None and self.fit_b is None:
            self._fit_hover = t; self.update()

    def _fit_release(self):
        if self._fit_drag:
            self._fit_drag = False
            if self._fit_b0 and abs(self.fit_b - self._fit_b0) > 1e-4:
                self.fit_applied.emit(float(self.fit_a), float(self._fit_b0), float(self.fit_b))
            self.fit_a = self.fit_b = self._fit_b0 = None      # applied → clear (board rebuilds)

    # --- Loop tool: drag to mark THIS soundwave's loop region (the sample a pad plays) ---
    def _sel_tk(self):
        ab = self._active_band()
        return self.takes[ab] if 0 <= ab < len(self.takes) else None

    def _paint_loop(self, p, y0, y1):
        """Shade the SELECTED soundwave's loop region (the sample a pad plays) + dim outside it."""
        tk = self._sel_tk()
        if not tk or tk.get("loop_a") is None or tk.get("loop_b") is None:
            return
        a, b = float(tk["loop_a"]), float(tk["loop_b"])
        if b <= a:
            return
        x0, x1 = self._xspan()
        xa = max(x0, min(x1, self._to_px_t(a))); xb = max(x0, min(x1, self._to_px_t(b)))
        p.fillRect(QRectF(x0, y0, xa - x0, y1 - y0), QColor(0, 0, 0, 96))    # dim before
        p.fillRect(QRectF(xb, y0, x1 - xb, y1 - y0), QColor(0, 0, 0, 96))    # dim after
        p.fillRect(QRectF(xa, y0, xb - xa, y1 - y0), QColor(61, 214, 255, 26))
        p.setPen(QPen(theme.ACCENT_CY, 2))
        p.drawLine(QPointF(xa, y0), QPointF(xa, y1)); p.drawLine(QPointF(xb, y0), QPointF(xb, y1))
        p.setFont(theme.sans(9, 700)); p.setPen(QPen(theme.ACCENT_CY, 1))
        p.drawText(QRectF(xa, y0 + 1, xb - xa, 14), Qt.AlignCenter, "⟳ LOOP")

    def _loop_press(self, ev, pos):
        if ev.button() == Qt.RightButton:                     # right-click clears the loop
            tk = self._sel_tk()
            if tk is not None:
                tk["loop_a"] = tk["loop_b"] = None
                self.loop_changed.emit(self._active_band())
            self.update(); return
        self._loop_drag = self._t_at_x(pos.x())
        tk = self._sel_tk()
        if tk is not None:
            tk["loop_a"] = tk["loop_b"] = self._loop_drag
        self.update()

    def _loop_move(self, pos):
        if self._loop_drag is None:
            return
        tk = self._sel_tk()
        if tk is not None:
            tk["loop_b"] = self._t_at_x(pos.x())
        self.update()

    def _loop_release(self):
        if self._loop_drag is None:
            return
        self._loop_drag = None
        tk = self._sel_tk()
        if tk is not None and tk.get("loop_a") is not None:
            a, b = tk["loop_a"], tk.get("loop_b", tk["loop_a"])
            a, b = min(a, b), max(a, b)
            if b - a < 0.01:                                  # a tiny drag = clear (loop the whole take)
                tk["loop_a"] = tk["loop_b"] = None
            else:
                tk["loop_a"], tk["loop_b"] = a, b
        self.loop_changed.emit(self._active_band())
        self.update()

    def mousePressEvent(self, ev):
        pos = ev.position()
        if ev.button() == Qt.LeftButton:
            di = self._hit_take_del(pos)
            if di is not None:
                self.delete_take.emit(di); return
            sm = self._hit_take_sm(pos)           # Solo / Mute the whole soundwave
            if sm is not None:
                self.take_flag.emit(sm[0], sm[1]); return
            si = self._hit_take_sel(pos)          # ticked a soundwave → work on THAT one
            if si is not None:
                self.set_sel_take(si); return
        if self._mm_rect().contains(pos):
            if ev.button() == Qt.LeftButton:
                self._pan_mm = True; r = self._mm_rect(); self._center_on((pos.x() - r.left()) / r.width()); self.update()
            return
        if self.tool == "loop":                    # set the sample loop region (works in both views)
            self._loop_press(ev, pos); return
        if self.mode == "notes":
            self._notes_press(ev, pos); return
        if self.tool == "grid":
            if ev.button() == Qt.LeftButton:
                self._grid_press(pos, stretch=True)        # left-drag = stretch/shrink tempo
            elif ev.button() == Qt.RightButton:
                self._grid_press(pos, stretch=False)       # right-drag = move the grid sideways
            return
        if self.tool == "fit":
            self._fit_press(ev, pos)
            return
        if ev.button() == Qt.RightButton:
            h = self._hit(pos)
            if h:
                self.set_active(h[0]); self.tracks[h[0]]["points"].pop(h[1]); self.update()
                self.edited.emit(h[0])
            return
        if ev.button() != Qt.LeftButton:
            return
        hh = self._hit_handle(pos)                     # grab a curve handle first
        if hh:
            self._drag = hh; self.update(); return
        h = self._hit(pos)                             # then an anchor
        if h:
            self._drag = ("anchor", h[0], h[1]); self.set_active(h[0])
            self._select_point(self.tracks[h[0]]["points"][h[1]].get("id"))    # link to the Studio beat
            self.update(); return
        bi = self._band_at(pos.y())          # clicked another soundwave's row → go there, don't
        if bi is not None and bi != self._active_band():   # silently drop the point on THIS one
            self.set_sel_take(bi); return
        if not (0 <= self.active < len(self.tracks)):
            return
        t, v = self._from_px(pos.x(), pos.y(), self._active_band()); pts = self.tracks[self.active]["points"]
        i = 0
        while i < len(pts) and pts[i]["t"] < t:
            i += 1
        pts.insert(i, {"id": uid("p"), "t": t, "v": v, "midi": DEF_MIDI, "hx": 0.0, "hy": 0.0})
        self._drag = ("handle_out", self.active, i)    # pen tool: drag now pulls out a curve handle
        self._select_point(pts[i]["id"]); self.update()

    def _update_hover(self, pos):
        """Note under the cursor → self._hover, for the ribbon label. Only repaints on a change."""
        note = None
        if self._drag is None and not self._pan_mm:
            x0, x1 = self._xspan()
            if x0 <= pos.x() <= x1:
                i = next((k for k in range(len(self.takes))
                          if self._band(k)[0] <= pos.y() <= self._band(k)[0] + self._band(k)[1]), 0)
                if i < len(self.takes):
                    tf = self.view0 + (pos.x() - x0) / max(1.0, (x1 - x0)) * self._span()
                    m = self._pitch_at(self.takes[i].get("pitch"), tf)
                    if m is not None:
                        note = (pos.x(), pos.y(), groove.note_name(m))
        prev = self._hover
        self._hover = note
        if (note is None) != (prev is None) or (note and prev and note[2] != prev[2]):
            self.update()
        elif note is not None:
            self._hover = note; self.update()      # label follows the cursor

    def leaveEvent(self, _):
        if self._hover is not None:
            self._hover = None; self.update()

    # --- notes-mode (piano-roll) interaction ---
    def _notes_press(self, ev, pos):
        if not self.tracks:
            return
        ab = self._active_band()                           # notes always belong to the SELECTED wave
        if not (0 <= self.active < len(self.tracks)) or self._track_band(self.tracks[self.active]) != ab:
            i = self._first_track_on(ab)                   # no track picked (or one from another wave)
            if i is None:
                return                                     # this wave has no track yet → nothing to draw on
            self.set_active(i)
        x0, _ = self._xspan()
        if pos.x() < x0:                                   # clicked a piano KEY → audition the note
            if ev.button() == Qt.LeftButton:
                m = int(round(self._midi_at_y(pos.y())))
                if self.note_lo <= m <= self.note_hi:
                    self.key_pressed.emit(m)
            return
        pts = self.tracks[self.active].setdefault("points", [])
        hit = self._notes_hit(pos)
        if ev.button() == Qt.RightButton:                  # right-click a point → delete; a LINE → cut it
            if hit is not None:
                pts.pop(hit); self.update(); self.edited.emit(self.active)
            else:
                seg = self._hit_segment(pos)               # right-click a line → remove just that line
                if seg is not None:
                    seg["tie"] = False; self.update(); self.edited.emit(self.active)
            return
        if ev.button() != Qt.LeftButton:
            return
        if hit is not None:                                # grab an existing point to re-pitch it
            self._note_drag = (self.active, hit)
            self._select_point(pts[hit].get("id")); self.update(); return
        # new point: it's a shared beat — carries a pitch (set here) AND a volume (edit in the Volume tab)
        m = max(self.note_lo, min(self.note_hi, int(round(self._midi_at_y(pos.y())))))
        t = self._snap_t(self._t_at_x(pos.x()))
        i = 0
        while i < len(pts) and pts[i]["t"] < t:
            i += 1
        # a shared beat: pitch set here, volume in the Volume tab — freely movable in either tab
        pts.insert(i, {"id": uid("p"), "t": t, "v": 0.8, "midi": m, "hx": 0.0, "hy": 0.0,
                       "tie": False, "glide": False})
        # PITCHED instruments auto-connect successive clicks: tie the previous point to this one
        # (a melody line). Plain click = HELD (step); drag while placing = GLIDE (set in _notes_move).
        self._tie_left = None
        if i > 0 and _is_pitched(self.tracks[self.active]):
            prev = pts[i - 1]; prev["tie"] = True; prev["glide"] = False
            self._tie_left = prev
        self._place_pos = pos
        self._note_drag = (self.active, i); self._select_point(pts[i]["id"])
        self.update(); self.edited.emit(self.active)

    def _notes_move(self, ev, pos):
        if self._pan_mm:
            r = self._mm_rect(); self._center_on((pos.x() - r.left()) / r.width()); self.update(); return
        self._notes_hover(pos)
        if self._note_drag is None:
            return
        ti, ni = self._note_drag; pts = self.tracks[ti].get("points") or []
        if ni >= len(pts):
            self._note_drag = None; return
        nt = pts[ni]
        nt["t"] = self._snap_t(self._t_at_x(pos.x()))
        nt["midi"] = max(self.note_lo, min(self.note_hi, int(round(self._midi_at_y(pos.y())))))
        # dragged while placing a tied note → that segment GLIDES (a pitch slide, not a step)
        if self._tie_left is not None and self._place_pos is not None:
            if (pos - self._place_pos).manhattanLength() > 6:
                self._tie_left["glide"] = True
        self.update()
        if self._emit_clock.elapsed() > 80:
            self._emit_clock.restart(); self.edited.emit(ti)

    def _notes_hover(self, pos):
        """Show the note name for the lane under the cursor (the note you'd place)."""
        x0, x1 = self._xspan(); note = None
        if self._note_drag is None and not self._pan_mm and x0 <= pos.x() <= x1:
            m = int(round(self._midi_at_y(pos.y())))
            if self.note_lo <= m <= self.note_hi:
                note = (pos.x(), pos.y(), groove.note_name(m))
        self._hover = note
        self.update()

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self.tool == "loop":
            self._loop_move(pos); return
        if self.mode == "notes":
            self._notes_move(ev, pos); return
        self._update_hover(pos)
        if self._pan_mm:
            r = self._mm_rect(); self._center_on((pos.x() - r.left()) / r.width()); self.update(); return
        if self.tool == "grid":
            if ev.buttons() & (Qt.LeftButton | Qt.RightButton):
                self._grid_move(pos)
            return
        if self.tool == "fit":
            self._fit_move(pos)
            return
        if self.tool == "loop":
            self._loop_move(pos)
            return
        if self._drag is None:
            return
        mode, ti, pi = self._drag; pts = self.tracks[ti]["points"]; pt = pts[pi]
        t, v = self._from_px(pos.x(), pos.y(), self._track_band(self.tracks[ti]))
        if mode == "anchor":
            lo = pts[pi - 1]["t"] + 1e-4 if pi > 0 else 0.0
            hi = pts[pi + 1]["t"] - 1e-4 if pi < len(pts) - 1 else 1.0
            pt["t"] = min(max(t, lo), hi); pt["v"] = v   # free to move in time AND volume here
            pt.pop("beat", None)                         # moving on the board un-locks the grid beat
        else:                                          # symmetric handle (out / in)
            hx, hy = t - pt["t"], v - pt["v"]
            if mode == "handle_in":
                hx, hy = -hx, -hy
            pt["hx"] = max(-0.35, min(0.35, hx)); pt["hy"] = max(-1.0, min(1.0, hy))
        self.update()
        if self._emit_clock.elapsed() > 80:           # throttled live sync while dragging
            self._emit_clock.restart(); self.edited.emit(ti)

    def mouseReleaseEvent(self, _):
        if self.tool == "loop":
            self._loop_release(); self._pan_mm = False; return
        if self.mode == "notes":
            if self._note_drag is not None:
                ti = self._note_drag[0]; self._note_drag = None
                pts = self.tracks[ti].get("points") or []; pts.sort(key=lambda q: q["t"])
                self.edited.emit(ti)
            self._tie_left = None; self._place_pos = None
            self._pan_mm = False
            return
        if self.tool == "grid":
            if self._grid_grab:
                self._grid_grab = None
                self.grid_scaled.emit(float(self.bpm))     # authoritative final tempo (+ undo)
            if self._grid_pan is not None:
                self._grid_pan = None
                self.grid_moved.emit()                     # authoritative final offset (re-time + undo)
            self._pan_mm = False
            return
        if self.tool == "fit":
            self._fit_release()
            self._pan_mm = False
            return
        gesture = self._drag is not None and not self._pan_mm
        ti = self._drag[1] if gesture else -1
        self._drag = None; self._pan_mm = False
        if gesture:
            self.edited.emit(ti)                       # authoritative end-of-gesture sync


# ---------------------------------------------------------------- a track row
_COMBO_CSS = ("QComboBox{background:#1c1c26;border:1px solid #3a3a48;border-radius:8px;color:#fff;"
              "padding:3px 10px;}QComboBox QAbstractItemView{background:#1c1c26;color:#fff;"
              "selection-background-color:#3a3a48;}")
_PLAY_CSS = ("QPushButton{background:#173a2a;border:1px solid #2f7d55;border-radius:8px;color:#6ef0a8;"
             "font-size:13px;}QPushButton:hover{background:#1e5138;}")
_STOP_CSS = ("QPushButton{background:#5a1e1e;border:1px solid #ff5d5d;border-radius:8px;color:#ffb4b4;"
             "font-size:13px;}QPushButton:hover{background:#6e2626;}")
_TOOL_ON = ("QPushButton{background:#7c5cff;border:1px solid #9b82ff;border-radius:8px;color:#fff;"
            "padding:0 10px;font-size:12px;font-weight:600;}")
_TOOL_OFF = ("QPushButton{background:#16161e;border:1px solid #2a2a36;border-radius:8px;color:#c0c0cc;"
             "padding:0 10px;font-size:12px;}QPushButton:hover{background:#1e1e28;}")


_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTE_RANGE = list(range(36, 85))     # C2 … C6


def note_name(m):
    return f"{_NOTE_NAMES[m % 12]}{m // 12 - 1}"


def seg_ctrls(pts, i):
    """(t,v) Bézier control points for the segment pts[i]→pts[i+1]. Straight by default (controls sit
    on the anchors); a hand-pulled handle (hx/hy ≠ 0) bends that end into a curve. So: one click =
    straight point, click-and-drag = curved point."""
    a, b = pts[i], pts[i + 1]
    c0 = (a["t"] + a["hx"], a["v"] + a["hy"])
    c1 = (b["t"] - b["hx"], b["v"] - b["hy"])
    return c0, c1


def _stop_css_from(css):
    """A red 'stop' stylesheet that keeps the button's EXACT geometry (padding / font-weight) — only
    the colours change, so a button never changes shape when it flips to ■."""
    return (css.replace("#173a2a", "#5a1e1e").replace("#2f7d55", "#ff5d5d")
               .replace("#6ef0a8", "#ffb4b4").replace("#1e5138", "#6e2626"))


def _mark_play(btn, text, css=_PLAY_CSS):
    """Tag a button so the board can flip every play button to ■ Stop and back in one call."""
    btn._play_text = text; btn._play_css = css; btn._stop_css = _stop_css_from(css)
    return btn


def _flip_play(btn, playing):
    # Keep the button's exact shape/label — swap only the ▶ glyph for ■ and the colours (same padding).
    if playing:
        btn.setText(btn._play_text.replace("▶", "■")); btn.setStyleSheet(btn._stop_css)
    else:
        btn.setText(btn._play_text); btn.setStyleSheet(btn._play_css)


class TrackRow(QFrame):
    activated = Signal(object)
    changed = Signal()
    preview = Signal(object)                 # ▶ play what's DRAWN for this track
    preview_sound = Signal(str, object, object)   # ▶ play one sound (preset, params, button) — Base/Morph
    delete = Signal(object)
    flag = Signal(object, str)               # per-track control: (track, "solo"|"mute"|"volume"|"notes")
    record = Signal(object)                  # ● record a guide into THIS track's soundwave
    duplicate = Signal(object)               # ⧉ duplicate this track (asks: soundwave only / full)
    add_variation = Signal(object)           # ＋ add a variation (alternate pattern) to this track
    select_variation = Signal(object, int)   # pick which variation is active (track, index)

    def __init__(self, track, items):
        super().__init__()
        self.track = track; self.items = items; self._play_widgets = []; self._sound_btns = {}
        track.setdefault("params", default_params())
        track.setdefault("params_b", default_params())
        self._active = False
        self._on_take = True        # False = belongs to a soundwave you're not editing → dimmed
        self._refresh_style(active=False)
        lay = QVBoxLayout(self); lay.setContentsMargins(10, 8, 10, 8); lay.setSpacing(6)

        top = QHBoxLayout(); top.setSpacing(8)
        self.swatch = QLabel(); self.swatch.setFixedSize(14, 14)
        self.swatch.setStyleSheet(f"background:{track['color'].name()};border-radius:4px;")
        self.name = QLineEdit(track["name"])
        self.name.setStyleSheet("QLineEdit{background:transparent;border:none;color:#e2e2ea;font-size:13px;font-weight:600;}")
        self.name.textChanged.connect(self._on_name)
        # per-track controls (like the Studio header): Record · Duplicate · Solo · Mute · Volume/Notes
        self.b_rec = QPushButton("●"); self.b_rec.setToolTip("Record a guide into this track's soundwave")
        self.b_dup = QPushButton("⧉"); self.b_dup.setToolTip("Duplicate this track (soundwave only / full)")
        self.b_solo = QPushButton("S"); self.b_mute = QPushButton("M"); self.b_vn = QPushButton("♪")
        self.b_solo.setToolTip("Solo this track"); self.b_mute.setToolTip("Mute this track")
        self.b_vn.setToolTip("This track's view: Volume ▁ / Notes ♪")
        self.b_rec.clicked.connect(lambda: self.record.emit(self.track))
        self.b_dup.clicked.connect(lambda: self.duplicate.emit(self.track))
        self.b_solo.clicked.connect(lambda: self.flag.emit(self.track, "solo"))
        self.b_mute.clicked.connect(lambda: self.flag.emit(self.track, "mute"))
        self.b_vn.clicked.connect(self._toggle_vn)
        self.eye = QPushButton("👁"); self.eye.setToolTip("Show / hide"); self.eye.clicked.connect(self._toggle_vis)
        self.b_del = QPushButton("✕"); self.b_del.setToolTip("Delete track")
        self.b_del.clicked.connect(lambda: self.delete.emit(self.track))
        for b in (self.b_rec, self.b_dup, self.b_solo, self.b_mute, self.b_vn, self.eye, self.b_del):
            b.setFixedSize(25, 25); b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("QPushButton{background:#16161e;border:1px solid #2a2a36;border-radius:6px;color:#c0c0cc;font-size:12px;}QPushButton:hover{background:#1e1e28;}")
        self.b_rec.setStyleSheet("QPushButton{background:rgba(255,93,93,0.16);border:1px solid #8a2a2a;border-radius:6px;color:#ff8a8a;font-size:12px;}QPushButton:hover{background:rgba(255,93,93,0.28);}")
        top.addWidget(self.swatch); top.addWidget(self.name, 1)
        top.addWidget(self.b_rec); top.addWidget(self.b_dup)
        top.addWidget(self.b_solo); top.addWidget(self.b_mute); top.addWidget(self.b_vn)
        top.addWidget(self.eye); top.addWidget(self.b_del)
        lay.addLayout(top)
        self.refresh_flags()

        # TOP-LEVEL group selector: Original · Hum · Synth · Instrument
        grp = QHBoxLayout(); grp.setSpacing(4)
        self._grp_btns = {}
        for g in GROUPS:
            gb = QPushButton(g); gb.setCursor(Qt.PointingHandCursor); gb.setFixedHeight(26)
            gb.setFont(theme.sans(10, 600))
            gb.clicked.connect(lambda _=False, gg=g: self._on_group(gg))
            self._grp_btns[g] = gb; grp.addWidget(gb)
        lay.addLayout(grp)

        bot = QHBoxLayout(); bot.setSpacing(8)
        self.combo = QComboBox(); self.combo.setFont(theme.sans(11)); self.combo.setMinimumHeight(30)
        self.combo.setStyleSheet(_COMBO_CSS)
        self._combo_items = []
        self.combo.currentIndexChanged.connect(self._on_instrument)
        self.b_prev = QPushButton("▶"); self.b_prev.setFixedSize(34, 30); self.b_prev.setCursor(Qt.PointingHandCursor)
        self.b_prev.setToolTip("Preview what you've drawn for this track")
        self.b_prev.setStyleSheet(_PLAY_CSS)
        self.b_prev.clicked.connect(lambda: self.preview.emit(self.track))
        _mark_play(self.b_prev, "▶"); self._play_widgets.append(self.b_prev)
        bot.addWidget(self.combo, 1); bot.addWidget(self.b_prev)
        lay.addLayout(bot)

        # SYNTH DESIGNER — Base and Modulator, each with its OWN waveform + knobs + a play button.
        # The drawn line morphs Base → Modulator (and follows volume), so both need full control.
        self.syn = QWidget(); syl = QVBoxLayout(self.syn); syl.setContentsMargins(0, 2, 0, 0); syl.setSpacing(4)
        self.combo_base = self._sound_head(syl, "BASE ▁ low", "params",
                                           track["sound"] if track["sound"] in WAVES else WAVES[0], self._on_base)
        syl.addWidget(self._divider())
        self.combo_mod = self._sound_head(syl, "MOD ▔ high", "params_b",
                                          track.get("sound_b") if track.get("sound_b") in WAVES else WAVES[1], self._on_mod)
        # siren pitch range — the line glides from the low note (bottom) to the high note (top)
        prow = QHBoxLayout(); prow.setSpacing(6)
        prow.addWidget(self._tag("Pitch"))
        self.combo_lo = QComboBox(); self.combo_hi = QComboBox()
        for c in (self.combo_lo, self.combo_hi):
            c.setFont(theme.sans(10)); c.setMinimumHeight(26); c.setStyleSheet(_COMBO_CSS)
            for m in NOTE_RANGE:
                c.addItem(note_name(m), m)
        self.combo_lo.setCurrentIndex(NOTE_RANGE.index(int(track.get("lo_note", 48))))
        self.combo_hi.setCurrentIndex(NOTE_RANGE.index(int(track.get("hi_note", 72))))
        self.combo_lo.currentIndexChanged.connect(lambda: self._on_note("lo_note", self.combo_lo))
        self.combo_hi.currentIndexChanged.connect(lambda: self._on_note("hi_note", self.combo_hi))
        prow.addWidget(self._tag("low")); prow.addWidget(self.combo_lo, 1)
        prow.addWidget(self._tag("→ high")); prow.addWidget(self.combo_hi, 1)
        syl.addLayout(prow)
        lay.addWidget(self.syn)
        self.syn.setVisible(track["kind"] == "synth")

        # FX RACK — unfolds under the picker when the instrument is "Original": transform your OWN
        # recorded sound (drive, massive bass, reverb, …). One amount slider per effect, 0 = off.
        track.setdefault("fx", default_fx())
        self.fxpanel = QWidget(); fxl = QVBoxLayout(self.fxpanel)
        fxl.setContentsMargins(0, 2, 0, 0); fxl.setSpacing(3)
        fxhead = QLabel("FX RACK — your sound, modified")
        fxhead.setStyleSheet("color:#6ef0a8;font-size:10px;font-weight:700;")
        fxl.addWidget(fxhead)
        for key, label, mn, mx, dflt, scale in FX_KNOBS:
            fxl.addLayout(self._knob_row(track["fx"], key, label, mn, mx, dflt, scale))
        lay.addWidget(self.fxpanel)
        self.fxpanel.setVisible(track["kind"] == "original")

        # HUM KNOBS — vowel voice controls (brightness / breath / vibrato / …), shown for a Hum track.
        self.humpanel = QWidget(); huml = QVBoxLayout(self.humpanel)
        huml.setContentsMargins(0, 2, 0, 0); huml.setSpacing(3)
        hhead = QLabel("HUM — sung vowel"); hhead.setStyleSheet("color:#c0a8ff;font-size:10px;font-weight:700;")
        huml.addWidget(hhead)
        track.setdefault("hum_params", default_hum_params())
        for key, label, mn, mx, dflt, scale in HUM_KNOBS:
            huml.addLayout(self._knob_row(track["hum_params"], key, label, mn, mx, dflt, scale))
        lay.addWidget(self.humpanel)
        self.humpanel.setVisible(track["kind"] == "hum")

        # MIX — 8 universal knobs (Volume/High/Mid/Low/Bal/Reverb/Gain/Comp) mapped 1:1 to the APC
        # knobs. Shown only when the track is SELECTED, so the card stays compact otherwise.
        track.setdefault("mix", default_mix())
        self.mixpanel = QWidget(); mxl = QVBoxLayout(self.mixpanel)
        mxl.setContentsMargins(0, 2, 0, 0); mxl.setSpacing(3)
        mhead = QLabel("MIX — knobs 1–8 on your keyboard"); mhead.setStyleSheet("color:#6ecbff;font-size:10px;font-weight:700;")
        mxl.addWidget(mhead)
        self._mix_sliders = {}
        for key, label, mn, mx, dflt, scale in MIX_KNOBS:
            mxl.addLayout(self._knob_row(track["mix"], key, label, mn, mx, dflt, scale, store=self._mix_sliders))
        lay.addWidget(self.mixpanel)
        self.mixpanel.setVisible(False)                  # revealed by set_active

        # VARIATIONS — main + alternates that play INSTEAD of it; on the APC each pad DOWN the column is
        # a variation. Shown on the selected card: numbered buttons to switch + ＋ to add.
        self.varbar = QWidget(); self._varlay = QHBoxLayout(self.varbar)
        self._varlay.setContentsMargins(0, 2, 0, 0); self._varlay.setSpacing(4)
        lay.addWidget(self.varbar); self.varbar.setVisible(False)

        self._group = _group_of(track)
        self._refresh_group_ui()

        # Reliable selection: a press anywhere on the row (even on a label/slider/combo) selects it.
        for w in self.findChildren(QWidget):
            w.installEventFilter(self)

    # ---- synth designer builders ----
    def _sound_head(self, parent_lay, title, pkey, wave, on_wave):
        head = QHBoxLayout(); head.setSpacing(6)
        head.addWidget(self._tag(title))
        combo = QComboBox(); combo.setFont(theme.sans(10)); combo.setMinimumHeight(28)
        for w in WAVES:
            combo.addItem(w)
        combo.setStyleSheet(_COMBO_CSS); combo.setCurrentText(wave)
        combo.currentTextChanged.connect(on_wave)
        play = QPushButton("▶"); play.setFixedSize(30, 26); play.setCursor(Qt.PointingHandCursor)
        play.setToolTip(f"Hear the {title.strip('→ ').lower()} sound"); play.setStyleSheet(_PLAY_CSS)
        play.clicked.connect(lambda _=False, k=pkey: self._preview_sound(k))
        _mark_play(play, "▶"); self._play_widgets.append(play); self._sound_btns[pkey] = play
        head.addWidget(combo, 1); head.addWidget(play)
        parent_lay.addLayout(head)
        params = self.track[pkey]
        for key, label, mn, mx, dflt, scale in SYNTH_KNOBS:
            parent_lay.addLayout(self._knob_row(params, key, label, mn, mx, dflt, scale))
        return combo

    def _knob_row(self, params, key, label, mn, mx, dflt, scale, store=None):
        row = QHBoxLayout(); row.setSpacing(6)
        lab = QLabel(label); lab.setFixedWidth(50); lab.setStyleSheet("color:#8a8a99;font-size:10px;")
        sld = QSlider(Qt.Horizontal); sld.setRange(mn, mx); sld.setFixedHeight(16)
        cur = params.get(key, dflt / scale)
        sld.setValue(int(round(cur if key == "octave" else cur * scale)))
        if store is not None:
            store[key] = sld                             # so a MIDI knob can move the slider
        sld.setStyleSheet("QSlider::groove:horizontal{height:4px;background:#26262f;border-radius:2px;}"
                          "QSlider::handle:horizontal{width:12px;margin:-5px 0;border-radius:6px;"
                          "background:#7c5cff;}")
        val = QLabel(); val.setFixedWidth(30); val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        val.setStyleSheet("color:#c0c0cc;font-size:10px;")

        def _show(v):
            val.setText(f"{v:+d}" if key == "octave" else str(int(v)))
        _show(sld.value())

        def _changed(v, k=key, s=scale):
            params[k] = int(v) if k == "octave" else v / s
            _show(v); self.changed.emit()
        sld.valueChanged.connect(_changed)
        row.addWidget(lab); row.addWidget(sld, 1); row.addWidget(val)
        return row

    def _divider(self):
        d = QFrame(); d.setFrameShape(QFrame.HLine); d.setStyleSheet("color:#22222c;"); d.setFixedHeight(8)
        return d

    def play_buttons(self):
        return list(self._play_widgets)

    def _preview_sound(self, pkey):
        preset = self.track["sound"] if pkey == "params" else self.track.get("sound_b") or WAVES[1]
        self.preview_sound.emit(preset, dict(self.track[pkey]), self._sound_btns[pkey])

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.MouseButtonPress:
            self.activated.emit(self.track)
        return False

    def _refresh_style(self, active):
        self._active = active
        c = self.track["color"].name()
        if self._on_take:
            bg, bd = "#13131b", ("2px solid " + c) if active else "1px solid #2a2a36"
        else:                      # another soundwave's track — visibly backgrounded
            bg, bd = "#0e0e14", "1px solid #1c1c24"
        self.setStyleSheet(f"TrackRow{{background:{bg};border:{bd};border-radius:10px;}}")

    def set_active(self, on):
        self._refresh_style(on)
        if hasattr(self, "mixpanel"):
            self.mixpanel.setVisible(bool(on))           # the 8 MIX knobs show on the SELECTED card
        if hasattr(self, "varbar"):
            self.varbar.setVisible(bool(on))

    def refresh_variations(self):
        """Rebuild the variation buttons (1..n + ＋) to match the track's variations + active index."""
        if not hasattr(self, "_varlay"):
            return
        while self._varlay.count():
            it = self._varlay.takeAt(0); w = it.widget()
            if w is not None:
                w.deleteLater()
        lab = QLabel("Variations"); lab.setStyleSheet("color:#8a8a99;font-size:10px;")
        self._varlay.addWidget(lab)
        variations = self.track.get("variations") or [self.track.get("points", [])]
        active = int(self.track.get("var", 0))
        on = ("QPushButton{background:#7c5cff;border:1px solid #9b82ff;border-radius:6px;color:#fff;"
              "font-size:11px;font-weight:600;}")
        off = ("QPushButton{background:#16161e;border:1px solid #2a2a36;border-radius:6px;color:#c0c0cc;"
               "font-size:11px;}QPushButton:hover{background:#1e1e28;}")
        for i in range(len(variations)):
            bb = QPushButton(str(i + 1)); bb.setFixedSize(24, 22); bb.setCursor(Qt.PointingHandCursor)
            bb.setStyleSheet(on if i == active else off)
            bb.clicked.connect(lambda _=False, k=i: self.select_variation.emit(self.track, k))
            self._varlay.addWidget(bb)
        plus = QPushButton("＋"); plus.setFixedSize(24, 22); plus.setCursor(Qt.PointingHandCursor)
        plus.setToolTip("Add a variation (a copy of this pattern you can tweak) — plays instead of the main")
        plus.setStyleSheet(off); plus.clicked.connect(lambda: self.add_variation.emit(self.track))
        self._varlay.addWidget(plus); self._varlay.addStretch(1)

    def set_mix_display(self, key, disp):
        """A keyboard knob moved this MIX control → move the on-screen slider to match (no re-emit)."""
        sld = getattr(self, "_mix_sliders", {}).get(key)
        if sld is not None:
            sld.blockSignals(True); sld.setValue(int(disp)); sld.blockSignals(False)

    def set_on_take(self, on):
        """Is this track on the soundwave currently selected? Tracks of another wave fade back, so
        the list reads as 'these are the tracks on the wave I'm editing'."""
        if on == self._on_take:
            return
        self._on_take = bool(on)
        if self._on_take:
            self.setGraphicsEffect(None)              # drops (deletes) the old effect
        else:
            fx = QGraphicsOpacityEffect(self); fx.setOpacity(0.42); self.setGraphicsEffect(fx)
        self._refresh_style(self._active)

    def mousePressEvent(self, ev):
        self.activated.emit(self.track); super().mousePressEvent(ev)

    def set_recording(self, on):
        """Flip the ● record button to ■ while this track is recording its guide."""
        self.b_rec.setText("■" if on else "●")

    def _toggle_vn(self):
        # ask the board to flip THIS track's soundwave between Volume and Notes
        self.flag.emit(self.track, "notes" if self._vn_mode() != "notes" else "volume")

    def _vn_mode(self):
        """This track's current view mode ('volume'/'notes'), read from the board via a callback."""
        fn = getattr(self, "_flags_fn", None)
        return (fn(self.track) or {}).get("mode", "volume") if fn else "volume"

    def refresh_flags(self):
        """Repaint Solo/Mute/V-N to match the track's soundwave state (board sets `_flags_fn`)."""
        fn = getattr(self, "_flags_fn", None)
        st = (fn(self.track) if fn else None) or {}
        on = "QPushButton{background:%s;border:1px solid %s;border-radius:6px;color:#12121a;font-weight:700;font-size:12px;}"
        off = "QPushButton{background:#16161e;border:1px solid #2a2a36;border-radius:6px;color:#c0c0cc;font-size:12px;}QPushButton:hover{background:#1e1e28;}"
        self.b_solo.setStyleSheet(on % ("#ffd24d", "#ffd24d") if st.get("solo") else off)
        self.b_mute.setStyleSheet(on % ("#ff7a7a", "#ff7a7a") if st.get("muted") else off)
        notes = st.get("mode") == "notes"
        self.b_vn.setText("♪" if notes else "▁")
        self.b_vn.setStyleSheet(on % ("#c0a8ff", "#c0a8ff") if notes else off)

    def _on_name(self, txt):
        self.track["name"] = txt; self.changed.emit()

    def _toggle_vis(self):
        self.track["visible"] = not self.track["visible"]
        self.eye.setText("👁" if self.track["visible"] else "🚫"); self.changed.emit()

    def _tag(self, t):
        l = QLabel(t); l.setStyleSheet("color:#8a8a99;font-size:10px;font-weight:600;"); return l

    def _refresh_group_ui(self):
        """Show the sub-picker/panel for the current group and select the track's current sound."""
        g = self._group
        for name, b in self._grp_btns.items():
            b.setStyleSheet(_TOOL_ON if name == g else _TOOL_OFF)
        self.syn.setVisible(g == "Synth")
        self.fxpanel.setVisible(g == "Original")
        self.humpanel.setVisible(g == "Hum")
        self._combo_items = _group_items(g)
        self.combo.blockSignals(True)
        self.combo.clear()
        for _, _, lbl in self._combo_items:
            self.combo.addItem(lbl)
        if self._combo_items:
            idx = next((i for i, (k, s, _) in enumerate(self._combo_items)
                        if k == self.track["kind"] and s == self.track["sound"]), 0)
            self.combo.setCurrentIndex(idx)
        self.combo.blockSignals(False)
        self.combo.setVisible(g in ("Hum", "Instrument"))     # Original/Synth use their own panels

    def _on_group(self, g):
        """Top-level Original · Hum · Synth · Instrument selector."""
        self._group = g
        if g == "Original":
            self.track["kind"] = "original"; self.track["sound"] = ""; self.track["sound_b"] = ""
            self.track.setdefault("fx", default_fx())
        elif g == "Synth":
            self.track["kind"] = "synth"
            self.track.setdefault("params", default_params()); self.track.setdefault("params_b", default_params())
            if self.track["sound"] not in WAVES:
                self.track["sound"] = self.combo_base.currentText()
            if self.track.get("sound_b") not in WAVES:
                self.track["sound_b"] = self.combo_mod.currentText()
        elif g == "Hum":
            self.track["kind"] = "hum"; self.track["sound_b"] = ""
            self.track.setdefault("hum_params", default_hum_params())
            if self.track["sound"] not in HUMS:
                self.track["sound"] = HUMS[0]
        else:                                                 # Instrument (drum / pitched families)
            if self.track["kind"] not in ("drum", "inst"):
                self.track["kind"] = "inst"; self.track["sound"] = next(iter(INST_SPECS)); self.track["sound_b"] = ""
        self._refresh_group_ui()
        self.changed.emit()

    def _on_instrument(self, idx):
        if not (0 <= idx < len(self._combo_items)):
            return
        k, s, _ = self._combo_items[idx]
        self.track["kind"] = k; self.track["sound"] = s; self.track["sound_b"] = ""
        self.changed.emit()

    def _on_note(self, key, combo):
        self.track[key] = int(combo.currentData()); self.changed.emit()

    def _on_base(self, w):
        if self.track["kind"] == "synth":
            self.track["sound"] = w; self.changed.emit()

    def _on_mod(self, w):
        if self.track["kind"] == "synth":
            self.track["sound_b"] = w; self.changed.emit()


# ---------------------------------------------------------------- the board
class SeparationBoard(QWidget):
    create_requested = Signal()          # legacy "resync all" hook (button removed)
    record_requested = Signal()          # ● Record main (the primary take) — legacy, unused
    record_secondary_requested = Signal()  # ● Record secondary (overdub) — legacy, unused
    record_track = Signal(str)           # ● on a track row → record a guide into that soundwave (take id)
    loop_region_changed = Signal(str)    # the Loop tool changed a soundwave's loop region (take id)
    tracks_changed = Signal(str)         # a track/points changed → live-sync that lane (id, "" = all)
    take_audio_changed = Signal()        # the take WAVEFORM itself changed (Fit stretch / delete) → resync audio
    bpm_changed = Signal(int)            # the board's BPM box changed → sync the Studio
    point_selected = Signal(str)         # a drawn anchor was selected → highlight its Studio beat
    playhead_moved = Signal(float)       # preview playhead (take-fraction 0..1, -1 = cleared)

    def __init__(self, buf, sr, bpm, instrument_items=None, preview_cb=None, preview_pattern_cb=None,
                 preview_original_cb=None, preview_both_cb=None, preview_sound_cb=None, stop_cb=None,
                 preview_note_cb=None):
        # A plain top-level QWidget (NOT a QDialog) so the window manager treats it as a normal,
        # fully independent window it will maximise / full-screen / move to a 2nd monitor. QDialogs
        # get a "dialog" type hint that GNOME/others refuse to full-screen — that was the whole bug.
        super().__init__()
        self.buf = buf.astype(np.float32) if buf is not None else np.zeros(sr, np.float32)
        self.sr = sr; self.bpm = bpm or 90
        self.items = _collapse_items(instrument_items or INSTRUMENT_ITEMS)
        self.preview_cb = preview_cb; self.preview_pattern_cb = preview_pattern_cb
        self.preview_original_cb = preview_original_cb; self.preview_both_cb = preview_both_cb
        self.preview_sound_cb = preview_sound_cb; self.stop_cb = stop_cb
        self.preview_note_cb = preview_note_cb
        self._play_btn = None; self._sound_ph = QTimer(self); self._sound_ph.setSingleShot(True)
        self._sound_ph.timeout.connect(self._stop_playback)
        self.tracks = []; self._n = 0; self._color_seq = 0; self._is_full = False; self._docked = False
        self.takes = [{"id": "T0main", "buf": self.buf, "color": take_color(0), "name": "Main"}]
        self._active_take = self.takes[0]["id"]
        self.setWindowTitle("Separation Board — draw your sounds apart")
        self.setWindowFlag(Qt.Window, True)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        self.resize(1180, 700)
        self.setStyleSheet(f"background:{theme.BG.name()};color:#d8d8e0;")

        self._ph_timer = QTimer(self); self._ph_timer.setInterval(30); self._ph_timer.timeout.connect(self._tick_playhead)
        self._ph_clock = QElapsedTimer(); self._ph_total = 0.0

        root = QVBoxLayout(self); root.setContentsMargins(14, 12, 14, 12); root.setSpacing(10)

        top = QHBoxLayout()
        # Record main/secondary REMOVED from the toolbar — recording is now per-track (the ● button on
        # each track row). The button objects are kept (hidden) so state helpers stay valid.
        self.rec_btn = QPushButton(); self.rec_btn.setParent(self); self.rec_btn.hide()
        self.rec2_btn = QPushButton(); self.rec2_btn.setParent(self); self.rec2_btn.hide()
        # tucked-away help: a small "?" that reveals the how-to only when clicked
        help_txt = ("Record here, then click the wave to place points — drag as you place to curve the "
                    "line (pen tool). Drag the round handles to reshape · scroll to zoom.")
        self.help_btn = QPushButton("?"); self.help_btn.setFixedSize(24, 24)
        self.help_btn.setCursor(Qt.PointingHandCursor); self.help_btn.setToolTip("How the Separation Board works")
        self.help_btn.setStyleSheet("QPushButton{background:#16161e;border:1px solid #2a2a36;border-radius:12px;"
                                    "color:#c0c0cc;font-weight:700;}QPushButton:hover{background:#1e1e28;}")
        self.help_btn.clicked.connect(
            lambda: QToolTip.showText(self.help_btn.mapToGlobal(self.help_btn.rect().bottomLeft()),
                                      help_txt, self.help_btn))
        top.addSpacing(10); top.addWidget(self.help_btn); top.addStretch(1)
        # VOLUME ↔ NOTES: same take, two ways to draw it (hits/loudness vs a piano-roll of pitches)
        top.addWidget(self._dim("draw"))
        self._mode_btns = {}
        for name, glyph, tip in (("volume", "▁ Volume", "Draw hits and loudness on the waveform"),
                                 ("notes", "♪ Notes", "Piano-roll: trace the pitch you hummed and place notes")):
            b = QPushButton(glyph); b.setCursor(Qt.PointingHandCursor); b.setFixedHeight(30); b.setToolTip(tip)
            b.clicked.connect(lambda _=False, n=name: self._set_mode(n))
            self._mode_btns[name] = b; top.addWidget(b)
        top.addSpacing(8)
        # tool selector: Pen (draw) · Grid (stretch tempo) · Fit (stretch a slice of audio)
        top.addWidget(self._dim("tool"))
        self._tool_btns = {}
        for name, glyph, tip in (("pen", "✎ Pen", "Draw sounds — place points on the wave"),
                                 ("grid", "⇋ Grid", "Left-drag = stretch/shrink tempo · Right-drag = move the grid"),
                                 ("fit", "⤢ Fit", "Pick two points on the wave, then drag to stretch/shrink that audio"),
                                 ("loop", "⟳ Loop", "Drag to set THIS soundwave's loop region — the sample a pad plays")):
            b = QPushButton(glyph); b.setCursor(Qt.PointingHandCursor); b.setFixedHeight(30); b.setToolTip(tip)
            b.clicked.connect(lambda _=False, n=name: self._set_tool(n))
            self._tool_btns[name] = b; top.addWidget(b)
        top.addSpacing(8)
        # tempo
        top.addWidget(self._dim("BPM"))
        self.bpm_box = QSpinBox(); self.bpm_box.setRange(40, 300); self.bpm_box.setValue(int(self.bpm))
        self.bpm_box.setFixedWidth(72); self.bpm_box.setStyleSheet(
            "QSpinBox{background:#16161e;border:1px solid #2a2a36;border-radius:8px;color:#e2e2ea;padding:4px 6px;}")
        self.bpm_box.valueChanged.connect(self._on_bpm)
        top.addWidget(self.bpm_box)
        # zoom
        top.addSpacing(8); top.addWidget(self._dim("zoom"))
        zout = self._chip("－"); zout.clicked.connect(lambda: self._zoom(1 / 0.7))
        self.zlbl = QLabel("100%"); self.zlbl.setFixedWidth(46); self.zlbl.setAlignment(Qt.AlignCenter)
        self.zlbl.setStyleSheet("color:#c0c0cc;font-size:12px;")
        zin = self._chip("＋"); zin.clicked.connect(lambda: self._zoom(0.7))
        top.addWidget(zout); top.addWidget(self.zlbl); top.addWidget(zin)
        top.addSpacing(8)
        self.b_full = self._chip("⛶ Full screen", wide=True); self.b_full.clicked.connect(self._toggle_full)
        top.addWidget(self.b_full)
        root.addLayout(top)

        self.canvas = CurveCanvas(self.buf, sr, self.bpm, self.tracks)
        self.canvas.set_takes(self.takes)                # share the board's take rows (matching ids)
        self.canvas.active_changed.connect(self._on_canvas_active)
        self.canvas.edited.connect(self._on_canvas_edited)
        self.canvas.point_selected.connect(self.point_selected.emit)
        self.canvas.grid_scaled.connect(self._on_grid_scaled)
        self.canvas.grid_moved.connect(lambda: self.tracks_changed.emit(""))
        self.canvas.fit_applied.connect(self._apply_fit)
        self.canvas.key_pressed.connect(self._on_key_pressed)
        self.canvas.delete_take.connect(self._delete_take)
        self.canvas.take_selected.connect(self._on_take_selected)
        self.canvas.take_flag.connect(self._on_take_flag)
        self.canvas.take_rename.connect(self._on_take_rename)
        self.canvas.loop_changed.connect(self._on_loop_changed)
        self._set_tool("pen")
        self._set_mode("volume")

        side = QVBoxLayout(); side.setSpacing(8)
        add = QPushButton("＋ Add track"); add.setCursor(Qt.PointingHandCursor); add.setFixedHeight(38); add.clicked.connect(self.add_track)
        add.setStyleSheet("QPushButton{background:#7c5cff;border:none;border-radius:9px;color:#fff;font-size:13px;font-weight:600;}QPushButton:hover{background:#8b6dff;}")
        side.addWidget(add)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.NoFrame)
        self._list_host = QWidget(); self._list = QVBoxLayout(self._list_host)
        self._list.setSpacing(8); self._list.setContentsMargins(0, 0, 4, 0); self._list.addStretch(1)
        scroll.setWidget(self._list_host); side.addWidget(scroll, 1)
        sw = QWidget(); sw.setLayout(side); sw.setMinimumWidth(210); sw.setMaximumWidth(620)
        # DRAGGABLE divider between the track list and the soundwave canvas (was a fixed 300px, which
        # cropped the wave). Grab the handle to widen either side.
        self._mid_split = QSplitter(Qt.Horizontal)
        self.canvas.setMinimumWidth(320)
        self._mid_split.addWidget(sw)                  # track list on the LEFT — every menu is left-side
        self._mid_split.addWidget(self.canvas)
        self._mid_split.setStretchFactor(0, 0); self._mid_split.setStretchFactor(1, 1)
        self._mid_split.setCollapsible(0, False); self._mid_split.setCollapsible(1, False)
        self._mid_split.setHandleWidth(8); self._mid_split.setSizes([300, 900])
        self._mid_split.setStyleSheet(
            "QSplitter::handle{background:#1a1a24;border-left:1px solid #2a2a36;border-right:1px solid #2a2a36;}"
            "QSplitter::handle:hover{background:#2a2a3a;}")
        root.addWidget(self._mid_split, 1)

        btns = QHBoxLayout()
        self.count = QLabel("0 tracks"); self.count.setStyleSheet("color:#8a8a99;font-size:12px;")
        btns.addWidget(self.count); btns.addSpacing(12)
        gstyle = ("QPushButton{background:#173a2a;border:1px solid #2f7d55;border-radius:8px;"
                  "color:#6ef0a8;padding:8px 14px;font-weight:600;}QPushButton:hover{background:#1e5138;}")
        self.b_prevall = QPushButton("▶ Mix"); self.b_prevall.setToolTip("Play what you drew")
        self.b_prevall.clicked.connect(self._preview_all)
        self.b_prevorig = QPushButton("▶ Original"); self.b_prevorig.setToolTip("Play your raw recording")
        self.b_prevorig.clicked.connect(self._preview_original)
        self.b_prevboth = QPushButton("▶ Both"); self.b_prevboth.setToolTip("Play drawn + original together to compare")
        self.b_prevboth.clicked.connect(self._preview_both)
        for bb, lbl in ((self.b_prevall, "▶ Mix"), (self.b_prevorig, "▶ Original"), (self.b_prevboth, "▶ Both")):
            bb.setCursor(Qt.PointingHandCursor); bb.setStyleSheet(gstyle)
            _mark_play(bb, lbl, gstyle)
            # pin the width to fit BOTH the ▶ and the ■ label so the flip never resizes the button
            wp = bb.sizeHint().width(); bb.setText(lbl.replace("▶", "■"))
            bb.setFixedWidth(max(wp, bb.sizeHint().width())); bb.setText(lbl)
            btns.addWidget(bb)
        live = QLabel("● live — tracks sync to the Studio as you draw")
        live.setStyleSheet("color:#6ef0a8;font-size:11px;")
        btns.addSpacing(16); btns.addWidget(live); btns.addStretch(1)
        self.b_close = close = QPushButton("Close"); close.clicked.connect(self.hide)
        close.setStyleSheet("QPushButton{background:#16161e;border:1px solid #2a2a36;border-radius:8px;color:#d8d8e0;padding:8px 16px;}")
        btns.addWidget(close)
        root.addLayout(btns)
        self._rows = []

    # ---- recording state (driven by the main window) ----
    def _style_rec(self, on):
        if on:
            self.rec_btn.setText("■  Stop")
            self.rec_btn.setStyleSheet("QPushButton{background:#8a2a2a;border:1px solid #ff5d5d;border-radius:9px;"
                                       "color:#fff;font-weight:600;padding:0 16px;}")
        else:
            self.rec_btn.setText("●  Record main")
            self.rec_btn.setStyleSheet("QPushButton{background:rgba(255,93,93,0.16);border:1px solid #8a2a2a;"
                                       "border-radius:9px;color:#ff9d9d;font-weight:600;padding:0 16px;}"
                                       "QPushButton:hover{background:rgba(255,93,93,0.26);}")

    def _style_rec2(self, on):
        if on:
            self.rec2_btn.setText("■  Stop overdub")
            self.rec2_btn.setStyleSheet("QPushButton{background:#8a2a2a;border:1px solid #ff5d5d;border-radius:9px;"
                                        "color:#fff;font-weight:600;padding:0 16px;}")
        else:
            self.rec2_btn.setText("＋ Record secondary")
            self.rec2_btn.setStyleSheet("QPushButton{background:rgba(124,92,255,0.16);border:1px solid #4a3a8a;"
                                        "border-radius:9px;color:#c0a8ff;font-weight:600;padding:0 16px;}"
                                        "QPushButton:hover{background:rgba(124,92,255,0.26);}")

    def set_recording(self, on, secondary=False):
        self.canvas.recording = on
        if not on:
            self.canvas.set_live([], False)
        (self._style_rec2 if secondary else self._style_rec)(on)
        self.canvas.update()

    # ---- play / stop: ONLY the button you pressed becomes ■ (one preview plays at a time) ----
    def _all_play_buttons(self):
        out = [self.b_prevall, self.b_prevorig, self.b_prevboth]
        for row in self._rows:
            out += row.play_buttons()
        return out

    def _is_playing(self):
        return self._play_btn is not None

    def _set_play_btn(self, btn):
        """Show ■ on `btn` only; revert whichever button was previously playing."""
        if self._play_btn is not None and self._play_btn is not btn:
            _flip_play(self._play_btn, False)
        self._play_btn = btn
        if btn is not None:
            _flip_play(btn, True)

    def clear_playing(self):
        """External stop (e.g. the Studio transport started) — revert the playing button."""
        self._sound_ph.stop()
        self._set_play_btn(None)

    def _toggle_preview(self, btn, start_fn, use_playhead=True):
        """Toggle a single preview button. Pressing the one that's playing stops; pressing another
        stops that one and starts this. `start_fn` returns the duration in seconds (0/None = nothing)."""
        same = self._play_btn is btn
        if self._play_btn is not None:
            self._stop_playback()
        if same:
            return
        dur = start_fn()
        if not dur or dur <= 0:
            return
        self._set_play_btn(btn)
        if use_playhead:
            self._start_playhead(dur)
        else:
            self._sound_ph.start(int(dur * 1000) + 150)

    def _stop_playback(self):
        self._ph_timer.stop(); self._sound_ph.stop(); self.canvas.set_playhead(None)
        self.playhead_moved.emit(-1.0)
        if self.stop_cb:
            self.stop_cb()
        self._set_play_btn(None)

    def add_take(self, buf, name=None):
        """A secondary recording → a NEW take row (its own colour) under the main, same tempo/length.
        New tracks you add are drawn over THIS take until you pick another row."""
        if buf is None or not len(buf):
            return None
        add = np.asarray(buf, np.float32)
        n = len(self.buf)                                    # pad/truncate to the main length
        row = np.zeros(n, np.float32); m = min(n, len(add)); row[:m] = add[:m]
        tid = uid("T")
        self.takes.append({"id": tid, "buf": row, "color": take_color(len(self.takes)),
                           "name": name or f"Secondary {len(self.takes)}"})
        self._active_take = tid
        v0, v1 = self.canvas.view0, self.canvas.view1        # keep the current zoom
        self.canvas.set_takes(self.takes)
        self._sync_sel_take()                                # a fresh overdub = the wave you're on now
        self.canvas.view0, self.canvas.view1 = v0, v1; self.canvas.update()
        return tid

    # ---- small style helpers ----
    def _dim(self, t):
        l = QLabel(t); l.setStyleSheet("color:#8a8a99;font-size:12px;"); return l

    def _chip(self, txt, wide=False):
        b = QPushButton(txt); b.setCursor(Qt.PointingHandCursor); b.setFixedHeight(30)
        if not wide:
            b.setFixedWidth(34)
        b.setStyleSheet("QPushButton{background:#16161e;border:1px solid #2a2a36;border-radius:8px;color:#d8d8e0;padding:0 10px;font-size:13px;}QPushButton:hover{background:#1e1e28;}")
        return b

    # ---- new MAIN take (re-record replaces everything; a NEW row is Record secondary → add_take) ----
    def set_take(self, buf, bpm):
        self.buf = buf.astype(np.float32) if buf is not None else np.zeros(self.sr, np.float32)
        self.bpm = bpm or self.bpm
        self.bpm_box.blockSignals(True); self.bpm_box.setValue(int(self.bpm)); self.bpm_box.blockSignals(False)
        for row in self._rows:
            self._list.removeWidget(row); row.deleteLater()
        self._rows = []; self.tracks.clear(); self._n = 0; self._color_seq = 0
        self.takes = [{"id": uid("T"), "buf": self.buf, "color": take_color(0), "name": "Main"}]
        self._active_take = self.takes[0]["id"]
        self.canvas.bpm = self.bpm; self.canvas.set_active(-1)
        self.canvas.set_takes(self.takes); self.canvas.view0, self.canvas.view1 = 0.0, 1.0
        self._sync_sel_take()
        self._update_zoom_label(); self._refresh()
        self.tracks_changed.emit("")               # structural: all auto lanes cleared

    # ---- undo/redo across both windows: a light snapshot of the board (buffers by reference) ----
    def snapshot(self):
        import copy
        tracks = []
        for tr in self.tracks:
            t = copy.deepcopy({k: v for k, v in tr.items() if k != "color"})   # points/params/etc.
            t["color"] = tr["color"].name()
            tracks.append(t)
        takes = [{"id": tk["id"], "name": tk["name"], "color": tk["color"].name(), "buf": tk["buf"],
                  "solo": tk.get("solo", False), "muted": tk.get("muted", False),
                  "loop_a": tk.get("loop_a"), "loop_b": tk.get("loop_b"), "mode": tk.get("mode", "volume")}
                 for tk in self.takes]                                          # buf by reference (cheap)
        return {"tracks": tracks, "takes": takes, "active_take": self._active_take,
                "bpm": self.bpm, "n": self._n, "color_seq": self._color_seq,
                "grid_off": self.canvas.grid_off}

    def restore(self, blob):
        import copy
        for row in self._rows:
            self._list.removeWidget(row); row.deleteLater()
        self._rows = []
        self.takes = [{"id": tk["id"], "buf": tk["buf"], "color": QColor(tk["color"]), "name": tk["name"],
                       "solo": tk.get("solo", False), "muted": tk.get("muted", False),
                       "loop_a": tk.get("loop_a"), "loop_b": tk.get("loop_b"), "mode": tk.get("mode", "volume")}
                      for tk in blob["takes"]]
        if self.takes:
            self.buf = self.takes[0]["buf"]
        self._active_take = blob.get("active_take")
        self.bpm = int(blob.get("bpm", self.bpm)); self.canvas.bpm = self.bpm
        self._n = blob.get("n", self._n); self._color_seq = blob.get("color_seq", self._color_seq)
        self.canvas.grid_off = float(blob.get("grid_off", 0.0))
        self.tracks.clear()                                                    # mutate in place (canvas shares it)
        for t in blob["tracks"]:
            tr = copy.deepcopy({k: v for k, v in t.items() if k != "color"})
            tr["color"] = QColor(t["color"])
            self.tracks.append(tr)
            self._add_row(tr)
        self.canvas.set_takes(self.takes)
        self.canvas.set_active(min(self.canvas.active, len(self.tracks) - 1) if self.tracks else -1)
        self._sync_sel_take()                              # restore the soundwave you were editing
        self.bpm_box.blockSignals(True); self.bpm_box.setValue(int(self.bpm)); self.bpm_box.blockSignals(False)
        self._update_zoom_label(); self._refresh()

    # ---- tracks ----
    def _add_row(self, tr):
        """Build a TrackRow for `tr` and wire its signals (shared by add_track + restore)."""
        row = TrackRow(tr, self.items)
        row._flags_fn = self._track_flags               # so the row can show Solo/Mute/V-N state
        row.activated.connect(self._activate_track); row.changed.connect(lambda t=tr: self._on_row_changed(t))
        row.preview.connect(self._preview_track); row.delete.connect(self._delete_track)
        row.preview_sound.connect(self._preview_sound)
        row.flag.connect(self._on_track_flag)
        row.record.connect(self._on_track_record)
        row.duplicate.connect(self._duplicate_track)
        row.add_variation.connect(self.add_variation)
        row.select_variation.connect(self.set_variation)
        self._ensure_variations(tr); row.refresh_variations()
        row.refresh_flags()
        self._rows.append(row); self._list.insertWidget(self._list.count() - 1, row)
        return row

    def _refresh_row_flags(self):
        for row in getattr(self, "_rows", []):
            row.refresh_flags()

    def _track_flags(self, tr):
        """The soundwave state a track's row shows: {solo, muted, mode} from its bound take."""
        tk = next((t for t in self.takes if t["id"] == tr.get("take")), None)
        if not tk:
            return {}
        return {"solo": tk.get("solo"), "muted": tk.get("muted"), "mode": tk.get("mode", "volume")}

    def _on_track_flag(self, tr, field):
        """A per-track Solo/Mute/View button (in the sidebar row) — acts on the track's soundwave."""
        ti = next((i for i, t in enumerate(self.takes) if t["id"] == tr.get("take")), None)
        if ti is None:
            return
        if field in ("solo", "mute"):
            self._on_take_flag(ti, field)
        else:                                            # volume / notes: focus this track + set its view
            self._activate_track(tr)
            self.takes[ti]["mode"] = field
            self._set_mode(field, remember=False)
        for row in self._rows:
            row.refresh_flags()

    def _take_len(self):
        return len(self.takes[0]["buf"]) if self.takes else (len(self.buf) if self.buf is not None else self.sr)

    def _new_take_row(self, buf=None, name=None):
        """Mint a soundwave (take) row — 1 track = 1 soundwave. Silent unless a buffer is given."""
        n = self._take_len()
        b = np.zeros(n, np.float32)
        if buf is not None:
            src = np.asarray(buf, np.float32); m = min(n, len(src)); b[:m] = src[:m]
        tk = {"id": uid("T"), "buf": b, "color": take_color(len(self.takes)),
              "name": name or f"Sound {len(self.takes) + 1}", "solo": False, "muted": False, "mode": "volume"}
        self.takes.append(tk)
        return tk

    def _make_track(self, take_id, name=None, base=None):
        """Build a track dict bound 1:1 to `take_id` (optionally copying instrument from `base`)."""
        self._n += 1
        color = theme.lane_color(self._color_seq); self._color_seq += 1
        tr = {"lane_id": uid("R"), "name": name or f"Track {self._n}", "color": color, "take": take_id,
              "kind": "drum", "sound": DRUMS[0], "sound_b": "", "points": [], "visible": True,
              "params": default_params(), "params_b": default_params(),
              "hum_params": default_hum_params(), "lo_note": 48, "hi_note": 72,
              "fx": default_fx(), "mix": default_mix()}
        tr["variations"] = [tr["points"]]; tr["var"] = 0   # main = variation 0 (pads switch variations)
        if base is not None:                             # duplicate the instrument (not the beats)
            for k in ("kind", "sound", "sound_b", "params", "params_b", "hum_params", "lo_note", "hi_note", "fx", "mix"):
                if k in base:
                    tr[k] = copy.deepcopy(base[k])
        return tr

    def add_track(self):
        # 1 track = 1 soundwave: reuse an unbound take (the initial Main) or mint a fresh silent one.
        bound = {t.get("take") for t in self.tracks}
        tk = next((t for t in self.takes if t["id"] not in bound), None) or self._new_take_row()
        tr = self._make_track(tk["id"])
        self.tracks.append(tr); self._active_take = tk["id"]
        self._add_row(tr)
        self.canvas.set_takes(self.takes); self._sync_sel_take()
        self._activate_track(tr); self._sel_take_rows(); self._refresh()
        self.tracks_changed.emit(tr["lane_id"])

    def _duplicate_track(self, src):
        """⧉ Duplicate: ask 'Soundwave' (copy the audio only) or 'Full' (audio + beats + instrument)."""
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(self); box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Duplicate track")
        box.setText(f"Duplicate “{src['name']}” — how much?")
        box.setInformativeText("Soundwave = copy just the recording (fresh beats).\n"
                               "Full = copy the recording, the beats and the instrument.")
        b_wave = box.addButton("Soundwave", QMessageBox.AcceptRole)
        b_full = box.addButton("Full", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked in (b_wave, b_full):
            self._do_duplicate(src, full=(clicked is b_full))

    def _do_duplicate(self, src, full):
        """Create a new 1:1 track+soundwave copying `src`'s audio (+ beats/instrument if `full`)."""
        src_take = next((t for t in self.takes if t["id"] == src.get("take")), None)
        tk = self._new_take_row(buf=(src_take["buf"].copy() if src_take is not None else None),
                                name=f"{src['name']} copy")
        tr = self._make_track(tk["id"], name=f"{src['name']} copy", base=(src if full else None))
        if full:
            self._ensure_pt_ids(src); self._ensure_variations(src)
            tr["variations"] = copy.deepcopy(src["variations"])   # copy ALL variations + the active one
            tr["var"] = max(0, min(int(src.get("var", 0)), len(tr["variations"]) - 1))
            tr["points"] = tr["variations"][tr["var"]]            # link points to the copied active var
        self.tracks.append(tr); self._active_take = tk["id"]
        self._add_row(tr)
        self.canvas.set_takes(self.takes); self._sync_sel_take()
        self._activate_track(tr); self._sel_take_rows(); self._refresh()
        self.tracks_changed.emit(tr["lane_id"])
        return tr

    # ---- variations: a track holds a LIST of patterns; only one plays; pads switch them ----
    @staticmethod
    def _ensure_variations(tr):
        """Guarantee tr['variations'] (list of point-lists) + tr['var']. Keep the ACTIVE slot pointing at
        the live tr['points'] list, so reassigning points (load/undo/sync) never loses the link."""
        if not tr.get("variations"):
            tr["variations"] = [tr.get("points") or []]
            tr["var"] = 0
        tr["var"] = max(0, min(int(tr.get("var", 0)), len(tr["variations"]) - 1))
        if tr.get("points") is None:
            tr["points"] = tr["variations"][tr["var"]]
        else:
            tr["variations"][tr["var"]] = tr["points"]   # active variation == the live points list

    def add_variation(self, tr):
        """＋ Variation — append a COPY of the current pattern (tweak a duplicate); it becomes active."""
        self._ensure_variations(tr)
        tr["variations"].append(copy.deepcopy(tr["points"]))
        tr["var"] = len(tr["variations"]) - 1
        tr["points"] = tr["variations"][tr["var"]]
        self._refresh_variations(tr); self.canvas.update()
        self.tracks_changed.emit(tr.get("lane_id", ""))

    def set_variation(self, tr, i):
        """Switch the active variation (what's shown/edited AND what a pad plays)."""
        self._ensure_variations(tr)
        if not (0 <= i < len(tr["variations"])):
            return
        tr["var"] = i; tr["points"] = tr["variations"][i]
        self._refresh_variations(tr); self.canvas.update()
        self.tracks_changed.emit(tr.get("lane_id", ""))

    def _refresh_variations(self, tr):
        try:
            idx = self.tracks.index(tr)
        except ValueError:
            return
        if idx < len(self._rows):
            self._rows[idx].refresh_variations()

    def _on_track_record(self, tr):
        """● on a track row → record a guide into THIS track's soundwave (handled by the Studio)."""
        self._activate_track(tr)          # so the live waveform draws on this track's row
        self.record_track.emit(tr.get("take", ""))

    def midi_mix(self, knob_idx, value):
        """A keyboard knob → the SELECTED track's MIX knob (volume/EQ/fx). The APC knobs are RELATIVE
        encoders (2's-complement: 1..63 = CW, 65..127 = CCW), so we accumulate a delta for a SMOOTH
        sweep instead of jumping to min/max. Moves the on-screen slider AND re-renders."""
        if not (0 <= self.canvas.active < len(self.tracks)) or knob_idx >= len(MIX_KNOBS):
            return
        tr = self.tracks[self.canvas.active]
        key, _, mn, mx, _, scale = MIX_KNOBS[knob_idx]
        mix = tr.setdefault("mix", default_mix())
        delta = value if value < 64 else value - 128     # relative encoder → signed step
        step = (mx - mn) / 96.0                           # ~a smooth turn covers the range
        sv = max(mn, min(mx, mix.get(key, 0.0) * scale + delta * step))
        mix[key] = sv / scale
        self._rows[self.canvas.active].set_mix_display(key, int(round(sv)))
        self._on_row_changed(tr)

    def set_take_buf(self, take_id, buf):
        """Replace a soundwave's audio (a per-track recording landed). Keeps all takes the same length."""
        tk = next((t for t in self.takes if t["id"] == take_id), None)
        if tk is None or buf is None or not len(buf):
            return
        buf = np.asarray(buf, np.float32)
        if self.takes.index(tk) == 0:                    # take 0 defines the grid length
            self.buf = buf; n = len(buf)
            for t in self.takes:
                if len(t["buf"]) != n:
                    row = np.zeros(n, np.float32); m = min(n, len(t["buf"])); row[:m] = t["buf"][:m]; t["buf"] = row
            tk["buf"] = buf
        else:
            n = self._take_len(); row = np.zeros(n, np.float32); m = min(n, len(buf)); row[:m] = buf[:m]; tk["buf"] = row
        v0, v1 = self.canvas.view0, self.canvas.view1
        self.canvas.set_takes(self.takes); self.canvas.view0, self.canvas.view1 = v0, v1
        self._sync_sel_take(); self.canvas.update()
        self.take_audio_changed.emit(); self.tracks_changed.emit("")

    def set_track_recording(self, take_id, on):
        """Flip the ● button on the row(s) bound to `take_id` while its guide records."""
        for tr, row in zip(self.tracks, self._rows):
            if tr.get("take") == take_id:
                row.set_recording(on)
        self.set_recording(on)               # live waveform on the canvas for that take

    def _preview_sound(self, preset, params, btn):
        def go():
            if self.preview_sound_cb:
                self.preview_sound_cb(preset, params)
                return 0.9
            return 0
        self._toggle_preview(btn, go, use_playhead=False)

    def _on_row_changed(self, tr):
        self._refresh()
        self.tracks_changed.emit(tr.get("lane_id", ""))

    def _activate_track(self, tr):
        idx = self.tracks.index(tr); self.canvas.set_active(idx)
        for i, row in enumerate(self._rows):
            row.set_active(i == idx)

    def _on_canvas_active(self, idx):
        for i, row in enumerate(self._rows):
            row.set_active(i == idx)

    def _on_take_selected(self, ti):
        """A soundwave was ticked on the canvas → new tracks bind to it, and the active track
        becomes one of ITS tracks (so drawing/notes can never land on a wave you're not seeing)."""
        if 0 <= ti < len(self.takes):
            self._active_take = self.takes[ti]["id"]
            self._reconcile_active()
            self._restore_take_mode()

    def _on_take_flag(self, ti, field):
        """Solo/Mute a whole soundwave → toggles it on the take, re-syncs render (which mutes/solos
        every track bound to that take)."""
        if not (0 <= ti < len(self.takes)):
            return
        key = "solo" if field == "solo" else "muted"
        self.takes[ti][key] = not self.takes[ti].get(key)
        self.canvas.set_takes(self.takes)              # carry the flag onto the canvas copy (for drawing)
        self._sync_sel_take()
        self.canvas.update()
        self._refresh_row_flags()
        self.tracks_changed.emit("")                   # render respects the new solo/mute

    def _on_loop_changed(self, ti):
        """The Loop tool set a soundwave's loop region on the canvas copy → mirror it onto the board
        take (so it saves / round-trips) and tell the Studio (a live loop may need to restart)."""
        if 0 <= ti < len(self.takes) and ti < len(self.canvas.takes):
            self.takes[ti]["loop_a"] = self.canvas.takes[ti].get("loop_a")
            self.takes[ti]["loop_b"] = self.canvas.takes[ti].get("loop_b")
        self.loop_region_changed.emit(self.takes[ti]["id"] if 0 <= ti < len(self.takes) else "")

    def _on_take_rename(self, ti):
        """Double-click a soundwave name → rename the take (shown in both views)."""
        if not (0 <= ti < len(self.takes)):
            return
        from PySide6.QtWidgets import QInputDialog
        cur = self.takes[ti]["name"]
        name, ok = QInputDialog.getText(self, "Rename soundwave", "Name:", text=cur)
        if ok and name.strip():
            self.takes[ti]["name"] = name.strip()
            self.canvas.set_takes(self.takes); self.canvas.update()

    def _sync_sel_take(self):
        """Point the canvas at `_active_take` (the board owns the take id, the canvas an index).
        Set directly — no signal — then reconcile, so restore/delete paths can't re-enter."""
        ids = [t["id"] for t in self.takes]
        if self._active_take not in ids:
            self._active_take = ids[0] if ids else None
        self.canvas.sel_take = ids.index(self._active_take) if self._active_take in ids else 0
        self._reconcile_active()

    def _reconcile_active(self):
        """Keep the invariant: the active track always belongs to the SELECTED soundwave."""
        ti = self.canvas._active_band(); cur = self.canvas.active
        if not (0 <= cur < len(self.tracks)) or self.canvas._track_band(self.tracks[cur]) != ti:
            i = self.canvas._first_track_on(ti)
            # set_active re-enters set_sel_take with the SAME index → no emit, no loop
            self.canvas.set_active(i if i is not None else -1)
        for k, row in enumerate(self._rows):
            row.set_active(k == self.canvas.active)
        self._sel_take_rows()

    def _sel_take_rows(self):
        """Dim the track rows that belong to another soundwave — you can see at a glance which
        tracks the selected wave owns."""
        tid = self._active_take
        for tr, row in zip(self.tracks, self._rows):
            row.set_on_take(tr.get("take") == tid)

    def _on_canvas_edited(self, idx):
        if 0 <= idx < len(self.tracks):
            self.tracks_changed.emit(self.tracks[idx].get("lane_id", ""))

    def _delete_track(self, tr):
        idx = self.tracks.index(tr); lane_id = tr.get("lane_id", ""); take_id = tr.get("take")
        self.tracks.pop(idx)
        row = self._rows.pop(idx); self._list.removeWidget(row); row.deleteLater()
        # 1 track = 1 soundwave: the wave goes with the track (no ghost rows). Keep ≥1 take so the
        # canvas always has a row; a leftover unbound take is reused by the next Add track.
        if take_id and len(self.takes) > 1 and not any(t.get("take") == take_id for t in self.tracks):
            self.takes = [t for t in self.takes if t["id"] != take_id]
            self.canvas.set_takes(self.takes)
        # colours are STABLE per track — do NOT re-assign them here (removing one keeps the rest).
        self.canvas.active = min(self.canvas.active, len(self.tracks) - 1)
        for i, r in enumerate(self._rows):
            r._refresh_style(i == self.canvas.active)
        self._sync_sel_take(); self._sel_take_rows()
        self.canvas.active_changed.emit(self.canvas.active); self._refresh()
        self.tracks_changed.emit(lane_id)              # tell the Studio to drop this lane

    def _delete_take(self, ti):
        """The ✕ on a soundwave → remove that take AND every track (beats/notes/volume) on it,
        after confirmation. Removing everything leaves one empty (silent) Main row."""
        if not (0 <= ti < len(self.takes)):
            return
        from PySide6.QtWidgets import QMessageBox
        tk = self.takes[ti]
        bound = [tr for tr in self.tracks if tr.get("take") == tk["id"]]
        n = len(bound); trk = f" and its {n} track" + ("s" if n != 1 else "") if n else ""
        box = QMessageBox(self); box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Delete soundwave")
        box.setText(f"Delete “{tk['name']}”{trk}?")
        box.setInformativeText("This removes its waveform and everything on it — beats, notes and volume.")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        box.button(QMessageBox.Yes).setText("Delete")
        if box.exec() != QMessageBox.Yes:
            return
        for tr in bound:                                   # drop its tracks (rows + Studio lanes)
            self._delete_track(tr)
        self.takes.pop(ti)
        if not self.takes:                                 # deleted the last one → keep a silent Main
            self.takes = [{"id": uid("T"), "buf": np.zeros(self.sr, np.float32),
                           "color": take_color(0), "name": "Main"}]
        if self._active_take not in [t["id"] for t in self.takes]:
            self._active_take = self.takes[0]["id"]
        self.buf = self.takes[0]["buf"]
        v0, v1 = self.canvas.view0, self.canvas.view1
        self.canvas.active = min(self.canvas.active, len(self.tracks) - 1)
        self.canvas.set_takes(self.takes)
        self.canvas.view0, self.canvas.view1 = v0, v1
        self._sync_sel_take()                              # deleted wave → fall back to a live one
        self.canvas.active_changed.emit(self.canvas.active); self._refresh()
        self.take_audio_changed.emit()                     # the main take audio may have changed
        self.tracks_changed.emit("")                       # structural resync (Studio drops the lanes)

    def _ensure_pt_ids(self, tr):
        for pt in tr["points"]:
            pt.setdefault("id", uid("p"))
            pt.setdefault("tie", False)      # a LINE runs from this point to the next (sustained note)
            pt.setdefault("glide", False)    # that line GLIDES (pitch slide) vs HELD (step) — NOTES view

    @staticmethod
    def _tied_runs(pts):
        """Split points (sorted by t) into RUNS: a run is a maximal group joined by `tie` on each
        point except the last. A lone point = a run of one (a normal one-shot hit)."""
        runs = []
        i = 0
        while i < len(pts):
            j = i
            while j < len(pts) - 1 and pts[j].get("tie"):
                j += 1
            runs.append(pts[i:j + 1]); i = j + 1
        return runs

    def _pitch_track_of(self, run, n=64):
        """Sample the run's MIDI over [t0,t1] into n steps. HELD segment (glide=False) = staircase
        (hold the left pitch, jump at the next point); GLIDE segment (glide=True) = linear slide."""
        t0, t1 = float(run[0]["t"]), float(run[-1]["t"])
        if t1 <= t0:
            return [int(run[0].get("midi", DEF_MIDI))]
        ts = np.linspace(t0, t1, n)
        out = np.empty(n, np.float32)
        for k, t in enumerate(ts):
            si = 0
            while si < len(run) - 1 and float(run[si + 1]["t"]) < t:
                si += 1
            a, b = run[si], run[min(si + 1, len(run) - 1)]
            ma, mb = float(a.get("midi", DEF_MIDI)), float(b.get("midi", DEF_MIDI))
            ta, tb = float(a["t"]), float(b["t"])
            if a.get("glide") and tb > ta:
                out[k] = ma + (mb - ma) * (t - ta) / (tb - ta)   # slide
            else:
                out[k] = ma                                      # hold (step)
        return [round(float(x), 2) for x in out]

    def _on_key_pressed(self, midi):
        """A piano key on the notes gutter was clicked → play the ACTIVE track's instrument at that
        note (a tom in B♭, the synth at that pitch, …). Pure audition — nothing is placed."""
        if not self.preview_note_cb or not (0 <= self.canvas.active < len(self.tracks)):
            return
        tr = self.tracks[self.canvas.active]
        prm = tr.get("hum_params") if tr["kind"] == "hum" else tr.get("params")
        self.preview_note_cb(tr["kind"], tr["sound"], prm, int(midi))

    def _preview_track(self, tr):
        btn = self._rows[self.tracks.index(tr)].b_prev if tr in self.tracks else self.b_prevall
        def go():
            lane, events = self._lane_events(tr)
            if lane and self.preview_pattern_cb:
                return self.preview_pattern_cb([lane], events)
            if self.preview_cb:
                self.preview_cb(tr["kind"], tr["sound"]); return 0.9
            return 0
        self._toggle_preview(btn, go, use_playhead=bool(self._lane_events(tr)[0]))

    def _preview_all(self):
        def go():
            lanes, events = self.build()
            if lanes and self.preview_pattern_cb:
                return self.preview_pattern_cb(lanes, events)
            return 0
        self._toggle_preview(self.b_prevall, go)

    def _preview_original(self):
        self._toggle_preview(self.b_prevorig, lambda: self.preview_original_cb() if self.preview_original_cb else 0)

    def _preview_both(self):
        def go():
            if self.preview_both_cb:
                lanes, events = self.build()
                return self.preview_both_cb(lanes, events)
            return 0
        self._toggle_preview(self.b_prevboth, go)

    def _refresh(self):
        n = len(self.tracks); self.count.setText(f"{n} track{'s' if n != 1 else ''}"); self.canvas.update()

    # ---- timing tools (Pen / Grid / Fit) ----
    def _set_mode(self, name, remember=True):
        self.canvas.set_mode(name)
        # each SOUNDWAVE remembers whether you were on its Volume or Notes view, so switching waves
        # restores what you were doing on it (see _restore_take_mode).
        if remember:
            ti = self.canvas._active_band()
            if 0 <= ti < len(self.takes):
                self.takes[ti]["mode"] = self.canvas.mode
        for n, b in self._mode_btns.items():
            b.setStyleSheet(_TOOL_ON if n == self.canvas.mode else _TOOL_OFF)
        self._refresh_row_flags()

    def _restore_take_mode(self):
        """Selecting a soundwave restores the Volume/Notes view you last used ON it."""
        ti = self.canvas._active_band()
        if 0 <= ti < len(self.takes):
            m = self.takes[ti].get("mode")
            if m and m != self.canvas.mode:
                self._set_mode(m, remember=False)

    def _set_tool(self, name):
        self.canvas.tool = name
        self.canvas.fit_a = self.canvas.fit_b = self.canvas._fit_b0 = None
        self.canvas._grid_grab = None; self.canvas._fit_drag = False
        for n, b in self._tool_btns.items():
            b.setStyleSheet(_TOOL_ON if n == name else _TOOL_OFF)
        self.canvas.setCursor(Qt.CrossCursor if name != "pen" else Qt.ArrowCursor)
        self.canvas.update()

    def _on_grid_scaled(self, bpm):
        """Grid tool dragged → uniform tempo. Mirror the box + tell the Studio (which rescales beats)."""
        b = int(round(bpm)); self.bpm = b; self.canvas.bpm = bpm
        self.bpm_box.blockSignals(True); self.bpm_box.setValue(b); self.bpm_box.blockSignals(False)
        self.bpm_changed.emit(b)

    def _apply_fit(self, a, b0, new_b):
        """Tape-style time-stretch of the audio slice [a, b0] (fractions of the active take) to end at
        new_b. Resample that region with np.interp, splice, remap the drawn points, then re-sync."""
        band = self.canvas._active_band()
        take = self.takes[band] if 0 <= band < len(self.takes) else self.takes[0]
        old = np.asarray(take["buf"], np.float32); N = len(old)
        if N < 4:
            return
        sa, sb0 = int(a * N), int(b0 * N)
        if sb0 - sa < 2:
            return
        old_dur = N / self.sr
        old_len = (b0 - a) * old_dur
        new_len = max(0.01, (new_b - a) * old_dur)
        new_samps = max(1, int(round(new_len * self.sr)))
        region = old[sa:sb0]
        stretched = np.interp(np.linspace(0, len(region) - 1, new_samps),
                              np.arange(len(region)), region).astype(np.float32)
        new_buf = np.concatenate([old[:sa], stretched, old[sb0:]]).astype(np.float32)
        new_N = len(new_buf); new_dur = new_N / self.sr
        delta = new_len - old_len
        a_time = a * old_dur; b0_time = b0 * old_dur
        # remap every drawn point on tracks bound to THIS take (piecewise time map → new fraction)
        for tr in self.tracks:
            if tr.get("take") != take["id"]:
                continue
            for pt in tr["points"]:
                ot = pt["t"] * old_dur
                if ot <= a_time:
                    nt = ot
                elif ot <= b0_time:
                    nt = a_time + (ot - a_time) * (new_len / max(1e-6, old_len))
                else:
                    nt = ot + delta
                pt["t"] = max(0.0, min(1.0, nt / new_dur))
                if ot >= a_time:
                    pt.pop("beat", None)                       # re-derive beats from the new audio position
        take["buf"] = new_buf
        if band == 0:                                          # main take drives length → keep others aligned
            self.buf = new_buf
            for tk in self.takes:
                if tk is take:
                    continue
                b = np.asarray(tk["buf"], np.float32)
                row = np.zeros(new_N, np.float32); m = min(new_N, len(b)); row[:m] = b[:m]
                tk["buf"] = row
        v0, v1 = self.canvas.view0, self.canvas.view1
        self.canvas.set_takes(self.takes)
        self.canvas.view0, self.canvas.view1 = v0, v1
        self.canvas.update()
        self.take_audio_changed.emit()                         # the actual audio changed length
        self.tracks_changed.emit("")                           # structural: resync all lanes + undo

    # ---- tempo / zoom / playhead ----
    def _on_bpm(self, v):
        self.bpm = v; self.canvas.bpm = v; self.canvas.update()
        self.bpm_changed.emit(int(v))

    def set_bpm_external(self, v):
        """Studio changed the tempo — update the box without re-emitting."""
        self.bpm = int(v); self.canvas.bpm = int(v)
        self.bpm_box.blockSignals(True); self.bpm_box.setValue(int(v)); self.bpm_box.blockSignals(False)
        self.canvas.update()

    def set_selected_pts(self, ids):
        """Studio grid selected some beats — ring the matching drawn anchors."""
        self.canvas.set_selected_pts(ids)

    def _zoom(self, factor):
        self.canvas.zoom_at(factor); self._update_zoom_label()

    def _update_zoom_label(self):
        self.zlbl.setText(f"{round(100 / self.canvas._span())}%")

    def _start_playhead(self, dur):
        if not dur or dur <= 0:
            return
        self._ph_total = float(dur); self._ph_clock.restart(); self._ph_timer.start()

    def _tick_playhead(self):
        e = self._ph_clock.elapsed() / 1000.0
        take = max(1e-6, len(self.buf) / self.sr)
        if e >= self._ph_total:
            self._ph_timer.stop(); self.canvas.set_playhead(None); self.playhead_moved.emit(-1.0)
            if self._is_playing():
                self._stop_playback()
            return
        frac = min(1.0, e / take)
        self.canvas.set_playhead(frac); self.playhead_moved.emit(frac)

    def wheelEvent(self, ev):
        self._update_zoom_label(); super().wheelEvent(ev)

    # ---- full screen ----
    def _toggle_full(self):
        if self._is_full:
            self.showNormal(); self.b_full.setText("⛶ Full screen")
        else:
            self.showFullScreen(); self.b_full.setText("⛶ Exit full screen")
        self._is_full = not self._is_full

    def set_docked(self, docked: bool):
        """Docked = embedded in the Studio window (one-screen). Hide the window-only chrome then."""
        self._docked = docked
        self.b_full.setVisible(not docked)
        self.b_close.setVisible(not docked)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_F11 and not self._docked:
            self._toggle_full(); return
        if ev.key() == Qt.Key_Escape and not self._docked:   # docked: Escape must not hide the pane
            if self._is_full:
                self._toggle_full()
            else:
                self.hide()
            return
        super().keyPressEvent(ev)

    # ---- build ----
    def _sample_curve(self, tr):
        """Sample the Bézier line to a fine (t_frac, value) grid so we can read the curve as a
        continuous modulator (not just at the anchors)."""
        pts = sorted(tr["points"], key=lambda p: p["t"])
        if not pts:
            return None, None
        ts, vs = [], []
        if len(pts) == 1:
            ts = [pts[0]["t"]]; vs = [pts[0]["v"]]
        else:
            for i in range(len(pts) - 1):
                a, b = pts[i], pts[i + 1]
                c0, c1 = seg_ctrls(pts, i)                   # smooth auto-tangent (or hand handle)
                p0, p1 = (a["t"], a["v"]), (c0[0], c0[1])
                p2, p3 = (c1[0], c1[1]), (b["t"], b["v"])
                for s in range(25):
                    u = s / 24.0; mu = 1 - u
                    ts.append(mu**3 * p0[0] + 3*mu**2*u*p1[0] + 3*mu*u**2*p2[0] + u**3*p3[0])
                    vs.append(mu**3 * p0[1] + 3*mu**2*u*p1[1] + 3*mu*u**2*p2[1] + u**3*p3[1])
        ts = np.asarray(ts); vs = np.clip(np.asarray(vs), 0.0, 1.0)
        dur = len(self.buf) / self.sr
        grid = np.linspace(0.0, 1.0, max(16, int(dur / 0.01)))     # ~10 ms resolution
        order = np.argsort(ts)
        val = np.interp(grid, ts[order], vs[order], left=0.0, right=0.0)
        val[(grid < ts.min()) | (grid > ts.max())] = 0.0           # silent outside the drawn span
        return grid, val

    def _src_t(self, t_frac):
        dur = len(self.buf) / self.sr
        a = int(t_frac * dur * self.sr); b = min(len(self.buf), a + int(0.28 * self.sr))
        return onset_start(self.buf, a, b) / self.sr

    def _beat_of(self, pt, t_frac, beat_len):
        """Grid-authoritative beat if the point is locked (edited on the Studio grid), else the beat
        of the DRAWN position — the dot's exact x drives the beat so even a tiny drag moves the grid
        (the audio slice `src_t` stays onset-refined so play-original still grabs the real sound)."""
        if pt is not None and pt.get("beat") is not None:
            return float(pt["beat"]), float(pt["beat"]) * beat_len
        drawn_t = t_frac * (len(self.buf) / self.sr)      # exact drawn time → beat (fine, no onset snap)
        return (drawn_t - self.canvas.grid_off) / beat_len, self._src_t(t_frac)   # relative to the moved grid

    def _lane_events(self, tr):
        self._ensure_pt_ids(tr)
        lid = tr.setdefault("lane_id", uid("R"))
        beat_len = 60.0 / self.bpm; synth = (tr["kind"] == "synth")
        is_orig = (tr["kind"] == "original")   # play YOUR recorded sound (through the FX rack)
        is_hum = (tr["kind"] == "hum")
        # each voice family reads its OWN knob dict as sound_params (synth→params, hum→hum_params)
        if synth:
            sparams = dict(tr.get("params") or {})
        elif is_hum:
            sparams = dict(tr.get("hum_params") or {})
        else:
            sparams = {}
        # a whole SOUNDWAVE can be soloed/muted → every track bound to it inherits that at render
        tk = next((t for t in self.takes if t["id"] == tr.get("take")), None)
        lane = Lane(id=lid, src_master=lid, kind=tr["kind"], sound=tr["sound"],
                    sound_b=(tr.get("sound_b", "") if synth else ""),
                    name=tr["name"], auto=True, has_original=True, play_original=is_orig,
                    muted=bool(tk and tk.get("muted")), solo=bool(tk and tk.get("solo")),
                    color=tr["color"].name() if hasattr(tr["color"], "name") else str(tr.get("color", "")),
                    sound_params=sparams,
                    sound_b_params=dict(tr.get("params_b") or {}) if synth else {},
                    lo_note=int(tr.get("lo_note", 48)), hi_note=int(tr.get("hi_note", 72)),
                    fx=dict(tr.get("fx") or {}) if is_orig else {},
                    mix=dict(tr.get("mix") or {}))       # per-track 8-knob MIX (applied at render)
        pts = sorted(tr["points"], key=lambda p: p["t"])
        events = []
        if is_orig:
            # ORIGINAL: play your WHOLE recording through the FX rack — no points to draw. It sits on
            # top of the soundwave, from the start, spanning the whole take (its length).
            dur = len(self.buf) / self.sr
            events.append(Event(lane_id=lid, beat=0.0, pitch=None, vel=0.95,
                                length=max(0.05, dur / beat_len),
                                src_t=0.0, src_dur=dur, src_track=lid, src_pts=[]))
        elif synth:
            # SYNTH SIREN: the WHOLE drawn line is ONE continuous, sustained morphing note. Height is
            # the morph/pitch (0 = Base @ lo_note, 1 = Modulator @ hi_note), NOT volume. It plays
            # across the drawn span, gliding pitch+timbre along the curve.
            if len(pts) < 1:
                return None, []
            grid, val = self._sample_curve(tr)
            if grid is None:
                return None, []
            dur = len(self.buf) / self.sr               # take length in SECONDS
            t0, t1 = float(pts[0]["t"]), float(pts[-1]["t"])
            if t1 <= t0:                                # a single dot → a short steady tone
                t1 = min(1.0, t0 + 0.05)
            mask = (grid >= t0 - 1e-6) & (grid <= t1 + 1e-6)
            seg = val[mask] if mask.any() else np.array([pts[0]["v"]], np.float32)
            k = max(2, min(400, int((t1 - t0) * dur / 0.02)))
            env = np.interp(np.linspace(0, 1, k), np.linspace(0, 1, len(seg)), seg)
            beat, src_t = self._beat_of(pts[0], t0, beat_len)
            # length in BEATS = span in seconds / beat_len (NOT the raw take-fraction — that made the
            # Studio note a couple of frames instead of the whole drawn span).
            length = max(0.05, (t1 - t0) * dur / beat_len)
            events.append(Event(lane_id=lid, beat=beat, pitch=None, vel=0.9,
                                length=length, src_t=src_t, src_dur=0.28,
                                env=[round(float(x), 3) for x in env],
                                src_track=lid, src_pts=[p["id"] for p in pts]))
        else:
            # INSTRUMENT: points are BEAT MARKS. A lone point = a one-shot hit (velocity = its 0–10
            # height). A LINE between points (a tied run in the NOTES view) means the note sustains:
            #   • HELD segment (straight)  → a piano-roll bar: a steady note that lasts until the next
            #   • GLIDE segment (curved)   → the pitch SLIDES; consecutive glides merge into one note
            # No line = the point plays its natural length (a kick decays, a piano rings).
            dur = len(self.buf) / self.sr

            def _hit(pt):
                beat, src_t = self._beat_of(pt, pt["t"], beat_len)
                return Event(lane_id=lid, beat=beat, vel=max(0.2, min(1.0, pt["v"])),
                             pitch=int(pt.get("midi", DEF_MIDI)),
                             src_t=src_t, src_dur=0.28, src_track=lid, src_pts=[pt["id"]])

            for run in self._tied_runs([p for p in pts if p["v"] > SILENCE]):
                if len(run) == 1:
                    events.append(_hit(run[0])); continue
                n = len(run); i = 0; consumed_last = False
                while i < n - 1:
                    a = run[i]
                    if a.get("glide"):                         # merge a chain of glide segments
                        j = i
                        while j < n - 1 and run[j].get("glide"):
                            j += 1
                        beat, src_t = self._beat_of(a, a["t"], beat_len)
                        length = max(0.05, (float(run[j]["t"]) - float(a["t"])) * dur / beat_len)
                        events.append(Event(lane_id=lid, beat=beat, vel=max(0.2, min(1.0, a["v"])),
                                            pitch=int(a.get("midi", DEF_MIDI)), length=length,
                                            pitch_track=self._pitch_track_of(run[i:j + 1]),
                                            src_t=src_t, src_dur=0.28, src_track=lid,
                                            src_pts=[p["id"] for p in run[i:j + 1]]))
                        i = j; consumed_last = (j == n - 1)
                    else:                                      # held: a bar lasting until the next point
                        beat, src_t = self._beat_of(a, a["t"], beat_len)
                        length = max(0.05, (float(run[i + 1]["t"]) - float(a["t"])) * dur / beat_len)
                        events.append(Event(lane_id=lid, beat=beat, vel=max(0.2, min(1.0, a["v"])),
                                            pitch=int(a.get("midi", DEF_MIDI)), length=length,
                                            src_t=src_t, src_dur=0.28, src_track=lid, src_pts=[a["id"]]))
                        i += 1
                if i == n - 1 and not consumed_last:           # the last note rings out naturally
                    events.append(_hit(run[n - 1]))
        return (lane, events) if events else (None, [])

    def build(self):
        lanes, events = [], []
        for tr in self.tracks:
            if not tr["visible"]:
                continue
            lane, ev = self._lane_events(tr)
            if lane:
                lanes.append(lane); events.extend(ev)
        return lanes, events
