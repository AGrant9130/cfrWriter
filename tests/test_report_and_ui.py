from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from cfrwriter import assets, colors, logdata, report, settings as S
from conftest import EXAMPLE_LOG


def _data(n=1):
    entries = [e for e in logdata.parse_log(EXAMPLE_LOG).entries if e.current_ma == 200][:n]
    return report.build_report_data(entries, ["ATV630D30N4"] * n, [f"SN{i}" for i in range(n)],
                                    "Pat", "Acme Motors", "note")


def test_accent_from_default_logo_is_green_and_legible(qapp):
    c = colors.dominant_color(assets.default_logo())
    assert c is not None and c.green() > c.red() and c.green() > c.blue()
    assert colors.contrast_with_white(colors.readable_on_white(c)) >= 4.5


def test_accent_ignores_white_and_grey(qapp):
    img = QImage(20, 20, QImage.Format.Format_ARGB32)
    img.fill(QColor("white"))
    assert colors.dominant_color(img) is None
    img.fill(QColor("#808080"))
    assert colors.dominant_color(img) is None


def test_accent_override_wins(qapp):
    cfg = S.Settings(accent_override="#aa0000")
    assert report.make_style(cfg, assets.default_logo()).accent.name() == "#aa0000"


def test_worst_case_report_fits_on_one_page(qapp):
    cfg = S.Settings()
    for f in ("company_name", "company_phone", "company_website", "company_hours", "user_name",
              "user_phone", "user_email", "support_general", "footer_note"):
        getattr(cfg, f).value = "x" * 40
    cfg.company_address.value = "line one\nline two\nline three"
    cfg.contacts = [S.Contact(f"Person {i}", "555-0100", "p@example.com", "Role") for i in range(4)]
    data = _data(5)
    data.notes = "word " * 120
    data.performed_for = "A Very Long Customer Name Incorporated of Greater Valley County California"
    for paper in ("Letter", "A4"):
        cfg.paper = paper
        logo = assets.load_logo(cfg)
        img = report.render_preview(data, cfg, report.make_style(cfg, logo), logo, 800)
        assert not img.isNull()
    page = report.page_size_points("A4")
    from PySide6.QtGui import QPainter
    img = QImage(400, 560, QImage.Format.Format_ARGB32)
    p = QPainter(img)
    p.scale(400 / page.width(), 400 / page.width())
    info = report.draw_report(p, page, data, cfg, report.make_style(cfg, None), None)
    p.end()
    assert info.fits, (info.end_y, info.footer_top)


def _draw(cfg, data, paper="Letter"):
    from PySide6.QtGui import QPainter
    cfg.paper = paper
    page = report.page_size_points(paper)
    img = QImage(400, round(400 * page.height() / page.width()), QImage.Format.Format_ARGB32)
    p = QPainter(img)
    p.scale(400 / page.width(), 400 / page.width())
    info = report.draw_report(p, page, data, cfg, report.make_style(cfg, None), None)
    p.end()
    return info


def test_realistic_full_report_keeps_normal_spacing_and_full_notes(qapp):
    cfg = S.Settings()
    cfg.company_name.value, cfg.company_phone.value = "Acme Drives", "555-0100"
    cfg.support_general.value = "800-555-0100"
    cfg.contacts = [S.Contact("A", "1", "a@x", "Eng"), S.Contact("B", "2", "b@x")]
    data = _data(5)
    data.notes = "Ran motor at 15, 30, 45 and 60 Hz. Output voltage good at each. " * 2
    info = _draw(cfg, data)
    assert info.fits and info.density == 1.0 and not info.notes_clipped


def test_overfull_report_tightens_before_clipping(qapp):
    cfg = S.Settings()
    cfg.company_address.value = "1\n2\n3"
    cfg.contacts = [S.Contact(f"P{i}", "555", "p@x", "R") for i in range(10)]
    data = _data(5)
    data.notes = "word " * 60            # ~6 lines
    info = _draw(cfg, data)
    assert info.fits and info.density < 1.0 and not info.notes_clipped


def test_pdf_is_written_and_reasonably_small(qapp, tmp_path):
    cfg = S.Settings()
    logo = assets.load_logo(cfg)
    out = tmp_path / "r.pdf"
    report.export_pdf(str(out), _data(), cfg, report.make_style(cfg, logo), logo)
    raw = out.read_bytes()
    assert raw.startswith(b"%PDF") and raw.count(b"/Type /Page\n") + raw.count(b"/Type /Page ") <= 2
    assert out.stat().st_size < 600_000


def test_hidden_fields_leave_no_trace(qapp):
    cfg = S.Settings()
    cfg.company_name = S.InfoField("SecretCo", show=False)
    cfg.disclaimer.show = False
    logo = assets.load_logo(cfg)
    base = report.render_preview(_data(), cfg, report.make_style(cfg, logo), logo, 600)
    cfg.company_name.show = True
    cfg.disclaimer.show = True
    full = report.render_preview(_data(), cfg, report.make_style(cfg, logo), logo, 600)
    assert base != full


def test_main_window_workflow(qapp, tmp_path):
    from cfrwriter.ui.main_window import MainWindow
    cfg = S.Settings(output_dir=str(tmp_path / "out"), first_run_done=True)
    cfg.user_name.value = "Taylor"
    w = MainWindow(cfg)
    assert not w.save_btn.isEnabled()                    # nothing loaded
    w.load_log(EXAMPLE_LOG)
    assert w.log_table.rowCount() == 13
    assert [e.when.month for e in w.selected] == [11]    # newest preselected
    assert w.performed_by.text() == "Taylor"
    assert not w.save_btn.isEnabled() and "part number" in w.problem_label.text()

    w.units_table.item(0, 2).setText("ATV630D30N4")
    w.units_table.item(0, 3).setText("SER123")
    w.performed_for.setText("Acme Motors")
    assert w.save_btn.isEnabled()

    path = w.save_pdf()
    assert path and path.exists() and path.parent == tmp_path / "out" / "Acme Motors" / "2026-11-04"
    assert w.save_pdf() == path                          # unchanged report: not rewritten
    w.notes.setPlainText("changed")
    path2 = w.save_pdf()
    assert path2 != path and path2.exists()              # changed: new file, old kept

    # multi-select with mismatched settings (11/04 is 500 mA, 10/15 is 100 mA) is refused
    w.log_table.selectRow(0)
    w.log_table.selectionModel().select(w.log_table.model().index(1, 0),
                                        w.log_table.selectionModel().SelectionFlag.Select
                                        | w.log_table.selectionModel().SelectionFlag.Rows)
    assert len(w.selected) == 2 and not w.save_btn.isEnabled() and "different" in w.problem_label.text()

    # five same-settings runs are accepted, a sixth is refused
    w.log_table.clearSelection()
    same = [r for r, e in enumerate(w.entries) if e.current_ma == 200]
    for r in same[:5]:
        w.log_table.selectionModel().select(w.log_table.model().index(r, 0),
                                            w.log_table.selectionModel().SelectionFlag.Select
                                            | w.log_table.selectionModel().SelectionFlag.Rows)
    assert len(w.selected) == 5 and "part number" in w.problem_label.text()
    w._update_preview()
    assert not w.preview.pixmap().isNull()
    w.close()


def test_new_report_clears_only_entered_data(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from cfrwriter.ui.main_window import MainWindow
    cfg = S.Settings(output_dir=str(tmp_path / "out"), first_run_done=True)
    cfg.user_name.value = "Taylor"
    w = MainWindow(cfg)
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(1) or QMessageBox.StandardButton.Yes)
    w.new_report()
    assert asked == []                                    # nothing entered: no confirmation

    w.load_log(EXAMPLE_LOG)
    w.units_table.item(0, 2).setText("ATV630D30N4")
    w.units_table.item(0, 3).setText("SER123")
    w.performed_for.setText("Acme Motors")
    w.performed_by.setText("Someone Else")
    w.notes.setPlainText("some notes")
    assert w.save_btn.isEnabled()

    w.new_report()
    assert asked == [1]
    assert w.performed_for.text() == "" and w.notes.toPlainText() == ""
    assert w.units_table.item(0, 2).text() == "" and w.units_table.item(0, 3).text() == ""
    assert w.performed_by.text() == "Taylor"               # back to the default
    assert w.log_table.rowCount() == 13 and len(w.selected) == 1   # log and selection kept
    assert not w.save_btn.isEnabled()                     # part/serial required again

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    w.performed_for.setText("Keep me")
    w.new_report()
    assert w.performed_for.text() == "Keep me"            # declining leaves everything alone
    w.close()


def test_settings_dialog_roundtrip(qapp):
    from cfrwriter.ui.settings_dialog import SettingsDialog
    cfg = S.Settings()
    cfg.company_name = S.InfoField("Acme", False)
    cfg.contacts = [S.Contact("A", "1", "a@x", "Eng", True), S.Contact("B", include=False)]
    cfg.accent_override = "#123456"
    cfg.last_printer = "HP"
    dlg = SettingsDialog(cfg, first_run=True)
    dlg.accept()
    out = dlg.result_settings
    assert out.company_name == S.InfoField("Acme", False)
    assert [(c.name, c.include) for c in out.contacts] == [("A", True), ("B", False)]
    assert out.accent_override == "#123456" and out.last_printer == "HP"
    assert out.disclaimer.value.startswith("Reform")
