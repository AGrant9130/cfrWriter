"""Drawing the forming report.

All geometry is in points (1/72 in). The same ``draw_report`` function renders to a PDF,
a printer, or an on-screen preview image, so they always match.

Fonts are sized in *pixels* because the painter is pre-scaled to points; using point
sizes there would scale the text twice.

Layout is done in a silent measuring pass first. If the content would run into the
footer, vertical spacing is tightened in steps, and as a last resort the notes are
clipped (with an ellipsis) to the space that remains. Nothing ever overlaps the footer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter

from .colors import DEFAULT_ACCENT, dominant_color, readable_on_white
from .formatting import format_date, minutes_text
from .logdata import LogEntry
from .settings import Settings

TITLE = "VFD Capacitor Forming Report"
MAX_UNITS = 5
MARGIN = 42.0
DENSITIES = (1.0, 0.9, 0.8, 0.7)    # vertical spacing multipliers, tried in order

_PAGE_IDS = {"Letter": QPageSize.PageSizeId.Letter, "A4": QPageSize.PageSizeId.A4}


# --- report content -------------------------------------------------------------

@dataclass
class Unit:
    when: date
    part: str
    serial: str
    capacitance: str


@dataclass
class ReportData:
    performed_by: str
    performed_for: str
    notes: str
    kind: str
    current_ma: int
    step_v: int
    step_min: int
    final_v: int
    final_min: int
    units: list[Unit] = field(default_factory=list)


def build_report_data(entries: list[LogEntry], parts: list[str], serials: list[str],
                      performed_by: str, performed_for: str, notes: str) -> ReportData:
    """Combine selected log entries (oldest first) with user-typed details."""
    first = entries[0]
    return ReportData(
        performed_by=performed_by.strip(), performed_for=performed_for.strip(), notes=notes.strip(),
        kind=first.kind, current_ma=first.current_ma, step_v=first.step_v, step_min=first.step_min,
        final_v=first.final_v, final_min=first.final_min,
        units=[Unit(e.when.date(), p.strip(), s.strip(), e.capacitance_text)
               for e, p, s in zip(entries, parts, serials)],
    )


# --- style ----------------------------------------------------------------------

@dataclass
class Style:
    accent: QColor
    accent_text: QColor
    family: str = "Inter"
    ink: QColor = field(default_factory=lambda: QColor("#1c2430"))
    muted: QColor = field(default_factory=lambda: QColor("#5a6573"))
    rule: QColor = field(default_factory=lambda: QColor("#cfd6de"))

    def font(self, px: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
        # No letter-spacing: Qt scales it differently for PDF/printer output than for the
        # preview, which stretched headings in the PDF. Plain fonts render identically everywhere.
        f = QFont(self.family)
        f.setPixelSize(max(1, round(px)))
        f.setWeight(weight)
        return f


def make_style(settings: Settings, logo: QImage | None, family: str = "Inter") -> Style:
    accent = QColor(settings.accent_override) if settings.accent_override else None
    if accent is None or not accent.isValid():
        accent = dominant_color(logo) if logo is not None else None
    accent = accent or QColor(DEFAULT_ACCENT)
    return Style(accent=accent, accent_text=readable_on_white(accent), family=family)


# --- drawing helpers ------------------------------------------------------------

LEFT = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
CENTER = int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)


class Canvas:
    """Thin wrapper over QPainter. In ``dry`` mode it measures but draws nothing."""

    def __init__(self, painter: QPainter, dry: bool = False):
        self.p = painter
        self.dry = dry

    def _metrics(self, font: QFont):
        self.p.setFont(font)
        return self.p.fontMetrics()

    def line_height(self, font: QFont) -> float:
        return self._metrics(font).height() * 1.22

    def wrap(self, text: str, font: QFont, width: float) -> list[str]:
        """Word-wrap to a width, honouring newlines and splitting over-long words."""
        fm = self._metrics(font)
        out: list[str] = []
        for para in text.replace("\r", "").split("\n"):
            line = ""
            for word in para.split(" "):
                while fm.horizontalAdvance(word) > width and len(word) > 1:      # over-long word
                    cut = len(word) - 1
                    while cut > 1 and fm.horizontalAdvance(word[:cut]) > width:
                        cut -= 1
                    if line:
                        out.append(line)
                        line = ""
                    out.append(word[:cut])
                    word = word[cut:]
                trial = f"{line} {word}" if line else word
                if line and fm.horizontalAdvance(trial) > width:
                    out.append(line)
                    line = word
                else:
                    line = trial
            out.append(line)
        return out or [""]

    def measure(self, width: float, text: str, font: QFont) -> float:
        """Height ``paragraph`` would use."""
        return len(self.wrap(text, font, width)) * self.line_height(font)

    def paragraph(self, x: float, y: float, width: float, text: str, font: QFont, color: QColor) -> float:
        """Draw wrapped text from the top-left; returns the height used."""
        lines = self.wrap(text, font, width)
        fm, lh = self._metrics(font), self.line_height(font)
        if not self.dry:
            self.p.setPen(color)
            for i, line in enumerate(lines):
                baseline = y + i * lh + (lh - fm.height()) / 2 + fm.ascent()
                self.p.drawText(QPointF(x, baseline), line)
        return len(lines) * lh

    def ruled_text(self, x: float, y: float, width: float, lines: list[str], line_h: float,
                   font: QFont, ink: QColor, rule: QColor, count: int) -> None:
        """Text sitting on ``count`` ruled lines."""
        if self.dry:
            return
        self._metrics(font)
        for i in range(count):
            bottom = y + (i + 1) * line_h
            if i < len(lines):
                self.p.setPen(ink)
                self.p.drawText(QPointF(x + 2, bottom - 5), lines[i])
            self.hline(x, bottom, width, 0.9, rule)

    def elide(self, text: str, font: QFont, width: float) -> str:
        return self._metrics(font).elidedText(text, Qt.TextElideMode.ElideRight, int(width))

    def cell(self, rect: QRectF, text: str, font: QFont, color: QColor, align: int = CENTER) -> None:
        if self.dry:
            return
        fm = self._metrics(font)
        self.p.setPen(color)
        self.p.drawText(rect, align, fm.elidedText(text, Qt.TextElideMode.ElideMiddle, int(rect.width())))

    def hline(self, x: float, y: float, w: float, thickness: float, color: QColor) -> None:
        if not self.dry:
            self.p.fillRect(QRectF(x, y - thickness / 2, w, thickness), color)

    def vline(self, x: float, y: float, h: float, thickness: float, color: QColor) -> None:
        if not self.dry:
            self.p.fillRect(QRectF(x - thickness / 2, y, thickness, h), color)

    def image(self, rect: QRectF, img: QImage) -> None:
        if not self.dry:
            self.p.drawImage(rect, img)


@dataclass
class LayoutInfo:
    end_y: float        # bottom of the last body element
    footer_top: float   # top of the footer; body must stay above this
    density: float = 1.0
    notes_clipped: bool = False     # notes were cut short (too long, or no room)
    notes_squeezed: bool = False    # ...because the page was full, not because they hit the 8-line cap

    @property
    def fits(self) -> bool:
        return self.end_y <= self.footer_top + 0.01


def _shown(f) -> str:
    return f.value.strip() if f.show else ""


# --- the report -----------------------------------------------------------------

def _layout(c: Canvas, page: QSizeF, data: ReportData, cfg: Settings, style: Style,
            logo: QImage | None, d: float) -> LayoutInfo:
    """Lay out (and, unless ``c.dry``, draw) the whole page at vertical density ``d``."""
    painter = c.p
    W, H, M = page.width(), page.height(), MARGIN
    CW = W - 2 * M
    y = M

    f_title = style.font(22, QFont.Weight.DemiBold)
    f_head = style.font(10.5, QFont.Weight.Bold)
    f_label = style.font(9)
    f_value = style.font(10, QFont.Weight.Medium)
    f_small = style.font(8.5)
    f_small_b = style.font(9, QFont.Weight.DemiBold)
    f_th = style.font(9.5, QFont.Weight.Bold)
    f_td = style.font(10)
    f_disclaimer = style.font(11, QFont.Weight.Medium)

    # ---- footer height first: it is anchored to the bottom and bounds everything else
    footer_texts = [t for t in (_shown(cfg.footer_note),) if t]     # the disclaimer now sits under the table
    footer_h = sum(c.measure(CW, t, f_small) + 4 for t in footer_texts)
    footer_top = H - M - footer_h - (10 if footer_texts else 0)

    # ---- header: title + logo
    logo_w, logo_h = 150.0, 58.0
    has_logo = logo is not None and not logo.isNull()
    title_w = CW - (logo_w + 16 if has_logo else 0)
    title_h = c.measure(title_w, TITLE, f_title)
    header_h = max(logo_h if has_logo else 0, title_h)
    c.paragraph(M, y + (header_h - title_h) / 2, title_w, TITLE, f_title, style.ink)
    if has_logo:
        scale = min(logo_w / logo.width(), logo_h / logo.height())
        w, h = logo.width() * scale, logo.height() * scale
        c.image(QRectF(W - M - w, y + (header_h - h) / 2, w, h), logo)
    y += header_h + 10 * d
    c.hline(M, y, CW, 2.5, style.accent)
    y += 14 * d

    # ---- company / contact band
    left_lines: list[tuple[str, QFont, QColor]] = []
    if name := _shown(cfg.company_name):
        left_lines.append((name, style.font(11.5, QFont.Weight.Bold), style.ink))
    if addr := _shown(cfg.company_address):
        left_lines.append((addr, f_small, style.muted))
    reach = "   ·   ".join(t for t in (_shown(cfg.company_phone), _shown(cfg.company_website)) if t)
    if reach:
        left_lines.append((reach, f_small, style.muted))
    if hours := _shown(cfg.company_hours):
        left_lines.append((f"Hours: {hours}", f_small, style.muted))
    right_lines: list[tuple[str, QFont, QColor]] = []
    if name := _shown(cfg.user_name):
        right_lines.append((name, f_small_b, style.ink))
    for t in (_shown(cfg.user_phone), _shown(cfg.user_email)):
        if t:
            right_lines.append((t, f_small, style.muted))

    def draw_lines(x: float, top: float, width: float, lines) -> float:
        used = 0.0
        for text, font, color in lines:
            used += c.paragraph(x, top + used, width, text, font, color)
        return used

    if left_lines or right_lines:
        if left_lines and right_lines:
            col = CW / 2 - 12
            hl = draw_lines(M, y, col, left_lines)
            hr = draw_lines(M + CW / 2 + 12, y + 1.5, col, right_lines)
        else:
            hl = draw_lines(M, y, CW, left_lines or right_lines)
            hr = 0.0
        y += max(hl, hr) + 8 * d
        c.hline(M, y, CW, 0.75, style.rule)
        y += 14 * d

    def section(title: str) -> None:
        nonlocal y
        c.paragraph(M, y, CW, title, f_head, style.accent_text)
        y += c.line_height(f_head) + 5 * d

    def grid(items: list[tuple[str, str]]) -> None:
        """Label/value pairs in two columns."""
        nonlocal y
        col_w, label_w = CW / 2, 106.0
        for i in range(0, len(items), 2):
            row_h = 0.0
            for j, (label, value) in enumerate(items[i:i + 2]):
                x = M + j * col_w + (10 if j else 0)
                c.paragraph(x, y + 1, label_w - 6, label, f_label, style.muted)
                h = c.paragraph(x + label_w, y, col_w - label_w - 18, value or "—", f_value, style.ink)
                row_h = max(row_h, h)
            y += max(row_h, 16) + 6 * d

    # ---- general + forming information
    section("GENERAL INFORMATION")
    grid([("Performed By:", data.performed_by), ("Performed For:", data.performed_for)])
    y += 2
    c.hline(M, y, CW, 1.2, style.accent)
    y += 16 * d

    section("FORMING INFORMATION")
    grid([
        ("Forming Type:", data.kind), ("Charge Current (mA):", str(data.current_ma)),
        ("Step Voltage:", f"{data.step_v}V"), ("Step Time:", minutes_text(data.step_min)),
        ("Final Voltage:", f"{data.final_v}V"), ("Final Holding Time:", minutes_text(data.final_min)),
    ])
    y += 6 * d

    # ---- units table
    headers = ("Date", "Part Number", "Serial Number", "Capacitance (µF)")
    xs = [M]
    for fr in (0.19, 0.29, 0.33, 0.19):
        xs.append(xs[-1] + CW * fr)
    head_h = row_h = 26.0 * d
    rows = [(format_date(u.when, cfg.date_format), u.part, u.serial, u.capacitance)
            for u in data.units[:MAX_UNITS]]
    table_h = head_h + row_h * len(rows)
    top = y
    c.hline(M, y, CW, 1.5, style.accent)
    for i, text in enumerate(headers):
        c.cell(QRectF(xs[i] + 6, y, xs[i + 1] - xs[i] - 12, head_h), text, f_th, style.accent_text)
    y += head_h
    c.hline(M, y, CW, 1.5, style.accent)
    for r in rows:
        for i, text in enumerate(r):
            c.cell(QRectF(xs[i] + 6, y, xs[i + 1] - xs[i] - 12, row_h), text, f_td, style.ink)
        y += row_h
        c.hline(M, y, CW, 0.75, style.rule)
    c.hline(M, y, CW, 2.0, style.accent)
    for x in xs[1:-1]:
        c.vline(x, top, table_h, 0.75, style.rule)
    y += 16 * d

    # ---- disclaimer: between the table and the notes, in a larger font than the footer
    if disclaimer := _shown(cfg.disclaimer):
        y += c.paragraph(M, y, CW, disclaimer, f_disclaimer, style.ink) + 18 * d
    else:
        y += 6 * d

    # ---- technical support content (measured now so notes can use what is left)
    support: list[tuple[str, str]] = []
    if g := _shown(cfg.support_general):
        support.append(("General Support", g))
    for ct in cfg.contacts:
        if ct.include and (ct.name.strip() or ct.phone.strip() or ct.email.strip()):
            title = ct.name.strip() + (f"  ·  {ct.role.strip()}" if ct.role.strip() else "")
            support.append((title, "   ·   ".join(t for t in (ct.phone.strip(), ct.email.strip()) if t)))
    col_w = CW / 2
    support_rows: list[float] = []
    for i in range(0, len(support), 2):
        support_rows.append(max(
            c.measure(col_w - 16, t, f_small_b) + (c.measure(col_w - 16, s, f_small) if s else 0)
            for t, s in support[i:i + 2]) + 8 * d)
    support_h = (c.line_height(f_head) + 5 * d + sum(support_rows)) if support else 0.0

    # ---- notes: as many lines as fit (at least 2 ruled lines, at most 8)
    note_w, lh = CW - 62, 19.0 * d
    note_lines = c.wrap(data.notes, f_td, note_w) if data.notes else []
    room = footer_top - (y + 18 * d) - support_h
    max_lines = max(1, min(8, int((room + 0.01) // lh)))
    wanted = max(2, min(len(note_lines), 8))
    n_lines = max(min(2, max_lines), min(len(note_lines), max_lines))
    squeezed = max_lines < wanted          # clipped only because the page is full
    clipped = len(note_lines) > n_lines
    if clipped:
        note_lines = note_lines[:n_lines]
        note_lines[-1] = c.elide(note_lines[-1] + " …", f_td, note_w - 4)
    c.paragraph(M, y + 2, 56, "NOTES", f_head, style.accent_text)
    c.ruled_text(M + 62, y, note_w, note_lines, lh, f_td, style.ink, style.rule, n_lines)
    y += n_lines * lh + 18 * d

    # ---- technical support
    if support:
        section("TECHNICAL SUPPORT")
        for i, row_h in zip(range(0, len(support), 2), support_rows):
            for j, (title, detail) in enumerate(support[i:i + 2]):
                x = M + j * col_w + (10 if j else 0)
                h = c.paragraph(x, y, col_w - 16, title, f_small_b, style.ink)
                if detail:
                    c.paragraph(x, y + h, col_w - 16, detail, f_small, style.muted)
            y += row_h

    # ---- footer
    if footer_texts:
        c.hline(M, footer_top, CW, 0.75, style.rule)
        fy = footer_top + 8
        for t in footer_texts:
            fy += c.paragraph(M, fy, CW, t, f_small, style.muted) + 4
    return LayoutInfo(end_y=y, footer_top=footer_top if footer_texts else H - M,
                      density=d, notes_clipped=clipped, notes_squeezed=squeezed)


def draw_report(painter: QPainter, page: QSizeF, data: ReportData, cfg: Settings,
                style: Style, logo: QImage | None) -> LayoutInfo:
    """Render the report onto a painter that is already scaled to points."""
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                           | QPainter.RenderHint.SmoothPixmapTransform)
    chosen = DENSITIES[-1]
    for d in DENSITIES:                                        # measuring pass
        trial = _layout(Canvas(painter, dry=True), page, data, cfg, style, logo, d)
        if trial.fits and not trial.notes_squeezed:      # prefer tighter spacing to clipped notes
            chosen = d
            break
    painter.fillRect(QRectF(0, 0, page.width(), page.height()), QColor("white"))
    return _layout(Canvas(painter), page, data, cfg, style, logo, chosen)


# --- output targets -------------------------------------------------------------

def qpage_size(paper: str) -> QPageSize:
    return QPageSize(_PAGE_IDS.get(paper, QPageSize.PageSizeId.Letter))


def page_size_points(paper: str) -> QSizeF:
    return qpage_size(paper).size(QPageSize.Unit.Point)


def export_pdf(path: str, data: ReportData, cfg: Settings, style: Style, logo: QImage | None) -> LayoutInfo:
    writer = QPdfWriter(path)
    writer.setPageSize(qpage_size(cfg.paper))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)
    writer.setResolution(600)
    writer.setTitle(TITLE)
    writer.setCreator("cfrWriter")
    painter = QPainter(writer)
    try:
        painter.scale(writer.resolution() / 72.0, writer.resolution() / 72.0)
        return draw_report(painter, page_size_points(cfg.paper), data, cfg, style, logo)
    finally:
        painter.end()


def print_report(printer, data: ReportData, cfg: Settings, style: Style, logo: QImage | None) -> LayoutInfo:
    """Draw onto a QPrinter (full-page, zero margins). Uses the paper the user actually picked."""
    painter = QPainter(printer)
    try:
        painter.scale(printer.resolution() / 72.0, printer.resolution() / 72.0)
        page = printer.pageLayout().fullRect(QPageLayout.Unit.Point).size()
        return draw_report(painter, page, data, cfg, style, logo)
    finally:
        painter.end()


def render_preview(data: ReportData, cfg: Settings, style: Style, logo: QImage | None,
                   width_px: int = 560) -> QImage:
    page = page_size_points(cfg.paper)
    scale = width_px / page.width()
    img = QImage(width_px, round(page.height() * scale), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor("white"))
    painter = QPainter(img)
    try:
        painter.scale(scale, scale)
        draw_report(painter, page, data, cfg, style, logo)
    finally:
        painter.end()
    return img
