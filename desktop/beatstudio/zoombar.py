"""Zoom pill overlay (−, %, +) bottom-right, above the minimap."""
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QLabel
from PySide6.QtCore import Qt

from . import theme


def _btn(txt, w=28):
    b = QPushButton(txt); b.setFixedSize(w, 26); b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet("QPushButton{background:#16161e;border:1px solid #2a2a36;border-radius:7px;"
                    "color:#d8d8e0;font-size:14px;}QPushButton:hover{background:#1e1e28;}")
    return b


class ZoomBar(QFrame):
    def __init__(self, timeline, minimap=None):
        super().__init__(timeline)
        self.timeline = timeline
        self.minimap = minimap
        self.setStyleSheet("background:rgba(16,16,22,0.94);border:1px solid #2a2a36;border-radius:12px;")
        lay = QHBoxLayout(self); lay.setContentsMargins(8, 5, 8, 5); lay.setSpacing(5)
        lbl = QLabel("zoom"); lbl.setStyleSheet("color:#5a5a68;font-size:10px;border:none;")
        self.minus = _btn("−"); self.reset = _btn("100%", 48); self.plus = _btn("+")
        self.reset.setStyleSheet(self.reset.styleSheet().replace("font-size:14px", "font-size:11px;font-weight:600"))
        self.minus.clicked.connect(lambda: self._zoom(1 / 1.2))
        self.plus.clicked.connect(lambda: self._zoom(1.2))
        self.reset.clicked.connect(lambda: (self.timeline.set_ppb(theme.PPB_DEFAULT), self._update()))
        for wdg in (lbl, self.minus, self.reset, self.plus):
            lay.addWidget(wdg)
        timeline.resized.connect(self.reposition)
        self._update()

    def _zoom(self, f):
        self.timeline.set_ppb(self.timeline.ppb * f)
        self._update()

    def _update(self):
        self.reset.setText(f"{int(self.timeline.ppb / theme.PPB_DEFAULT * 100)}%")

    def reposition(self):
        self.adjustSize()
        vp = self.timeline.viewport()
        # Always sit ABOVE the minimap (which grows on hover) so they never overlap.
        if self.minimap is not None:
            top_of_minimap = self.minimap.y()
        else:
            top_of_minimap = vp.height() - 46
        self.move(int(vp.width() - self.width() - 12), int(top_of_minimap - self.height() - 8))
        self.raise_()
