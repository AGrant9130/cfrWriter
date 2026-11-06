"""Settings dialog, also used (with ``first_run=True``) as the welcome screen."""

from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from .. import assets
from ..colors import DEFAULT_ACCENT, dominant_color
from ..settings import (DATE_FORMATS, PAPER_SIZES, Contact, InfoField, Settings,
                        export_bundle, import_bundle)
from ..assets import save_logo

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp)"
SUPPORT_FIT = 4   # contacts that comfortably fit on the report


class FieldRow:
    """A text box with a 'show on report' checkbox. Works for one or many lines."""

    def __init__(self, placeholder: str = "", multiline: bool = False):
        self.multiline = multiline
        if multiline:
            self.edit: QLineEdit | QPlainTextEdit = QPlainTextEdit()
            self.edit.setFixedHeight(56)
        else:
            self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.show = QCheckBox("Show on report")
        self.show.setChecked(True)
        self.widget = QWidget()
        lay = QHBoxLayout(self.widget)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.show, 0, Qt.AlignmentFlag.AlignTop if multiline else Qt.AlignmentFlag.AlignVCenter)

    def load(self, f: InfoField) -> None:
        (self.edit.setPlainText if self.multiline else self.edit.setText)(f.value)
        self.show.setChecked(f.show)

    def value(self) -> InfoField:
        text = self.edit.toPlainText() if self.multiline else self.edit.text()
        return InfoField(text.strip(), self.show.isChecked())


class ContactDialog(QDialog):
    def __init__(self, contact: Contact | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Support contact")
        c = contact or Contact()
        self.name, self.role = QLineEdit(c.name), QLineEdit(c.role)
        self.phone, self.email = QLineEdit(c.phone), QLineEdit(c.email)
        self.role.setPlaceholderText("optional, e.g. Applications Engineer")
        self.include = QCheckBox("Include on report")
        self.include.setChecked(c.include)
        form = QFormLayout(self)
        for label, w in (("Name", self.name), ("Role", self.role), ("Phone", self.phone), ("Email", self.email)):
            form.addRow(label, w)
        form.addRow("", self.include)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def contact(self) -> Contact:
        return Contact(self.name.text().strip(), self.phone.text().strip(), self.email.text().strip(),
                       self.role.text().strip(), self.include.isChecked())


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None, first_run: bool = False):
        super().__init__(parent)
        self.first_run = first_run
        self.setWindowTitle("Welcome to cfrWriter" if first_run else "Settings")
        self.setMinimumWidth(640)
        self.result_settings: Settings | None = None
        self._base = copy.deepcopy(settings)     # holds values not editable here (last printer etc.)
        self._pending_logo: QImage | None = None  # chosen but not yet saved
        self._reset_logo = False
        self._accent_custom = QColor()

        root = QVBoxLayout(self)
        if first_run:
            intro = QLabel("<b>Let's set up your reports.</b><br>Everything here is optional. "
                           "Tick <i>Show on report</i> for each detail you want printed. "
                           "You can change any of this later under File → Settings.")
            intro.setWordWrap(True)
            root.addWidget(intro)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self._build_you()
        self._build_company()
        self._build_support()
        self._build_report()
        self._build_output()

        bottom = QHBoxLayout()
        imp, exp = QPushButton("Import…"), QPushButton("Export…")
        imp.setToolTip("Load settings (and logo) from a file made by Export")
        exp.setToolTip("Save these settings (and logo) to a file you can share or back up")
        imp.clicked.connect(self._import)
        exp.clicked.connect(self._export)
        bottom.addWidget(imp)
        bottom.addWidget(exp)
        bottom.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        if first_run:
            buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Skip for now")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        bottom.addWidget(buttons)
        root.addLayout(bottom)

        self._load(settings)

    # ---- tabs ------------------------------------------------------------
    def _page(self, title: str) -> QFormLayout:
        page = QWidget()
        form = QFormLayout(page)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.tabs.addTab(page, title)
        return form

    def _build_you(self) -> None:
        f = self._page("You")
        self.user_name = FieldRow("Your name")
        self.user_phone = FieldRow("Cell phone")
        self.user_email = FieldRow("Email")
        self.default_by = QLineEdit()
        self.default_by.setPlaceholderText("Leave blank to use your name")
        f.addRow("Name", self.user_name.widget)
        f.addRow("Cell phone", self.user_phone.widget)
        f.addRow("Email", self.user_email.widget)
        f.addRow("Default “Performed by”", self.default_by)

    def _build_company(self) -> None:
        f = self._page("Company")
        self.co_name = FieldRow("Company name")
        self.co_phone = FieldRow("Phone number")
        self.co_web = FieldRow("Website")
        self.co_addr = FieldRow("Street, city, state, ZIP", multiline=True)
        self.co_hours = FieldRow("e.g. Mon–Fri 7:00 am – 4:30 pm")
        f.addRow("Name", self.co_name.widget)
        f.addRow("Phone", self.co_phone.widget)
        f.addRow("Website", self.co_web.widget)
        f.addRow("Address", self.co_addr.widget)
        f.addRow("Business hours", self.co_hours.widget)

    def _build_support(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        self.general = FieldRow("General support phone or email")
        top = QFormLayout()
        top.addRow("General support", self.general.widget)
        lay.addLayout(top)
        lay.addWidget(QLabel("Contacts — tick the ones to print on the report:"))
        self.contact_list = QListWidget()
        self.contact_list.itemChanged.connect(self._check_support_count)
        self.contact_list.itemDoubleClicked.connect(lambda _: self._edit_contact())
        lay.addWidget(self.contact_list, 1)
        row = QHBoxLayout()
        for text, slot in (("Add…", self._add_contact), ("Edit…", self._edit_contact),
                           ("Remove", self._remove_contact), ("Move up", lambda: self._move_contact(-1)),
                           ("Move down", lambda: self._move_contact(1))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.support_warning = QLabel()
        self.support_warning.setStyleSheet("color: #b45309;")
        self.support_warning.setWordWrap(True)
        lay.addWidget(self.support_warning)
        self.tabs.addTab(page, "Technical support")

    def _build_report(self) -> None:
        f = self._page("Report")
        self.logo_preview = QLabel()
        self.logo_preview.setFixedSize(220, 90)
        self.logo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_preview.setStyleSheet("border: 1px solid #c8ced6; background: white;")
        choose, reset = QPushButton("Choose logo…"), QPushButton("Reset to default")
        choose.clicked.connect(self._choose_logo)
        reset.clicked.connect(self._reset_logo_clicked)
        logo_box = QWidget()
        lg = QHBoxLayout(logo_box)
        lg.setContentsMargins(0, 0, 0, 0)
        btns = QVBoxLayout()
        btns.addWidget(choose)
        btns.addWidget(reset)
        btns.addStretch(1)
        lg.addWidget(self.logo_preview)
        lg.addLayout(btns)
        lg.addStretch(1)
        f.addRow("Logo", logo_box)
        logo_hint = QLabel("Best: a landscape PNG about 800 × 400 px with a transparent background. "
                           "It prints about 2 inches wide; larger images are shrunk automatically.")
        logo_hint.setWordWrap(True)
        logo_hint.setStyleSheet("color: #5b6472;")
        f.addRow("", logo_hint)

        self.accent_auto = QCheckBox("Pick automatically from the logo")
        self.accent_swatch = QPushButton("Choose color…")
        self.accent_auto.toggled.connect(lambda _: self._refresh_accent())
        self.accent_swatch.clicked.connect(self._choose_accent)
        acc = QWidget()
        al = QHBoxLayout(acc)
        al.setContentsMargins(0, 0, 0, 0)
        al.addWidget(self.accent_auto)
        al.addWidget(self.accent_swatch)
        al.addStretch(1)
        f.addRow("Accent color", acc)

        self.disclaimer = FieldRow("Standard disclaimer printed in the footer", multiline=True)
        self.footer_note = FieldRow("Optional extra footer note", multiline=True)
        f.addRow("Disclaimer", self.disclaimer.widget)
        f.addRow("Footer note", self.footer_note.widget)
        self.date_format = QComboBox()
        self.date_format.addItems(DATE_FORMATS)
        self.paper = QComboBox()
        self.paper.addItems(PAPER_SIZES)
        f.addRow("Date format", self.date_format)
        f.addRow("Paper size", self.paper)

    def _build_output(self) -> None:
        f = self._page("Saving && printing")
        self.out_dir = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_output)
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.out_dir, 1)
        h.addWidget(browse)
        f.addRow("Save reports in", w)
        self.subfolder = QLineEdit()
        self.filename = QLineEdit()
        f.addRow("Subfolders", self.subfolder)
        f.addRow("File name", self.filename)
        help_ = QLabel("Available: {customer}  {date}  {serial}  {part}  {user}.  "
                       "{date} is written year-month-day so files sort in order. "
                       "Existing files are never overwritten.")
        help_.setWordWrap(True)
        f.addRow("", help_)
        self.print_now = QCheckBox("Print straight to the default printer (skip the print dialog)")
        f.addRow("Printing", self.print_now)

    # ---- load / collect ------------------------------------------------------
    def _load(self, s: Settings) -> None:
        self._base = copy.deepcopy(s)
        self.user_name.load(s.user_name)
        self.user_phone.load(s.user_phone)
        self.user_email.load(s.user_email)
        self.default_by.setText(s.default_performed_by)
        self.co_name.load(s.company_name)
        self.co_phone.load(s.company_phone)
        self.co_web.load(s.company_website)
        self.co_addr.load(s.company_address)
        self.co_hours.load(s.company_hours)
        self.general.load(s.support_general)
        self.contact_list.clear()
        for c in s.contacts:
            self._append_contact(c)
        self._check_support_count()
        self.disclaimer.load(s.disclaimer)
        self.footer_note.load(s.footer_note)
        self.date_format.setCurrentText(s.date_format)
        self.paper.setCurrentText(s.paper)
        self.out_dir.setText(s.output_dir)
        self.subfolder.setText(s.subfolder_pattern)
        self.filename.setText(s.filename_pattern)
        self.print_now.setChecked(s.print_immediately)
        self._logo_file = s.logo_file
        self._pending_logo, self._reset_logo = None, False
        self._accent_custom = QColor(s.accent_override) if s.accent_override else QColor()
        self.accent_auto.setChecked(not s.accent_override)
        self._refresh_logo()

    def _collect(self) -> Settings:
        s = copy.deepcopy(self._base)
        s.user_name, s.user_phone, s.user_email = (self.user_name.value(), self.user_phone.value(),
                                                    self.user_email.value())
        s.default_performed_by = self.default_by.text().strip()
        s.company_name, s.company_phone = self.co_name.value(), self.co_phone.value()
        s.company_website, s.company_address = self.co_web.value(), self.co_addr.value()
        s.company_hours = self.co_hours.value()
        s.support_general = self.general.value()
        s.contacts = [self.contact_list.item(i).data(Qt.ItemDataRole.UserRole)
                      for i in range(self.contact_list.count())]
        for i, c in enumerate(s.contacts):
            c.include = self.contact_list.item(i).checkState() == Qt.CheckState.Checked
        s.disclaimer, s.footer_note = self.disclaimer.value(), self.footer_note.value()
        s.date_format, s.paper = self.date_format.currentText(), self.paper.currentText()
        s.output_dir = self.out_dir.text().strip() or s.output_dir
        s.subfolder_pattern, s.filename_pattern = self.subfolder.text().strip(), self.filename.text().strip() or "{customer}_{date}_{serial}"
        s.print_immediately = self.print_now.isChecked()
        s.accent_override = "" if self.accent_auto.isChecked() or not self._accent_custom.isValid() \
            else self._accent_custom.name()
        return s

    # ---- logo / accent ---------------------------------------------------------
    def _current_logo(self) -> QImage:
        if self._pending_logo is not None:
            return self._pending_logo
        if self._reset_logo:
            return assets.default_logo()
        probe = Settings(logo_file=self._logo_file)
        return assets.load_logo(probe)

    def _refresh_logo(self) -> None:
        img = self._current_logo()
        pm = QPixmap.fromImage(img).scaled(210, 80, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
        self.logo_preview.setPixmap(pm)
        self._refresh_accent()

    def _effective_accent(self) -> QColor:
        if not self.accent_auto.isChecked() and self._accent_custom.isValid():
            return self._accent_custom
        return dominant_color(self._current_logo()) or QColor(DEFAULT_ACCENT)

    def _refresh_accent(self) -> None:
        color = self._effective_accent()
        self.accent_swatch.setStyleSheet(f"background: {color.name()}; color: "
                                         f"{'white' if color.lightness() < 140 else 'black'}; padding: 4px 10px;")
        self.accent_swatch.setEnabled(not self.accent_auto.isChecked())

    def _choose_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose logo", "", IMAGE_FILTER)
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "Logo", "That file could not be read as an image.")
            return
        self._pending_logo, self._reset_logo = img, False
        self._refresh_logo()

    def _reset_logo_clicked(self) -> None:
        self._pending_logo, self._reset_logo = None, True
        self._refresh_logo()

    def _choose_accent(self) -> None:
        color = QColorDialog.getColor(self._effective_accent(), self, "Accent color")
        if color.isValid():
            self._accent_custom = color
            self._refresh_accent()

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Save reports in", self.out_dir.text())
        if path:
            self.out_dir.setText(path)

    # ---- support contacts -----------------------------------------------------
    @staticmethod
    def _contact_text(c: Contact) -> str:
        head = c.name + (f" — {c.role}" if c.role else "")
        return head + (f"\n{c.phone}   {c.email}".rstrip() if c.phone or c.email else "")

    def _append_contact(self, c: Contact) -> None:
        item = QListWidgetItem(self._contact_text(c))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if c.include else Qt.CheckState.Unchecked)
        item.setData(Qt.ItemDataRole.UserRole, c)
        self.contact_list.addItem(item)

    def _add_contact(self) -> None:
        dlg = ContactDialog(parent=self)
        if dlg.exec():
            self._append_contact(dlg.contact())
            self._check_support_count()

    def _edit_contact(self) -> None:
        item = self.contact_list.currentItem()
        if item is None:
            return
        dlg = ContactDialog(item.data(Qt.ItemDataRole.UserRole), self)
        if dlg.exec():
            c = dlg.contact()
            item.setData(Qt.ItemDataRole.UserRole, c)
            item.setText(self._contact_text(c))
            item.setCheckState(Qt.CheckState.Checked if c.include else Qt.CheckState.Unchecked)

    def _remove_contact(self) -> None:
        row = self.contact_list.currentRow()
        if row >= 0:
            self.contact_list.takeItem(row)
            self._check_support_count()

    def _move_contact(self, delta: int) -> None:
        row = self.contact_list.currentRow()
        new = row + delta
        if row < 0 or not 0 <= new < self.contact_list.count():
            return
        item = self.contact_list.takeItem(row)
        self.contact_list.insertItem(new, item)
        self.contact_list.setCurrentRow(new)

    def _check_support_count(self, *_) -> None:
        checked = sum(self.contact_list.item(i).checkState() == Qt.CheckState.Checked
                      for i in range(self.contact_list.count()))
        self.support_warning.setText(
            f"{checked} contacts are ticked. The report fits about {SUPPORT_FIT} comfortably; "
            "more may crowd the page." if checked > SUPPORT_FIT else "")

    # ---- import / export ---------------------------------------------------------
    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export settings", "cfrWriter-settings.json", "JSON (*.json)")
        if not path:
            return
        try:
            export_bundle(self._collect(), assets.image_to_png_bytes(self._current_logo()), path)
        except OSError as e:
            QMessageBox.warning(self, "Export", f"Could not save the file:\n{e}")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import settings", "", "JSON (*.json)")
        if not path:
            return
        try:
            s, logo = import_bundle(path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Import", f"Could not read that settings file:\n{e}")
            return
        s.last_printer, s.last_log_dir, s.first_run_done = (self._base.last_printer,
                                                            self._base.last_log_dir, self._base.first_run_done)
        self._load(s)
        if logo:
            img = assets.image_from_png_bytes(logo)
            if not img.isNull():
                self._pending_logo = img
                self._refresh_logo()

    # ---- finish -----------------------------------------------------------------
    def accept(self) -> None:
        s = self._collect()
        try:
            if self._pending_logo is not None:
                s.logo_file = save_logo(self._pending_logo)
            elif self._reset_logo:
                assets.remove_user_logo()
                s.logo_file = ""
        except OSError as e:
            QMessageBox.warning(self, "Logo", f"Could not save the logo:\n{e}")
            return
        self.result_settings = s
        super().accept()
