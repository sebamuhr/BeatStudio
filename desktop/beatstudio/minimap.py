"""Bottom-right minimap: an EXACT miniature of the whole grid with a draggable VIEWPORT BOX —
the same box-drag navigator the Separation Board uses, so both windows feel identical. Hover
the corner to expand; drag the box (or click) to pan the grid in both axes.
"""
from __future__ import annotations
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtCore import Qt, QRectF, QPointF

from . import theme

MAX_W, MAX_H = 248, 190
MARGIN = 12


class Minimap(QWidget):
    def __init__(self, timeline):
        super().__init__(timeline)
        self.timeline = timeline
        self._expanded = True        # ALWAYS visible now (like the Separation Board navigator) — no hover
        self._dragging = False
        self._loc = None            # absolute (scene_x, scene_y) while/after dragging
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.zoombar = None          # set by MainWindow so we can keep it stacked above us
        timeline.resized.connect(self.reposition)
        timeline.scrolled.connect(self._on_scroll)

    # ---- geometry ----
    def _totals(self):
        w = max(1.0, self.timeline._scene.sceneRect().width())
        h = max(1.0, self.timeline.content_height())
        return w, h

    def _map_size(self):
        tw, th = self._totals()
        scale = min(MAX_W / tw, MAX_H / th)
        return max(48, round(tw * scale)), max(30, round(th * scale)), scale

    def reposition(self):
        vp = self.timeline.viewport()
        w, h, _ = self._map_size(); W, H = w + 2, h + 2
        self.resize(int(W), int(H))
        self.move(int(vp.width() - W - MARGIN), int(vp.height() - H - MARGIN))
        if self.zoombar is not None:
            self.zoombar.reposition()

    def _loc_now(self):
        if self._loc is not None:
            return self._loc
        tw, th = self._totals()
        tl = self.timeline
        vw, vh = tl.viewport().width(), tl.viewport().height()
        return (min(tw, tl.horizontalScrollBar().value() + vw / 2),
                min(th, tl.verticalScrollBar().value() + vh / 2))

    def _view_box(self, w, h):
        """The visible-viewport rectangle mapped into the minimap (the draggable box)."""
        tw, th = self._totals(); tl = self.timeline
        vw, vh = tl.viewport().width(), tl.viewport().height()
        sx, sy = tl.horizontalScrollBar().value(), tl.verticalScrollBar().value()
        bx = sx / tw * w; by = sy / th * h
        bw = max(6.0, min(w, vw / tw * w)); bh = max(6.0, min(h, vh / th * h))
        bx = min(max(0.0, bx), w - bw); by = min(max(0.0, by), h - bh)
        return QRectF(bx, by, bw, bh)

    def _on_scroll(self):
        if self._dragging:
            return
        self._loc = None            # follow the view when scrolled by other means
        self.update()

    # ---- paint ----
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h, scale = self._map_size()
        p.fillRect(QRectF(0, 0, w, h), QColor(13, 13, 18, 245))
        proj = self.timeline.project; laneH = theme.LANE_H; ppb = self.timeline.ppb
        idx = {l.id: i for i, l in enumerate(proj.lanes)}
        for i in range(len(proj.lanes)):
            ty = (i * laneH) * scale
            p.fillRect(QRectF(0, ty, w, laneH * scale), QColor(255, 255, 255, 13 if i % 2 else 5))
        for e in proj.events:
            i = idx.get(e.lane_id)
            if i is None:
                continue
            x = (theme.PAD + proj.snap(e.beat) * ppb) * scale
            ww = max(1.0, (e.length * ppb * scale if e.length else 1.5))
            ty = (i * laneH) * scale
            p.fillRect(QRectF(x, ty + laneH * scale * 0.25, ww, max(1.0, laneH * scale * 0.5)),
                       theme.lane_color(i))
        p.setPen(QPen(theme.BORDER_2, 1)); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 8, 8)
        # VIEWPORT BOX (drag it to pan) — the same box-drag navigator the Separation Board uses, so
        # both windows feel identical. The box = the region you can currently see, in both axes.
        p.setPen(QPen(theme.ACCENT_CY, 1.4)); p.setBrush(QColor(61, 214, 255, 45))
        p.drawRoundedRect(self._view_box(w, h), 3, 3)

    # ---- drag ----
    def mousePressEvent(self, ev):
        self._dragging = True
        self._go(ev.position())

    def mouseMoveEvent(self, ev):
        if self._dragging:
            self._go(ev.position())

    def mouseReleaseEvent(self, ev):
        self._dragging = False
        self.update()

    def _go(self, pos):
        w, h, _ = self._map_size(); tw, th = self._totals()
        fx = max(0.0, min(1.0, pos.x() / w)); fy = max(0.0, min(1.0, pos.y() / h))
        lx, ly = fx * tw, fy * th
        self._loc = (lx, ly)
        tl = self.timeline
        vw, vh = tl.viewport().width(), tl.viewport().height()
        tl.horizontalScrollBar().setValue(int(max(0, lx - vw / 2)))
        tl.verticalScrollBar().setValue(int(max(0, ly - vh / 2)))
        tl.viewport().update()
        self.update()
