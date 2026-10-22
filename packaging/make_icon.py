"""Render the app icon to PNG and ICO for packaging: python packaging/make_icon.py <out_dir>"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QGuiApplication

from domain_pulse.theme import make_icon

app = QGuiApplication(sys.argv)
out = Path(sys.argv[1] if len(sys.argv) > 1 else "build")
out.mkdir(parents=True, exist_ok=True)
icon = make_icon()
icon.pixmap(256, 256).save(str(out / "domain-pulse.png"))
if not icon.pixmap(256, 256).save(str(out / "domain-pulse.ico")):
    sys.exit("could not write .ico")
print(f"icons written to {out}")
