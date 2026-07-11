"""Bottom track-settings panel: instrument picker (keeps the beats), 3-band EQ,
Test, per-track Record, Delete, Close. Matches the web layout."""
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel,
                               QComboBox, QPushButton, QSlider, QFrame, QCheckBox)
from PySide6.QtCore import Qt, Signal

from . import theme
from .synth import DRUMS, WAVES

# (kind, sound-key, label) for the unified instrument list
ITEMS = ([("drum", k, "Drum — " + k) for k in DRUMS] +
         [("synth", k, "Synth — " + k) for k in WAVES])


class _Slider(QWidget):
    changed = Signal(int)

    def __init__(self, name):
        super().__init__()
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(8)
        lab = QLabel(name); lab.setFixedWidth(44); lab.setStyleSheet("color:#8a8a99;font-size:11px;")
        self.s = QSlider(Qt.Horizontal); self.s.setRange(-12, 12)
        self.s.setStyleSheet(
            "QSlider::groove:horizontal{height:4px;background:#22222c;border-radius:2px;}"
            "QSlider::handle:horizontal{width:14px;height:14px;margin:-6px 0;border-radius:7px;"
            "background:#fff;border:2px solid #ff5d5d;}")
        self.val = QLabel("0 dB"); self.val.setFixedWidth(44)
        self.val.setStyleSheet("color:#8a8a99;font-size:11px;")
        self.s.valueChanged.connect(lambda v: (self.val.setText(f"{v} dB"), self.changed.emit(v)))
        lay.addWidget(lab); lay.addWidget(self.s, 1); lay.addWidget(self.val)

    def set_value(self, v):
        self.s.blockSignals(True); self.s.setValue(int(v)); self.val.setText(f"{int(v)} dB")
        self.s.blockSignals(False)


class SettingsPanel(QFrame):
    changed = Signal()
    delete_requested = Signal(str)
    closed = Signal()
    test_requested = Signal(str)
    record_requested = Signal(str)

    def __init__(self, project):
        super().__init__()
        self.project = project
        self.lane = None
        self.setFixedHeight(210)
        self.setStyleSheet(f"background:{theme.PANEL.name()};border-top:1px solid {theme.BORDER.name()};")

        root = QVBoxLayout(self); root.setContentsMargins(24, 14, 24, 16); root.setSpacing(10)

        # header row
        head = QHBoxLayout()
        self.chip = QLabel(); self.chip.setFixedSize(14, 14)
        self.title = QLabel("settings"); self.title.setStyleSheet("color:#e2e2ea;font-size:14px;font-weight:600;")
        head.addWidget(self.chip); head.addSpacing(6); head.addWidget(self.title); head.addStretch(1)
        self.b_del = QPushButton("Delete track"); self.b_close = QPushButton("Close ✕")
        for b in (self.b_del, self.b_close):
            b.setCursor(Qt.PointingHandCursor); b.setFixedHeight(30)
            b.setStyleSheet("QPushButton{background:#16161e;border:1px solid #2a2a36;border-radius:8px;"
                            "color:#d8d8e0;padding:0 12px;font-size:12px;}QPushButton:hover{background:#1e1e28;}")
        self.b_del.clicked.connect(lambda: self.lane and self.delete_requested.emit(self.lane.id))
        self.b_close.clicked.connect(self.closed.emit)
        self.orig_chk = QCheckBox("Play original take")
        self.orig_chk.setStyleSheet("color:#c0a8ff;font-size:12px;")
        self.orig_chk.stateChanged.connect(self._on_orig)
        head.addWidget(self.orig_chk); head.addSpacing(10)
        head.addWidget(self.b_del); head.addWidget(self.b_close)
        root.addLayout(head)

        # body: left (instrument + EQ), right (recording)
        body = QGridLayout(); body.setHorizontalSpacing(28); body.setVerticalSpacing(6)
        left = QVBoxLayout(); left.setSpacing(6)
        left.addWidget(self._label("Instrument"))
        pick = QHBoxLayout()
        self.items = list(ITEMS)          # extended with My Sounds at runtime
        self.combo = QComboBox()
        self.combo.setFont(theme.sans(12))
        self.combo.setMinimumHeight(32)
        for _, _, lbl in self.items:
            self.combo.addItem(lbl)
        self.combo.setStyleSheet(
            "QComboBox{background:#1c1c26;border:1px solid #3a3a48;border-radius:8px;color:#ffffff;"
            "padding:4px 12px;min-height:24px;}"
            "QComboBox:hover{border-color:#4a4a5a;}"
            "QComboBox::drop-down{border:none;width:24px;}"
            "QComboBox::down-arrow{width:10px;height:10px;}"
            "QComboBox QAbstractItemView{background:#1c1c26;color:#ffffff;"
            "selection-background-color:#3a3a48;outline:none;padding:2px;}")
        self.combo.currentIndexChanged.connect(self._on_instrument)
        self.b_test = QPushButton("▶ Test"); self.b_test.setCursor(Qt.PointingHandCursor)
        self.b_test.setFont(theme.sans(12, 600)); self.b_test.setMinimumHeight(32)
        self.b_test.setStyleSheet("QPushButton{background:#173a2a;border:1px solid #2f7d55;border-radius:8px;"
                                  "color:#6ef0a8;padding:4px 16px;}"
                                  "QPushButton:hover{background:#1e5138;}")
        self.b_test.clicked.connect(lambda: self.lane and self.test_requested.emit(self.lane.id))
        pick.addWidget(self.combo, 1); pick.addWidget(self.b_test)
        left.addLayout(pick)
        left.addSpacing(6)
        left.addWidget(self._label("Instrument EQ"))
        self.eq = {}
        for key, name in (("low", "Bass"), ("mid", "Mid"), ("high", "Treble")):
            sl = _Slider(name); self.eq[key] = sl
            sl.changed.connect(lambda v, k=key: self._on_eq(k, v))
            left.addWidget(sl)
        left.addStretch(1)
        lw = QWidget(); lw.setLayout(left); lw.setFixedWidth(260)
        body.addWidget(lw, 0, 0)

        right = QVBoxLayout(); right.setSpacing(6)
        right.addWidget(self._label("Beatbox recording for this track"))
        box = QFrame(); box.setStyleSheet("border:1px dashed #33333f;border-radius:12px;")
        bl = QVBoxLayout(box); bl.setContentsMargins(10, 18, 10, 18)
        msg = QLabel("No recording yet. Beatbox a part for this track, then extract it.")
        msg.setAlignment(Qt.AlignCenter); msg.setStyleSheet("color:#8a8a99;font-size:12px;border:none;")
        self.b_rec = QPushButton("●  Record beatbox"); self.b_rec.setCursor(Qt.PointingHandCursor)
        self.b_rec.setFixedHeight(42)
        self.b_rec.setStyleSheet("QPushButton{background:#ff5d5d;border:none;border-radius:9px;color:#fff;"
                                 "font-size:13px;font-weight:600;padding:0 20px;}QPushButton:hover{background:#ff6d6d;}")
        self.b_rec.clicked.connect(lambda: self.lane and self.record_requested.emit(self.lane.id))
        bl.addWidget(msg); bl.addSpacing(8)
        brow = QHBoxLayout(); brow.addStretch(1); brow.addWidget(self.b_rec); brow.addStretch(1)
        bl.addLayout(brow)
        right.addWidget(box, 1)
        rw = QWidget(); rw.setLayout(right)
        body.addWidget(rw, 0, 1)
        body.setColumnStretch(1, 1)
        root.addLayout(body)

    def _label(self, t):
        l = QLabel(t); l.setStyleSheet("color:#8a8a99;font-size:11px;border:none;")
        return l

    def set_my_sounds(self, sounds):
        """Append the user's gallery sounds to the instrument picker."""
        self.items = list(ITEMS) + [("sample", "mys:" + s.id, "My — " + s.name) for s in sounds]
        self.combo.blockSignals(True)
        self.combo.clear()
        for _, _, lbl in self.items:
            self.combo.addItem(lbl)
        self.combo.blockSignals(False)
        if self.lane:
            self._select_instrument(self.lane)

    def _select_instrument(self, lane):
        idx = next((i for i, (k, s, _) in enumerate(self.items) if k == lane.kind and s == lane.sound), 0)
        self.combo.blockSignals(True); self.combo.setCurrentIndex(idx); self.combo.blockSignals(False)

    # ---- open / bind ----
    def open_for(self, lane):
        self.lane = lane
        self.chip.setStyleSheet(f"background:{theme.lane_color(self.project.lane_index(lane.id)).name()};border-radius:4px;")
        self.title.setText(f"{lane.id} · {lane.name} — settings")
        self._select_instrument(lane)
        for key in ("low", "mid", "high"):
            self.eq[key].set_value(lane.eq.get(key, 0))
        self.orig_chk.blockSignals(True); self.orig_chk.setChecked(lane.play_original); self.orig_chk.blockSignals(False)
        self.show()

    def _on_instrument(self, idx):
        if not self.lane or idx < 0 or idx >= len(self.items):
            return
        kind, sound, label = self.items[idx]
        self.lane.kind = kind
        self.lane.sound = sound
        self.lane.name = label.split(" — ", 1)[-1]   # keep beats; only the instrument changes
        self.changed.emit()

    def _on_orig(self, _):
        if self.lane:
            self.lane.play_original = self.orig_chk.isChecked()
            self.changed.emit()

    def _on_eq(self, key, v):
        if self.lane:
            self.lane.eq[key] = v
            self.changed.emit()

    def set_recording(self, on: bool):
        self.b_rec.setText("■  Stop recording" if on else "●  Record beatbox")
        if on:
            self.b_rec.setStyleSheet("QPushButton{background:#8a2a2a;border:none;border-radius:9px;"
                                     "color:#fff;font-size:13px;font-weight:600;padding:0 20px;}")
        else:
            self.b_rec.setStyleSheet("QPushButton{background:#ff5d5d;border:none;border-radius:9px;"
                                     "color:#fff;font-size:13px;font-weight:600;padding:0 20px;}"
                                     "QPushButton:hover{background:#ff6d6d;}")
