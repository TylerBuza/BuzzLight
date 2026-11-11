"""Application entry: single instance, tray, main window."""

from __future__ import annotations

import os
import sys
import time

from buzzlight.paths import config_dir, log_file


def _log_to_file_if_windowless() -> None:
    """pythonw / the frozen exe have no console: keep output in a log."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        path = log_file()
        mode = "w" if os.path.exists(path) and os.path.getsize(path) > 1_000_000 else "a"
        log = open(path, mode, encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
        print(f"--- BuzzLight started {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
    except OSError:
        pass


KEY = "buzzlight-single-instance"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    _log_to_file_if_windowless()

    from PyQt6.QtCore import QLockFile
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    from PyQt6.QtWidgets import QApplication

    app = QApplication(argv)
    app.setApplicationName("BuzzLight")
    app.setQuitOnLastWindowClosed(False)

    def ping_running() -> bool:
        s = QLocalSocket()
        s.connectToServer(KEY)
        if not s.waitForConnected(300):
            return False
        s.write(b"show")
        s.waitForBytesWritten(300)
        s.disconnectFromServer()
        return True

    # One copy owns the strip. The lock is taken immediately at startup, so
    # a copy launched a moment later waits for the first one's socket and
    # hands over instead of starting a second instance.
    lock = QLockFile(os.path.join(config_dir(), "instance.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if ping_running():
                print("[app] already running; showing it")
                return 0
            time.sleep(0.25)
        print("[app] another instance holds the lock; exiting")
        return 0

    from buzzlight.controller import Controller
    from buzzlight.ui import theme
    from buzzlight.ui.main_window import MainWindow
    from buzzlight.ui.tray import Tray

    app.setStyleSheet(theme.STYLESHEET)
    app.setWindowIcon(theme.app_icon())

    controller = Controller()
    window = MainWindow(controller)
    tray = None
    if Tray.available():
        tray = Tray(window, controller, app)
        window.attach_tray(tray)

    server = QLocalServer(window)
    QLocalServer.removeServer(KEY)
    if server.listen(KEY):
        def on_conn():
            conn = server.nextPendingConnection()
            if conn:
                conn.readyRead.connect(lambda: (conn.readAll(),
                                                tray.show_window() if tray else window.show()))
                conn.disconnected.connect(conn.deleteLater)
        server.newConnection.connect(on_conn)

    controller.start()
    if "--minimized" not in argv or tray is None:
        window.show()

    app.aboutToQuit.connect(controller.shutdown)
    code = app.exec()
    lock.unlock()
    return code
