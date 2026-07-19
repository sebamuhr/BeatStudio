"""Akai APC Key 25 mk2 control-surface integration (optional — degrades to nothing if absent).

The APC is USB class-compliant, so ALSA/mido see it with no driver. It exposes two useful ports:
  • "Keys"    — the velocity-sensitive keybed (play instruments / place notes).
  • "Control" — the 40 pads, 8 knobs, transport + track/scene buttons, AND their LEDs (two-way).

We poll both inputs on a QTimer (Qt main thread — no locks) and emit Qt signals. LEDs are lit by
sending note-on to the Control OUTPUT: velocity = colour (128-colour palette), channel = behaviour
(solid brightness / pulse / blink). Protocol: Akai "APC Key 25 mk2 Communication Protocol v1.1".
"""
from __future__ import annotations
from PySide6.QtCore import QObject, QTimer, Signal

try:
    import mido
    mido.set_backend("mido.backends.rtmidi")
    _MIDI_OK = True
except Exception:
    _MIDI_OK = False

# --- APC mk2 control-surface map (Control port) ---
PAD_LO, PAD_HI = 0x00, 0x27          # 40 pads, notes 0..39
KNOB_CC = list(range(48, 56))        # 8 knobs → CC 48..55
BUTTONS = {                          # note -> logical name
    0x51: "stop_all", 0x5b: "play", 0x5d: "record",
    **{0x40 + i: f"track{i+1}" for i in range(8)},
    **{0x52 + i: f"scene{i+1}" for i in range(5)},
}
BTN_NOTE = {v: k for k, v in BUTTONS.items()}

# LED behaviour = MIDI channel; colour = velocity (see the palette in the protocol PDF)
LED_SOLID = 6                        # channel 6 = solid, 100% brightness
LED_PULSE = 9                        # channel 9 = pulse 1/4
LED_BLINK = 13                       # channel 13 = blink 1/8 (a pad that's actively playing)
COLORS = {"off": 0, "white": 3, "red": 5, "orange": 9, "yellow": 13, "green": 21,
          "cyan": 37, "blue": 45, "purple": 49, "magenta": 53}


class MidiController(QObject):
    """Emits control-surface events; call `light_pad` / `light_button` for LED feedback."""
    note_on = Signal(int, int)       # keybed: (midi, velocity 1..127)
    note_off = Signal(int)           # keybed: (midi)
    pad = Signal(int, bool)          # grid pad: (index 0..39, pressed)
    knob = Signal(int, int)          # (knob index 0..7, value 0..127)
    button = Signal(str, bool)       # (name, pressed) — play/record/stop_all/track*/scene*

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keys = self._ctrl_in = self._ctrl_out = None
        self.connected = False
        self._timer = QTimer(self); self._timer.setInterval(8)
        self._timer.timeout.connect(self._poll)

    # ---- lifecycle ----
    def start(self) -> bool:
        """Open the APC if present. Returns True when connected. Safe to call with no device."""
        if not _MIDI_OK:
            return False
        try:
            keys = _find(mido.get_input_names(), "APC Key 25", "Keys")
            ctrl_in = _find(mido.get_input_names(), "APC Key 25", "Control")
            ctrl_out = _find(mido.get_output_names(), "APC Key 25", "Control")
            if not (keys and ctrl_in and ctrl_out):
                return False
            self._keys = mido.open_input(keys)
            self._ctrl_in = mido.open_input(ctrl_in)
            self._ctrl_out = mido.open_output(ctrl_out)
        except Exception:
            self.stop(); return False
        self.connected = True
        self._timer.start()
        return True

    def stop(self):
        self._timer.stop()
        for p in (self._keys, self._ctrl_in, self._ctrl_out):
            try:
                if p is not None:
                    p.close()
            except Exception:
                pass
        self._keys = self._ctrl_in = self._ctrl_out = None
        self.connected = False

    # ---- input (polled on the Qt main thread) ----
    def _poll(self):
        if self._keys is not None:
            for m in self._keys.iter_pending():
                if m.type == "note_on" and m.velocity > 0:
                    self.note_on.emit(m.note, m.velocity)
                elif m.type in ("note_off",) or (m.type == "note_on" and m.velocity == 0):
                    self.note_off.emit(m.note)
        if self._ctrl_in is not None:
            for m in self._ctrl_in.iter_pending():
                if m.type == "control_change" and m.control in KNOB_CC:
                    self.knob.emit(KNOB_CC.index(m.control), m.value)
                elif m.type in ("note_on", "note_off"):
                    pressed = (m.type == "note_on" and m.velocity > 0)
                    if PAD_LO <= m.note <= PAD_HI:
                        self.pad.emit(m.note - PAD_LO, pressed)
                    elif m.note in BUTTONS and pressed:
                        self.button.emit(BUTTONS[m.note], True)

    # ---- output (LED feedback) ----
    def light_pad(self, index: int, color, behavior: int = LED_SOLID):
        if self._ctrl_out is None or not (0 <= index <= 39):
            return
        vel = COLORS.get(color, color if isinstance(color, int) else 0)
        self._send("note_on", behavior, PAD_LO + index, int(vel))

    def light_button(self, name: str, on: bool):
        if self._ctrl_out is None or name not in BTN_NOTE:
            return
        self._send("note_on", 0, BTN_NOTE[name], 1 if on else 0)

    def clear(self):
        for i in range(40):
            self.light_pad(i, "off")
        for name in BTN_NOTE:
            self.light_button(name, False)

    def _send(self, kind, channel, note, velocity):
        try:
            self._ctrl_out.send(mido.Message(kind, channel=channel, note=note, velocity=velocity))
        except Exception:
            pass


def _find(names, *needles):
    for n in names:
        if all(x.lower() in n.lower() for x in needles):
            return n
    return None
