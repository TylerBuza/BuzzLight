# PyInstaller spec — builds dist\BuzzLight\BuzzLight.exe
#
#   .venv\Scripts\python -m PyInstaller BuzzLight.spec --noconfirm
#
# One-folder build: starts quickly, which matters for Start with Windows.

import os
import sys
from pathlib import Path

root = Path(os.getcwd())
sys.path.insert(0, str(root))


def make_ico():
    """Render the in-code app icon to an .ico for the exe."""
    from PyQt6.QtWidgets import QApplication
    from buzzlight.ui.theme import make_icon_pixmap
    app = QApplication.instance() or QApplication([])
    out = root / "build" / "BuzzLight.ico"
    out.parent.mkdir(parents=True, exist_ok=True)
    make_icon_pixmap(256).save(str(out), "ICO")
    return str(out)


a = Analysis(
    [str(root / "BuzzLight.pyw")],
    pathex=[str(root)],
    hiddenimports=["bettercam", "comtypes", "comtypes.stream", "serial.tools.list_ports"],
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "cv2", "PIL", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="BuzzLight",
          console=False, upx=False, icon=make_ico())
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="BuzzLight")
