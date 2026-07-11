"""Left track-header column: colour chip, name, subtitle, REC/S/M/gear buttons.

Custom-painted (with click hit-testing) so it stays cheap and scrolls in sync with
the timeline's vertical scroll. Button actions are wired up by the main window.
"""
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QPainterPath
from PySide6.QtCore import Qt, QRectF, Signal

from . import theme

# Header rows must start at y=0 so they line up exactly with the timeline's lane rows
# (the "TRACK · REC · SOLO · MUTE" caption lives in the corner box above, not here).
_HEADER_BAND = 0


class TrackHeaders(QWidget):
    # emitted with (lane_id, action) where action in {rec, solo, mute, gear}
    action = Signal(str, str)
    add_track = Signal()

    def __init__(self, project, timeline):
        super().__init__()
        self.project = project
        self.timeline = timeline
        self.recording_lane = None      # lane id currently recording (row glows red)
        self.setFixedWidth(theme.HEADER_W)
        self._hit = []      # list of (QRectF, lane_id, action)

    def y_offset(self) -> int:
        return self.timeline.verticalScrollBar().value()

    def _btn(self, p, x, y, w, h, label, fg, bg, border, font):
        r = QRectF(x, y, w, h)
        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)
        p.fillPath(path, QBrush(bg))
        p.setPen(QPen(border, 1))
        p.drawPath(path)
        p.setPen(fg)
        p.setFont(font)
        p.drawText(r, Qt.AlignCenter, label)
        return r

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), theme.PANEL)
        self._hit = []
        laneH = theme.LANE_H
        off = self.y_offset()
        p.setPen(QPen(theme.BORDER_2, 1))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())

        for i, lane in enumerate(self.project.lanes):
            top = _HEADER_BAND + i * laneH - off
            if top + laneH < _HEADER_BAND or top > self.height():
                continue
            p.setPen(QPen(QColor(255, 255, 255, 12), 1))
            p.drawLine(0, int(top), self.width(), int(top))
            if lane.id == self.recording_lane:      # recording row glows red
                p.fillRect(QRectF(0, top, self.width(), laneH), QColor(255, 93, 93, 34))
            # colour chip
            lc = theme.lane_color_of(lane, i)
            p.setBrush(QBrush(lc))
            p.setPen(Qt.NoPen)
            chip = QRectF(9, top + laneH / 2 - 5, 10, 10)
            path = QPainterPath(); path.addRoundedRect(chip, 3, 3); p.fillPath(path, QBrush(lc))
            # name + subtitle
            p.setPen(theme.INK)
            p.setFont(theme.sans(10, 600))
            p.drawText(28, int(top + 26), f"{lane.tag} · {lane.name}")
            p.setPen(QColor("#48e08b") if lane.kind != "synth" else QColor("#c0a8ff"))
            p.setFont(theme.mono(8))
            p.drawText(28, int(top + 42), lane.subtitle)
            # Extract / Original toggle for tracks that have an original recording
            if getattr(lane, "has_original", False):
                on = lane.play_original
                ex = self._btn(p, 28, top + 47, 58, 15, "Extract",
                               QColor("#06222b") if not on else theme.INK_DIM,
                               theme.ACCENT_CY if not on else QColor("#16161e"),
                               theme.ACCENT_CY if not on else theme.BORDER_2, theme.mono(8, 600))
                self._hit.append((ex, lane.id, "extract"))
                og = self._btn(p, 90, top + 47, 62, 15, "Original",
                               QColor("#06222b") if on else theme.INK_DIM,
                               theme.ACCENT_CY if on else QColor("#16161e"),
                               theme.ACCENT_CY if on else theme.BORDER_2, theme.mono(8, 600))
                self._hit.append((og, lane.id, "original"))
            # buttons on the right: REC, S, V, M, gear
            bw, bh = 26, 26
            gap = 6
            bx = self.width() - (bw * 5 + gap * 4) - 9
            by = top + laneH / 2 - bh / 2
            rec = self._btn(p, bx, by, bw, bh, "●", theme.REC, QColor(255, 93, 93, 28),
                            QColor(255, 93, 93, 120), theme.mono(9))
            self._hit.append((rec, lane.id, "rec"))
            s = self._btn(p, bx + (bw + gap), by, bw, bh, "S", theme.INK_DIM,
                          QColor("#16161e"), theme.BORDER_2, theme.mono(10, 700))
            self._hit.append((s, lane.id, "solo"))
            # V — show/hide this lane's volume automation line on the timeline
            vol_on = lane.id in getattr(self.timeline, "vol_lanes", set())
            v_bg = theme.ACCENT_CY if vol_on else QColor("#16161e")
            v_fg = QColor("#06222b") if vol_on else theme.INK_DIM
            v = self._btn(p, bx + (bw + gap) * 2, by, bw, bh, "V", v_fg, v_bg,
                          theme.ACCENT_CY if vol_on else theme.BORDER_2, theme.mono(10, 700))
            self._hit.append((v, lane.id, "vol"))
            m_bg = theme.REC if lane.muted else QColor("#16161e")
            m_fg = QColor("#2a0d0d") if lane.muted else theme.INK_DIM
            m = self._btn(p, bx + (bw + gap) * 3, by, bw, bh, "M", m_fg, m_bg,
                          theme.BORDER_2, theme.mono(10, 700))
            self._hit.append((m, lane.id, "mute"))
            g = self._btn(p, bx + (bw + gap) * 4, by, bw, bh, "⚙", theme.INK_DIM,
                          QColor("#16161e"), theme.BORDER_2, theme.mono(11))
            self._hit.append((g, lane.id, "gear"))

        # + New track row
        top = _HEADER_BAND + len(self.project.lanes) * laneH - off
        if top < self.height():
            r = QRectF(9, top + 8, self.width() - 18, 30)
            pen = QPen(QColor("#33333f"), 1); pen.setStyle(Qt.DashLine)
            p.setPen(pen); p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 7, 7)
            p.setPen(QColor("#8a8a99")); p.setFont(theme.sans(10))
            p.drawText(r, Qt.AlignCenter, "+ New track")
            self._hit.append((r, "", "add"))

    def mousePressEvent(self, ev):
        pt = ev.position()
        for r, lane_id, act in self._hit:
            if r.contains(pt):
                if act == "add":
                    self.add_track.emit()
                else:
                    self.action.emit(lane_id, act)
                return
