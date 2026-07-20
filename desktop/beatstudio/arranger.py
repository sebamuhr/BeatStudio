"""The Studio CLIP ARRANGER — the Studio is now a timeline of CLIPS (sample instances), not beats.
Each lane is a pad column / separator track; each clip is a bar you record by performing on the pads,
placed at the beat you hit it, lasting how long you held it. Phase 1: display + playhead + click-select
+ drag/extend/delete. Loops inside a clip are shown as faint seam lines."""
from __future__ import annotations
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QPen, QBrush
from PySide6.QtCore import Qt, QRectF, QPointF, Signal

from . import theme
from .padgrid import COLS

LANE_H = 54
RULER_H = 22
LEFT_W = 96          # lane-label gutter
PPB = 26.0           # pixels per beat (horizontal zoom)


class ClipArranger(QWidget):
    """`clips`: list of {col, lane_id, variation, start, length, color, name}. Emits `changed` after an
    edit (move/extend/delete) and `selected(clip or None)`."""
    changed = Signal()
    selected = Signal(object)

    def __init__(self, beats_per_bar=lambda: 4, parent=None):
        super().__init__(parent)
        self.clips = []
        self._bpb = beats_per_bar
        self.playhead = None          # beat, or None
        self._sel = None
        self._drag = None             # ("move"|"len", clip, grab_beat)
        self.setMouseTracking(True)
        self.setMinimumHeight(RULER_H + LANE_H * 3 + 20)

    # ---- data ----
    def set_clips(self, clips):
        self.clips = clips
        if self._sel not in clips:
            self._sel = None
        self._resize(); self.update()

    def set_playhead(self, beat):
        self.playhead = beat; self.update()

    def _lanes(self):
        cols = sorted({c["col"] for c in self.clips})
        return cols if cols else [0]

    def _total_beats(self):
        return max([c["start"] + c["length"] for c in self.clips], default=0) + self._bpb() * 2

    def _resize(self):
        self.setMinimumWidth(int(LEFT_W + self._total_beats() * PPB + 20))
        self.setMinimumHeight(RULER_H + LANE_H * max(1, len(self._lanes())) + 20)

    # ---- geometry ----
    def _x_of(self, beat):
        return LEFT_W + beat * PPB

    def _beat_of(self, x):
        return max(0.0, (x - LEFT_W) / PPB)

    def _lane_y(self, col):
        lanes = self._lanes()
        return RULER_H + (lanes.index(col) if col in lanes else 0) * LANE_H

    def _clip_rect(self, c):
        y = self._lane_y(c["col"]) + 6
        return QRectF(self._x_of(c["start"]), y, max(6.0, c["length"] * PPB), LANE_H - 12)

    # ---- paint ----
    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#0d0d14"))
        bpb = self._bpb(); w = self.width()
        # ruler: bar numbers + lines
        p.fillRect(QRectF(0, 0, w, RULER_H), QColor("#12121a"))
        beat = 0; bar = 1
        while self._x_of(beat) < w:
            x = self._x_of(beat)
            is_bar = (beat % bpb == 0)
            p.setPen(QPen(QColor(255, 255, 255, 22 if is_bar else 8), 1))
            p.drawLine(int(x), RULER_H, int(x), self.height())
            if is_bar:
                p.setPen(QPen(QColor("#6a6a7a"), 1)); p.setFont(theme.sans(8))
                p.drawText(QRectF(x + 3, 0, 40, RULER_H), Qt.AlignVCenter | Qt.AlignLeft, str(bar)); bar += 1
            beat += 1
        # lane rows + labels
        lanes = self._lanes()
        for i, col in enumerate(lanes):
            y = RULER_H + i * LANE_H
            p.fillRect(QRectF(0, y, w, LANE_H), QColor(255, 255, 255, 6 if i % 2 else 0))
            p.fillRect(QRectF(0, y, LEFT_W, LANE_H), QColor("#12121a"))
            p.setPen(QPen(QColor(COLS[col % 8]), 3)); p.drawLine(0, y, 0, y + LANE_H)
            nm = next((c["name"] for c in self.clips if c["col"] == col), f"Col {col+1}")
            p.setPen(QPen(QColor("#c0c0cc"), 1)); p.setFont(theme.sans(9, 600))
            p.drawText(QRectF(8, y, LEFT_W - 12, LANE_H), Qt.AlignVCenter | Qt.AlignLeft, nm)
        # clips
        for c in self.clips:
            r = self._clip_rect(c); col = QColor(c.get("color") or COLS[c["col"] % 8])
            sel = (c is self._sel)
            p.setBrush(QColor(col.red(), col.green(), col.blue(), 210 if sel else 150))
            p.setPen(QPen(QColor("#ffffff") if sel else col, 2 if sel else 1))
            p.drawRoundedRect(r, 5, 5)
            # loop seams (each bar-length repeat) — a sample loops to fill the clip
            seam = self._bpb() * PPB
            x = r.left() + seam
            p.setPen(QPen(QColor(0, 0, 0, 70), 1))
            while x < r.right() - 2:
                p.drawLine(QPointF(x, r.top() + 3), QPointF(x, r.bottom() - 3)); x += seam
            p.setPen(QPen(QColor("#12121a"), 1)); p.setFont(theme.sans(8, 700))
            lbl = f"{c['name']}  v{c['variation']+1}"
            p.drawText(r.adjusted(6, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, lbl)
        # playhead
        if self.playhead is not None:
            x = self._x_of(self.playhead)
            p.setPen(QPen(theme.REC, 2)); p.drawLine(int(x), 0, int(x), self.height())
        if not self.clips:
            p.setPen(QPen(QColor("#5a5a6a"), 1)); p.setFont(theme.sans(12))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Record a pad performance (● Record perf.) — your loops land here as clips")
        p.end()

    # ---- edit: click select · drag move · right-edge extend · right-click / Del delete ----
    def _hit(self, pos):
        for c in reversed(self.clips):
            if self._clip_rect(c).contains(pos):
                return c
        return None

    def mousePressEvent(self, ev):
        pos = ev.position(); c = self._hit(pos)
        if ev.button() == Qt.RightButton:
            if c is not None:
                self.clips.remove(c); self._sel = None
                self.changed.emit(); self.selected.emit(None); self._resize(); self.update()
            return
        self._sel = c; self.selected.emit(c)
        if c is not None:
            r = self._clip_rect(c)
            if abs(pos.x() - r.right()) <= 7:            # grab the right edge → change length
                self._drag = ("len", c, self._beat_of(pos.x()))
            else:
                self._drag = ("move", c, self._beat_of(pos.x()) - c["start"])
        self.update()

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._drag is None:
            c = self._hit(pos)
            near = c is not None and abs(pos.x() - self._clip_rect(c).right()) <= 7
            self.setCursor(Qt.SizeHorCursor if near else Qt.ArrowCursor)
            return
        kind, c, grab = self._drag; bpb = self._bpb()
        if kind == "move":
            c["start"] = max(0.0, round((self._beat_of(pos.x()) - grab) / bpb) * bpb)   # snap to bar
        else:
            c["length"] = max(bpb, round((self._beat_of(pos.x()) - c["start"]) / bpb) * bpb)
        self._resize(); self.update()

    def mouseReleaseEvent(self, _):
        if self._drag is not None:
            self._drag = None; self.changed.emit()

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self._sel is not None:
            self.clips.remove(self._sel); self._sel = None
            self.changed.emit(); self.selected.emit(None); self._resize(); self.update()
