"""Run the panel on a machine without Qt's `qml6` tool (a dev PC): same Main.qml,
loaded through PySide6. `pyside6-qml` cannot pass --api to the app."""
import os
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

app = QGuiApplication(sys.argv)
engine = QQmlApplicationEngine()
engine.load(QUrl.fromLocalFile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Main.qml")))
if not engine.rootObjects():
    sys.exit(1)
sys.exit(app.exec())
