"""Colours, metrics and fonts — matched to the web app's reference screenshots."""
from PySide6.QtGui import QColor, QFont, QFontDatabase

# ---- grid metrics (taken straight from the web app) ----
PPB_DEFAULT = 64      # pixels per beat at 100% zoom
LANE_H      = 66      # per-track row height
RULER_H     = 26      # top ruler band height
HEADER_W    = 300     # left track-header column width
PAD         = 12      # left padding before beat 0
BEATS_PER_BAR = 4

# ---- palette ----
BG        = QColor("#0a0a0f")   # app background
PANEL     = QColor("#0d0d12")   # timeline / panel background
PANEL_2   = QColor("#101016")
BORDER    = QColor("#1a1a24")
BORDER_2  = QColor("#2a2a36")
INK       = QColor("#e2e2ea")   # primary text
INK_DIM   = QColor("#8a8a99")   # secondary text
INK_FAINT = QColor("#4a4a56")   # labels
ACCENT    = QColor("#7c5cff")   # purple (master / brand)
ACCENT_CY = QColor("#3dd6ff")   # cyan (selection / dot)
REC       = QColor("#ff5d5d")   # record red
GREEN     = QColor("#48e08b")

_LANE_HEX = ["#ff5d5d", "#ffb13d", "#3dd6ff", "#7c5cff", "#48e08b",
             "#ff6fd8", "#ffd24d", "#5cd6c0", "#c08cff", "#ff8c5c"]


def lane_color(i: int) -> QColor:
    """Same rule as the web _colorAt: 10 fixed hues, then hsl((i*53)%360,68%,62%)."""
    if i < len(_LANE_HEX):
        return QColor(_LANE_HEX[i])
    h = (i * 53) % 360
    return QColor.fromHsl(h, int(0.68 * 255), int(0.62 * 255))


def lane_color_of(lane, i: int) -> QColor:
    """A lane's STABLE colour: its own stored hue if it has one, else the index colour. This is
    what keeps a track's colour fixed even when tracks above it are removed."""
    c = getattr(lane, "color", "") or ""
    return QColor(c) if c else lane_color(i)


def _w(weight) -> QFont.Weight:
    return weight if isinstance(weight, QFont.Weight) else QFont.Weight(int(weight))


def mono(size: int = 10, weight=QFont.Weight.Normal) -> QFont:
    f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    f.setPointSize(size)
    f.setWeight(_w(weight))
    return f


def sans(size: int = 12, weight=QFont.Weight.Normal) -> QFont:
    f = QFont()
    for fam in ("Inter", "Segoe UI", "DejaVu Sans", "Sans Serif"):
        if fam in QFontDatabase.families():
            f.setFamily(fam)
            break
    f.setPointSize(size)
    f.setWeight(_w(weight))
    return f
