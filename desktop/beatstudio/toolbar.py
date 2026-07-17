"""Top toolbar: transport, record-master, project info, Save/Grooves/My Sounds."""
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QFrame, QSpinBox
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont

from . import theme


def _icon_btn(txt, tip="", size=54):
    b = QPushButton(txt)
    b.setToolTip(tip)
    b.setFixedSize(size, size)
    b.setCursor(Qt.PointingHandCursor)
    b.setFont(theme.sans(16))
    b.setStyleSheet(
        "QPushButton{background:#101016;border:1px solid #2a2a36;border-radius:12px;color:#d8d8e0;}"
        "QPushButton:hover{background:#16161e;border-color:#3a3a48;}"
        "QPushButton:disabled{color:#4a4a56;border-color:#20202a;}")  # dim but clearly present
    return b


class _LevelMeter(QWidget):
    """Vertical input-level bar shown while recording: green→amber→red, so you can
    calibrate your beatbox volume (aim near the top without hitting red = clipping)."""
    def __init__(self):
        super().__init__()
        self.setFixedSize(60, 54)
        self.level = None
        self.peak = 0.0
        self.hide()

    def set_level(self, level, peak):
        if level is None:
            self.hide(); self.level = None; return
        self.level = level
        self.peak = peak or 0.0
        if not self.isVisible():
            self.show()
        self.update()

    def paintEvent(self, _):
        from PySide6.QtGui import QPainter, QColor
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#101016"))
        h = self.height() - 8
        # map RMS (~0..0.4) to a 0..1 bar with headroom
        v = max(0.0, min(1.0, (self.level or 0) / 0.4))
        bar_h = int(h * v)
        clip = self.peak > 0.92
        col = QColor("#ff5d5d") if clip else (QColor("#ffb13d") if v > 0.75 else QColor("#48e08b"))
        p.fillRect(6, 4 + (h - bar_h), 16, bar_h, col)
        p.setPen(QColor("#2a2a36"))
        p.drawRect(6, 4, 16, h)
        p.setPen(QColor("#ff5d5d") if clip else QColor("#5a5a68"))
        p.setFont(mono(8))
        p.drawText(26, 20, "CLIP" if clip else "MIC")
        p.drawText(26, 34, "peak" if not clip else "!!")


def mono(size):
    return theme.mono(size)


class Toolbar(QWidget):
    play = Signal(); stop = Signal(); record_master = Signal()
    open_separator = Signal()
    layout_toggled = Signal()                 # ⊟/⊞ — one-screen (docked) vs two-screen (separate windows)
    fullscreen_toggled = Signal()             # ⛶ — global full screen (both windows), lives here now
    metronome = Signal(); bpm_changed = Signal(int)
    undo = Signal(); redo = Signal(); clear_all = Signal()

    def __init__(self, project):
        super().__init__()
        self.project = project
        self.setFixedHeight(96)
        lay = QHBoxLayout(self); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(10)

        self.b_play = b_play = _icon_btn("▶", "Play / Pause (Space)"); b_play.clicked.connect(self.play.emit)
        b_stop = _icon_btn("■", "Stop"); b_stop.clicked.connect(self.stop.emit)
        self.b_undo = _icon_btn("↺", "Undo (Ctrl+Z)"); self.b_undo.clicked.connect(self.undo.emit)
        self.b_redo = _icon_btn("↻", "Redo (Ctrl+Shift+Z)"); self.b_redo.clicked.connect(self.redo.emit)
        b_clear = _icon_btn("🗑", "Clear all beats"); b_clear.clicked.connect(self.clear_all.emit)
        b_mic = _icon_btn("🎤", "Live monitor")
        self.b_metro = _icon_btn("♩", "Metronome"); self.b_metro.clicked.connect(self.metronome.emit)
        for b in (b_play, b_stop, self.b_undo, self.b_redo, b_clear, b_mic, self.b_metro):
            lay.addWidget(b)

        # beat LED — blinks on every beat while recording (visual metronome)
        self.led = QLabel(); self.led.setFixedSize(20, 54); self.led.setAlignment(Qt.AlignCenter)
        self._led_on = False; self._led_accent = False
        self._paint_led()
        lay.addWidget(self.led)
        self._led_timer = QTimer(self); self._led_timer.setSingleShot(True)
        self._led_timer.timeout.connect(lambda: (setattr(self, "_led_on", False), self._paint_led()))

        # BPM stepper
        self.bpm = QSpinBox(); self.bpm.setRange(40, 240); self.bpm.setValue(project.bpm)
        self.bpm.setFixedHeight(54); self.bpm.setSuffix(" BPM"); self.bpm.setButtonSymbols(QSpinBox.UpDownArrows)
        self.bpm.setStyleSheet(
            "QSpinBox{background:#101016;border:1px solid #2a2a36;border-radius:12px;color:#d8d8e0;"
            "padding:0 10px;font-size:13px;font-weight:600;min-width:88px;}")
        self.bpm.valueChanged.connect(self.bpm_changed.emit)
        lay.addWidget(self.bpm)

        self.rec_master = QPushButton("●  Record master")
        self.rec_master.setFixedHeight(54); self.rec_master.setCursor(Qt.PointingHandCursor)
        self.rec_master.setFont(theme.sans(13, 600))
        self.rec_master.setStyleSheet(
            "QPushButton{background:rgba(124,92,255,0.14);border:1px solid #5a4a8a;"
            "border-radius:12px;color:#c0a8ff;padding:0 16px;}"
            "QPushButton:hover{background:rgba(124,92,255,0.22);}")
        self.rec_master.clicked.connect(self.record_master.emit)
        # Record master lives ONLY on the Separation Board now — keep this widget (its state helpers
        # are still called) but hide it from the main screen.
        self.rec_master.setParent(self); self.rec_master.hide()

        # (The "⊞ Separator" button was removed — the board is always present now, one-screen by
        # default. `open_separator` stays as a signal for the launch/record flow.)

        # live input level meter (only visible while recording)
        self.meter = _LevelMeter()
        lay.addWidget(self.meter)

        lay.addStretch(1)

        self.info = QLabel()
        self.info.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.info.setTextFormat(Qt.RichText)
        lay.addWidget(self.info)

        # Layout toggle: 1 screen (separator + studio stacked in ONE window) / 2 screens (separate windows).
        self.layout_btn = QPushButton("2 screens"); self.layout_btn.setFixedHeight(54)
        self.layout_btn.setCursor(Qt.PointingHandCursor); self.layout_btn.setFont(theme.sans(12, 600))
        self.layout_btn.setToolTip("Toggle layout: one window (stacked) or two separate windows. "
                                   "If the separator was closed, this reopens it.")
        self.layout_btn.setStyleSheet(
            "QPushButton{background:#101016;border:1px solid #2a2a36;border-radius:12px;"
            "color:#d8d8e0;padding:0 16px;}QPushButton:hover{background:#16161e;}")
        self.layout_btn.clicked.connect(self.layout_toggled.emit)
        lay.addWidget(self.layout_btn)

        # Full screen: GLOBAL (was on the board only, so it vanished when the board was closed).
        self.full_btn = QPushButton("⛶ Full screen"); self.full_btn.setFixedHeight(54)
        self.full_btn.setCursor(Qt.PointingHandCursor); self.full_btn.setFont(theme.sans(12, 600))
        self.full_btn.setToolTip("Full screen (F11) — both windows")
        self.full_btn.setStyleSheet(
            "QPushButton{background:#101016;border:1px solid #2a2a36;border-radius:12px;"
            "color:#d8d8e0;padding:0 16px;}QPushButton:hover{background:#16161e;}")
        self.full_btn.clicked.connect(self.fullscreen_toggled.emit)
        lay.addWidget(self.full_btn)

        self.refresh_info()

    def set_layout_mode(self, one_screen: bool):
        self.layout_btn.setText("1 screen" if one_screen else "2 screens")

    def set_fullscreen(self, on: bool):
        self.full_btn.setText("⛶ Exit full screen" if on else "⛶ Full screen")

    def refresh_info(self):
        n = len(self.project.events)
        t = len(self.project.lanes)
        self.info.setText(
            f"<span style='color:#e2e2ea;font-size:16px;font-weight:700'>{n}</span>"
            f"<span style='color:#8a8a99;font-size:11px'> notes</span><br>"
            f"<span style='color:#8a8a99;font-size:11px'>{t} tracks</span>")

    def set_master_recording(self, on: bool):
        if on:
            self.rec_master.setText("●  Recording master…")
            self.rec_master.setStyleSheet(
                "QPushButton{background:#d63a3a;border:1px solid #ff5d5d;border-radius:12px;"
                "color:#fff;padding:0 16px;font-weight:600;}")
        else:
            self.rec_master.setText("●  Record master")
            self.rec_master.setStyleSheet(
                "QPushButton{background:rgba(124,92,255,0.14);border:1px solid #5a4a8a;"
                "border-radius:12px;color:#c0a8ff;padding:0 16px;}"
                "QPushButton:hover{background:rgba(124,92,255,0.22);}")

    def _paint_led(self):
        if self._led_on:
            c = "#ff5d5d" if self._led_accent else "#48e08b"
            self.led.setStyleSheet(f"QLabel{{background:transparent;color:{c};font-size:20px;}}")
            self.led.setText("●")
        else:
            self.led.setStyleSheet("QLabel{background:transparent;color:#26262e;font-size:20px;}")
            self.led.setText("○")

    def pulse_beat(self, accent=False):
        self._led_on = True; self._led_accent = accent
        self._paint_led()
        self._led_timer.start(120)

    def set_rec_level(self, level, peak):
        self.meter.set_level(level, peak)

    def set_playing(self, playing: bool):
        # ▶ while stopped/paused, ⏸ while playing — Stop (■) is a separate button that rewinds.
        self.b_play.setText("⏸" if playing else "▶")
        self.b_play.setToolTip("Pause (Space)" if playing else "Play (Space)")

    def set_undo_state(self, can_undo, can_redo):
        self.b_undo.setEnabled(can_undo); self.b_undo.setStyleSheet(self.b_undo.styleSheet())
        self.b_redo.setEnabled(can_redo)

    def set_metro_active(self, on: bool):
        if on:
            self.b_metro.setStyleSheet(
                "QPushButton{background:rgba(124,92,255,0.22);border:1px solid #7c5cff;"
                "border-radius:12px;color:#c0a8ff;}")
        else:
            self.b_metro.setStyleSheet(
                "QPushButton{background:#101016;border:1px solid #2a2a36;border-radius:12px;color:#d8d8e0;}"
                "QPushButton:hover{background:#16161e;}")
