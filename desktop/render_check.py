#!/usr/bin/env python3
"""Headless render check: build the window offscreen and grab it to a PNG so we can
eyeball it against the web reference. Run with QT_QPA_PLATFORM=offscreen BEAT_NO_GL=1."""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from beatstudio.mainwindow import MainWindow

app = QApplication(sys.argv)
win = MainWindow()
win.resize(1440, 900)
win.show()

def shoot():
    app.processEvents()
    pm = win.grab()
    out = "/home/sebastian/Documents/APPS/Beat/desktop/ref/native-01.png"
    pm.save(out)
    print("saved", out, pm.width(), "x", pm.height())
    app.quit()

QTimer.singleShot(400, shoot)
sys.exit(app.exec())
