"""Top ruler with bar numbers — scrolls horizontally in sync with the timeline.
Drag on it to set the loop region; click without dragging clears it."""
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtCore import Qt, Signal

from . import theme


class Ruler(QWidget):
    loop_changed = Signal()

    def __init__(self, timeline):
        super().__init__()
        self.timeline = timeline
        self.setFixedHeight(theme.RULER_H)
        self.setAutoFillBackground(True)
        self._drag_a = None

    def _beat_at(self, x):
        off = self.timeline.horizontalScrollBar().value()
        return self.timeline.project.snap(self.timeline.beat_of_x(x + off))

    def mousePressEvent(self, ev):
        self._drag_a = self._beat_at(ev.position().x())

    def mouseMoveEvent(self, ev):
        if self._drag_a is None:
            return
        b = self._beat_at(ev.position().x())
        p = self.timeline.project
        p.loop_start = min(self._drag_a, b); p.loop_end = max(self._drag_a, b)
        p.loop_on = p.loop_end - p.loop_start > 0.06
        self.timeline.viewport().update(); self.update(); self.loop_changed.emit()

    def mouseReleaseEvent(self, ev):
        p = self.timeline.project
        if self._drag_a is not None and (p.loop_end or 0) - (p.loop_start or 0) <= 0.06:
            p.loop_on = False; p.loop_start = p.loop_end = None
            self.timeline.viewport().update(); self.update(); self.loop_changed.emit()
        self._drag_a = None

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), theme.PANEL)
        tl = self.timeline
        off = tl.horizontalScrollBar().value()
        ppb = tl.ppb
        w = self.width()
        p.setFont(theme.mono(9, 600))
        # which beats are visible
        b0 = max(0, int(tl.beat_of_x(off)) - 1)
        b1 = int(tl.beat_of_x(off + w)) + 2
        for b in range(b0, b1):
            x = tl.x_of_beat(b) - off
            bar = (b % theme.BEATS_PER_BAR) == 0
            p.setPen(QPen(QColor(255, 255, 255, 46 if bar else 15), 1))
            p.drawLine(int(x), 4, int(x), theme.RULER_H)
            if bar:
                p.setPen(QColor("#5a5a68"))
                p.drawText(int(x) + 4, 15, str(b // theme.BEATS_PER_BAR + 1))
        # loop band
        pr = tl.project
        if pr.loop_on and pr.loop_start is not None and pr.loop_end and pr.loop_end > pr.loop_start:
            xs = tl.x_of_beat(pr.loop_start) - off; xe = tl.x_of_beat(pr.loop_end) - off
            p.fillRect(int(xs), 0, int(xe - xs), theme.RULER_H, QColor(61, 214, 255, 90))
        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        p.drawLine(0, theme.RULER_H - 1, w, theme.RULER_H - 1)
