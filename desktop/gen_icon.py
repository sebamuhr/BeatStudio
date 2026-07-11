#!/usr/bin/env python3
"""Generate a 256x256 app icon (dark rounded tile with beat blocks + play arrow)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QImage, QPainter, QColor, QBrush, QPainterPath, QPolygonF
from PySide6.QtCore import Qt, QRectF, QPointF

S = 256
img = QImage(S, S, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)

# rounded tile
path = QPainterPath(); path.addRoundedRect(QRectF(8, 8, S - 16, S - 16), 52, 52)
p.fillPath(path, QBrush(QColor("#0d0d12")))
p.setPen(Qt.NoPen)

# beat blocks (brand palette)
cols = ["#ff5d5d", "#ffb13d", "#3dd6ff", "#7c5cff", "#48e08b", "#ff6fd8"]
rows_y = [70, 104, 138, 172]
p.setClipPath(path)
for i, y in enumerate(rows_y):
    xs = [56, 96, 150, 196]
    for j, x in enumerate(xs):
        if (i + j) % 3 == 0:
            continue
        c = QColor(cols[(i * 2 + j) % len(cols)])
        w = 30 if (i + j) % 2 else 16
        p.fillRect(QRectF(x, y, w, 18), c)

# purple play arrow badge
p.setBrush(QBrush(QColor("#7c5cff"))); p.setPen(Qt.NoPen)
p.drawEllipse(QRectF(150, 150, 74, 74))
tri = QPolygonF([QPointF(178, 170), QPointF(178, 204), QPointF(206, 187)])
p.setBrush(QBrush(QColor("#0d0d12"))); p.drawPolygon(tri)
p.end()

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
img.save(out)
print("wrote", out)
