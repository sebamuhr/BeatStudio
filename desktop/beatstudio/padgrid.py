"""On-screen 8x5 clip-launch pad grid — mirrors the Akai APC pad grid on the laptop, so you can
perform (and debug) without the hardware. Click a pad to start/stop/switch that column's loop; the
lit state matches the live looper. Column = a track, rows going UP = its variations (main at bottom)."""
from __future__ import annotations
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QPen, QBrush
from PySide6.QtCore import Qt, QRectF, Signal

from . import theme

# 8 column colours (match the APC pad-column palette)
COLS = ["#ff5d5d", "#ff9d3d", "#ffd24d", "#4be08b", "#3dd6ff", "#5c8aff", "#a06cff", "#ff6cf0"]
NCOL, NROW = 8, 5


class PadGrid(QWidget):
    """`provider()` returns the state dict (see MainWindow._pad_state). Emits `pad_hit(index)` on click
    (index 0..39, bottom-left = 0, same layout as the APC)."""
    pad_hit = Signal(int)

    def __init__(self, provider, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.setMinimumSize(380, 236)
        self.setCursor(Qt.PointingHandCursor)
        self._blink = False
        # a lightweight blink for playing pads
        from PySide6.QtCore import QTimer
        self._t = QTimer(self); self._t.setInterval(280)
        self._t.timeout.connect(self._tick); self._t.start()

    def _tick(self):
        self._blink = not self._blink
        self.update()

    def _rects(self):
        gap = 6.0; w, h = self.width(), self.height()
        pw = (w - gap * (NCOL + 1)) / NCOL; ph = (h - gap * (NROW + 1)) / NROW
        for col in range(NCOL):
            for row in range(NROW):
                x = gap + col * (pw + gap)
                y = gap + (NROW - 1 - row) * (ph + gap)     # row 0 at the BOTTOM
                yield col, row, QRectF(x, y, pw, ph)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#0c0c14"))
        s = self.provider() if self.provider else {}
        ntr = s.get("ntracks", 0); active = s.get("active", -1)
        nvar = s.get("nvar", {}); var = s.get("var", {})
        looping = s.get("looping", {}); loop_row = s.get("loop_row", {})
        for col, row, r in self._rects():
            has = col < ntr and row < nvar.get(col, 0)
            if not has:
                p.setBrush(QColor(22, 22, 30)); p.setPen(QPen(QColor(38, 38, 50), 1))
                p.drawRoundedRect(r, 7, 7); continue
            c = QColor(COLS[col])
            playing = looping.get(col) and loop_row.get(col) == row
            if playing:
                if self._blink:
                    p.setBrush(QColor("#ffffff")); p.setPen(QPen(c, 2))
                else:
                    p.setBrush(c); p.setPen(QPen(QColor("#ffffff"), 2))
            elif col == active and row == var.get(col, 0):
                p.setBrush(c); p.setPen(QPen(QColor("#ffffff"), 2))       # active variation
            else:
                cc = QColor(c); cc.setAlpha(120); p.setBrush(cc); p.setPen(QPen(c, 1))
            p.drawRoundedRect(r, 7, 7)

    def mousePressEvent(self, ev):
        pos = ev.position()
        for col, row, r in self._rects():
            if r.contains(pos):
                self.pad_hit.emit(row * NCOL + col)         # index: bottom-left = 0
                return
