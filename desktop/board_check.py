"""End-to-end check for the Separation Board:
  1. the board: add tracks, pen-tool place/drag/delete dots, zoom/pan, navigator, build lanes;
  2. the wiring: feed a board result through MainWindow._apply_board_result and prove the tracks
     actually land on the project + timeline ("Create these tracks" really works).
Saves ref/board-01.png."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("BEAT_NO_GL", "1")
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPointF

sys.path.insert(0, os.path.dirname(__file__))
from beatstudio.synth import SR
from beatstudio.separationboard import SeparationBoard

dur = 4.0
t = np.arange(int(dur * SR)) / SR
buf = 0.06 * np.sin(2 * np.pi * 110 * t) * np.exp(-((t % 1.0)) * 0.6)
rng = np.random.default_rng(3)
for hit in (0.05, 1.0, 2.0, 2.55, 3.05):
    i = int(hit * SR); env = np.exp(-np.arange(SR // 2) / (SR * 0.03))
    buf[i:i + len(env)] += 0.8 * (rng.standard_normal(len(env)) * env).astype(np.float32)
mid = (t > 1.4) & (t < 1.8); buf[mid] += 0.25 * np.sin(2 * np.pi * 1200 * t[mid])
buf = buf.astype(np.float32)


class E:
    def __init__(s, x, y, btn=Qt.LeftButton, mods=Qt.NoModifier):
        s._p = QPointF(x, y); s._b = btn; s._m = mods
    def position(s): return s._p
    def button(s): return s._b
    def buttons(s): return s._b
    def modifiers(s): return s._m
    def angleDelta(s):
        from PySide6.QtCore import QPoint; return QPoint(0, 120)


app = QApplication.instance() or QApplication(sys.argv)
b = SeparationBoard(buf, SR, 120, preview_cb=lambda k, s: None, preview_pattern_cb=lambda l, e: 1.2)
b.resize(1180, 700); b.show(); app.processEvents()
cv = b.canvas

b.add_track(); b.add_track()
b._activate_track(b.tracks[0])
for frac in (0.05, 0.25, 0.5, 0.64, 0.76):
    q = cv._to_px(frac, 0.85); cv.mousePressEvent(E(q.x(), q.y())); cv.mouseReleaseEvent(None)
b._activate_track(b.tracks[1])
for frac in (0.3, 0.35, 0.4):
    q = cv._to_px(frac, 0.7); cv.mousePressEvent(E(q.x(), q.y())); cv.mouseReleaseEvent(None)

# points are Bézier anchors now (dicts). Drag anchor, delete, and pull out a CURVE handle.
b._activate_track(b.tracks[0])
pt = b.tracks[0]["points"][1]; q = cv._apx(pt)
cv.mousePressEvent(E(q.x(), q.y())); cv.mouseMoveEvent(E(q.x(), cv._to_px(0.25, 0.2).y())); cv.mouseReleaseEvent(None)
assert round(b.tracks[0]["points"][1]["v"], 2) <= 0.25, "anchor drag failed"
before = len(b.tracks[0]["points"]); q = cv._apx(b.tracks[0]["points"][3])
cv.mousePressEvent(E(q.x(), q.y(), Qt.RightButton))
assert len(b.tracks[0]["points"]) == before - 1, "delete anchor failed"
q = cv._to_px(0.92, 0.6); cv.mousePressEvent(E(q.x(), q.y()))          # add anchor, drag = curve
cv.mouseMoveEvent(E(q.x() + 40, q.y() - 20)); cv.mouseReleaseEvent(None)
nph = b.tracks[0]["points"][-1]
assert nph["hx"] != 0 or nph["hy"] != 0, "curve handle not pulled out"
print("curve handle:", (round(nph["hx"], 3), round(nph["hy"], 3)))

# zoom via plain scroll (touchpad-friendly), zoom buttons, then pan via navigator
cv.wheelEvent(E(cv.width() * 0.4, cv.height() * 0.5))
assert cv.view1 - cv.view0 < 0.99, "scroll zoom did not change the view span"
b._zoom(0.7); b._zoom(1 / 0.7)                       # + then − buttons
mm = cv._mm_rect(); cv.mousePressEvent(E(mm.center().x(), mm.center().y())); cv.mouseReleaseEvent(None)
cv.view0, cv.view1 = 0.0, 1.0; b._update_zoom_label()
print("zoom label:", b.zlbl.text(), "| tempo box:", b.bpm_box.value())

# tempo control + playhead sweep
b.bpm_box.setValue(140); assert b.canvas.bpm == 140, "bpm control not wired"
b._start_playhead(1.0); app.processEvents()
b._tick_playhead(); print("playhead:", b.canvas.playhead)

# --- SYNTH (B+C): the Synth group opens the two-field designer; a sustained line = a held morph note ---
b.add_track(); st = b.tracks[-1]; row = b._rows[-1]
row._on_group("Synth"); row.combo_base.setCurrentText("sine"); row.combo_mod.setCurrentText("saw")
assert st["kind"] == "synth" and st["sound"] == "sine" and st["sound_b"] == "saw", st
b._activate_track(st)
st["points"] = [{"t": 0.10, "v": 0.0, "hx": 0, "hy": 0}, {"t": 0.16, "v": 0.35, "hx": 0, "hy": 0},
                {"t": 0.45, "v": 0.9, "hx": 0, "hy": 0}, {"t": 0.50, "v": 0.0, "hx": 0, "hy": 0}]
slane, sev = b._lane_events(st)
print("synth:", slane.kind, slane.sound, "→", slane.sound_b, "| notes:", len(sev),
      "| len:", round(sev[0].length, 2), "| env pts:", len(sev[0].env or []))
assert slane.kind == "synth" and slane.sound_b == "saw" and len(sev) == 1 and sev[0].length > 0.1 \
    and sev[0].env and len(sev[0].env) > 3, "synth held/follow note wrong"
# env follows the line: rises toward the peak then falls
assert max(sev[0].env) > 0.7 and sev[0].env[0] < 0.3, "env does not follow the drawn shape"

lanes, events = b.build()
print("board.build ->", [(l.name, l.kind, l.sound, sum(1 for e in events if e.lane_id == l.id)) for l in lanes])
assert lanes and events, "build produced nothing"
# render (exercises morph_synth + drum_roll paths)
from beatstudio.render import render_project
from beatstudio.model import Project
rbuf, _ = render_project(Project(lanes=lanes, events=events, bpm=b.bpm))
assert rbuf is not None and len(rbuf) > 1000, "render produced no audio"
print("rendered", round(len(rbuf) / SR, 2), "s")

app.processEvents()
b.grab().save("ref/board-01.png")
print("saved ref/board-01.png")

# ===== STABLE COLOURS: removing a track keeps every other track's colour =====
b.add_track(); b.add_track()
cols = [t["color"].name() for t in b.tracks]
b._delete_track(b.tracks[0])                     # remove the TOP one
rest = [t["color"].name() for t in b.tracks]
assert rest == cols[1:], f"colours shifted on delete: {rest} != {cols[1:]}"
drawn = next(t for t in b.tracks if t["points"])
lane_c, _ = b._lane_events(drawn); assert lane_c.color, "lane carries no stable colour"
print("COLOURS ok: stable across delete + carried onto the lane")

# ===== SELECTION: the canvas only edits the ACTIVE track (pick from the list first) =====
b._activate_track(b.tracks[-1])                  # active = the synth track
other = next(t for t in b.tracks if t is not b.tracks[b.canvas.active] and t["points"])
qo = cv._apx(other["points"][0]); hit = cv._hit(qo)
assert hit is None or hit[0] == b.canvas.active, "canvas grabbed a NON-active track's dot"
print("SELECTION ok: non-active tracks are inert on the canvas")

# ===== SYNTH KNOBS: Base/Morph params reach the lane and audibly change the voice =====
from beatstudio.synth import voice, midi_to_hz, default_params
sy = next(t for t in b.tracks if t["kind"] == "synth")
sy.setdefault("params", default_params()); sy.setdefault("params_b", default_params())
slane, _ = b._lane_events(sy)
assert slane.sound_params and "cutoff" in slane.sound_params, "synth knobs missing on lane"
op = dict(sy["params"]); op["cutoff"] = 1.0
dp = dict(sy["params"]); dp["cutoff"] = 0.05; dp["drive"] = 0.8
xa = voice("saw", midi_to_hz(60), 0.4, 0.9, op); xb = voice("saw", midi_to_hz(60), 0.4, 0.9, dp)
assert xa.shape == xb.shape and float(np.abs(xa - xb).mean()) > 1e-4, "knobs had no effect on the sound"
print("SYNTH KNOBS ok: params on the lane + audibly change the voice")

# ===== SIREN: the synth line glides PITCH (low→high) + timbre as one sustained morphing note =====
from beatstudio.synth import morph_glide
rise = list(np.linspace(0.0, 1.0, 60))
xg = morph_glide("sine", "sine", 48, 72, 1.0, rise)     # rising line → pitch should rise
def _zcr(s): return float(np.mean(np.abs(np.diff(np.sign(s))) > 0))
assert _zcr(xg[len(xg)//2:]) > _zcr(xg[:len(xg)//2]) * 1.3, "siren pitch did not rise with the line"
sl2, se2 = b._lane_events(sy)
assert len(se2) == 1 and se2[0].pitch is None and se2[0].env and sl2.hi_note > sl2.lo_note, \
    "synth should be ONE continuous morph note with a pitch range"
# length must be SECONDS-based (span_seconds / beat_len), not the raw take-fraction
_pts = sorted(sy["points"], key=lambda p: p["t"])
_dur_s = len(b.buf) / SR; _blen = 60.0 / b.bpm
_exp = (_pts[-1]["t"] - _pts[0]["t"]) * _dur_s / _blen
assert abs(se2[0].length - _exp) < 0.05 and se2[0].length > 1.0, \
    f"synth length not seconds-based ({round(se2[0].length,3)} vs {round(_exp,3)})"
print(f"SIREN ok: one sustained note, pitch glides up; length={round(se2[0].length,2)} beats (seconds-based)")

# ================= LIVE BIDIRECTIONAL SYNC (v0.18.0) =================
from beatstudio.mainwindow import MainWindow
w = MainWindow(); w._orig_rec = (0.2 * np.random.randn(SR * 2)).astype("float32")
w._open_separator(); bd = w._board; app.processEvents()
base = len(w.project.lanes)
assert base == 0, f"Studio should start EMPTY, had {base} lanes"

# FORWARD: adding a track instantly creates the lane; drawing points creates events (no Create button)
bd.add_track(); tr = bd.tracks[0]; cv2 = bd.canvas; cv2.set_active(0)
assert any(l.id == tr["lane_id"] for l in w.project.lanes), "add_track did not create a Studio lane"
for frac in (0.25, 0.5, 0.75):
    q = cv2._to_px(frac, 0.8); cv2.mousePressEvent(E(q.x(), q.y())); cv2.mouseReleaseEvent(E(q.x(), q.y()))
app.processEvents()
evs = [e for e in w.project.events if e.lane_id == tr["lane_id"]]
assert len(evs) == 3 and evs[0].src_pts, f"forward draw->events failed ({len(evs)})"
lane_obj = next(l for l in w.project.lanes if l.id == tr["lane_id"])
assert lane_obj.color == tr["color"].name(), "stable colour did not reach the Studio lane"
print(f"FORWARD ok: lanes {base}->{len(w.project.lanes)}, drew 3 points -> {len(evs)} events")

# REVERSE move: change a note's beat on the grid -> the drawn anchor locks/moves, shape preserved
victim = evs[1]; pid = victim.src_pts[0]
pt = next(p for p in tr["points"] if p["id"] == pid); shape = (pt["hx"], pt["hy"])
victim.beat = 1.0; w._sync_grid_to_board()
pt = next(p for p in tr["points"] if p["id"] == pid)
assert pt.get("beat") == 1.0 and (pt["hx"], pt["hy"]) == shape, "reverse move/shape-preserve failed"
print("REVERSE move ok: anchor beat-locked to grid, shape preserved")

# GRAIN: a TINY board move changes the event beat (drawn position drives the beat, no onset snap)
gtrk = tr; gp = gtrk["points"][0]; gp.pop("beat", None)
gp["t"] = 0.400; b1 = gtrk_beat = w._board._lane_events(gtrk)[1]
e_a = next(e for e in w._board._lane_events(gtrk)[1] if gp["id"] in (e.src_pts or []))
gp["t"] = 0.402                                   # ~2 ms nudge
e_b = next(e for e in w._board._lane_events(gtrk)[1] if gp["id"] in (e.src_pts or []))
assert abs(e_b.beat - e_a.beat) > 1e-4, "tiny board move did not change the beat (grain too coarse)"
print("GRAIN ok: a tiny board nudge moves the grid beat")

# GRID-ADD: adding a beat on the Studio grid creates a board anchor (x=time, y=between neighbours)
lid = tr["lane_id"]; npts_before = len(tr["points"])
from beatstudio.model import Event as _Ev
w.project.events.append(_Ev(lane_id=lid, beat=2.0, vel=0.8))
w._sync_grid_to_board()
made = [p for p in tr["points"] if abs(p.get("beat", -9) - w.project.snap(2.0)) < 1e-6]
assert made and len(tr["points"]) > npts_before, "grid-added beat did not create a board anchor"
print("GRID-ADD ok: a new grid beat created a matching board point")

# REVERSE delete: remove a grid note -> its drawn anchor disappears
cur = [e for e in w.project.events if e.lane_id == tr["lane_id"]]
gone = cur[0].src_pts[0]; w.project.events = [e for e in w.project.events if e is not cur[0]]
w._sync_grid_to_board()
assert all(p["id"] != gone for p in tr["points"]), "reverse delete failed"
print("REVERSE delete ok: grid delete removed the drawn anchor")

# TEMPO both ways
bd.bpm_box.setValue(140); assert w.project.bpm == 140, "board->studio bpm failed"
w.toolbar.bpm.setValue(100); assert bd.bpm == 100, "studio->board bpm failed"
print("TEMPO ok: board<->studio both ways")

# PER-BUTTON PLAY/STOP: only the button you pressed becomes ■; pressing it again stops
bd.clear_playing()
bd._preview_all()                                    # start Mix (drew events exist)
assert bd.b_prevall.text() == "■ Mix" and bd.b_prevorig.text() == "▶ Original", \
    "playing button keeps its label with only ▶→■ swapped; others unchanged"
bd._preview_all()                                    # press the SAME button → stop
assert bd._play_btn is None and bd.b_prevall.text() == "▶ Mix", "pressing the playing button did not stop"
print("PLAY/STOP ok: only the pressed button toggles, click it again to stop")

# LINKED SELECTION: board anchor -> Studio beat, and Studio beat -> board anchor ring
selev = [e for e in w.project.events if e.lane_id == tr["lane_id"] and e.src_pts][0]
apid = selev.src_pts[0]
bd.canvas._select_point(apid); app.processEvents()
assert selev.id in w.timeline.selected, "board->studio selection link failed"
w.timeline.selected = set(); bd.canvas.set_selected_pts([])
w.timeline.selected = {selev.id}; w.timeline.selection_changed.emit(); app.processEvents()
assert apid in bd.canvas.sel_pts, "studio->board selection link failed"
print("LINKED SELECTION ok: board anchor <-> Studio beat both ways")

# 1 TRACK = 1 SOUNDWAVE: each add_track mints its OWN take (bound 1:1), not shared.
nt0 = len(bd.tracks); nk0 = len(bd.takes)
bd.add_track()
assert len(bd.tracks) == nt0 + 1 and len(bd.takes) == nk0 + 1, "add_track should mint its own soundwave"
assert bd.tracks[-1]["take"] == bd.takes[-1]["id"], "new track not bound 1:1 to its own soundwave"
assert len({t["take"] for t in bd.tracks}) == len(bd.tracks), "takes must be unique per track (1:1)"
t_a = bd.tracks[-1]; ka = next(i for i, t in enumerate(bd.takes) if t["id"] == t_a["take"])
t_a["kind"] = "hum"; t_a["sound"] = "aah"
t_a["points"] = [{"id": "d1", "t": 0.3, "v": 0.8, "midi": 60, "hx": 0, "hy": 0}]
print("1:1 MODEL ok: add_track mints its own soundwave, bound one-to-one")

# TAKE SELECT: tick a soundwave → the working row + active track + notes view scope to IT
bd.canvas.set_sel_take(ka)
assert bd.canvas._active_band() == ka, "selecting a wave did not move the working row"
assert bd._active_take == bd.takes[ka]["id"], "board _active_take did not follow the selection"
assert bd.tracks[bd.canvas.active]["take"] == t_a["take"], "active track must belong to the selected wave"
bd._set_mode("notes"); assert bd.canvas._active_band() == ka, "notes view ignored the selected wave"
assert bd.canvas._hit_take_sel(bd.canvas._take_chip_rect(ka).center()) == ka, "notes take chip not hittable"
bd._set_mode("volume")
assert bd.canvas._hit_take_sel(bd.canvas._take_chk_rect(ka).center()) == ka, "volume take checkbox not hittable"
print("TAKE SELECT ok: ticking a soundwave scopes the working row / active track / notes view to it")

# DUPLICATE: 'Soundwave' copies the audio only (fresh beats); 'Full' copies audio + beats + instrument.
bd.takes[ka]["buf"][:100] = 0.5                            # give the source some audio to copy
nt1 = len(bd.tracks)
dw = bd._do_duplicate(t_a, full=False)
assert len(bd.tracks) == nt1 + 1 and dw["take"] != t_a["take"], "duplicate did not make a new track+wave"
assert not dw.get("points"), "'Soundwave' duplicate must NOT copy the beats"
dtk = next(t for t in bd.takes if t["id"] == dw["take"])
assert float(np.abs(dtk["buf"][:100]).sum()) > 0, "'Soundwave' duplicate did not copy the audio"
df = bd._do_duplicate(t_a, full=True)
assert len(df.get("points") or []) == 1 and df["kind"] == "hum", "'Full' duplicate must copy beats + instrument"
bd._delete_track(dw); bd._delete_track(df)

# PER-TRACK RECORD: the ● button emits record_track(take_id); set_take_buf replaces that wave's audio.
_got = {}
bd.record_track.connect(lambda tid: _got.setdefault("tid", tid))
bd._on_track_record(t_a); assert _got.get("tid") == t_a["take"], "record button did not target this soundwave"
newaud = (0.4 * np.random.randn(2048)).astype("float32")
bd.set_take_buf(t_a["take"], newaud)
assert float(np.abs(bd.canvas.takes[ka]["buf"][:2048]).sum()) > 0, "set_take_buf did not load the recording"
print("PER-TRACK RECORD ok: ● targets the track's soundwave; set_take_buf loads the guide audio")

# NOTES LINE (ties): pitched clicks auto-connect; held = bars, glide = a sliding pitch_track;
# right-click cuts a line; drums never auto-tie.
bd.canvas.set_sel_take(0)
bd.add_track(); ntr = bd.tracks[-1]; ntr["kind"] = "sample"
bd.canvas.set_active(bd.tracks.index(ntr))
bd._set_mode("notes"); cvn = bd.canvas
def _nclick(tf, midi):
    x = cvn._to_px_t(tf); y = cvn._note_y(midi)
    cvn.mousePressEvent(E(x, y)); cvn.mouseReleaseEvent(E(x, y)); app.processEvents()
_nclick(0.15, 60); _nclick(0.45, 64); _nclick(0.75, 67)
npts = sorted(ntr["points"], key=lambda q: q["t"])
assert len(npts) == 3 and npts[0]["tie"] and npts[1]["tie"] and not npts[2]["tie"], \
    "pitched clicks did not auto-tie into a melody line"
_lane, _evs = bd._lane_events(ntr)
assert sorted(e.pitch for e in _evs) == [60, 64, 67] and all(e.pitch_track is None for e in _evs), \
    "held run should be steady piano-roll bars (60,64,67), no glide"
npts[1]["glide"] = True                                # make the 2nd segment a slide
_lane, _evs = bd._lane_events(ntr)
_gl = [e for e in _evs if e.pitch_track]
assert len(_gl) == 1 and max(_gl[0].pitch_track) - min(_gl[0].pitch_track) >= 2.5, \
    "glide segment did not become one sliding note"
axn = cvn._to_px_t((npts[0]["t"] + npts[1]["t"]) / 2); ayn = cvn._note_y(npts[0]["midi"])
cvn.mousePressEvent(E(axn, ayn, btn=Qt.RightButton)); cvn.mouseReleaseEvent(E(axn, ayn, btn=Qt.RightButton))
app.processEvents()
assert not npts[0]["tie"] and len(bd._tied_runs(npts)) == 2, "right-click did not cut the tie"
bd.add_track(); dtr = bd.tracks[-1]; dtr["kind"] = "drum"; bd.canvas.set_active(bd.tracks.index(dtr))
_nclick(0.3, 60); _nclick(0.6, 60)
assert not any(p.get("tie") for p in dtr["points"]), "a drum auto-tied (must stay separate hits)"
bd._delete_track(dtr); bd._delete_track(ntr); bd._set_mode("volume")
print("NOTES LINE ok: pitched clicks tie into held bars + glides; right-click cuts; drums stay hits")

# WAVE CONTROLS (#6): Solo/Mute a soundwave reaches its (1:1) track's lane; per-wave view remembered.
cvw = bd.canvas; bd._set_mode("volume")
bd.add_track(); wa = bd.tracks[-1]; kwa = next(i for i, t in enumerate(bd.takes) if t["id"] == wa["take"])
bd.add_track(); wb = bd.tracks[-1]; kwb = next(i for i, t in enumerate(bd.takes) if t["id"] == wb["take"])
wa["points"] = [{"id": "wc1", "t": 0.3, "v": 0.8, "midi": 60, "hx": 0, "hy": 0}]
wb["points"] = [{"id": "wc2", "t": 0.3, "v": 0.8, "midi": 60, "hx": 0, "hy": 0}]
s_r, m_r = cvw._take_sm_rects(kwa)
assert cvw._hit_take_sm(s_r.center()) == (kwa, "solo") and cvw._hit_take_sm(m_r.center()) == (kwa, "mute"), \
    "Solo/Mute buttons not hittable"
bd._on_take_flag(kwa, "mute"); assert bd.takes[kwa]["muted"], "wave mute did not set on the take"
lane_m, _ = bd._lane_events(wa); assert lane_m.muted, "a muted wave's track did not inherit mute"
bd._on_take_flag(kwa, "mute")
bd._on_take_flag(kwb, "solo")
lane_s, _ = bd._lane_events(wb); assert lane_s.solo, "a soloed wave's track did not inherit solo"
bd._on_take_flag(kwb, "solo")
# per-wave mode memory: wave A in notes, wave B in volume → selecting flips the view back
bd.canvas.set_sel_take(kwa); bd._set_mode("notes")
bd.canvas.set_sel_take(kwb); bd._set_mode("volume")
bd.canvas.set_sel_take(kwa); assert bd.canvas.mode == "notes", "selecting a wave did not restore its view"
bd.canvas.set_sel_take(kwb); assert bd.canvas.mode == "volume", "selecting a wave did not restore its view"
bd._delete_track(wa); bd._delete_track(wb); bd._set_mode("volume")
print("WAVE CONTROLS ok: soundwave Solo/Mute reach the lanes; per-wave view remembered")

# INSTRUMENTS (#4): the top-level Original·Hum·Synth·Instrument selector switches kind + sub-picker;
# hum and pitched-instrument voices render.
from beatstudio.render import render_project as _rp
from beatstudio.model import Project as _Proj
from beatstudio import synth as _syn
assert len(_syn.HUMS) >= 10 and len(_syn.INSTS) >= 20, "need ≥10 hums and a big instrument palette"
bd.canvas.set_sel_take(0); bd.add_track(); hrow = bd._rows[-1]; htr = bd.tracks[-1]
hrow._on_group("Hum")
assert htr["kind"] == "hum" and htr["sound"] in _syn.HUMS, "Hum group did not set a hum voice"
vi = next(i for i, (k, s, l) in enumerate(hrow._combo_items) if s == "eee")
hrow.combo.setCurrentIndex(vi); assert htr["sound"] == "eee", "hum sub-picker did not set the sound"
bd.add_track(); irow = bd._rows[-1]; itr = bd.tracks[-1]
irow._on_group("Instrument")
vj = next(i for i, (k, s, l) in enumerate(irow._combo_items) if s == "violin")
irow.combo.setCurrentIndex(vj)
assert itr["kind"] == "inst" and itr["sound"] == "violin", "Instrument group did not pick the violin"
# both render audibly (a held note each)
for _t, _snd in ((htr, "eee"), (itr, "violin")):
    _t["points"] = [{"id": "z", "t": 0.2, "v": 0.8, "midi": 62, "hx": 0, "hy": 0}]
_hl, _he = bd._lane_events(htr); _il, _ie = bd._lane_events(itr)
_pp = _Proj(bpm=120); _pp.lanes += [_hl, _il]; _pp.events += _he + _ie
_out, _ = _rp(_pp, {})
assert float(np.abs(_out).sum()) > 0, "hum/instrument rendered silent"
bd._delete_track(itr); bd._delete_track(htr)
print(f"INSTRUMENTS ok: {len(_syn.HUMS)} hums + {len(_syn.INSTS)} instruments; group selector + voices render")

# ROW CONTROLS (v0.35 phase 1a): each separator track row has Solo/Mute/View buttons that act on
# the track's soundwave (Studio-header style, moved off the canvas onto the row).
bd.canvas.set_sel_take(0); bd.add_track(); rc_tr = bd.tracks[-1]; rc_row = bd._rows[-1]
rc_take = next(i for i, t in enumerate(bd.takes) if t["id"] == rc_tr["take"])
bd._on_track_flag(rc_tr, "solo"); assert bd.takes[rc_take]["solo"], "row Solo did not reach the soundwave"
bd._on_track_flag(rc_tr, "mute"); assert bd.takes[rc_take]["muted"], "row Mute did not reach the soundwave"
bd._on_track_flag(rc_tr, "notes"); assert bd.takes[rc_take].get("mode") == "notes", "row View did not set Notes"
assert rc_row.b_vn.text() == "♪", "row View button did not reflect Notes"
bd._on_track_flag(rc_tr, "solo"); bd._on_track_flag(rc_tr, "mute"); bd._on_track_flag(rc_tr, "volume")
bd._delete_track(rc_tr)
print("ROW CONTROLS ok: per-track Solo/Mute/View buttons act on the track's soundwave")

# MIDI (control surface): the module maps the APC correctly and its LED calls are safe with no
# device; the app wires keybed/knob/transport handlers without needing hardware.
from beatstudio.midi import MidiController, BUTTONS, KNOB_CC, PAD_LO, PAD_HI
assert PAD_HI - PAD_LO + 1 == 40 and len(KNOB_CC) == 8, "APC pad/knob map wrong"
assert BUTTONS[0x5b] == "play" and BUTTONS[0x5d] == "record", "APC transport notes wrong"
_mc = MidiController(); _mc.light_pad(0, "red"); _mc.light_button("play", True); _mc.clear()  # no crash
bd.add_track(); _mt = bd.tracks[-1]; _mt["kind"] = "hum"; _mt["sound"] = "aah"
bd.canvas.set_active(bd.tracks.index(_mt))
w._midi_note_on(60, 100)                                # keybed → audition the selected instrument
_p0 = dict(_mt["hum_params"]); w._midi_knob(0, 20)     # knobs drive the instrument's knob stack (NOT tempo)
assert _mt["hum_params"] != _p0, "knob did not drive the selected instrument's knob stack"
_bpm0 = w.toolbar.bpm.value(); w._midi_knob(3, 100)
assert w.toolbar.bpm.value() == _bpm0, "knob must NOT change tempo any more (that broke the grid)"
w._midi_pad(0, True); w._midi_pad(0, False)            # pad col 0 = tracks[0]: play + light (no crash)
w._midi_button("track1", True)                          # a Track button selects that column's track
bd._delete_track(_mt)
print("MIDI ok: 1-track-per-column grid; knobs drive the instrument (not tempo); handlers/LEDs safe")

# NO INFINITE LOOP: a nested sync call is guarded
calls = {"n": 0}; _orig = w._on_board_track_changed
def _count(x):
    calls["n"] += 1
    if calls["n"] < 50:
        _orig(x)
w._on_board_track_changed = _count
bd.add_track(); q = cv2._to_px(0.3, 0.6)
bd.canvas.set_active(len(bd.tracks) - 1)
cv2.mousePressEvent(E(q.x(), q.y())); cv2.mouseReleaseEvent(E(q.x(), q.y()))
assert calls["n"] < 10, f"possible sync loop ({calls['n']} calls)"
print(f"LOOP-GUARD ok: bounded sync calls ({calls['n']})")

# UNDO BOTH WINDOWS: an undo restores the board points AND the project together
app.processEvents()
w._committed = w._snapshot(); w._undo_stack = []; w._redo_stack = []
assert isinstance(w._committed, dict) and "project" in w._committed and "board" in w._committed, \
    "snapshot is not a {project, board} blob"
tr3 = next(t for t in bd.tracks if t.get("points"))
n_before = len(tr3["points"]); ev_before = len(w.project.events)
# add a new anchor on that track and commit — this is the state we will undo back FROM
bd.canvas.set_active(bd.tracks.index(tr3))
qb = bd.canvas._to_px(0.8, 0.5)
bd.canvas.mousePressEvent(E(qb.x(), qb.y())); bd.canvas.mouseReleaseEvent(E(qb.x(), qb.y()))
app.processEvents(); w._commit()
assert len(tr3["points"]) == n_before + 1, "new anchor was not added"
w._undo(); app.processEvents()
tr3 = next(t for t in bd.tracks if t.get("lane_id") == tr3.get("lane_id")) if tr3.get("lane_id") else bd.tracks[bd.tracks.index(tr3)]
assert len(tr3["points"]) == n_before, \
    f"undo did not restore board points ({len(tr3['points'])} != {n_before})"
assert len(w.project.events) == ev_before, "undo did not restore the project"
w._redo(); app.processEvents()
assert len(w.project.events) >= ev_before, "redo did not re-apply"
print("UNDO ok: undo/redo restores BOTH the board and the Studio project")

# VOLUME AUTOMATION: the V button toggles a lane's line; the envelope dips the rendered lane
import numpy as _np
from beatstudio.render import render_project as _render
lane_v = next(l for l in w.project.lanes if any(e.lane_id == l.id for e in w.project.events))
# clone a project with ONLY this lane's events so we measure it in isolation
w._on_header_action(lane_v.id, "vol")
assert lane_v.id in w.timeline.vol_lanes, "V button did not turn the volume line on"
w._on_header_action(lane_v.id, "vol")
assert lane_v.id not in w.timeline.vol_lanes, "V button did not toggle the line off"
ev_v = min((e.beat for e in w.project.events if e.lane_id == lane_v.id))
lane_v.vol_pts = []
loud, _ = _render(w.project, w._samples, orig=w._orig_rec)
lane_v.vol_pts = [{"beat": ev_v, "v": 0.0}, {"beat": ev_v + 8, "v": 0.0}]   # silence this lane
quiet, _ = _render(w.project, w._samples, orig=w._orig_rec)
assert float(_np.abs(quiet).sum()) < float(_np.abs(loud).sum()), \
    "volume envelope did not reduce the rendered signal"
lane_v.vol_pts = []
print("VOLUME ok: V toggles the line; a vol_pts dip renders quieter (per-lane gain)")

# GRID STRETCH: LEFT-drag in Grid mode uniformly rescales the tempo (bpm)
bd._set_tool("grid")
cvg = bd.canvas; xg0, xg1 = cvg._xspan(); gx = xg0 + (xg1 - xg0) * 0.5
bpm0 = bd.bpm
cvg.mousePressEvent(E(gx, cvg.height() / 2))
cvg.mouseMoveEvent(E(gx + 120, cvg.height() / 2))
cvg.mouseReleaseEvent(None)
app.processEvents()
assert bd.bpm != bpm0 and w.project.bpm == bd.bpm, f"grid stretch failed ({bpm0}->{bd.bpm}, studio={w.project.bpm})"
print(f"GRID ok: left-drag rescaled tempo {bpm0}->{bd.bpm} and synced to the Studio")

# GRID MOVE: RIGHT-drag in Grid mode slides the grid sideways (offset), no tempo change
off0 = cvg.grid_off; bpm_before = bd.bpm
cvg.mousePressEvent(E(gx, cvg.height() / 2, btn=Qt.RightButton))
cvg.mouseMoveEvent(E(gx + 60, cvg.height() / 2, btn=Qt.RightButton))
cvg.mouseReleaseEvent(None)
app.processEvents()
assert cvg.grid_off != off0 and bd.bpm == bpm_before, f"grid move failed (off {off0}->{cvg.grid_off}, bpm {bpm_before}->{bd.bpm})"
print(f"GRID MOVE ok: right-drag slid the grid (offset {off0:.3f}->{cvg.grid_off:.3f}s), tempo unchanged")
bd._set_tool("pen")

# FIT: resample an audio slice shrinks the take and remaps points (in-region moves, before-region ~stays)
trf = next(t for t in bd.tracks if t.get("points")); bd.canvas.set_active(bd.tracks.index(trf))
trf["points"] = [{"id": "fa", "t": 0.1, "v": 0.8, "hx": 0.0, "hy": 0.0},
                 {"id": "fb", "t": 0.7, "v": 0.8, "hx": 0.0, "hy": 0.0}]
N0 = len(bd.buf); t_after0 = trf["points"][1]["t"]; t_before0 = trf["points"][0]["t"]
bd._apply_fit(0.3, 0.6, 0.45)                      # shrink [0.3,0.6] → ends at 0.45
app.processEvents()
N1 = len(bd.buf)
assert N1 < N0, f"fit shrink did not shorten the take ({N0}->{N1})"
assert abs(trf["points"][1]["t"] - t_after0) > 0.01, "a point after the region did not move"
# a point BEFORE the region keeps its absolute audio time (fraction × length ≈ unchanged)
assert abs(trf["points"][0]["t"] * N1 - t_before0 * N0) < 0.03 * N0, "a point before the region drifted"
print(f"FIT ok: region resample shortened the take {N0}->{N1} and remapped drawn points")

# FULLSCREEN (global) + REOPEN: the Studio toolbar drives full screen for both windows, and the
# screens button reopens a separator that was closed in two-screen mode.
w._one_screen = False; w._float_board(); app.processEvents()
w._toggle_fullscreen(); app.processEvents()
assert w.isFullScreen() and getattr(bd, "_is_full", False), "global full screen did not cover both windows"
w._toggle_fullscreen(); app.processEvents()
assert not w.isFullScreen() and not getattr(bd, "_is_full", False), "exit full screen failed"
bd.hide(); app.processEvents()                       # user closed the separator (two-screen)
assert not bd.isVisible()
w._toggle_layout(); app.processEvents()               # screens button → reopens it (no layout flip)
assert bd.isVisible() and not w._one_screen, "screens button did not reopen the closed separator"
print("FULLSCREEN ok: global full screen covers both windows; screens button reopens a closed separator")

# NAVIGATOR (#5): the Studio minimap is a box-drag navigator (like the board) — a viewport box,
# no on-grid mirror, and dragging it pans the timeline.
w.timeline.set_ppb(80); app.processEvents()
mm = w.minimap; mm._expanded = True
mw, mh, _ = mm._map_size(); vb = mm._view_box(mw, mh)
assert vb.width() > 0 and vb.height() > 0, "minimap has no viewport box"
from PySide6.QtCore import QPointF as _QP
sx0 = w.timeline.horizontalScrollBar().value()
mm._dragging = True; mm._go(_QP(mw * 0.8, mh * 0.5)); app.processEvents()
assert w.timeline.horizontalScrollBar().value() != sx0, "dragging the navigator did not pan"
assert w.timeline.mirror is None, "navigator should not draw an on-grid mirror (board-style box only)"
mm._dragging = False
print("NAVIGATOR ok: Studio minimap is a box-drag navigator (matches the board); drag pans")

# LIFECYCLE: closing the Studio closes the separator (float it out first — separate-window path)
w._float_board(); app.processEvents()
assert bd.isVisible(); w.close(); app.processEvents()
assert w._board is None, "closing Studio did not close the separator"
print("LIFECYCLE ok: closing Studio closed the separator")
print("LIVE SYNC WORKS ✓")
