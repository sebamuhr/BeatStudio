"""The timeline canvas.

Uses QGraphicsView with an OpenGL viewport. We custom-paint the grid + events in
drawBackground(), which Qt only calls for the *exposed* rectangle — so scrolling and
zooming never repaint the whole (potentially huge) timeline. That is the fix for the
browser's full-canvas-repaint stutter.
"""
from __future__ import annotations
import os
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PySide6.QtCore import Qt, QRectF, QPointF, Signal

from . import theme
from .model import Project, Event

try:
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
    _HAS_GL = True
except Exception:                       # pragma: no cover
    _HAS_GL = False


class TimelineView(QGraphicsView):
    scrolled = Signal()
    edited = Signal()               # project data changed (add/move/delete a beat)
    selection_changed = Signal()
    resized = Signal()
    committed = Signal()                 # a gesture finished → snapshot for undo
    context_requested = Signal(object)   # global QPoint for the per-beat EQ popover

    def __init__(self, project: Project):
        super().__init__()
        self.project = project
        self.ppb = float(theme.PPB_DEFAULT)
        self.playhead_beat: float | None = None
        self.selected: set[str] = set()
        self.mirror = None          # (scene_x, scene_y) "you are here" circle from the minimap
        self.live_markers = []      # [(lane_index, beat)] shown while recording
        self.rec_wave = None        # (lane_index, start_beat, head_beat, env list) live waveform
        self.rec_clip = False       # peak near 1.0 → draw the wave red (too loud)
        self._drag = None           # (event, moved?)
        self._marquee = None        # (lane_index, x0, x1)
        self.vol_lanes: set[str] = set()   # lane ids whose volume-automation line is shown
        self._vol_drag = None       # (lane, point_dict) while dragging a volume node
        self.VOL_MAX = 1.5          # gain at the top of a lane row (1.0 = unity, 0 = silent)
        self.setMouseTracking(True)
        self.setDragMode(QGraphicsView.NoDrag)
        # Pin the scene to the top-left; otherwise QGraphicsView CENTERS content that's
        # smaller than the viewport, so the lane rows drift out of line with the headers.
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        if _HAS_GL and not os.environ.get("BEAT_NO_GL"):
            self.setViewport(QOpenGLWidget())
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)   # tracks scroll with headers
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.setBackgroundBrush(QBrush(theme.PANEL))
        self.horizontalScrollBar().valueChanged.connect(lambda *_: self.scrolled.emit())
        self.verticalScrollBar().valueChanged.connect(lambda *_: self.scrolled.emit())
        self._refresh_scene_rect()

    # ---- geometry ----
    def x_of_beat(self, beat: float) -> float:
        return theme.PAD + beat * self.ppb

    def beat_of_x(self, x: float) -> float:
        return (x - theme.PAD) / self.ppb

    def content_height(self) -> float:
        return len(self.project.lanes) * theme.LANE_H

    def _refresh_scene_rect(self):
        total_beats = max(16, self.project.max_beat() + 5)
        w = theme.PAD * 2 + total_beats * self.ppb
        h = max(self.content_height(), 1)
        self._scene.setSceneRect(0, 0, w, h)

    def set_project(self, project: Project):
        self.project = project
        self._refresh_scene_rect()
        self.viewport().update()

    def set_ppb(self, ppb: float):
        self.ppb = max(8.0, min(600.0, ppb))
        self._refresh_scene_rect()
        self.viewport().update()

    def set_playhead(self, beat: float | None):
        self.playhead_beat = beat
        self.viewport().update()

    # ---- painting (only the exposed rect) ----
    def drawBackground(self, p: QPainter, rect: QRectF):
        p.fillRect(rect, theme.PANEL)
        proj = self.project
        ppb = self.ppb
        laneH = theme.LANE_H
        n = len(proj.lanes)

        # lane row stripes (only the visible ones)
        first = max(0, int(rect.top() // laneH))
        last = min(n, int(rect.bottom() // laneH) + 1)
        for i in range(first, last):
            top = i * laneH
            stripe = QColor(255, 255, 255, 9 if i % 2 else 3)
            p.fillRect(QRectF(rect.left(), top, rect.width(), laneH), stripe)
            if proj.lanes[i].kind == "synth":
                p.fillRect(QRectF(rect.left(), top, rect.width(), laneH), QColor(124, 92, 255, 13))
            p.setPen(QPen(QColor(255, 255, 255, 12), 1))
            p.drawLine(int(rect.left()), int(top), int(rect.right()), int(top))

        # vertical grid lines across the visible x-range
        g = proj.grid or 4
        b0 = max(0, int(self.beat_of_x(rect.left())) - 1)
        b1 = int(self.beat_of_x(rect.right())) + 2
        H = self.content_height()
        for b in range(b0, b1):
            x = self.x_of_beat(b)
            for k in range(1, g):
                xs = x + k * ppb / g
                p.setPen(QPen(QColor(255, 255, 255, 7), 1))
                p.drawLine(QRectF(xs, 0, 0, H).topLeft(), QRectF(xs, H, 0, 0).topLeft())
            bar = (b % theme.BEATS_PER_BAR) == 0
            p.setPen(QPen(QColor(255, 255, 255, 46 if bar else 15), 1))
            p.drawLine(int(x), 0, int(x), int(H))

        # events
        idx = {l.id: i for i, l in enumerate(proj.lanes)}
        for e in proj.events:
            i = idx.get(e.lane_id)
            if i is None or i < first - 1 or i > last:
                continue
            lane = proj.lanes[i]
            r = self._event_rect(e, i)
            if r.right() < rect.left() or r.left() > rect.right():
                continue
            p.setBrush(QBrush(theme.lane_color_of(lane, i)))
            p.setPen(Qt.NoPen)
            p.setOpacity(0.30 if lane.muted else 0.95)
            p.drawRoundedRect(r, 3, 3)
            if e.id in self.selected:
                p.setOpacity(1.0); p.setBrush(Qt.NoBrush)
                p.setPen(QPen(theme.ACCENT_CY, 2))
                p.drawRoundedRect(r.adjusted(-1.5, -1.5, 1.5, 1.5), 4, 4)
        p.setOpacity(1.0)

    def drawForeground(self, p: QPainter, rect: QRectF):
        proj = self.project
        H = self.content_height()
        # loop region highlight
        if proj.loop_on and proj.loop_start is not None and proj.loop_end and proj.loop_end > proj.loop_start:
            xs = self.x_of_beat(proj.loop_start); xe = self.x_of_beat(proj.loop_end)
            p.fillRect(QRectF(xs, 0, xe - xs, H), QColor(61, 214, 255, 24))
            p.setPen(QPen(theme.ACCENT_CY, 2))
            p.drawLine(int(xs), 0, int(xs), int(H)); p.drawLine(int(xe), 0, int(xe), int(H))
        # start line (dashed red)
        xs = self.x_of_beat(proj.start_at)
        pen = QPen(QColor(255, 93, 93, 115), 1.5)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.drawLine(int(xs), 0, int(xs), int(H))
        # playhead
        if self.playhead_beat is not None:
            x = self.x_of_beat(self.playhead_beat)
            p.setPen(QPen(theme.REC, 2))
            p.drawLine(int(x), 0, int(x), int(H))
        # live recording waveform (so you can calibrate your volume). li == -1 → master:
        # draw it full-height across the whole grid since there's no single lane yet.
        if self.rec_wave is not None:
            li, sb, hb, env = self.rec_wave
            if env is not None and len(env) and hb > sb:
                laneH = theme.LANE_H
                if li < 0:
                    half = max(20.0, self.content_height() / 2); cy = self.content_height() / 2
                else:
                    half = laneH / 2 - 3; cy = li * laneH + laneH / 2
                x0 = self.x_of_beat(sb); x1 = self.x_of_beat(hb)
                col = QColor(255, 93, 93) if self.rec_clip else QColor(61, 214, 255)
                p.setPen(QPen(col, 1))
                n = len(env); span = x1 - x0
                cols = max(1, min(int(span), 1400))
                for c in range(cols):
                    a = int(c / cols * n); b = max(a + 1, int((c + 1) / cols * n))
                    mx = max(env[a:b]) if b <= n else 0.0
                    yy = min(half, mx * half * 3.0)
                    x = x0 + c / cols * span
                    p.drawLine(int(x), int(cy - yy), int(x), int(cy + yy))
        # live recording markers
        for li, beat in self.live_markers:
            x = self.x_of_beat(beat)
            top = li * theme.LANE_H
            p.setBrush(QColor(255, 255, 255, 220)); p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(x, top + theme.LANE_H * 0.29, max(3, self.ppb / 5), theme.LANE_H * 0.42), 3, 3)
        # marquee selection rectangle
        if self._marquee is not None:
            i, x0, x1 = self._marquee
            top = i * theme.LANE_H
            p.fillRect(QRectF(min(x0, x1), top, abs(x1 - x0), theme.LANE_H), QColor(61, 214, 255, 30))
            p.setPen(QPen(QColor(61, 214, 255, 140), 1))
            p.drawRect(QRectF(min(x0, x1), top, abs(x1 - x0), theme.LANE_H))
        # volume automation lines (only the lanes with V toggled on)
        if self.vol_lanes:
            for i, lane in enumerate(proj.lanes):
                if lane.id in self.vol_lanes:
                    self._draw_vol_lane(p, i, lane, rect)
        # mirror of the minimap dot ("you are here")
        if self.mirror is not None:
            mx, my = self.mirror
            p.setBrush(QColor(61, 214, 255, 22)); p.setPen(QPen(QColor(61, 214, 255, 130), 2))
            p.drawEllipse(QPointF(mx, my), 48, 48)
            p.setBrush(QColor(61, 214, 255, 160)); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(mx, my), 5, 5)

    # ---- volume automation geometry ----
    _VOL_PAD = 7.0

    def _vol_y_of(self, i, v):
        top = i * theme.LANE_H + self._VOL_PAD
        h = theme.LANE_H - 2 * self._VOL_PAD
        frac = 1.0 - max(0.0, min(self.VOL_MAX, v)) / self.VOL_MAX
        return top + frac * h

    def _vol_v_of(self, i, y):
        top = i * theme.LANE_H + self._VOL_PAD
        h = theme.LANE_H - 2 * self._VOL_PAD
        frac = (y - top) / max(1.0, h)
        return max(0.0, min(self.VOL_MAX, (1.0 - frac) * self.VOL_MAX))

    def _draw_vol_lane(self, p, i, lane, rect):
        pts = sorted(lane.vol_pts or [], key=lambda q: q["beat"])
        col = theme.lane_color_of(lane, i)
        line = QColor(col); line.setAlpha(230)
        # unity reference line
        yu = self._vol_y_of(i, 1.0)
        up = QPen(QColor(255, 255, 255, 40), 1); up.setStyle(Qt.DashLine)
        p.setPen(up); p.drawLine(int(rect.left()), int(yu), int(rect.right()), int(yu))
        # the envelope polyline (flat unity when empty)
        p.setPen(QPen(line, 2))
        if not pts:
            p.drawLine(int(rect.left()), int(yu), int(rect.right()), int(yu))
            return
        x0 = self.x_of_beat(pts[0]["beat"]); y0 = self._vol_y_of(i, pts[0]["v"])
        p.drawLine(int(rect.left()), int(y0), int(x0), int(y0))     # hold before first
        prev = (x0, y0)
        for q in pts[1:]:
            x = self.x_of_beat(q["beat"]); y = self._vol_y_of(i, q["v"])
            p.drawLine(int(prev[0]), int(prev[1]), int(x), int(y))
            prev = (x, y)
        p.drawLine(int(prev[0]), int(prev[1]), int(rect.right()), int(prev[1]))  # hold after last
        # nodes
        p.setBrush(QBrush(QColor(col))); p.setPen(QPen(QColor("#0b0b12"), 1.5))
        for q in pts:
            x = self.x_of_beat(q["beat"]); y = self._vol_y_of(i, q["v"])
            p.drawEllipse(QPointF(x, y), 4.5, 4.5)

    def _vol_node_at(self, sp):
        """Return (lane, point_dict, index) for a volume node under the scene point, else None."""
        i = int(sp.y() // theme.LANE_H)
        if i < 0 or i >= len(self.project.lanes):
            return None
        lane = self.project.lanes[i]
        if lane.id not in self.vol_lanes:
            return None
        for q in (lane.vol_pts or []):
            x = self.x_of_beat(q["beat"]); y = self._vol_y_of(i, q["v"])
            if abs(x - sp.x()) <= 7 and abs(y - sp.y()) <= 7:
                return (lane, q, i)
        return None

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.resized.emit()

    # ---- hit testing + editing ----
    def _event_rect(self, e, i) -> QRectF:
        laneH = theme.LANE_H
        ppb = self.ppb
        lane = self.project.lanes[i]
        x = self.x_of_beat(self.project.snap(e.beat))
        top = i * laneH
        if lane.kind == "synth" and e.length:
            hh = 14.0
            w = max(8.0, e.length * ppb)
        else:
            hh = max(10.0, laneH * 0.42)
            w = e.length * ppb if (e.length and e.length * ppb > 11) else max(9.0, ppb / 4 - 3)
        y = top + (laneH - hh) / 2
        return QRectF(x, y, w, hh)

    def _event_at(self, sp):
        i = int(sp.y() // theme.LANE_H)
        if i < 0 or i >= len(self.project.lanes):
            return None
        lane_id = self.project.lanes[i].id
        for e in self.project.events:
            if e.lane_id != lane_id:
                continue
            if self._event_rect(e, i).adjusted(-3, -3, 3, 3).contains(sp):
                return e
        return None

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return super().mousePressEvent(ev)
        sp = self.mapToScene(ev.position().toPoint())
        i = int(sp.y() // theme.LANE_H)
        if i < 0 or i >= len(self.project.lanes):
            return super().mousePressEvent(ev)
        lane = self.project.lanes[i]
        if lane.id in self.vol_lanes:          # volume-line editing takes over this lane
            hit = self._vol_node_at(sp)
            if hit is not None:
                self._vol_drag = (hit[0], hit[1])
            else:
                q = {"beat": self.project.snap(self.beat_of_x(sp.x())),
                     "v": round(self._vol_v_of(i, sp.y()), 3)}
                lane.vol_pts.append(q)
                self._vol_drag = (lane, q)
            self.viewport().update()
            ev.accept()
            return
        e = self._event_at(sp)
        if e is not None:
            self.selected = {e.id}
            self._drag = [e, False]
            self.selection_changed.emit()
            self.viewport().update()
        else:
            # start a marquee; a click that doesn't drag becomes an add on release
            self._marquee = [i, sp.x(), sp.x()]
            self.selected = set()
            self.selection_changed.emit()
            self.viewport().update()
        ev.accept()

    def mouseMoveEvent(self, ev):
        if self._vol_drag and (ev.buttons() & Qt.LeftButton):
            lane, q = self._vol_drag
            sp = self.mapToScene(ev.position().toPoint())
            i = self.project.lanes.index(lane)
            q["beat"] = self.project.snap(max(0.0, self.beat_of_x(sp.x())))
            q["v"] = round(self._vol_v_of(i, sp.y()), 3)
            self.viewport().update()
            self.edited.emit()
            ev.accept()
            return
        if self._drag and (ev.buttons() & Qt.LeftButton):
            e = self._drag[0]
            sp = self.mapToScene(ev.position().toPoint())
            nb = self.project.snap(self.beat_of_x(sp.x()))
            i = int(sp.y() // theme.LANE_H)
            if 0 <= i < len(self.project.lanes):
                e.lane_id = self.project.lanes[i].id
            if nb != e.beat:
                e.beat = nb
                self._drag[1] = True
            self._refresh_scene_rect()
            self.viewport().update()
            self.edited.emit()
            ev.accept()
            return
        if self._marquee and (ev.buttons() & Qt.LeftButton):
            sp = self.mapToScene(ev.position().toPoint())
            self._marquee[2] = sp.x()
            self._select_in_marquee()
            self.viewport().update()
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        committed = False
        if self._vol_drag is not None:
            self._vol_drag = None
            self.committed.emit()
            super().mouseReleaseEvent(ev)
            return
        if self._marquee is not None:
            i, x0, x1 = self._marquee
            if abs(x1 - x0) < 4:            # a click, not a drag → add a beat
                lane = self.project.lanes[i]
                e = Event(lane_id=lane.id, beat=self.project.snap(self.beat_of_x(x0)), vel=0.85)
                self.project.events.append(e)
                self.selected = {e.id}
                self._refresh_scene_rect(); self.edited.emit(); self.selection_changed.emit()
                committed = True
            self._marquee = None
            self.viewport().update()
        if self._drag and self._drag[1]:
            committed = True
        self._drag = None
        if committed:
            self.committed.emit()
        super().mouseReleaseEvent(ev)

    def _select_in_marquee(self):
        i, x0, x1 = self._marquee
        lo, hi = min(x0, x1), max(x0, x1)
        lane_id = self.project.lanes[i].id
        sel = set()
        for e in self.project.events:
            if e.lane_id != lane_id:
                continue
            x = self.x_of_beat(self.project.snap(e.beat))
            if lo - 4 <= x <= hi + 4:
                sel.add(e.id)
        self.selected = sel
        self.selection_changed.emit()

    def contextMenuEvent(self, ev):
        sp = self.mapToScene(ev.pos())
        node = self._vol_node_at(sp)
        if node is not None:                    # right-click a volume node → delete it
            lane, q, _ = node
            lane.vol_pts.remove(q)
            self.viewport().update(); self.edited.emit(); self.committed.emit()
            ev.accept()
            return
        e = self._event_at(sp)
        if e is None:
            return
        if e.id not in self.selected:
            self.selected = {e.id}
            self.selection_changed.emit()
            self.viewport().update()
        self.context_requested.emit(ev.globalPos())

    def mouseDoubleClickEvent(self, ev):
        sp = self.mapToScene(ev.position().toPoint())
        node = self._vol_node_at(sp)
        if node is not None:                    # double-click a volume node → delete it
            lane, q, _ = node
            lane.vol_pts.remove(q)
            self._vol_drag = None
            self.viewport().update(); self.edited.emit(); self.committed.emit()
            ev.accept()
            return
        e = self._event_at(sp)
        if e is not None:
            self.project.events = [x for x in self.project.events if x.id != e.id]
            self.selected.discard(e.id)
            self._drag = None
            self.viewport().update()
            self.edited.emit()
            self.committed.emit()
            self.selection_changed.emit()
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)

    # ctrl+wheel zoom (keeps the beat under the cursor stable)
    def wheelEvent(self, ev):
        if ev.modifiers() & Qt.ControlModifier:
            anchor_beat = self.beat_of_x(self.mapToScene(ev.position().toPoint()).x())
            factor = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
            before = self.horizontalScrollBar().value()
            self.set_ppb(self.ppb * factor)
            new_x = self.x_of_beat(anchor_beat) - (ev.position().x())
            self.horizontalScrollBar().setValue(int(new_x))
            ev.accept()
        else:
            super().wheelEvent(ev)
