"""The main window: pick log rows, add details, preview, save and print."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QMarginsF, QSignalBlocker, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QPageLayout, QPalette, QPixmap
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import __version__, assets, report
from ..formatting import build_output_path, format_date
from ..logdata import LogEntry, LogFormatError, find_latest_csv, parse_log, removable_roots
from ..settings import Settings, save_settings
from .settings_dialog import SettingsDialog

NOTES_LIMIT = 500
PREVIEW_WIDTH = 520
COLUMN_PADDING = 16         # extra width around each title/value, so headers are not tight
MIN_COLUMN_PADDING = 6      # floor when the window is narrow
LAST_COLUMN_PADDING = 10   # the Current column stays snug; spare width goes to the others


class _LogTable(QTableWidget):
    """Table that reports when its width changes, so columns can be refitted."""
    resized = Signal()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.resized.emit()


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, font_family: str = "Inter"):
        super().__init__()
        self.cfg = settings
        self.family = font_family
        self.setWindowTitle("cfrWriter — Capacitor Forming Reports")
        self.resize(1280, 800)

        self.entries: list[LogEntry] = []
        self.selected: list[LogEntry] = []                    # oldest first
        self.inputs: dict[datetime, list[str]] = {}           # entry time -> [part, serial]
        self.last_pdf: Path | None = None
        self._saved_key: str | None = None
        self._populating = False
        self._fitting = False
        self._reload_style()

        self._build_menu()
        self._build_ui()
        self._debounce = QTimer(self, singleShot=True, interval=120)
        self._debounce.timeout.connect(self._update_preview)
        self._refresh_all()

    # ---- setup ---------------------------------------------------------------
    def _reload_style(self) -> None:
        self.logo = assets.load_logo(self.cfg)
        self.style_ = report.make_style(self.cfg, self.logo, self.family)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        for text, slot, key in (("&New report", self.new_report, QKeySequence.StandardKey.New),
                                ("&Open log…", self.browse_log, QKeySequence.StandardKey.Open),
                                ("Find log on &USB drive", self.find_usb, None),
                                ("&Settings…", self.open_settings, None)):
            act = QAction(text, self, triggered=slot)
            if key:
                act.setShortcut(key)
            file_menu.addAction(act)
        file_menu.addSeparator()
        file_menu.addAction(QAction("&Quit", self, triggered=self.close, shortcut=QKeySequence.StandardKey.Quit))
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(QAction("&About", self, triggered=self._about))

    def _build_ui(self) -> None:
        split = QSplitter(self)
        self.setCentralWidget(split)

        left = QWidget()
        lv = QVBoxLayout(left)

        # 1. log
        box1 = QGroupBox("1. Choose the run(s) to report")
        b1 = QVBoxLayout(box1)
        row = QHBoxLayout()
        usb = QPushButton("Find log on USB drive")
        usb.clicked.connect(self.find_usb)
        browse = QPushButton("Open log file…")
        browse.clicked.connect(self.browse_log)
        self.log_label = QLabel("No log loaded.")
        self.log_label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        row.addWidget(usb)
        row.addWidget(browse)
        row.addWidget(self.log_label, 1)
        b1.addLayout(row)
        self.log_table = _LogTable(0, 8)
        # Two-line column titles keep the header from feeling crowded.
        self.log_table.setHorizontalHeaderLabels(["Date", "Time", "Type", "Capacitance\n(µF)",
                                                  "Final\nVoltage", "Step\nVoltage", "Final / Step\n(minutes)",
                                                  "Current\n(mA)"])
        self.log_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.log_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.log_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.log_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.log_table.resized.connect(self._fit_log_columns)
        self.log_table.itemSelectionChanged.connect(self._selection_changed)
        b1.addWidget(self.log_table, 1)
        hint = QLabel(f"The newest run is selected for you. Ctrl-click to add more (up to {report.MAX_UNITS}); "
                      "runs on one report must use the same forming settings. Aborted runs are hidden.")
        hint.setWordWrap(True)
        hint.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        b1.addWidget(hint)
        lv.addWidget(box1, 3)

        # 2. details
        box2 = QGroupBox("2. Report details")
        b2 = QVBoxLayout(box2)
        grid = QHBoxLayout()
        self.performed_for = QLineEdit()
        self.performed_for.setPlaceholderText("Customer name")
        self.performed_by = QLineEdit()
        for label, w in (("Performed for", self.performed_for), ("Performed by", self.performed_by)):
            col = QVBoxLayout()
            col.addWidget(QLabel(label))
            col.addWidget(w)
            grid.addLayout(col)
        b2.addLayout(grid)
        self.units_table = QTableWidget(0, 4)
        self.units_table.setHorizontalHeaderLabels(["Date", "Capacitance (µF)", "Part number *", "Serial number *"])
        self.units_table.verticalHeader().setVisible(False)
        self.units_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.units_table.setMaximumHeight(190)
        self.units_table.itemChanged.connect(self._unit_edited)
        b2.addWidget(self.units_table)
        b2.addWidget(QLabel("Notes"))
        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(64)
        self.notes.setPlaceholderText("Optional")
        self.notes.textChanged.connect(self._notes_changed)
        b2.addWidget(self.notes)
        lv.addWidget(box2, 2)

        for w in (self.performed_for, self.performed_by):
            w.textChanged.connect(self._changed)

        # actions
        actions = QHBoxLayout()
        self.problem_label = QLabel()
        self.problem_label.setStyleSheet("color: #b45309;")
        self.problem_label.setWordWrap(True)
        self.new_btn = QPushButton("New report")
        self.new_btn.setToolTip("Clear the customer, part and serial numbers, and notes (Ctrl+N)")
        self.new_btn.clicked.connect(self.new_report)
        self.save_btn = QPushButton("Save PDF")
        self.print_btn = QPushButton("Save && Print…")
        self.open_btn = QPushButton("Open PDF")
        self.folder_btn = QPushButton("Show folder")
        self.save_btn.clicked.connect(lambda: self.save_pdf(show_message=True))
        self.print_btn.clicked.connect(self.print_report)
        self.open_btn.clicked.connect(lambda: self._open(self.last_pdf))
        self.folder_btn.clicked.connect(lambda: self._open(self.last_pdf.parent if self.last_pdf else None))
        self.print_btn.setDefault(True)
        actions.addWidget(self.new_btn)
        actions.addWidget(self.problem_label, 1)
        for b in (self.open_btn, self.folder_btn, self.save_btn, self.print_btn):
            actions.addWidget(b)
        lv.addLayout(actions)
        split.addWidget(left)

        # preview
        self.preview = QLabel("Choose a run to see the report.")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.preview.setStyleSheet("background: white; border: 1px solid #c8ced6;")
        scroll = QScrollArea()
        scroll.setWidget(self.preview)
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        scroll.setStyleSheet("QScrollArea { background: #e9ecf0; }")
        scroll.setMinimumWidth(PREVIEW_WIDTH + 40)
        split.addWidget(scroll)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        self.statusBar().showMessage("Ready")

    # ---- loading a log -----------------------------------------------------------
    def browse_log(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Bonitron log", self.cfg.last_log_dir,
                                              "Bonitron logs (*.csv);;All files (*)")
        if path:
            self.load_log(Path(path))

    def find_usb(self) -> None:
        roots = removable_roots()
        found = find_latest_csv(roots) if roots else None
        if found is None:
            QMessageBox.information(self, "USB drive", "No log file was found on a USB drive.\n"
                                    "Insert the drive, or use “Open log file…” to browse.")
            return
        self.load_log(found)

    def load_log(self, path: Path) -> None:
        try:
            parsed = parse_log(path)
        except (OSError, LogFormatError) as e:
            QMessageBox.warning(self, "Open log", f"Could not read this log:\n{e}")
            return
        if not parsed.entries:
            QMessageBox.information(self, "Open log", "This log has no completed runs (all were aborted).")
            return
        self.entries = parsed.entries
        self.cfg.last_log_dir = str(path.parent)
        save_settings(self.cfg)
        note = f" ({parsed.skipped} aborted/unreadable hidden)" if parsed.skipped else ""
        self.log_label.setText(f"{path.name} — {len(self.entries)} runs{note}")
        self.log_label.setToolTip(str(path))
        self._populate_log_table()
        self.log_table.selectRow(0)           # newest run
        self.statusBar().showMessage(f"Loaded {path}")

    def _populate_log_table(self) -> None:
        self._populating = True
        with QSignalBlocker(self.log_table):
            self.log_table.setRowCount(len(self.entries))
            for r, e in enumerate(self.entries):
                cells = [format_date(e.when.date(), self.cfg.date_format), e.when.strftime("%H:%M"), e.kind,
                         e.capacitance_text, str(e.final_v), str(e.step_v),
                         f"{e.final_min} / {e.step_min}", str(e.current_ma)]
                for c, text in enumerate(cells):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.log_table.setItem(r, c, item)
        self._populating = False
        self._fit_log_columns()

    def _fit_log_columns(self) -> None:
        """Size columns to their titles/values plus padding; spare width goes to every column
        except the last (Current), which stays snug."""
        if self._fitting:
            return
        self._fitting = True
        try:
            table = self.log_table
            table.resizeColumnsToContents()
            last = table.columnCount() - 1
            contents = [table.columnWidth(c) for c in range(last + 1)]
            # Full padding if it fits; otherwise shrink it (down to a floor) rather than scroll.
            room = table.viewport().width() - sum(contents) - LAST_COLUMN_PADDING
            pad = max(MIN_COLUMN_PADDING, min(COLUMN_PADDING, room // last))
            widths = [w + (LAST_COLUMN_PADDING if c == last else pad) for c, w in enumerate(contents)]
            spare = table.viewport().width() - sum(widths)
            if spare > 0:
                share, rest = divmod(spare, last)
                widths = [w + share + (1 if c < rest else 0) if c < last else w for c, w in enumerate(widths)]
            for c, w in enumerate(widths):
                table.setColumnWidth(c, w)
        finally:
            self._fitting = False

    # ---- selection and inputs ---------------------------------------------------------
    def _selection_changed(self) -> None:
        rows = sorted({i.row() for i in self.log_table.selectedIndexes()})
        self.selected = sorted((self.entries[r] for r in rows), key=lambda e: e.when)
        self._rebuild_units()
        self._changed()

    def _rebuild_units(self) -> None:
        self._populating = True
        with QSignalBlocker(self.units_table):
            self.units_table.setRowCount(len(self.selected))
            for r, e in enumerate(self.selected):
                part, serial = self.inputs.setdefault(e.when, ["", ""])
                for c, (text, editable) in enumerate(((format_date(e.when.date(), self.cfg.date_format), False),
                                                      (e.capacitance_text, False), (part, True), (serial, True))):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if not editable:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.units_table.setItem(r, c, item)
        self._populating = False
        if self.selected:
            self.units_table.setCurrentCell(0, 2)

    def new_report(self) -> None:
        """Clear what the user typed (customer, part/serial numbers, notes) for the next report.

        The loaded log and the selected runs are left alone, and "Performed by" goes back to
        its default. Asks first only if there is something to lose.
        """
        has_input = (any(any(v) for v in self.inputs.values()) or self.notes.toPlainText().strip()
                     or self.performed_for.text().strip())
        if has_input and QMessageBox.question(
                self, "New report", "Clear the customer, part and serial numbers, and notes?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.inputs.clear()
        self.performed_for.clear()
        self.notes.clear()
        self.performed_by.setText(self.cfg.performed_by_default())
        self._rebuild_units()
        self._changed()
        self.performed_for.setFocus()
        self.statusBar().showMessage("Ready for a new report")

    def _unit_edited(self, item: QTableWidgetItem) -> None:
        if self._populating or item.column() < 2:
            return
        entry = self.selected[item.row()]
        self.inputs[entry.when][item.column() - 2] = item.text().strip()
        self._changed()

    def _notes_changed(self) -> None:
        if len(self.notes.toPlainText()) > NOTES_LIMIT:
            with QSignalBlocker(self.notes):
                self.notes.setPlainText(self.notes.toPlainText()[:NOTES_LIMIT])
                self.notes.moveCursor(self.notes.textCursor().MoveOperation.End)
        self._changed()

    def _changed(self, *_) -> None:
        if self._populating:
            return
        problems = self._problems()
        self.problem_label.setText(problems[0] if problems else "")
        ok = not problems
        self.save_btn.setEnabled(ok)
        self.print_btn.setEnabled(ok)
        self._debounce.start()

    def _problems(self) -> list[str]:
        if not self.selected:
            return ["Choose at least one run."]
        if len(self.selected) > report.MAX_UNITS:
            return [f"Select at most {report.MAX_UNITS} runs for one report."]
        if len({e.settings_key() for e in self.selected}) > 1:
            return ["The selected runs used different forming settings. Pick runs with matching settings."]
        missing = [e for e in self.selected if not all(self.inputs.get(e.when, ["", ""]))]
        if missing:
            return ["Enter a part number and serial number for each run."]
        return []

    # ---- report ------------------------------------------------------------------------------
    def _report_data(self) -> report.ReportData | None:
        if not self.selected:
            return None
        parts = [self.inputs.get(e.when, ["", ""])[0] for e in self.selected]
        serials = [self.inputs.get(e.when, ["", ""])[1] for e in self.selected]
        return report.build_report_data(self.selected[:report.MAX_UNITS], parts, serials,
                                        self.performed_by.text(), self.performed_for.text(),
                                        self.notes.toPlainText())

    def _update_preview(self) -> None:
        data = self._report_data() if len(self.selected) <= report.MAX_UNITS and \
            len({e.settings_key() for e in self.selected}) <= 1 else None
        if data is None:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("Choose a run to see the report.")
            self.preview.resize(PREVIEW_WIDTH, 120)
            return
        dpr = self.devicePixelRatioF()
        img = report.render_preview(data, self.cfg, self.style_, self.logo, round(PREVIEW_WIDTH * dpr))
        img.setDevicePixelRatio(dpr)
        pm = QPixmap.fromImage(img)
        self.preview.setPixmap(pm)
        self.preview.resize(PREVIEW_WIDTH, round(pm.height() / dpr))

    def _refresh_all(self) -> None:
        if not self.performed_by.text().strip():
            self.performed_by.setText(self.cfg.performed_by_default())
        self._changed()

    # ---- saving and printing -----------------------------------------------------------------
    def _key(self, data: report.ReportData) -> str:
        return repr((data, self.cfg.date_format, self.cfg.paper, self.style_.accent.name(), self.cfg.to_dict()))

    def save_pdf(self, show_message: bool = False) -> Path | None:
        """Write the PDF (once per unique report content). Returns its path, or None on failure."""
        if self._problems():
            return None
        data = self._report_data()
        key = self._key(data)
        if key == self._saved_key and self.last_pdf and self.last_pdf.exists():
            return self.last_pdf
        first = data.units[0]
        values = {"customer": data.performed_for or "Customer", "date": first.when.isoformat(),
                  "serial": first.serial, "part": first.part, "user": data.performed_by}
        try:
            path = build_output_path(self.cfg.output_dir, self.cfg.subfolder_pattern,
                                     self.cfg.filename_pattern, values)
            path.parent.mkdir(parents=True, exist_ok=True)
            report.export_pdf(str(path), data, self.cfg, self.style_, self.logo)
            if not path.exists():
                raise OSError("The PDF was not created.")
        except OSError as e:
            QMessageBox.warning(self, "Save PDF", f"Could not save the report:\n{e}\n\n"
                                "Check the output folder in Settings → Saving and printing.")
            return None
        self.last_pdf, self._saved_key = path, key
        self.statusBar().showMessage(f"Saved {path}")
        if show_message:
            self.statusBar().showMessage(f"Saved {path}", 15000)
        return path

    def print_report(self) -> None:
        if self._problems():
            return
        if self.save_pdf() is None:        # the digital record comes first
            return
        names = QPrinterInfo.availablePrinterNames()
        if not names:
            QMessageBox.information(self, "Print", "No printers are installed. The PDF was saved.")
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPageSize(report.qpage_size(self.cfg.paper))
        printer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)
        printer.setFullPage(True)
        if self.cfg.last_printer in names:
            printer.setPrinterName(self.cfg.last_printer)
        if not self.cfg.print_immediately:
            if not QPrintDialog(printer, self).exec():
                return
            self.cfg.last_printer = printer.printerName()
            save_settings(self.cfg)
        report.print_report(printer, self._report_data(), self.cfg, self.style_, self.logo)
        self.statusBar().showMessage(f"Sent to {printer.printerName()}  (saved: {self.last_pdf})", 15000)

    def _open(self, path: Path | None) -> None:
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ---- settings ------------------------------------------------------------------------------
    def open_settings(self, first_run: bool = False) -> None:
        dlg = SettingsDialog(self.cfg, self, first_run=first_run)
        if dlg.exec() and dlg.result_settings is not None:
            self.cfg = dlg.result_settings
            self.cfg.first_run_done = True
            save_settings(self.cfg)
            self._reload_style()
            if self.entries:
                self._populate_log_table()
                self.log_table.clearSelection()
                self.log_table.selectRow(0)
            self.performed_by.setText(self.cfg.performed_by_default())
            self._changed()
        elif first_run:
            self.cfg.first_run_done = True    # skipped: don't ask again
            save_settings(self.cfg)

    def maybe_first_run(self) -> None:
        if not self.cfg.first_run_done:
            self.open_settings(first_run=True)

    def _about(self) -> None:
        QMessageBox.about(self, "About cfrWriter",
                          f"<b>cfrWriter {__version__}</b><br>Capacitor forming reports from Bonitron logs."
                          "<p>Copyright © 2026 Aaron Grant.<br>Free software under the GNU General Public "
                          "License v3 or later, with no warranty. See the LICENSE and "
                          "THIRD_PARTY_NOTICES files in the application folder.</p>")
