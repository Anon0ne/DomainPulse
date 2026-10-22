"""Main window, tray icon and background checking loop."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QObject, QRunnable, QSortFilterProxyModel,
                            QStandardPaths, Qt, QThreadPool, QTimer, QUrl, Signal)
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QSystemTrayIcon,
                               QTableView, QVBoxLayout, QWidget)

from . import APP_NAME, BRAND_NAME, BRAND_URL, REGISTER_URL, __version__, csv_io, monitor, theme
from .rdap import AVAILABLE, REGISTERED, LookupResult, RdapClient, is_valid, normalize
from .store import Domain, Store, utcnow

COLUMNS = ["Domain", "Status", "Registrar", "Expires", "Days left", "Last checked", ""]
COL_ACTION = 6


def display_status(d: Domain, now: datetime) -> str:
    if d.status == REGISTERED:
        days = d.days_left(now)
        if days is not None and days < 0:
            return "expired"
        if days is not None and days <= monitor.NEAR_EXPIRY_DAYS:
            return "expiring"
    if d.error and d.status in ("pending", "unknown"):
        return "error"
    return d.status


def ago(dt: datetime | None, now: datetime) -> str:
    if not dt:
        return "never"
    secs = int((now - dt).total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


class DomainModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.rows: list[Domain] = []

    def set_rows(self, rows: list[Domain]):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section].upper()
        return None

    def data(self, index, role=Qt.DisplayRole):
        d = self.rows[index.row()]
        col = index.column()
        now = utcnow()
        status = display_status(d, now)
        days = d.days_left(now)

        if role == Qt.DisplayRole:
            if col == 0:
                return d.name
            if col == 1:
                return "● " + status.upper()
            if col == 2:
                return d.registrar or "—"
            if col == 3:
                return d.expires.strftime("%Y-%m-%d") if d.expires else "—"
            if col == 4:
                return "—" if days is None else str(days)
            if col == 5:
                return ago(d.last_checked, now)
            if col == COL_ACTION:
                return "Register ↗" if d.status == AVAILABLE else ""
        if role == Qt.UserRole:  # sort keys
            return [d.name, status, d.registrar, d.expires.timestamp() if d.expires else float("inf"),
                    days if days is not None else 10**9,
                    d.last_checked.timestamp() if d.last_checked else 0, d.status][col]
        if role == Qt.ForegroundRole:
            if col == 1:
                return QColor(theme.STATUS_COLORS.get(status, theme.MUTED))
            if col == 4 and days is not None and days <= monitor.NEAR_EXPIRY_DAYS:
                return QColor(theme.WARN if days >= 0 else theme.BAD)
            if col == COL_ACTION:
                return QColor(theme.GOOD)
            if col in (2, 3, 5):
                return QColor(theme.MUTED)
        if role == Qt.FontRole and col in (1, COL_ACTION):
            f = QFont()
            f.setBold(True)
            return f
        if role == Qt.ToolTipRole:
            if d.error:
                return f"Last check failed: {d.error}"
            if col == COL_ACTION and d.status == AVAILABLE:
                return f"Register {d.name} at {BRAND_NAME}"
        return None


class FilterProxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.setSortRole(Qt.UserRole)
        self.setFilterKeyColumn(0)
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)


class LookupSignals(QObject):
    done = Signal(object)


class LookupJob(QRunnable):
    def __init__(self, client: RdapClient, name: str):
        super().__init__()
        self.client, self.name = client, name
        self.signals = LookupSignals()

    def run(self):
        try:
            result = self.client.lookup(self.name)
        except Exception as exc:  # never let a worker thread die silently
            result = LookupResult(self.name, "unknown", error=str(exc))
        self.signals.done.emit(result)


class StatCard(QFrame):
    def __init__(self, label: str, color: str):
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        self.value = QLabel("0")
        self.value.setObjectName("cardValue")
        self.value.setStyleSheet(f"color: {color};")
        cap = QLabel(label.upper())
        cap.setObjectName("cardLabel")
        lay.addWidget(self.value)
        lay.addWidget(cap)


class MainWindow(QMainWindow):
    def __init__(self, store: Store, client: RdapClient):
        super().__init__()
        self.store, self.client = store, client
        self.in_flight: str | None = None
        self.quitting = False
        self.hint_shown = False

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(theme.make_icon())
        self.resize(1080, 680)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QVBoxLayout()
        body.setContentsMargins(24, 20, 24, 16)
        body.setSpacing(16)
        outer.addLayout(body, 1)

        # Header
        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("DOMAIN PULSE")
        title.setObjectName("title")
        subtitle = QLabel(f"Registration & expiry monitor  ·  by {BRAND_NAME}")
        subtitle.setObjectName("subtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch()
        self.cards = {
            "total": StatCard("Watching", theme.TEXT),
            "available": StatCard("Available", theme.GOOD),
            "expiring": StatCard("Expiring ≤30d", theme.WARN),
            "error": StatCard("Check errors", theme.BAD),
        }
        for c in self.cards.values():
            header.addWidget(c)
        body.addLayout(header)

        # Toolbar
        bar = QHBoxLayout()
        self.add_input = QLineEdit()
        self.add_input.setPlaceholderText("Add domains (comma separated)…")
        self.add_input.returnPressed.connect(self.add_from_input)
        add_btn = QPushButton("Add")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self.add_from_input)
        import_btn = QPushButton("Import CSV")
        import_btn.clicked.connect(self.import_csv)
        export_btn = QPushButton("Export CSV")
        export_btn.clicked.connect(self.export_csv)
        check_btn = QPushButton("Check all now")
        check_btn.clicked.connect(self.check_all)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter…")
        self.search.setFixedWidth(180)
        for w in (self.add_input, add_btn, import_btn, export_btn, check_btn):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(self.search)
        body.addLayout(bar)

        # Table
        self.model = DomainModel()
        self.proxy = FilterProxy()
        self.proxy.setSourceModel(self.model)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.AscendingOrder)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setHighlightSections(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.table_menu)
        self.table.clicked.connect(self.table_clicked)
        body.addWidget(self.table, 1)

        # Footer: status on the left, BizHostNC promo on the right
        footer = QFrame()
        footer.setObjectName("footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(24, 10, 24, 10)
        self.status_label = QLabel()
        self.status_label.setObjectName("footerText")
        promo = QLabel(f'Built by <b>{BRAND_NAME}</b>  ·  Web hosting, design &amp; domains  ·  '
                       f'<a style="color:{theme.ACCENT_2}; text-decoration:none;" href="{BRAND_URL}">'
                       f'<b>Register today →</b></a>')
        promo.setObjectName("footerText")
        promo.setOpenExternalLinks(True)
        fl.addWidget(self.status_label)
        fl.addStretch()
        fl.addWidget(promo)
        outer.addWidget(footer)

        self.build_tray()
        self.refresh()

        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.tick)
        self.tick_timer.start(monitor.TICK_SECONDS * 1000)
        self.ui_timer = QTimer(self)  # keeps "x m ago" fresh
        self.ui_timer.timeout.connect(self.refresh)
        self.ui_timer.start(60_000)
        QTimer.singleShot(500, self.tick)

    # -- tray ----------------------------------------------------------------
    def build_tray(self):
        self.tray = QSystemTrayIcon(theme.make_icon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        menu.addAction("Open Domain Pulse", self.show_window)
        menu.addAction("Check all now", self.check_all)
        menu.addSeparator()
        menu.addAction(f"Visit {BRAND_NAME}", lambda: QDesktopServices.openUrl(QUrl(BRAND_URL)))
        menu.addSeparator()
        menu.addAction("Quit", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.messageClicked.connect(self.show_window)
        self.tray.show()

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_window()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.tray.setIcon(theme.make_icon())

    def notify(self, title: str, message: str):
        if QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(title, message, theme.make_icon(alert=True), 10_000)
        if not self.isVisible():
            self.tray.setIcon(theme.make_icon(alert=True))

    def closeEvent(self, event):
        if self.quitting or not QSystemTrayIcon.isSystemTrayAvailable():
            event.accept()
            return
        event.ignore()
        self.hide()
        if not self.hint_shown:
            self.tray.showMessage(APP_NAME, "Still watching your domains from the tray.", theme.make_icon(), 4000)
            self.hint_shown = True

    def quit(self):
        self.quitting = True
        self.tray.hide()
        QApplication.quit()

    # -- checking ------------------------------------------------------------
    def tick(self):
        if self.in_flight:
            return
        d = self.store.next_due()
        if not d:
            self.update_status()
            return
        self.in_flight = d.name
        job = LookupJob(self.client, d.name)
        job.signals.done.connect(self.on_result)
        QThreadPool.globalInstance().start(job)
        self.update_status()

    def on_result(self, result: LookupResult):
        name = self.in_flight
        self.in_flight = None
        d = self.store.get(name)
        if not d:  # removed while the lookup was running
            return
        for alert in monitor.apply_result(d, result):
            self.notify(alert.title, alert.message)
        self.store.save(d)
        self.refresh()

    def check_all(self):
        self.store.mark_all_due()
        self.update_status()

    # -- data ----------------------------------------------------------------
    def refresh(self):
        rows = self.store.all()
        self.model.set_rows(rows)
        now = utcnow()
        statuses = [display_status(d, now) for d in rows]
        self.cards["total"].value.setText(str(len(rows)))
        self.cards["available"].value.setText(str(statuses.count("available")))
        self.cards["expiring"].value.setText(str(statuses.count("expiring") + statuses.count("expired")))
        self.cards["error"].value.setText(str(sum(1 for d in rows if d.error)))
        self.update_status()

    def update_status(self):
        due = self.store.due_count()
        if self.in_flight:
            text = f"Checking {self.in_flight}…"
            if due > 1:
                text += f"  ({due - 1} queued)"
        elif due:
            text = f"{due} queued"
        else:
            upcoming = [d.next_check for d in self.model.rows if d.next_check]
            text = f"Idle · next check {min(upcoming).astimezone():%H:%M}" if upcoming else "Add domains to start"
        self.status_label.setText(text)
        self.tray.setToolTip(f"{APP_NAME} · {text}")

    def add_names(self, names: list[str], rejected: list[str]):
        added = self.store.add(names)
        self.refresh()
        msg = f"Added {added} new domain{'s' if added != 1 else ''}."
        if len(names) - added:
            msg += f" {len(names) - added} already watched."
        if rejected:
            preview = ", ".join(rejected[:5]) + ("…" if len(rejected) > 5 else "")
            msg += f"\nSkipped {len(rejected)} invalid: {preview}"
        self.status_label.setText(msg.splitlines()[0])
        if rejected:
            QMessageBox.information(self, APP_NAME, msg)

    def add_from_input(self):
        raw = [p.strip() for p in self.add_input.text().replace(";", ",").replace(" ", ",").split(",") if p.strip()]
        if not raw:
            return
        valid = list(dict.fromkeys(normalize(r) for r in raw if is_valid(r)))
        rejected = [r for r in raw if not is_valid(r)]
        self.add_input.clear()
        self.add_names(valid, rejected)

    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import domains", str(Path.home()),
                                              "CSV or text (*.csv *.txt);;All files (*)")
        if not path:
            return
        try:
            valid, rejected = csv_io.read_domains(path)
        except (OSError, UnicodeDecodeError) as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not read file:\n{exc}")
            return
        self.add_names(valid, rejected)

    def export_csv(self):
        default = str(Path.home() / f"domain-pulse-{datetime.now():%Y%m%d}.csv")
        path, _ = QFileDialog.getSaveFileName(self, "Export availability", default, "CSV (*.csv)")
        if not path:
            return
        try:
            csv_io.write_domains(path, self.store.all())
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not write file:\n{exc}")
            return
        self.status_label.setText(f"Exported to {path}")

    def selected_names(self) -> list[str]:
        rows = {self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()}
        return [self.model.rows[r].name for r in sorted(rows)]

    def table_clicked(self, index):
        if index.column() == COL_ACTION:
            d = self.model.rows[self.proxy.mapToSource(index).row()]
            if d.status == AVAILABLE:
                QDesktopServices.openUrl(QUrl(REGISTER_URL))

    def table_menu(self, pos):
        names = self.selected_names()
        if not names:
            return
        menu = QMenu(self)
        menu.addAction("Check now", lambda: (self.store.mark_all_due(names), self.update_status()))
        menu.addAction("Copy", lambda: QApplication.clipboard().setText("\n".join(names)))
        menu.addAction(f"Register at {BRAND_NAME}", lambda: QDesktopServices.openUrl(QUrl(REGISTER_URL)))
        menu.addSeparator()
        remove = QAction(f"Remove {len(names)} domain{'s' if len(names) != 1 else ''}", menu)
        remove.triggered.connect(lambda: (self.store.remove(names), self.refresh()))
        menu.addAction(remove)
        menu.exec(self.table.viewport().mapToGlobal(pos))


def data_dir() -> Path:
    path = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    path.mkdir(parents=True, exist_ok=True)
    return path


def main() -> int:
    QApplication.setApplicationName("DomainPulse")
    QApplication.setOrganizationName(BRAND_NAME)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.STYLESHEET)
    app.setWindowIcon(theme.make_icon())

    folder = data_dir()
    store = Store(folder / "domains.sqlite")
    client = RdapClient(folder)
    window = MainWindow(store, client)
    if "--minimized" not in sys.argv or not QSystemTrayIcon.isSystemTrayAvailable():
        window.show()
    return app.exec()
