"""Main window — assembles toolbar, ruler, track headers and the timeline with
classic DAW scroll-syncing (ruler follows horizontal scroll, headers follow vertical)."""
import os
import numpy as np
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QGridLayout, QFrame, QFileDialog,
                               QSplitter)
from PySide6.QtGui import QPainter, QPen, QColor, QKeySequence, QShortcut, QAction
from PySide6.QtCore import Qt, QTimer

from . import theme
from .model import Project, demo_project, empty_project, Lane, Event, uid
from .timeline import TimelineView
from .ruler import Ruler
from .headers import TrackHeaders
from .toolbar import Toolbar
from .audio import AudioEngine
from .render import render_project, _voice_for
from . import synth
from .synth import SR, click as synth_click
from .settings import SettingsPanel
from .recorder import Recorder
from .analysis import onsets_from, gate_lin
from .extract import multi_extract, smart_extract, analyze_clusters, build_from_review
from . import groove
from .usermodel import UserModel
from .reviewdialog import ReviewDialog
from .separationboard import SeparationBoard, SILENCE
from .minimap import Minimap
from .beateq import BeatEQ
from .sounds import SoundLibrary
from . import persistence
from . import __version__
import threading

def _interp_v(points, t, default):
    """Value for a new anchor at time-fraction `t`: linearly between its two neighbours (so a beat
    added on the grid lands vertically between the surrounding drawn points)."""
    left = [p for p in points if p["t"] <= t]; right = [p for p in points if p["t"] > t]
    if left and right:
        a = max(left, key=lambda p: p["t"]); b = min(right, key=lambda p: p["t"])
        if b["t"] > a["t"]:
            return a["v"] + (b["v"] - a["v"]) * (t - a["t"]) / (b["t"] - a["t"])
        return a["v"]
    if left:
        return max(left, key=lambda p: p["t"])["v"]
    if right:
        return min(right, key=lambda p: p["t"])["v"]
    return default


_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../desktop
_PROJECTS_DIR = os.path.join(_HERE, "projects")
_MYSOUNDS_DIR = os.path.join(_HERE, "mysounds")


class CornerBox(QFrame):
    def __init__(self):
        super().__init__()
        self.setFixedSize(theme.HEADER_W, theme.RULER_H)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), theme.PANEL)
        p.setPen(QColor("#4a4a56"))
        p.setFont(theme.mono(8, 500))
        p.drawText(11, 16, "TRACK · ● REC · SOLO · MUTE · ⚙")
        p.setPen(QPen(theme.BORDER_2, 1))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


class MainWindow(QMainWindow):
    from PySide6.QtCore import Signal as _Signal
    calc_done = _Signal(object, int)      # (cleaned take array, bpm) after a master recording

    def __init__(self, project: Project | None = None):
        super().__init__()
        self.project = project or empty_project()
        self._set_title()
        self.resize(1440, 900)
        self.setStyleSheet(f"QMainWindow{{background:{theme.BG.name()};}}")

        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        self.toolbar = Toolbar(self.project)

        grid_host = QWidget()
        g = QGridLayout(grid_host); g.setContentsMargins(16, 8, 16, 16); g.setSpacing(0)
        self.timeline = TimelineView(self.project)
        self.ruler = Ruler(self.timeline)
        self.headers = TrackHeaders(self.project, self.timeline)
        g.addWidget(CornerBox(), 0, 0)
        g.addWidget(self.ruler, 0, 1)
        g.addWidget(self.headers, 1, 0)
        g.addWidget(self.timeline, 1, 1)
        g.setColumnStretch(1, 1); g.setRowStretch(1, 1)
        # panel frame around the grid
        grid_host.setStyleSheet("")
        self._grid_host = grid_host
        # The Studio pane = its toolbar + grid kept TOGETHER, so in one-screen mode the toolbar
        # stays attached to the Studio (the board docks ABOVE this whole pane, exactly like the
        # separate window does in two-screen mode) instead of being stranded at the window top.
        studio = QWidget()
        sv = QVBoxLayout(studio); sv.setContentsMargins(0, 0, 0, 0); sv.setSpacing(0)
        sv.addWidget(self.toolbar)
        sv.addWidget(grid_host, 1)
        self._studio_pane = studio
        # A vertical splitter is the home for the studio; in one-screen mode the Separation Board
        # docks ABOVE it (each pane resizable + scrolls on its own, like two windows).
        self._split = QSplitter(Qt.Vertical); self._split.setChildrenCollapsible(False)
        self._split.setHandleWidth(6)
        self._split.addWidget(studio)
        root.addWidget(self._split, 1)
        self._one_screen = True                 # default: separator docked ABOVE the studio (one window)
        self.toolbar.set_layout_mode(True)

        # bottom settings panel (hidden until you open a track's gear)
        self.settings = SettingsPanel(self.project)
        self.settings.hide()
        self.settings.changed.connect(self._on_settings_changed)
        self.settings.delete_requested.connect(self._delete_track)
        self.settings.closed.connect(self.settings.hide)
        self.settings.closed.connect(self._commit)
        self.settings.test_requested.connect(self._test_instrument)
        self.settings.record_requested.connect(self._toggle_record)
        root.addWidget(self.settings)

        # minimap + zoom overlays (bottom-right of the timeline)
        self.minimap = Minimap(self.timeline)
        self.minimap.raise_()
        from .zoombar import ZoomBar
        self.zoombar = ZoomBar(self.timeline, self.minimap)
        self.minimap.zoombar = self.zoombar
        self.zoombar.raise_()

        # scroll syncing
        self.timeline.scrolled.connect(self.ruler.update)
        self.timeline.scrolled.connect(self.headers.update)

        # interactions
        self.headers.action.connect(self._on_header_action)
        self.headers.add_track.connect(self._add_track)
        self.timeline.edited.connect(self._on_edit)
        self.timeline.committed.connect(self._sync_grid_to_board)   # reflect grid moves onto the drawn line
        self.timeline.committed.connect(self._commit)
        self.timeline.selection_changed.connect(self._on_grid_selection)   # link selection to the board
        self.timeline.context_requested.connect(self._open_beat_eq)
        self.beat_eq = BeatEQ(self)
        self.beat_eq.changed.connect(self._on_beat_eq_changed)
        self.beat_eq.preview.connect(self._preview_beat)
        self.beat_eq.closed.connect(self._commit)
        self.toolbar.play.connect(self._toggle_play)
        self.toolbar.stop.connect(self._stop)
        self.toolbar.metronome.connect(self._toggle_metro)
        self.toolbar.bpm_changed.connect(self._set_bpm)
        self.toolbar.record_master.connect(self._toggle_master_record)
        self.toolbar.open_separator.connect(self._open_separator)
        self.toolbar.layout_toggled.connect(self._toggle_layout)
        self.toolbar.fullscreen_toggled.connect(self._toggle_fullscreen)
        self.toolbar.undo.connect(self._undo)
        self.toolbar.redo.connect(self._redo)
        self.toolbar.clear_all.connect(self._clear_beats_confirm)
        self.ruler.loop_changed.connect(self._on_loop_changed)

        # undo/redo state (each entry snapshots BOTH windows: project + board)
        self._committed = self._snapshot()
        self._undo_stack = []
        self._redo_stack = []
        self._refresh_undo_buttons()

        self._build_menu()
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self._toggle_play)
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self._undo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self._redo)
        QShortcut(QKeySequence("Ctrl+Y"), self, activated=self._redo)
        QShortcut(QKeySequence(Qt.Key_F11), self, activated=self._toggle_fullscreen)

        # transport + audio
        self.engine = AudioEngine()
        self.recorder = Recorder()
        self._rec_lane = None
        self._orig_rec = None       # whole-groove master take
        self._lane_audio = {}       # lane_id -> recorded float32 (original take)
        self._spb = 60.0 / max(1, self.project.bpm)
        self._paused_beat = None    # set while the transport is paused, None when stopped/playing
        self.library = SoundLibrary(_MYSOUNDS_DIR)
        self.usermodel = UserModel(os.path.join(_HERE, "usermodel"))   # learns your kit from labels
        self.calc_done.connect(self._on_calc_done)
        self._busy = None
        self._board = None            # the persistent Separation Board (always-on golden surface)
        self._syncing = False         # reentrancy guard for the two-way board<->studio sync
        self._sel_syncing = False     # reentrancy guard for linked beat selection
        self._sync_commit = QTimer(self); self._sync_commit.setSingleShot(True)
        self._sync_commit.setInterval(400); self._sync_commit.timeout.connect(self._commit)
        self._samples = self.library.samples_dict()
        self._timer = QTimer(self); self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._metro_timer = QTimer(self); self._metro_timer.timeout.connect(self._metro_click)
        self._metro_beat = 0
        if not self.engine.available:
            self._set_title("(no audio device: sudo apt install libportaudio2)")

    def _set_title(self, note: str = ""):
        """Show the version so you know which build is live."""
        base = f"Beat Studio · v{__version__}"
        self.setWindowTitle(f"{base}  —  {note}" if note else base)

    def showEvent(self, ev):
        super().showEvent(ev)
        self.minimap.reposition(); self.minimap.raise_()
        self.zoombar.reposition(); self.zoombar.raise_()
        if not getattr(self, "_shown_once", False):        # one-screen default: dock the separator on launch
            self._shown_once = True
            if self._one_screen:
                QTimer.singleShot(0, self._open_separator)

    # ---- menu + persistence ----
    def _build_menu(self):
        m = self.menuBar().addMenu("File")
        for label, key, fn in (("New (clear grid)", "Ctrl+N", self._new_project),
                               ("Clear all beats", "Ctrl+Backspace", self._clear_beats),
                               (None, None, None),
                               ("Open (MIDI / project)…", "Ctrl+O", self._open_project),
                               ("Save (MIDI + project)…", "Ctrl+S", self._save_project),
                               ("Export MIDI (notes only)…", "Ctrl+E", self._export_midi)):
            if label is None:
                m.addSeparator(); continue
            a = QAction(label, self); a.setShortcut(QKeySequence(key)); a.triggered.connect(fn)
            m.addAction(a)
        self.menuBar().setStyleSheet("QMenuBar{background:#0d0d12;color:#c0c0cc;}"
                                     "QMenuBar::item:selected{background:#1e1e28;}"
                                     "QMenu{background:#13131b;color:#d8d8e0;border:1px solid #2a2a36;}"
                                     "QMenu::item:selected{background:#2a2a36;}")

    def _new_project(self):
        self._orig_rec = None; self._lane_audio = {}
        self._load_fresh(empty_project())

    def _clear_beats(self):
        self.project.events = []
        self.timeline.selected = set()
        self.timeline.set_project(self.project)
        self.headers.update(); self.toolbar.refresh_info(); self._commit(); self._rerender_if_playing()

    def _set_project(self, p):
        self._stop()
        self.project = p
        self._spb = 60.0 / max(1, p.bpm)
        self.timeline.set_project(p)
        self.headers.project = p; self.settings.project = p; self.toolbar.project = p
        self.toolbar.bpm.blockSignals(True); self.toolbar.bpm.setValue(p.bpm); self.toolbar.bpm.blockSignals(False)
        self.settings.hide()
        self.headers.update(); self.ruler.update(); self.toolbar.refresh_info()

    def _save_project(self):
        """Save as MIDI (opens in any DAW) + a full-fidelity .beat sidecar (reopens here intact)."""
        os.makedirs(_PROJECTS_DIR, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Save (MIDI + project)",
                                              os.path.join(_PROJECTS_DIR, "groove.mid"),
                                              "MIDI file (*.mid)")
        if path:
            board = self._board.snapshot() if self._board is not None else None
            saved = persistence.save_song(self.project, path, board=board)
            self.statusBar().showMessage(f"Saved {os.path.basename(saved)} (+ .beat project)", 4000)

    def _load_fresh(self, p, board_blob=None):
        self._set_project(p)
        if board_blob is not None:                 # restore the Separation Board (waves, lines, FX)
            takes = board_blob.get("takes") or []
            main = np.asarray(takes[0]["buf"], np.float32) if takes else np.zeros(SR // 2, np.float32)
            self._orig_rec = main                  # so play-original / previews work again
            self._syncing = True                   # keep _make_board's resync from wiping loaded lanes
            try:
                if self._board is None:
                    self._make_board(main, p.bpm)
                self._board.restore(board_blob)
            finally:
                self._syncing = False
            self._resync_all_board()
        self._committed = self._snapshot()
        self._undo_stack.clear(); self._redo_stack.clear()

    def _open_project(self):
        os.makedirs(_PROJECTS_DIR, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(self, "Open (MIDI or project)", _PROJECTS_DIR,
                                              "Song (*.mid *.beat *.json);;All files (*)")
        if path:
            proj, board_blob = persistence.open_song(path)
            self._load_fresh(proj, board_blob)

    def _export_midi(self):
        """Notes-only MIDI export (no .beat sidecar)."""
        path, _ = QFileDialog.getSaveFileName(self, "Export MIDI (notes only)",
                                              os.path.join(_HERE, "groove.mid"), "MIDI file (*.mid)")
        if path:
            persistence.export_midi(self.project, path)

    # ---- header buttons ----
    def _on_header_action(self, lane_id: str, act: str):
        lane = next((l for l in self.project.lanes if l.id == lane_id), None)
        if not lane:
            return
        if act == "mute":
            lane.muted = not lane.muted
            self._rerender_if_playing()
        elif act == "solo":
            lane.solo = not lane.solo
            self._rerender_if_playing()
        elif act == "vol":                 # toggle this lane's volume-automation line
            if lane_id in self.timeline.vol_lanes:
                self.timeline.vol_lanes.discard(lane_id)
            else:
                self.timeline.vol_lanes.add(lane_id)
        elif act == "gear":
            self.settings.open_for(lane)
        elif act == "rec":
            self._toggle_record(lane_id)
        elif act == "extract":
            lane.play_original = False; self._rerender_if_playing()
        elif act == "original":
            lane.play_original = True; self._rerender_if_playing()
        self.headers.update(); self.timeline.viewport().update()

    # ---- recording ----
    def _stop_any_record(self):
        if self._rec_lane == "__master__":
            self._stop_master_record()
        elif self._rec_lane == "__secondary__":
            self._stop_secondary_record()
        else:
            self._stop_record()

    def _toggle_record(self, lane_id: str):
        if self.recorder.recording:
            self._stop_any_record()
        else:
            self._start_record(lane_id)

    def _start_record(self, lane_id: str):
        if not self.recorder.available:
            self._set_title("no mic/audio (sudo apt install libportaudio2)")
            return
        self._stop()
        self._rec_lane = lane_id
        if not self.recorder.start():
            self._rec_lane = None
            return
        self.settings.set_recording(True)
        lane = next((l for l in self.project.lanes if l.id == lane_id), None)
        self.headers.recording_lane = lane_id
        self._set_title(f"● RECORDING “{lane.name if lane else ''}”  (click the red ● again to stop)")
        self.headers.update()
        self.timeline.live_markers = []
        self.timeline.horizontalScrollBar().setValue(int(self.timeline.x_of_beat(self.project.start_at) - 40))
        self._timer.start()
        self._start_beat_clock()

    def _stop_record(self):
        self._metro_timer.stop(); self._timer.stop()
        self.timeline.live_markers = []; self.timeline.rec_wave = None; self.timeline.set_playhead(None)
        self.toolbar.set_rec_level(None, None)
        self.headers.recording_lane = None
        self._set_title()
        buf = self.recorder.stop()
        lane_id, self._rec_lane = self._rec_lane, None
        self.settings.set_recording(False)
        if lane_id is None:
            return
        self._lane_audio[lane_id] = buf
        ons = onsets_from(buf, SR, gate_lin(10))
        spb, sa = self._spb, self.project.start_at
        new = [Event(lane_id=lane_id, beat=self.project.snap(sa + o["t"] / spb),
                     vel=max(0.4, min(1.0, o["amp"])), length=o["dur"] / spb) for o in ons]
        self.project.events = [e for e in self.project.events if e.lane_id != lane_id] + new
        self.timeline._refresh_scene_rect(); self.timeline.viewport().update()
        self.headers.update(); self.toolbar.refresh_info(); self._commit()
        if not new:
            self._set_title("no beats detected (record a bit louder, or check the mic)")

    def _start_beat_clock(self):
        """Beat clock during recording: always blinks the LED; clicks only if the metronome
        is on. (Fixes 'metronome does nothing on record' — now there's always a visual beat.)"""
        self._metro_beat = 0
        self._metro_click()
        self._metro_timer.start(int(self._spb * 1000))

    def _preview_category(self, cat_id):
        """Play the built-in instrument for a questionnaire category so it can be compared."""
        from .usermodel import CAT_BY_ID
        from . import synth
        c = CAT_BY_ID.get(cat_id)
        if not c:
            return
        _id, _lbl, kind, sound, _po = c
        if kind == "drum":
            v = synth.drum(sound, 0.9)
        elif kind == "synth":
            v = synth.synth(sound, synth.midi_to_hz(60), 0.4, 0.9)
        else:
            return
        self.engine.one_shot(v)

    def _metro_click(self):
        accent = (self._metro_beat % 4 == 0)
        self.toolbar.pulse_beat(accent)               # visual LED every beat
        if self.project.metronome:
            self.engine.one_shot(synth_click(accent=accent))
        self._metro_beat += 1

    # ---- master record -> auto-split ----
    def _toggle_master_record(self):
        if self.recorder.recording:
            self._stop_any_record()
        else:
            if not self.recorder.available:
                self._set_title("no mic/audio (sudo apt install libportaudio2)")
                return
            self._stop()
            self._rec_lane = "__master__"
            if not self.recorder.start():
                self._rec_lane = None
                return
            self.toolbar.set_master_recording(True)
            if self._board is not None:
                self._board.set_recording(True)
            self.timeline.live_markers = []
            self._timer.start()
            self._start_beat_clock()

    def _stop_master_record(self):
        self._metro_timer.stop(); self._timer.stop()
        self.timeline.live_markers = []; self.timeline.rec_wave = None; self.timeline.set_playhead(None)
        self.toolbar.set_rec_level(None, None)
        buf = self.recorder.stop()
        self._rec_lane = None
        self.toolbar.set_master_recording(False)
        if self._board is not None:
            self._board.set_recording(False)
        if buf is None or len(buf) < SR // 8:
            self._set_title("recording too short — try again")
            return
        # Compute tempo + a cleaned take OFF the UI thread so the window shows a live
        # "Calculating…" busy dialog instead of freezing. (No CLAP here — the Separation
        # Board is manual now, so we only need bpm + the high-passed audio.)
        self._show_busy("Calculating your take…  (tempo + clean-up)")
        def work():
            try:
                hp = groove.highpass(buf, SR)
                onsets = groove.onsets_from(hp, SR, groove.gate_lin(10))
                bpm = groove.detect_tempo(hp, SR, [o["t"] for o in onsets])
            except Exception:
                hp, bpm = buf, self.project.bpm
            self.calc_done.emit(hp, int(bpm or self.project.bpm))
        threading.Thread(target=work, daemon=True).start()

    def _toggle_secondary_record(self):
        """Overdub: the MAIN take plays in the background while you record an extra sound on top,
        at the same tempo. On stop it's mixed into the board wave (a slave layer of the main)."""
        if self.recorder.recording:
            self._stop_any_record()
            return
        if not self.recorder.available:
            self._set_title("no mic/audio (sudo apt install libportaudio2)")
            return
        if self._board is None:
            return
        self._stop()                                      # clear any transport/preview first
        if self._orig_rec is not None and len(self._orig_rec):   # hear the main while you overdub
            self.engine.set_buffer(np.ascontiguousarray(self._orig_rec, np.float32))
            self.engine.play(0, loop=False)
        self._rec_lane = "__secondary__"
        if not self.recorder.start():
            self._rec_lane = None; self.engine.stop(); return
        self._board.set_recording(True, secondary=True)
        self.timeline.live_markers = []
        self._timer.start(); self._start_beat_clock()

    def _stop_secondary_record(self):
        self._metro_timer.stop(); self._timer.stop(); self.engine.stop()
        self.timeline.rec_wave = None; self.timeline.set_playhead(None)
        self.toolbar.set_rec_level(None, None)
        buf = self.recorder.stop(); self._rec_lane = None
        if self._board is not None:
            self._board.set_recording(False, secondary=True)
        if buf is None or len(buf) < SR // 8:
            self._set_title("overdub too short — try again")
            return
        try:
            hp = groove.highpass(buf, SR)
        except Exception:
            hp = buf
        if self._board is not None:
            self._board.add_take(hp)                      # NEW waveform row (its own colour), same tempo
        # mix it into the master take so ▶ Original / Both play it back too
        if self._orig_rec is None:
            self._orig_rec = np.asarray(hp, np.float32)
        else:
            n = max(len(self._orig_rec), len(hp)); mix = np.zeros(n, np.float32)
            mix[:len(self._orig_rec)] += self._orig_rec; mix[:len(hp)] += hp
            self._orig_rec = np.clip(mix, -1.0, 1.0).astype(np.float32)
        self._set_title("secondary added — draw a track over its row to separate it")

    def _make_board(self, hp, bpm):
        board = SeparationBoard(hp, SR, bpm,
                                instrument_items=self.settings.items,
                                preview_cb=self._preview_instrument,
                                preview_pattern_cb=self._preview_pattern,
                                preview_original_cb=self._preview_original,
                                preview_both_cb=self._preview_both,
                                preview_sound_cb=self._preview_synth_sound,
                                preview_note_cb=self._preview_note,
                                stop_cb=self._stop_preview)
        board.create_requested.connect(self._resync_all_board)   # legacy "resync everything"
        board.record_requested.connect(self._toggle_master_record)
        board.record_secondary_requested.connect(self._toggle_secondary_record)
        board.tracks_changed.connect(self._on_board_track_changed)
        board.take_audio_changed.connect(self._on_take_audio_changed)
        board.bpm_changed.connect(self._on_board_bpm)
        board.point_selected.connect(self._on_board_point_selected)
        board.playhead_moved.connect(self._on_board_playhead)
        self._board = board
        self._resync_all_board()
        if self._one_screen:
            self._dock_board()
        return board

    def _show_board(self):
        """Show/raise the board. In one-screen mode it lives docked in the splitter (always visible);
        in two-screen mode it's a separate window (keep its full-screen state, don't yank it out)."""
        b = self._board
        if b is None:
            return
        if self._one_screen:
            self._dock_board()
            return
        if not b.isVisible():
            b.show()
        b.raise_(); b.activateWindow()

    def _open_separator(self):
        """Open/show the Separation Board. In one-screen mode it docks above the Studio; in two-screen
        mode it's a separate window that keeps all its work between open/close."""
        if self._board is None:
            hp = self._orig_rec if self._orig_rec is not None else np.zeros(SR // 2, np.float32)
            self._make_board(hp, self.project.bpm)
            if self._orig_rec is None:
                self._set_title("Separator open — record a master take to fill it")
        self._show_board()

    # ---- global full screen (both windows) ----
    def _toggle_fullscreen(self):
        on = not self.isFullScreen()
        self.showFullScreen() if on else self.showNormal()
        # In two-screen mode the separator is its OWN window — full-screen it too, so the button
        # really is global (one-screen mode has only this window, so nothing else to flip).
        b = self._board
        if not self._one_screen and b is not None and b.isVisible():
            if bool(getattr(b, "_is_full", False)) != on:
                b._toggle_full()
        self.toolbar.set_fullscreen(on)

    # ---- one-screen (docked) vs two-screen (separate windows) ----
    def _toggle_layout(self):
        # If the separator was CLOSED while in two-screen mode, the screens button just REOPENS it
        # (instead of flipping the layout) — so a stray Close is always recoverable.
        if (not self._one_screen and self._board is not None and not self._board.isVisible()):
            self._show_board()
            return
        self._one_screen = not self._one_screen
        self.toolbar.set_layout_mode(self._one_screen)
        if self._one_screen:
            if self._board is None:
                hp = self._orig_rec if self._orig_rec is not None else np.zeros(SR // 2, np.float32)
                self._make_board(hp, self.project.bpm)     # docks itself (one_screen is set)
            else:
                self._dock_board()
        else:
            self._float_board()

    def _dock_board(self):
        """Embed the board ABOVE the Studio in the splitter (separator on top, studio on bottom)."""
        b = self._board
        if b is None:
            return
        if not getattr(b, "_docked", False):
            if getattr(b, "_is_full", False):
                b.showNormal()
            b.setParent(None); b.setWindowFlag(Qt.Window, False)
            self._split.insertWidget(0, b)               # index 0 = top pane
            h = max(self.centralWidget().height(), 640)
            self._split.setSizes([int(h * 0.5), int(h * 0.5)])
        b.set_docked(True)
        b.show()

    def _float_board(self):
        """Pop the board back out into its own separate window (two-screen mode)."""
        b = self._board
        if b is None:
            return
        if getattr(b, "_docked", False):
            b.setParent(None); b.setWindowFlag(Qt.Window, True)
            b.resize(1180, 700)
        b.set_docked(False)
        b.showNormal(); b.raise_(); b.activateWindow()

    def _on_calc_done(self, hp, bpm):
        """A master recording finished: load the take into the Separation Board (a separate window).
        The board persists — open/close it with the Separator button without losing your work."""
        self._hide_busy()
        self._orig_rec = hp                # cleaned take (used for play-original + previews)
        self._set_title()
        # the take's detected tempo is authoritative — both windows adopt it so BPM always matches
        self.project.bpm = int(bpm); self._spb = 60.0 / max(1, self.project.bpm)
        self.project.grid = max(self.project.grid, 16)      # fine grid: tiny board moves still register
        self.toolbar.bpm.blockSignals(True); self.toolbar.bpm.setValue(int(bpm)); self.toolbar.bpm.blockSignals(False)
        self.toolbar.refresh_info()
        if self._board is None:
            self._make_board(hp, bpm)
        else:
            self._board.set_take(hp, bpm)  # a NEW take replaces the wave in the separator
        self._show_board()                 # keeps full screen if it was full screen

    # ---- Board → Studio live sync (per-track upsert) ----
    def _resync_all_board(self):
        """Rebuild every board track's lane+events (used on connect / after a new take / tempo change)."""
        if self._board is None:
            return
        for tr in list(self._board.tracks):
            self._on_board_track_changed(tr.get("lane_id", ""))

    def _on_board_track_changed(self, lane_id: str):
        """One board track was added / drawn / renamed / deleted → upsert just its lane on the grid."""
        if self._syncing or self._board is None:
            return
        self._syncing = True
        try:
            if not lane_id:                                  # structural (new take clears all)
                self._sync_all_tracks()
            else:
                self._upsert_lane(lane_id)
            self.timeline.set_project(self.project)
            self.headers.update(); self.toolbar.refresh_info(); self._rerender_if_playing()
            self._sync_commit.start()                        # debounce → one undo entry per gesture
        finally:
            self._syncing = False

    def _sync_all_tracks(self):
        board_ids = {tr.get("lane_id") for tr in self._board.tracks}
        # drop auto lanes whose board track is gone
        self.project.lanes = [l for l in self.project.lanes if not l.auto or l.id in board_ids]
        for tr in self._board.tracks:
            self._upsert_lane(tr.get("lane_id", ""))

    def _upsert_lane(self, lane_id: str):
        tr = next((t for t in self._board.tracks if t.get("lane_id") == lane_id), None)
        existing = next((l for l in self.project.lanes if l.id == lane_id), None)
        if tr is None or not tr.get("visible", True):        # deleted / hidden → remove the lane
            self.project.lanes = [l for l in self.project.lanes if l.id != lane_id]
            self.project.events = [e for e in self.project.events if e.lane_id != lane_id]
            return
        lane, events = self._board._lane_events(tr)
        # replace only this lane's events
        self.project.events = [e for e in self.project.events if e.lane_id != lane_id]
        col = tr["color"].name() if hasattr(tr["color"], "name") else str(tr.get("color", ""))
        synthp = tr["kind"] == "synth"
        bp = dict(tr.get("params") or {}) if synthp else {}
        mp = dict(tr.get("params_b") or {}) if synthp else {}
        lo = int(tr.get("lo_note", 48)); hi = int(tr.get("hi_note", 72))
        is_orig = tr["kind"] == "original"
        fx = dict(tr.get("fx") or {}) if is_orig else {}
        if lane is None:                                     # nothing drawn yet — keep an empty lane
            if existing is None:
                self._insert_lane(Lane(id=lane_id, src_master=lane_id, kind=tr["kind"], sound=tr["sound"],
                                       sound_b=tr.get("sound_b", ""), name=tr["name"], auto=True,
                                       has_original=True, play_original=is_orig, color=col,
                                       sound_params=bp, sound_b_params=mp, fx=fx,
                                       lo_note=lo, hi_note=hi), tr)
            else:
                existing.kind = tr["kind"]; existing.sound = tr["sound"]
                existing.sound_b = tr.get("sound_b", ""); existing.name = tr["name"]
                existing.color = col; existing.sound_params = bp; existing.sound_b_params = mp
                existing.lo_note = lo; existing.hi_note = hi
                existing.play_original = is_orig; existing.fx = fx
            return
        if existing is None:
            self._insert_lane(lane, tr)
        else:                                                # mutate in place (keep mute/solo/eq/order)
            existing.kind = lane.kind; existing.sound = lane.sound
            existing.sound_b = lane.sound_b; existing.name = lane.name
            existing.color = lane.color
            existing.sound_params = lane.sound_params; existing.sound_b_params = lane.sound_b_params
            existing.lo_note = lane.lo_note; existing.hi_note = lane.hi_note; existing.vol_pts = lane.vol_pts or existing.vol_pts
            existing.play_original = lane.play_original; existing.fx = lane.fx
        self.project.events += events

    def _insert_lane(self, lane, tr):
        """Insert a new auto lane so Studio order matches the board's track order (index-based colors)."""
        idx = self._board.tracks.index(tr)
        before = [t.get("lane_id") for t in self._board.tracks[:idx]]
        pos = len(self.project.lanes)
        for i, l in enumerate(self.project.lanes):
            if l.auto and l.id not in before:
                pos = i; break
        self.project.lanes.insert(pos, lane)

    # ---- Studio → Board reverse sync (grid move/quantize/delete → the drawn line) ----
    def _sync_grid_to_board(self):
        """A grid gesture finished. For each synced (auto) lane, push note timing/volume/deletes back
        onto the board's drawn points (shape preserved), then regenerate that lane's events."""
        if self._syncing or self._board is None:
            return
        self._syncing = True
        try:
            dur = max(1e-6, len(self._board.buf) / SR)
            beat_len = 60.0 / max(1, self.project.bpm)
            changed = False
            for lane in [l for l in self.project.lanes if l.auto and l.src_master]:
                tr = next((t for t in self._board.tracks if t.get("lane_id") == lane.id), None)
                if tr is None:
                    continue
                pts_by_id = {p.get("id"): p for p in tr["points"]}
                evs = [e for e in self.project.events if e.lane_id == lane.id]
                referenced = set()
                synth = tr["kind"] == "synth"
                for e in evs:
                    ids = e.src_pts or []
                    snapped = self.project.snap(e.beat)
                    if not any(i in pts_by_id for i in ids):
                        # a NEW beat drawn on the grid → make a matching anchor on the board:
                        # x = its time, y = interpolated between the neighbouring points.
                        newt = min(1.0, max(0.0, snapped * beat_len / dur))
                        nv = _interp_v(tr["points"], newt, max(0.2, min(1.0, e.vel or 0.85)))
                        npt = {"id": uid("p"), "t": newt, "v": nv, "beat": snapped, "hx": 0.0, "hy": 0.0}
                        pts = tr["points"]; k = 0
                        while k < len(pts) and pts[k]["t"] < newt:
                            k += 1
                        pts.insert(k, npt); pts_by_id[npt["id"]] = npt
                        e.src_pts = [npt["id"]]; e.src_track = lane.id
                        referenced.add(npt["id"]); changed = True
                        continue
                    referenced.update(ids)
                    if not synth:
                        pt = pts_by_id.get(ids[0]) if ids else None
                        if pt is None:
                            continue
                        if pt.get("beat") is None or abs(pt["beat"] - snapped) > 1e-6:
                            pt["beat"] = snapped
                            pt["t"] = min(1.0, max(0.0, snapped * beat_len / dur)); changed = True
                        nv = max(0.0, min(1.0, e.vel))
                        if abs(pt.get("v", 0) - nv) > 1e-3:
                            pt["v"] = nv; changed = True
                    else:
                        members = [pts_by_id[i] for i in ids if i in pts_by_id]
                        if not members:
                            continue
                        start = members[0]
                        old = start.get("beat")
                        if old is None:
                            old = self._board._beat_of(start, start["t"], beat_len)[0]
                        if abs(old - snapped) > 1e-6:
                            dfrac = (snapped - old) * beat_len / dur
                            for m in members:
                                m["t"] = min(1.0, max(0.0, m["t"] + dfrac))
                            start["beat"] = snapped; changed = True
                # a point that would sound but has no event anymore = deleted on the grid
                kept = [p for p in tr["points"]
                        if not (p.get("v", 0) > SILENCE and p.get("id") not in referenced)]
                if len(kept) != len(tr["points"]):
                    tr["points"] = kept; changed = True
            if changed:
                for lane in [l for l in self.project.lanes if l.auto and l.src_master]:
                    self._upsert_lane(lane.id)
                self._board.canvas.update()
                self.timeline.set_project(self.project); self.headers.update()
                self.toolbar.refresh_info(); self._rerender_if_playing(); self._sync_commit.start()
        finally:
            self._syncing = False

    # ---- busy indicator (so long steps never look frozen) ----
    def _show_busy(self, msg: str):
        from PySide6.QtWidgets import QProgressDialog, QApplication
        self._hide_busy()
        dlg = QProgressDialog(msg, "", 0, 0, self)        # range 0,0 = indeterminate spinner
        dlg.setWindowTitle("Beat Studio"); dlg.setCancelButton(None)
        dlg.setWindowModality(Qt.ApplicationModal); dlg.setMinimumDuration(0)
        dlg.setAutoClose(False); dlg.setAutoReset(False); dlg.setMinimumWidth(320)
        dlg.show(); QApplication.processEvents()
        self._busy = dlg

    def _hide_busy(self):
        dlg = getattr(self, "_busy", None)
        if dlg is not None:
            dlg.close(); self._busy = None

    def _render_pattern(self, lanes, events):
        """Render the DRAWN tracks to a buffer (no playback)."""
        if not lanes or not events:
            return None
        bpm = self._board.bpm if self._board else self.project.bpm
        tmp = Project(lanes=list(lanes), events=list(events), bpm=bpm)
        buf, _ = render_project(tmp, self._samples, orig=self._orig_rec)
        return buf

    def _preview_pattern(self, lanes, events):
        """▶ Preview mix — hear what you drew. Returns duration (s) for the board's playhead."""
        self.engine.stop()                          # never overlap the streaming transport
        buf = self._render_pattern(lanes, events)
        if buf is not None and len(buf):
            self.engine.one_shot(buf)
            return len(buf) / SR
        return 0.0

    def _preview_original(self):
        """▶ Original — hear the raw recorded take."""
        self.engine.stop()
        o = self._orig_rec
        if o is None or not len(o):
            return 0.0
        self.engine.one_shot(np.ascontiguousarray(o, np.float32))
        return len(o) / SR

    def _preview_both(self, lanes, events):
        """▶ Both — drawn tracks AND the original together, to compare."""
        self.engine.stop()
        pat = self._render_pattern(lanes, events)
        o = self._orig_rec
        if o is None and pat is None:
            return 0.0
        n = max(len(o) if o is not None else 0, len(pat) if pat is not None else 0)
        mix = np.zeros(n, np.float32)
        if o is not None:
            mix[:len(o)] += o
        if pat is not None:
            mix[:len(pat)] += pat * 0.9
        np.tanh(mix, out=mix)
        self.engine.one_shot(mix)
        return n / SR

    def _rerender_if_playing(self):
        if self.engine.playing:
            buf, self._spb = render_project(self.project, self._samples, orig=self._orig_rec)
            self.engine.set_buffer(buf)

    def _on_settings_changed(self):
        self.headers.update(); self.timeline.viewport().update(); self.toolbar.refresh_info()
        self._rerender_if_playing()

    def _delete_track(self, lane_id: str):
        from PySide6.QtWidgets import QMessageBox
        lane = next((l for l in self.project.lanes if l.id == lane_id), None)
        name = lane.name if lane else "this track"
        board_tr = None
        if self._board is not None:
            board_tr = next((t for t in self._board.tracks if t.get("lane_id") == lane_id), None)
        box = QMessageBox(self)
        box.setWindowTitle("Delete track")
        box.setText(f"Delete “{name}”?")
        box.setInformativeText("This removes it from the Studio and the Separation Board."
                               if board_tr is not None else "This removes it from the Studio.")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        box.setStyleSheet("QMessageBox{background:#13131b;} QLabel{color:#d8d8e0;}")
        if box.exec() != QMessageBox.Yes:
            return
        if board_tr is not None:                 # drop it on the separator too (this also drops the lane)
            self._board._delete_track(board_tr)
        self.project.lanes = [l for l in self.project.lanes if l.id != lane_id]
        self.project.events = [e for e in self.project.events if e.lane_id != lane_id]
        self.settings.hide()
        self.timeline.set_project(self.project)
        self.headers.update(); self.toolbar.refresh_info(); self._rerender_if_playing(); self._commit()

    def _test_instrument(self, lane_id: str):
        lane = next((l for l in self.project.lanes if l.id == lane_id), None)
        if not lane:
            return
        li = self.project.lane_index(lane_id)
        e = Event(lane_id=lane_id, beat=0, vel=0.9, pitch=(60 if lane.kind == "synth" else None))
        v = _voice_for(lane, e, self._spb, li, self._samples)
        if v is not None:
            self.engine.one_shot(v)

    def _preview_instrument(self, kind: str, sound: str):
        """Play a one-shot of an instrument (used by the Separation Board's per-track ▶)."""
        lane = Lane(kind=kind, sound=sound)
        e = Event(lane_id=lane.id, beat=0, vel=0.9, pitch=(60 if kind == "synth" else None))
        v = _voice_for(lane, e, self._spb, 0, self._samples)
        if v is not None:
            self.engine.one_shot(v)

    def _preview_note(self, kind: str, sound: str, params, midi: int):
        """Audition an instrument at a specific pitch (piano key in the NOTES gutter). Synth plays
        that frequency; a drum/sample is RESAMPLED to that note (so a tom really toms up/down)."""
        if kind == "synth":
            v = synth.voice(sound or "sine", synth.midi_to_hz(midi), 0.5, 0.9, params or {})
        elif kind == "sample":
            samp = (self._samples or {}).get(sound)
            v = synth.sample_voice(samp["buf"], samp.get("base", 60), midi, 0.5, 0.9) if samp else None
        else:                                              # drum (+ 'original' fallback): pitch by resampling (C4 = natural)
            v = synth.sample_voice(synth.drum(sound or "kick", 0.9), 60, midi, 0.0, 0.9, loop=False)
        if v is not None and len(v):
            self.engine.stop_one_shot(); self.engine.one_shot(v)

    def _preview_synth_sound(self, preset: str, params: dict):
        """Play a single synth voice with its knobs applied (Base / Morph ▶ on the board)."""
        v = synth.voice(preset or "sine", synth.midi_to_hz(60), 0.6, 0.9, params)
        if v is not None and len(v):
            self.engine.one_shot(v)

    def _stop_preview(self):
        """Stop whatever is previewing (board stop_cb) — one-shot AND the streaming transport."""
        self.engine.stop_one_shot(); self.engine.stop(); self._timer.stop()
        self.timeline.set_playhead(None)

    def _on_board_playhead(self, frac: float):
        """The board preview playhead moved → mirror the red line onto the Studio grid (live in both)."""
        if frac is None or frac < 0:
            self.timeline.set_playhead(None); return
        take = max(1e-6, len(self._board.buf) / SR) if self._board else 1.0
        self.timeline.set_playhead(frac * take / self._spb)

    # ---- linked beat selection (board anchor <-> Studio grid beat) ----
    def _on_board_point_selected(self, pt_id: str):
        """An anchor was picked on the board → select the matching beat(s) on the Studio grid."""
        if self._sel_syncing:
            return
        self._sel_syncing = True
        try:
            self.timeline.selected = {e.id for e in self.project.events
                                      if e.src_pts and pt_id in e.src_pts} if pt_id else set()
            self.timeline.viewport().update(); self.headers.update()
        finally:
            self._sel_syncing = False

    def _on_grid_selection(self):
        """Beats selected on the Studio grid → ring the drawn anchors behind them on the board."""
        if self._sel_syncing or self._board is None:
            return
        self._sel_syncing = True
        try:
            pts = []
            for e in self.project.events:
                if e.id in self.timeline.selected and e.src_pts:
                    pts.extend(e.src_pts)
            self._board.set_selected_pts(pts)
        finally:
            self._sel_syncing = False

    def _add_track(self):
        self.project.lanes.append(Lane(kind="drum", sound="kick", name="Kick"))
        self.timeline.set_project(self.project)
        self.headers.update(); self.toolbar.refresh_info(); self._commit()

    def _on_edit(self):
        """A beat was added/moved/deleted on the grid."""
        self.toolbar.refresh_info()
        self._rerender_if_playing()

    # ---- undo / redo ----
    def _refresh_undo_buttons(self):
        self.toolbar.set_undo_state(bool(self._undo_stack), bool(self._redo_stack))

    def _on_take_audio_changed(self):
        """The board's take waveform itself changed (Fit stretch / delete) → the ACTUAL sound must
        follow, not just the picture. Keep play-original / render in sync with the (main) take."""
        if self._board is not None:
            self._orig_rec = np.asarray(self._board.buf, np.float32)
            self._rerender_if_playing()

    def _board_fp(self):
        """A cheap fingerprint of board state that ISN'T in the Studio project — take audio lengths +
        grid offset + bpm — so `_commit` also fires for audio-only changes (Fit, grid move, delete)."""
        b = getattr(self, "_board", None)
        if b is None:
            return None
        return (tuple((tk["id"], len(tk["buf"])) for tk in b.takes),
                round(b.canvas.grid_off, 4), int(b.bpm))

    def _snapshot(self):
        """One undo entry = the Studio project AND the Separation Board (points/takes)."""
        board = getattr(self, "_board", None)
        return {"project": persistence.to_dict(self.project),
                "board": board.snapshot() if board is not None else None,
                "fp": self._board_fp()}

    def _restore(self, blob):
        """Restore BOTH windows from an undo entry (project + board drawn state + take audio)."""
        self._syncing = True
        try:
            self._set_project(persistence.from_dict(blob["project"]))
            if self._board is not None and blob.get("board") is not None:
                self._board.restore(blob["board"])
                self._orig_rec = np.asarray(self._board.buf, np.float32)   # the SOUND follows the restored take
        finally:
            self._syncing = False
        self.timeline.set_project(self.project)
        self.headers.update(); self.toolbar.refresh_info(); self._rerender_if_playing()

    def _commit(self):
        proj = persistence.to_dict(self.project)
        fp = self._board_fp()
        if (self._committed is not None and proj == self._committed.get("project")
                and fp == self._committed.get("fp")):
            return                          # nothing changed on the grid OR the board audio/grid
        self._undo_stack.append(self._committed)
        self._undo_stack = self._undo_stack[-80:]
        self._redo_stack.clear()
        self._committed = {"project": proj, "board": self._board.snapshot() if self._board else None, "fp": fp}
        self._refresh_undo_buttons()

    def _undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(self._committed)
        self._committed = self._undo_stack.pop()
        self._restore(self._committed)      # both windows follow
        self._refresh_undo_buttons()

    def _redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(self._committed)
        self._committed = self._redo_stack.pop()
        self._restore(self._committed)      # both windows follow
        self._refresh_undo_buttons()

    def _clear_beats_confirm(self):
        from PySide6.QtWidgets import QMessageBox
        if not self.project.events:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Clear all beats")
        box.setText(f"Remove all {len(self.project.events)} beats from every track?")
        box.setInformativeText("Your tracks stay; only the beats are cleared. You can undo this.")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        box.setStyleSheet("QMessageBox{background:#13131b;} QLabel{color:#d8d8e0;}")
        if box.exec() == QMessageBox.Yes:
            self._clear_beats()

    # ---- per-beat EQ popover ----
    def _selected_events(self):
        return [e for e in self.project.events if e.id in self.timeline.selected]

    def _open_beat_eq(self, global_pos):
        events = self._selected_events()
        if not events:
            return
        self.beat_eq.set_targets(events)
        self.beat_eq.move(global_pos)
        self.beat_eq.show()

    def _on_beat_eq_changed(self):
        self.timeline.viewport().update()
        self._rerender_if_playing()

    def _preview_beat(self):
        events = self.beat_eq.targets
        if not events:
            return
        e = events[0]
        li = self.project.lane_index(e.lane_id)
        lane = self.project.lanes[li]
        v = _voice_for(lane, e, self._spb, li, self._samples)
        if v is not None:
            self.engine.one_shot(v)

    def _toggle_metro(self):
        self.project.metronome = not self.project.metronome
        self.toolbar.set_metro_active(self.project.metronome)
        self._rerender_if_playing()

    def _set_bpm(self, bpm: int):
        self.project.bpm = int(bpm)
        self._spb = 60.0 / max(1, self.project.bpm)
        self.toolbar.refresh_info()
        self._rerender_if_playing()
        if self._board is not None and not self._syncing:      # mirror to the board + rescale beats
            self._board.set_bpm_external(int(bpm))
            self._resync_all_board()
        self._sync_commit.start()                              # tempo changes are undoable (debounced)

    def _on_board_bpm(self, bpm: int):
        """The board's BPM box changed → mirror to the Studio toolbar + rescale the grid."""
        if self._syncing:
            return
        self.toolbar.bpm.blockSignals(True); self.toolbar.bpm.setValue(int(bpm)); self.toolbar.bpm.blockSignals(False)
        self._set_bpm(int(bpm))

    def closeEvent(self, ev):
        """Closing the Studio closes the Separation Board too (it's a separate top-level window that
        would otherwise keep the app alive)."""
        if self._board is not None:
            self._board.close(); self._board.deleteLater(); self._board = None
        super().closeEvent(ev)

    def _on_loop_changed(self):
        # restart playback with the new loop so it takes effect immediately
        if self.engine.playing:
            self._play_from(self.project.loop_start if self.project.loop_on else self.project.start_at)

    # ---- transport ----
    def _toggle_play(self):
        if self.engine.playing:                     # PAUSE: freeze the playhead where it is
            self._paused_beat = self.engine.position_frames() / SR / max(1e-6, self._spb)
            self.engine.stop(); self._timer.stop()
            self.toolbar.set_playing(False)
            return
        # resume from the paused spot, or from the start marker if we're fully stopped
        self._play_from(self._paused_beat if self._paused_beat is not None else self.project.start_at)

    def _play_from(self, start_beat: float):
        if self._board is not None:                 # starting the transport clears board ■ state
            self._board.clear_playing()
        buf, self._spb = render_project(self.project, self._samples, orig=self._orig_rec)
        self.engine.set_buffer(buf)
        start_frame = int(start_beat * self._spb * SR)
        loop = self.project.loop_on and self.project.loop_end and self.project.loop_start is not None
        la = int((self.project.loop_start or 0) * self._spb * SR) if loop else 0
        lb = int((self.project.loop_end or 0) * self._spb * SR) if loop else 0
        self.engine.play(start_frame, loop, la, lb)
        self._paused_beat = None
        self.toolbar.set_playing(True)
        self._timer.start()

    def _stop(self):
        self.engine.stop(); self.engine.stop_one_shot(); self._timer.stop()
        self._paused_beat = None                    # STOP rewinds to the start
        self.timeline.set_playhead(None)
        self.toolbar.set_playing(False)
        if self._board is not None:
            self._board.clear_playing()

    def _tick(self):
        if self.recorder.recording:
            beat = self.project.start_at + (self.recorder.frames / SR) / self._spb
            self.timeline.set_playhead(beat)
            # live waveform: on the recording lane, or full-height (li=-1) for master
            li = -1 if self._rec_lane == "__master__" else self.project.lane_index(self._rec_lane)
            self.timeline.rec_wave = (li, self.project.start_at, beat, list(self.recorder.live_env))
            self.timeline.rec_clip = self.recorder.peak > 0.92
            if li >= 0:
                self.timeline.live_markers = [(li, self.project.start_at + t / self._spb)
                                              for t in list(self.recorder.live_onsets)]
            self.toolbar.set_rec_level(self.recorder.level, self.recorder.peak)
            if self._rec_lane in ("__master__", "__secondary__") and self._board is not None and self._board.isVisible():
                self._board.canvas.set_live(list(self.recorder.live_env), self.recorder.peak > 0.92)
            self.timeline.viewport().update()
            x = self.timeline.x_of_beat(beat)
            sb = self.timeline.horizontalScrollBar(); vw = self.timeline.viewport().width()
            if x - sb.value() > vw * 0.75:
                sb.setValue(int(x - vw * 0.5))
            return
        pos = self.engine.position_frames()
        beat = pos / SR / self._spb
        self.timeline.set_playhead(beat)
        if self._board is not None:                       # mirror the red line onto the board too
            take = max(1e-6, len(self._board.buf) / SR)
            self._board.canvas.set_playhead(min(1.0, (pos / SR) / take) if self.engine.playing else None)
        if not self.engine.playing:
            self._timer.stop()
            self._paused_beat = None            # reached the end → next play starts from the top
            self.toolbar.set_playing(False)
            return
        # keep the playhead in view
        x = self.timeline.x_of_beat(beat)
        sb = self.timeline.horizontalScrollBar()
        vw = self.timeline.viewport().width()
        if x - sb.value() > vw * 0.75 or x - sb.value() < 0:
            sb.setValue(int(x - vw * 0.5))
