"""AI Settings dialog — point the app at your home-server model.

Type the server URL and Beat Studio asks the server what models it has and shows them in a
dropdown, so you pick instead of typing a tag by hand (mistyped tags are the usual failure).
The model box is still editable if you want to type one. 'Test' pings without freezing the UI.
"""
from __future__ import annotations
import threading

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QComboBox, QCheckBox, QPushButton)
from PySide6.QtCore import Qt, Signal, QTimer

from . import config, llm

_CSS = """
QDialog{background:#13131b;color:#e4e4ec;}
QLabel{color:#c8c8d4;}
QLineEdit,QComboBox{background:#0d0d12;color:#ffffff;border:1px solid #2f2f3c;border-radius:6px;
          padding:7px 9px;min-height:20px;}
QLineEdit:focus,QComboBox:focus{border:1px solid #5a5af0;}
QComboBox QAbstractItemView{background:#0d0d12;color:#ffffff;selection-background-color:#3a3a55;}
QCheckBox{color:#c8c8d4;}
QPushButton{background:#23232f;color:#ffffff;border:1px solid #34344a;border-radius:6px;
            padding:7px 14px;}
QPushButton:hover{background:#2c2c3c;}
QPushButton#primary{background:#4a4af0;border:1px solid #6a6aff;}
QPushButton#primary:hover{background:#5a5aff;}
"""


class AISettingsDialog(QDialog):
    _tested = Signal(bool, str)
    _models = Signal(list, str)          # (model ids, error message)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Arrange — Server Settings")
        self.setMinimumWidth(560)
        self.setStyleSheet(_CSS)
        self._cfg = dict(cfg)

        root = QVBoxLayout(self)
        intro = QLabel("Point Beat Studio at a model on your home server. Any OpenAI-compatible "
                       "server works — Ollama, vLLM, LM Studio, llama.cpp. Enter the URL and the "
                       "model list loads automatically; change it anytime.")
        intro.setWordWrap(True)
        root.addWidget(intro)

        grid = QGridLayout(); grid.setColumnStretch(1, 1)
        # URL row
        self.url = QLineEdit(cfg.get("ai_base_url", ""))
        self.url.setPlaceholderText("192.168.1.50  (or http://host:11434/v1)")
        self.url.editingFinished.connect(self._load_models)
        grid.addWidget(QLabel("Server URL"), 0, 0); grid.addWidget(self.url, 0, 1)
        # Model row: editable combo + refresh
        self.model = QComboBox(); self.model.setEditable(True)
        self.model.setInsertPolicy(QComboBox.NoInsert)
        if cfg.get("ai_model"):
            self.model.addItem(cfg["ai_model"]); self.model.setCurrentText(cfg["ai_model"])
        mrow = QHBoxLayout(); mrow.setContentsMargins(0, 0, 0, 0)
        mrow.addWidget(self.model, 1)
        self.reload_btn = QPushButton("↻"); self.reload_btn.setFixedWidth(40)
        self.reload_btn.setToolTip("Reload the model list from the server")
        self.reload_btn.clicked.connect(self._load_models)
        mrow.addWidget(self.reload_btn)
        grid.addWidget(QLabel("Model"), 1, 0); grid.addLayout(mrow, 1, 1)
        # Key row
        self.key = QLineEdit(cfg.get("ai_api_key", ""))
        self.key.setPlaceholderText("(usually blank for local servers)")
        grid.addWidget(QLabel("API key (optional)"), 2, 0); grid.addWidget(self.key, 2, 1)
        root.addLayout(grid)

        self.enabled = QCheckBox("Enable AI arranging")
        self.enabled.setChecked(bool(cfg.get("ai_enabled", True)))
        root.addWidget(self.enabled)

        self.status = QLabel(""); self.status.setWordWrap(True)
        root.addWidget(self.status)

        row = QHBoxLayout()
        self.test_btn = QPushButton("Test connection"); self.test_btn.clicked.connect(self._test)
        row.addWidget(self.test_btn); row.addStretch(1)
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        save = QPushButton("Save"); save.setObjectName("primary"); save.clicked.connect(self._save)
        row.addWidget(cancel); row.addWidget(save)
        root.addLayout(row)

        self._tested.connect(self._on_tested)
        self._models.connect(self._on_models)
        self._elapsed = 0
        self._tick = QTimer(self); self._tick.setInterval(1000); self._tick.timeout.connect(self._on_tick)
        if cfg.get("ai_base_url"):
            QTimer.singleShot(0, self._load_models)     # auto-load on open

    # ---- model list ----
    def _load_models(self):
        url = self.url.text().strip()
        if not url:
            return
        self.reload_btn.setEnabled(False)
        self.status.setStyleSheet("color:#c8c8d4;")
        self.status.setText(f"Loading models from {llm.normalize_base_url(url)} …")
        key = self.key.text().strip()

        def work():
            try:
                ids = llm.list_models(url, key)
                self._models.emit(ids, "")
            except Exception as e:
                self._models.emit([], str(e))
        threading.Thread(target=work, daemon=True).start()

    def _on_models(self, ids: list, err: str):
        self.reload_btn.setEnabled(True)
        keep = self.model.currentText().strip()
        if err:
            self.status.setText("✕ " + err); self.status.setStyleSheet("color:#ff8a8a;")
            return
        self.model.blockSignals(True)
        self.model.clear(); self.model.addItems(ids)
        if keep and keep in ids:
            self.model.setCurrentText(keep)
        elif keep:
            self.model.insertItem(0, keep); self.model.setCurrentIndex(0)
        self.model.blockSignals(False)
        self.status.setText(f"✓ {len(ids)} model(s) available — pick one from the list.")
        self.status.setStyleSheet("color:#6fdc8c;")

    # ---- test ----
    def _on_tick(self):
        self._elapsed += 1
        self.status.setText(f"⏳ Testing {llm.normalize_base_url(self.url.text().strip())} … "
                            f"{self._elapsed}s (a big model can take ~30–60s to load the first time)")

    def _test(self):
        url, model = self.url.text().strip(), self.model.currentText().strip()
        if not url or not model:
            self.status.setText("✕ Fill in the server URL and pick a model.")
            self.status.setStyleSheet("color:#ff8a8a;"); return
        key = self.key.text().strip()
        self.test_btn.setEnabled(False); self._elapsed = 0
        self.status.setStyleSheet("color:#c8c8d4;")
        self._on_tick(); self._tick.start()

        def work():
            try:
                ok, msg = llm.ping(url, model, key)
            except Exception as e:
                ok, msg = False, f"Unexpected error: {e}"
            self._tested.emit(ok, msg)
        threading.Thread(target=work, daemon=True).start()

    def _on_tested(self, ok: bool, msg: str):
        self._tick.stop(); self.test_btn.setEnabled(True)
        self.status.setText(("✓ " if ok else "✕ ") + msg)
        self.status.setStyleSheet("color:#6fdc8c;" if ok else "color:#ff8a8a;")

    # ---- save ----
    def _save(self):
        self._cfg.update({"ai_base_url": llm.normalize_base_url(self.url.text().strip()),
                          "ai_model": self.model.currentText().strip(),
                          "ai_api_key": self.key.text().strip(),
                          "ai_enabled": self.enabled.isChecked()})
        config.save(self._cfg)
        self.accept()

    def result_config(self) -> dict:
        return self._cfg
