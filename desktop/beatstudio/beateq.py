"""Per-beat EQ popover: Tune + Bass/Mid/Treble + Volume, applied to the whole selection.
Opened by right-clicking a beat (or a marquee selection)."""
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QPushButton
from PySide6.QtCore import Qt, Signal

from . import theme


class BeatEQ(QFrame):
    changed = Signal()
    preview = Signal()
    closed = Signal()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self.closed.emit()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup)
        self.targets = []
        self.setStyleSheet(f"background:#13131b;border:1px solid {theme.BORDER_2.name()};border-radius:13px;")
        lay = QVBoxLayout(self); lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(8)
        self.title = QLabel("Beat tone"); self.title.setStyleSheet("color:#e2e2ea;font-size:12px;font-weight:600;")
        lay.addWidget(self.title)
        self.sliders = {}
        for key, name, lo, hi, unit in (("tune", "Tune", -12, 12, " st"),
                                        ("low", "Bass", -12, 12, " dB"),
                                        ("mid", "Mid", -12, 12, " dB"),
                                        ("high", "Treble", -12, 12, " dB"),
                                        ("vol", "Volume", 5, 130, "%")):
            row = QHBoxLayout(); row.setSpacing(8)
            lab = QLabel(name); lab.setFixedWidth(52); lab.setStyleSheet("color:#8a8a99;font-size:11px;")
            s = QSlider(Qt.Horizontal); s.setRange(lo, hi); s.setFixedWidth(150)
            s.setStyleSheet("QSlider::groove:horizontal{height:4px;background:#22222c;border-radius:2px;}"
                            "QSlider::handle:horizontal{width:14px;height:14px;margin:-6px 0;border-radius:7px;"
                            "background:#fff;border:2px solid #3dd6ff;}")
            val = QLabel(""); val.setFixedWidth(42); val.setStyleSheet("color:#8a8a99;font-size:11px;")
            s.valueChanged.connect(lambda v, k=key, u=unit, vl=val: self._on(k, v, u, vl))
            row.addWidget(lab); row.addWidget(s); row.addWidget(val)
            lay.addLayout(row)
            self.sliders[key] = (s, val, unit)
        pv = QPushButton("▶ Preview"); pv.setCursor(Qt.PointingHandCursor)
        pv.setStyleSheet("QPushButton{background:#16161e;border:1px solid #2a2a36;border-radius:8px;"
                         "color:#48e08b;padding:6px 12px;font-size:12px;font-weight:600;}")
        pv.clicked.connect(self.preview.emit)
        lay.addWidget(pv)

    def _fmt(self, key, v, unit):
        return f"{v}{unit}"

    def _set(self, key, v):
        s, val, unit = self.sliders[key]
        s.blockSignals(True); s.setValue(int(v)); val.setText(self._fmt(key, int(v), unit)); s.blockSignals(False)

    def set_targets(self, events):
        self.targets = list(events)
        self.title.setText(f"Beat tone · {len(self.targets)} selected")
        if not self.targets:
            return
        e = self.targets[0]
        self._set("tune", e.tune or 0)
        self._set("low", e.eq.get("low", 0)); self._set("mid", e.eq.get("mid", 0)); self._set("high", e.eq.get("high", 0))
        self._set("vol", round((e.vel or 0.85) * 100))

    def _on(self, key, v, unit, val_label):
        val_label.setText(self._fmt(key, v, unit))
        for e in self.targets:
            if key == "tune":
                e.tune = v
            elif key == "vol":
                e.vel = max(0.05, min(1.3, v / 100.0))
            else:
                e.eq[key] = v
        self.changed.emit()
