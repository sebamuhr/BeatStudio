"""Bottom-right minimap: an EXACT miniature of the whole grid with a draggable location
dot. Hover the corner to expand; drag the dot to move (it can reach every corner) and a
translucent 'mirror' circle shows the spot on the real grid. Ports the web v0.7.6 minimap.
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
        self._expanded = False
        self._dragging = False
        self._loc = None            # absolute (scene_x, scene_y) while/after dragging
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.resize(34, 34)
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
        if self._expanded:
            w, h, _ = self._map_size(); W, H = w + 2, h + 2
        else:
            W, H = 34, 34
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

    # ---- hover expand/collapse ----
    def enterEvent(self, _):
        self._expanded = True
        self.reposition()
        self._push_mirror()
        self.update()

    def leaveEvent(self, _):
        if self._dragging:
            return
        self._expanded = False
        self.timeline.mirror = None
        self.timeline.viewport().update()
        self.reposition()
        self.update()

    def _on_scroll(self):
        if self._dragging:
            return
        self._loc = None            # follow the view when scrolled by other means
        if self._expanded:
            self._push_mirror()
            self.update()

    def _push_mirror(self):
        self.timeline.mirror = self._loc_now() if self._expanded else None
        self.timeline.viewport().update()

    # ---- paint ----
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self._expanded:
            p.setBrush(QColor(16, 16, 22, 180)); p.setPen(QPen(theme.BORDER_2, 1))
            p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 9, 9)
            p.setPen(QColor("#7a7a88")); p.drawText(self.rect(), Qt.AlignCenter, "⊞")
            return
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
        # location dot
        tw, th = self._totals(); lx, ly = self._loc_now()
        cx = max(6, min(w - 6, lx / tw * w)); cy = max(6, min(h - 6, ly / th * h))
        p.setPen(Qt.NoPen); p.setBrush(QColor(61, 214, 255, 60)); p.drawEllipse(QPointF(cx, cy), 9, 9)
        p.setBrush(theme.ACCENT_CY); p.drawEllipse(QPointF(cx, cy), 6, 6)
        p.setPen(QPen(QColor("#fff"), 2)); p.setBrush(Qt.NoBrush); p.drawEllipse(QPointF(cx, cy), 6, 6)

    # ---- drag ----
    def mousePressEvent(self, ev):
        if self._expanded:
            self._dragging = True
            self._go(ev.position())

    def mouseMoveEvent(self, ev):
        if self._dragging:
            self._go(ev.position())

    def mouseReleaseEvent(self, ev):
        self._dragging = False
        if not self.rect().contains(ev.position().toPoint()):
            self.leaveEvent(None)
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
        tl.mirror = (lx, ly); tl.viewport().update()
        self.update()
