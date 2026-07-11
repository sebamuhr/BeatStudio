"""My Sounds gallery + waveform editor dialog: record your own sounds, trim them, set
base pitch / gain / loop, preview, delete. These become instruments and match targets."""
from __future__ import annotations
import numpy as np
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout, QListWidget, QPushButton,
                               QLabel, QWidget, QSlider, QCheckBox, QSpinBox, QListWidgetItem)
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtCore import Qt, Signal, QRectF, QTimer

from . import theme
from . import synth
from .recorder import Recorder

try:
    import sounddevice as sd
except Exception:
    sd = None


_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(m):
    return f"{_NOTES[int(m) % 12]}{int(m) // 12 - 1}"


class WaveformView(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(150)
        self.sound = None
        self.live_env = None       # while recording: list of per-block RMS
        self.live_clip = False
        self._drag = None

    def set_sound(self, s):
        self.sound = s
        self.live_env = None
        self.update()

    def set_live(self, env, clip=False):
        self.live_env = env
        self.live_clip = clip
        self.update()

    def _x_of(self, t):
        if not self.sound or self.sound.length <= 0:
            return 0
        return t / self.sound.length * self.width()

    def _t_of(self, x):
        if not self.sound or self.width() <= 0:
            return 0
        return max(0.0, min(self.sound.length, x / self.width() * self.sound.length))

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#0d0d12"))
        w, h = self.width(), self.height(); mid = h / 2
        # live recording: draw the incoming envelope so you can calibrate volume
        if self.live_env is not None:
            env = self.live_env
            col = QColor("#ff5d5d") if self.live_clip else QColor("#3dd6ff")
            p.setPen(QPen(col, 1))
            n = len(env)
            if n:
                cols = min(w, 1400)
                for px in range(cols):
                    a = int(px / cols * n); b = max(a + 1, int((px + 1) / cols * n))
                    mx = max(env[a:b]) if b <= n else 0.0
                    yy = min(mid - 3, mx * (mid - 4) * 3.0)
                    x = px / cols * w
                    p.drawLine(int(x), int(mid - yy), int(x), int(mid + yy))
            p.setPen(QColor("#ff5d5d") if self.live_clip else QColor("#5a5a68"))
            p.drawText(8, 16, "● REC — too loud (clipping)" if self.live_clip else "● REC")
            return
        s = self.sound
        if not s or len(s.buf) < 2:
            p.setPen(QColor("#5a5a68")); p.drawText(self.rect(), Qt.AlignCenter, "No sound selected")
            return
        buf = s.buf; N = len(buf)
        p.setPen(QPen(QColor(124, 92, 255, 150), 1))
        step = max(1, N // w)
        for px in range(w):
            a = int(px / w * N); b = min(N, a + step)
            if b <= a:
                continue
            seg = buf[a:b]
            p.drawLine(px, int(mid - abs(seg).max() * (mid - 4)), px, int(mid + abs(seg).max() * (mid - 4)))
        # trim region
        xs, xe = self._x_of(s.trim_start), self._x_of(s.trim_end)
        p.fillRect(QRectF(0, 0, xs, h), QColor(0, 0, 0, 130))
        p.fillRect(QRectF(xe, 0, w - xe, h), QColor(0, 0, 0, 130))
        p.setPen(QPen(theme.ACCENT_CY, 2))
        p.drawLine(int(xs), 0, int(xs), h); p.drawLine(int(xe), 0, int(xe), h)

    def mousePressEvent(self, ev):
        if not self.sound:
            return
        x = ev.position().x()
        self._drag = "start" if abs(x - self._x_of(self.sound.trim_start)) < abs(x - self._x_of(self.sound.trim_end)) else "end"
        self.mouseMoveEvent(ev)

    def mouseMoveEvent(self, ev):
        if not self._drag or not self.sound:
            return
        t = self._t_of(ev.position().x())
        if self._drag == "start":
            self.sound.trim_start = min(t, self.sound.trim_end - 0.01)
        else:
            self.sound.trim_end = max(t, self.sound.trim_start + 0.01)
        self.update(); self.changed.emit()

    def mouseReleaseEvent(self, ev):
        self._drag = None


class SoundsDialog(QDialog):
    def __init__(self, library, play_cb, parent=None):
        super().__init__(parent)
        self.library = library
        self.play_cb = play_cb
        self.recorder = Recorder()
        self.setWindowTitle("My Sounds")
        self.resize(720, 420)
        self.setStyleSheet(f"background:{theme.PANEL.name()};color:#d8d8e0;")

        root = QHBoxLayout(self); root.setContentsMargins(16, 16, 16, 16); root.setSpacing(16)

        # left: list + record/delete
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.setStyleSheet("QListWidget{background:#101016;border:1px solid #2a2a36;border-radius:8px;}"
                                "QListWidget::item:selected{background:#2a2a36;}")
        self.list.currentRowChanged.connect(self._select)
        left.addWidget(self.list, 1)
        self.b_rec = QPushButton("●  Record sound"); self.b_rec.setCursor(Qt.PointingHandCursor)
        self.b_rec.setStyleSheet("QPushButton{background:#ff5d5d;border:none;border-radius:8px;color:#fff;"
                                 "padding:8px;font-weight:600;}")
        self.b_rec.clicked.connect(self._toggle_record)
        self.b_del = QPushButton("Delete"); self.b_del.clicked.connect(self._delete)
        self.b_del.setStyleSheet("QPushButton{background:#16161e;border:1px solid #2a2a36;border-radius:8px;padding:8px;}")
        left.addWidget(self.b_rec); left.addWidget(self.b_del)
        lw = QWidget(); lw.setLayout(left); lw.setFixedWidth(240)
        root.addWidget(lw)

        # poll timer for the live recording waveform
        self._rec_timer = QTimer(self); self._rec_timer.setInterval(40)
        self._rec_timer.timeout.connect(self._poll_record)
        self._play_stream = None

        # right: waveform + controls
        right = QVBoxLayout()
        self.wave = WaveformView(); self.wave.changed.connect(self._save_current)
        right.addWidget(self.wave, 1)
        ctl = QHBoxLayout()
        ctl.addWidget(QLabel("Base pitch"))
        self.pitch = QSpinBox(); self.pitch.setRange(24, 96); self.pitch.setValue(60)
        self.pitch.valueChanged.connect(self._on_pitch)
        self.pitch_lbl = QLabel("C4"); self.pitch_lbl.setStyleSheet("color:#8a8a99;")
        ctl.addWidget(self.pitch); ctl.addWidget(self.pitch_lbl)
        ctl.addSpacing(12); ctl.addWidget(QLabel("Gain"))
        self.gain = QSlider(Qt.Horizontal); self.gain.setRange(10, 300); self.gain.setValue(100); self.gain.setFixedWidth(120)
        self.gain.valueChanged.connect(self._on_gain)
        ctl.addWidget(self.gain)
        self.loop = QCheckBox("Loop"); self.loop.stateChanged.connect(self._on_loop)
        ctl.addWidget(self.loop)
        ctl.addStretch(1)
        self.b_prev = QPushButton("▶ Preview"); self.b_prev.clicked.connect(self._preview)
        self.b_prev.setStyleSheet("QPushButton{background:#16161e;border:1px solid #2a2a36;border-radius:8px;"
                                  "color:#48e08b;padding:6px 12px;font-weight:600;}")
        ctl.addWidget(self.b_prev)
        right.addLayout(ctl)
        rw = QWidget(); rw.setLayout(right)
        root.addWidget(rw, 1)

        self._refresh_list()

    def current(self):
        i = self.list.currentRow()
        return self.library.sounds[i] if 0 <= i < len(self.library.sounds) else None

    def _refresh_list(self):
        cur = self.list.currentRow()
        self.list.blockSignals(True)
        self.list.clear()
        for s in self.library.sounds:
            item = QListWidgetItem(); self.list.addItem(item)
            row = QWidget(); rl = QHBoxLayout(row); rl.setContentsMargins(8, 4, 6, 4); rl.setSpacing(6)
            lab = QLabel(f"{s.name}  ·  {s.length:.2f}s"); lab.setStyleSheet("color:#d8d8e0;background:transparent;")
            play = QPushButton("▶"); play.setFixedSize(24, 24); play.setCursor(Qt.PointingHandCursor)
            play.setStyleSheet("QPushButton{background:#16161e;border:1px solid #2a2a36;border-radius:6px;"
                               "color:#48e08b;font-size:11px;}QPushButton:hover{background:#1e1e28;}")
            play.clicked.connect(lambda _=False, sid=s.id, btn=play: self._toggle_play_sound(sid, btn))
            rl.addWidget(lab, 1); rl.addWidget(play)
            item.setSizeHint(row.sizeHint())
            self.list.setItemWidget(item, row)
        self.list.blockSignals(False)
        if self.library.sounds:
            self.list.setCurrentRow(min(cur if cur >= 0 else 0, len(self.library.sounds) - 1))

    def _select(self, _):
        s = self.current()
        self.wave.set_sound(s)
        if s:
            self.pitch.blockSignals(True); self.pitch.setValue(s.base_pitch); self.pitch.blockSignals(False)
            self.pitch_lbl.setText(note_name(s.base_pitch))
            self.gain.blockSignals(True); self.gain.setValue(int(s.gain * 100)); self.gain.blockSignals(False)
            self.loop.blockSignals(True); self.loop.setChecked(s.loop); self.loop.blockSignals(False)

    def _save_current(self):
        s = self.current()
        if s:
            self.library.save(s)

    def _on_pitch(self, v):
        s = self.current()
        if s:
            s.base_pitch = v; self.pitch_lbl.setText(note_name(v)); self.library.save(s)

    def _on_gain(self, v):
        s = self.current()
        if s:
            s.gain = v / 100.0; self.library.save(s)

    def _on_loop(self, _):
        s = self.current()
        if s:
            s.loop = self.loop.isChecked(); self.library.save(s)

    def _audio_for(self, s):
        """Build the preview buffer, looped a few times when Loop is on."""
        buf = s.trimmed()
        if s.loop and len(buf) > 100:
            return synth.sample_voice(buf, s.base_pitch, s.base_pitch, dur=2.4, vel=1.0, loop=True)
        return buf

    def _stop_playback(self):
        if sd is not None:
            try:
                sd.stop()
            except Exception:
                pass

    def _preview(self):
        s = self.current()
        if s:
            self._stop_playback()
            if sd is not None:
                sd.play(np.ascontiguousarray(self._audio_for(s), dtype="float32"), synth.SR)
            elif self.play_cb:
                self.play_cb(self._audio_for(s))

    def _toggle_play_sound(self, sid, btn):
        s = self.library.get(sid)
        if not s:
            return
        self._stop_playback()
        if sd is not None:
            sd.play(np.ascontiguousarray(self._audio_for(s), dtype="float32"), synth.SR)
        elif self.play_cb:
            self.play_cb(self._audio_for(s))

    def _delete(self):
        s = self.current()
        if s:
            self.library.delete(s.id); self._refresh_list(); self.wave.set_sound(self.current())

    def _toggle_record(self):
        if self.recorder.recording:
            self._rec_timer.stop()
            buf = self.recorder.stop()
            self.b_rec.setText("●  Record sound")
            self.wave.set_live(None)
            if len(buf) > 1000:
                self.library.add(buf, name=f"Sound {len(self.library.sounds) + 1}")
                self._refresh_list(); self.list.setCurrentRow(len(self.library.sounds) - 1)
        else:
            if self.recorder.start():
                self.b_rec.setText("■  Stop")
                self.wave.set_live([])
                self._rec_timer.start()

    def _poll_record(self):
        if self.recorder.recording:
            self.wave.set_live(list(self.recorder.live_env), self.recorder.peak > 0.92)

    def closeEvent(self, ev):
        if self.recorder.recording:
            self.recorder.stop()
        self._rec_timer.stop(); self._stop_playback()
        super().closeEvent(ev)
