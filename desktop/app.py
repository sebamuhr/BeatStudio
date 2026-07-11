#!/usr/bin/env python3
"""Entry point for Beat Studio (native desktop)."""
import sys
from PySide6.QtWidgets import QApplication
from beatstudio.mainwindow import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Beat Studio")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
