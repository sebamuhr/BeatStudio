"""Post-recording questionnaire: for each distinct sound the software found in your beatbox,
play an example and ask what it is. Your answers build the track AND train your personal model
so next time it recognises the sound itself."""
from __future__ import annotations
import numpy as np
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QComboBox, QWidget, QScrollArea, QFrame)
from PySide6.QtCore import Qt

from . import theme
from .usermodel import CATEGORIES, CAT_BY_ID
from .synth import SR


class _ClusterRow(QFrame):
    def __init__(self, cluster, play_cb, instr_cb):
        super().__init__()
        self.cluster = cluster
        self.play_cb = play_cb
        self.instr_cb = instr_cb
        self.setStyleSheet("QFrame{background:#13131b;border:1px solid #2a2a36;border-radius:10px;}")
        lay = QHBoxLayout(self); lay.setContentsMargins(12, 10, 12, 10); lay.setSpacing(12)

        play = QPushButton("▶"); play.setFixedSize(40, 40); play.setCursor(Qt.PointingHandCursor)
        play.setToolTip("Hear YOUR recorded sound")
        play.setStyleSheet("QPushButton{background:#173a2a;border:1px solid #2f7d55;border-radius:20px;"
                           "color:#6ef0a8;font-size:16px;}QPushButton:hover{background:#1e5138;}")
        play.clicked.connect(lambda: self.play_cb(self.cluster["rep_audio"]))
        lay.addWidget(play)

        info = QVBoxLayout(); info.setSpacing(2)
        n = cluster["n"]
        conf = cluster.get("suggest_conf", 0)
        hint = "  (learned)" if conf > 0.5 else "  (guess)"
        title = QLabel(f"Sound with {n} hit{'s' if n != 1 else ''}")
        title.setStyleSheet("color:#e2e2ea;font-size:13px;font-weight:600;border:none;")
        sub = QLabel("What instrument should this become?" + hint)
        sub.setStyleSheet("color:#8a8a99;font-size:11px;border:none;")
        info.addWidget(title); info.addWidget(sub)
        w = QWidget(); w.setLayout(info); w.setStyleSheet("border:none;")
        lay.addWidget(w, 1)

        self.combo = QComboBox(); self.combo.setFixedWidth(190); self.combo.setMinimumHeight(34)
        self.combo.setFont(theme.sans(12))
        for cid, label, *_ in CATEGORIES:
            self.combo.addItem(label, cid)
        # preselect the suggestion
        sug = cluster.get("suggest") or "kick"
        for i in range(self.combo.count()):
            if self.combo.itemData(i) == sug:
                self.combo.setCurrentIndex(i); break
        self.combo.setStyleSheet(
            "QComboBox{background:#1c1c26;border:1px solid #3a3a48;border-radius:8px;color:#fff;"
            "padding:4px 12px;}QComboBox QAbstractItemView{background:#1c1c26;color:#fff;"
            "selection-background-color:#3a3a48;}")
        lay.addWidget(self.combo)

        # preview the CHOSEN INSTRUMENT (so you can compare it to your sound)
        pin = QPushButton("🔊"); pin.setFixedSize(34, 34); pin.setCursor(Qt.PointingHandCursor)
        pin.setToolTip("Hear the chosen instrument")
        pin.setStyleSheet("QPushButton{background:#16161e;border:1px solid #2a2a36;border-radius:8px;"
                          "color:#c0a8ff;font-size:14px;}QPushButton:hover{background:#1e1e28;}")
        pin.clicked.connect(lambda: self.instr_cb(self.combo.currentData()))
        lay.addWidget(pin)

    def decision(self):
        return self.cluster["id"], self.combo.currentData()


class ReviewDialog(QDialog):
    def __init__(self, bpm, clusters, play_cb, instr_cb, parent=None):
        super().__init__(parent)
        self.clusters = clusters
        self.setWindowTitle("What did you just beatbox?")
        self.resize(620, 560)
        self.setStyleSheet(f"background:{theme.BG.name()};color:#d8d8e0;")
        root = QVBoxLayout(self); root.setContentsMargins(18, 16, 18, 16); root.setSpacing(12)

        head = QLabel(f"I found <b>{len(clusters)}</b> distinct sounds at <b>{bpm} BPM</b>. "
                      f"Tell me what each one is — I'll build the track and remember your kit.")
        head.setWordWrap(True); head.setStyleSheet("color:#c0c0cc;font-size:13px;")
        root.addWidget(head)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget(); il = QVBoxLayout(inner); il.setSpacing(8); il.setContentsMargins(0, 0, 6, 0)
        self.rows = []
        for c in clusters:
            r = _ClusterRow(c, play_cb, instr_cb); self.rows.append(r); il.addWidget(r)
        il.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        btns = QHBoxLayout(); btns.addStretch(1)
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        cancel.setStyleSheet("QPushButton{background:#16161e;border:1px solid #2a2a36;border-radius:8px;"
                             "color:#d8d8e0;padding:8px 16px;}")
        ok = QPushButton("Build the track  →"); ok.setCursor(Qt.PointingHandCursor); ok.clicked.connect(self.accept)
        ok.setStyleSheet("QPushButton{background:#7c5cff;border:none;border-radius:8px;color:#fff;"
                         "padding:8px 18px;font-weight:600;}QPushButton:hover{background:#8b6dff;}")
        btns.addWidget(cancel); btns.addWidget(ok)
        root.addLayout(btns)

    def decisions(self):
        return {cid: cat for cid, cat in (r.decision() for r in self.rows)}
