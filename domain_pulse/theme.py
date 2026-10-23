"""Colors, stylesheet and the app icon (drawn in code so there are no binary assets)."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

BG = "#06080d"
PANEL = "#0c1220"
PANEL_HI = "#111a2e"
BORDER = "#1a2742"
TEXT = "#e4ecf8"
MUTED = "#7d8aa6"
ACCENT = "#1e90ff"
ACCENT_2 = "#00c8ff"
GOOD = "#2ee6a6"
WARN = "#ffb020"
BAD = "#ff4d6a"
DROP = "#b67cff"

STATUS_COLORS = {"available": GOOD, "expiring": WARN, "expired": BAD, "error": BAD,
                 "registered": ACCENT_2, "pending": MUTED, "unknown": MUTED,
                 "grace period": WARN, "redemption": BAD, "pending delete": DROP}

STYLESHEET = f"""
* {{ font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif; font-size: 13px; color: {TEXT}; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QLabel#title {{ font-size: 22px; font-weight: 700; letter-spacing: 3px; }}
QLabel#subtitle {{ color: {MUTED}; letter-spacing: 1px; }}
QFrame#card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; }}
QLabel#cardValue {{ font-size: 26px; font-weight: 700; }}
QLabel#cardLabel {{ color: {MUTED}; font-size: 11px; letter-spacing: 1px; }}
QPushButton {{
    background: {PANEL_HI}; border: 1px solid {BORDER}; border-radius: 6px; padding: 7px 14px;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {ACCENT_2});
    border: none; color: #001020; font-weight: 600;
}}
QPushButton#primary:hover {{ background: {ACCENT_2}; }}
QLineEdit {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; padding: 7px 10px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QTableView {{
    background: {PANEL}; alternate-background-color: #0e1526; border: 1px solid {BORDER};
    border-radius: 10px; gridline-color: transparent; selection-background-color: #12305a;
    selection-color: {TEXT};
}}
QTableView::item {{ padding: 4px 8px; border: none; }}
QHeaderView::section {{
    background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
    padding: 8px; font-size: 11px; font-weight: 600; letter-spacing: 1px;
}}
QTableCornerButton::section {{ background: {PANEL}; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {ACCENT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QFrame#footer {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}
QLabel#footerText {{ color: {MUTED}; }}
QMenu {{ background: {PANEL}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: #12305a; }}
QToolTip {{ background: {PANEL_HI}; color: {TEXT}; border: 1px solid {ACCENT}; }}
QMessageBox, QDialog {{ background: {PANEL}; }}
"""


def make_icon(alert: bool = False) -> QIcon:
    """Rounded dark tile with a blue heartbeat line; a green dot when something needs attention."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        s = size / 64
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(BG))
        p.drawRoundedRect(QRectF(2 * s, 2 * s, 60 * s, 60 * s), 14 * s, 14 * s)

        path = QPainterPath(QPointF(8 * s, 34 * s))
        for x, y in ((20, 34), (26, 20), (34, 48), (40, 28), (44, 34), (56, 34)):
            path.lineTo(QPointF(x * s, y * s))
        grad = QLinearGradient(0, 0, size, 0)
        grad.setColorAt(0, QColor(ACCENT))
        grad.setColorAt(1, QColor(ACCENT_2))
        pen = QPen(grad, max(1.5, 5 * s), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        if alert:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(GOOD))
            p.drawEllipse(QPointF(50 * s, 14 * s), 9 * s, 9 * s)
        p.end()
        icon.addPixmap(pm)
    return icon
