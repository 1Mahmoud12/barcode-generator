"""Print a complete product label, not just bars.

A label is a small block of text with a barcode in it. Everything on it is data
the operator types or imports; this module only places it. No field is derived
from the barcode and no field is interpreted.

Two paper models are supported, because they are genuinely different:

* **Sheet** -- many labels on one page with cut lines. Used for A4 sticker stock.
* **Roll** -- one label per page, page size equal to the label. This is the only
  model a receipt or label printer understands; the printer itself decides where
  the page ends.

Text is Latin-only on purpose. Arabic needs shaping and bidi reordering, which a
PDF canvas does not do by itself, and a label with reversed letters is worse than
no label.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from reportlab.pdfgen import canvas as pdfcanvas

from . import render

# Receipt printers are almost always 203 dpi; label printers are often 300.
RECEIPT_DPI = 203
LABEL_DPI = 300

# Common thermal widths in millimetres (paper width, printable slightly less).
ROLL_WIDTHS = (58.0, 80.0)

DEFAULT_LABEL_W_MM = 50.0
DEFAULT_LABEL_H_MM = 25.0

MAX_TEXT_CHARS = 60


class LabelError(ValueError):
    """Raised when the label cannot be laid out as asked."""


@dataclass
class LabelData:
    """Everything printed on one label.

    Only ``code`` goes into the bars. The rest is human-readable text and is
    never encoded, so a mistyped lot number cannot silently become barcode data.
    """

    code: str = ""
    product: str = ""
    lot: str = ""
    expiry: str = ""
    produced: str = ""
    volume: str = ""
    storage: str = ""
    notes: str = ""
    copies: int = 1
    extra: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.code.strip():
            raise LabelError("the barcode text is empty")
        try:
            render.code128.module_count(self.code)
        except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the operator
            raise LabelError(f"barcode text cannot be encoded: {exc}") from exc

        for name, value in (
            ("product", self.product),
            ("lot", self.lot),
            ("expiry", self.expiry),
            ("produced", self.produced),
            ("volume", self.volume),
            ("storage", self.storage),
            ("notes", self.notes),
        ):
            if len(value) > MAX_TEXT_CHARS:
                raise LabelError(f"{name} is longer than {MAX_TEXT_CHARS} characters")
            if not value.isascii():
                raise LabelError(
                    f"{name} contains non-Latin characters; this build prints Latin text only"
                )
        if not self.code.isascii():
            raise LabelError("the barcode text must be Latin characters only")
        if self.copies < 1:
            raise LabelError("copies must be at least 1")


@dataclass(frozen=True)
class LabelLayout:
    width_mm: float
    height_mm: float
    margin_mm: float
    bar_height_mm: float
    text_pt: float
    title_pt: float


def _fit_text_size(
    c: pdfcanvas.Canvas, text: str, max_mm: float, start_pt: float, minimum: float = 4.0
) -> float:
    size = start_pt
    while size > minimum and render.text_width_mm(c, text, size, bold=True) > max_mm:
        size -= 0.25
    return size


def _draw_lines(
    c: pdfcanvas.Canvas,
    lines: list[tuple[str, float, bool]],
    *,
    x_mm: float,
    y_mm: float,
    max_width_mm: float,
    line_gap_mm: float,
) -> float:
    """Draw (text, size_pt, bold) rows top to bottom; return the next free y."""
    cursor = y_mm
    for text, size, bold in lines:
        if not text:
            continue
        fitted = _fit_text_size(c, text, max_width_mm, size)
        render.draw_text(c, text, x_mm=x_mm, y_mm=cursor, size_pt=fitted, bold=bold)
        cursor += line_gap_mm
    return cursor


def _line_mm(text_pt: float) -> float:
    """Line advance in millimetres for a given font size.

    A fixed advance wastes vertical space on a small label: 6 pt text with a
    3.2 mm step leaves gaps bigger than the glyphs. Scaling the advance with the
    font is what lets small labels hold more rows.
    """
    return text_pt * 0.62


def _title_mm(title_pt: float) -> float:
    return title_pt * 0.62


def _data_rows(data: LabelData) -> list[str]:
    rows: list[str] = []
    if data.volume:
        rows.append(data.volume)
    if data.lot:
        rows.append(f"LOT {data.lot}")
    if data.expiry:
        rows.append(f"EXP {data.expiry}")
    if data.produced:
        rows.append(f"MFG {data.produced}")
    if data.storage:
        rows.append(data.storage)
    if data.notes:
        rows.append(data.notes)
    return rows


def _rows_per_column(
    c: pdfcanvas.Canvas, data: LabelData, layout: LabelLayout
) -> tuple[int, bool]:
    """How many columns of data rows are needed for the content to fit.

    Short, wide labels (receipt paper) cannot stack six rows, so the rows split
    into two columns when that is what makes the data fit.
    """
    rows = _data_rows(data)
    if not rows:
        return 1, False

    line = _line_mm(layout.text_pt)
    fixed = 2 * layout.margin_mm
    if data.product:
        fixed += _title_mm(layout.title_pt)
    fixed += layout.bar_height_mm + 2.4 + _code_line_mm(layout)
    available = layout.height_mm - fixed

    per_column = max(0, int(available // line))
    if len(rows) <= per_column:
        return 1, False

    inner_w = layout.width_mm - 2 * layout.margin_mm
    widest = max(render.text_width_mm(c, text, layout.text_pt) for text in rows)
    if per_column * 2 >= len(rows) and widest * 2 + 3.0 <= inner_w:
        return 2, True

    return 1, False


def _code_line_mm(layout: LabelLayout) -> float:
    """Advance used for the human-readable code line under the bars."""
    return _line_mm(layout.text_pt + 0.5) + 0.4


def _vertical_need(c: pdfcanvas.Canvas, data: LabelData, layout: LabelLayout) -> float:
    """Height in millimetres the content wants, without drawing anything.

    This must mirror :func:`draw_label` step for step. When the two disagree,
    ``auto_fit`` accepts a layout that drawing then rejects.
    """
    columns, _ = _rows_per_column(c, data, layout)
    rows = _data_rows(data)
    row_lines = -(-len(rows) // columns) if rows else 0

    need = 2 * layout.margin_mm
    if data.product:
        need += _title_mm(layout.title_pt)
    need += layout.bar_height_mm + 2.4
    need += _code_line_mm(layout)
    need += row_lines * _line_mm(layout.text_pt)
    return need


# ISO/IEC 15417 leaves height to the application, but a bar shorter than this is
# unreliable on a handheld or a fixed reader. 6 mm is the usual industrial floor.
MIN_BAR_HEIGHT_MM = 6.0

# The narrowest module worth printing on thermal stock. Below ~0.19 mm a thermal
# head cannot hold the edge, so the symbol decays even if it was generated right.
MIN_X_MM = 0.19


def auto_fit(
    c: pdfcanvas.Canvas,
    data: LabelData,
    *,
    width_mm: float,
    height_mm: float,
    margin_mm: float,
    dpi: int,
    bar_height_mm: float | None = None,
) -> LabelLayout:
    """Choose a bar height and text size that make the data fit the label.

    Instead of refusing a small label because the operator typed six fields,
    shrink the bar and the text until it fits, within limits that keep the
    barcode scannable. If even the minimum does not fit, the error names what to
    change.
    """
    heights = [bar_height_mm] if bar_height_mm is not None else [
        12.0, 11.0, 10.0, 9.0, 8.0, 7.0, MIN_BAR_HEIGHT_MM
    ]

    best: LabelLayout | None = None
    for title_pt in (8.0, 7.5, 7.0, 6.5, 6.0):
        for text_pt in (6.0, 5.5, 5.0, 4.5, 4.0):
            for bar_mm in heights:
                layout = LabelLayout(
                    width_mm=width_mm,
                    height_mm=height_mm,
                    margin_mm=margin_mm,
                    bar_height_mm=bar_mm,
                    text_pt=text_pt,
                    title_pt=title_pt,
                )
                best = layout
                if _vertical_need(c, data, layout) <= height_mm:
                    return layout

    rows = len(_data_rows(data))
    need = _vertical_need(c, data, best) if best else 0.0
    raise LabelError(
        f"this data needs about {need:.0f} mm of height at a "
        f"{MIN_BAR_HEIGHT_MM:.0f} mm bar, but the label is {height_mm:.0f} mm. "
        f"Shorten the fields, drop rows (currently {rows}), or use a taller label."
    )


def draw_label(
    c: pdfcanvas.Canvas,
    data: LabelData,
    *,
    x_mm: float,
    y_mm: float,
    layout: LabelLayout,
    dpi: int,
    cut_line: bool = False,
) -> render.Geometry:
    """Draw one complete label with its top-left corner at (x_mm, y_mm)."""
    data.validate()

    inner_w = layout.width_mm - 2 * layout.margin_mm
    inner_x = x_mm + layout.margin_mm
    cursor = y_mm + layout.margin_mm

    # Header: product name, large and bold.
    if data.product:
        size = _fit_text_size(c, data.product, inner_w, layout.title_pt)
        render.draw_text(c, data.product, x_mm=inner_x, y_mm=cursor, size_pt=size, bold=True)
        cursor += _title_mm(layout.title_pt)

    # Barcode, sized to fill the inner width.
    target_w = inner_w
    try:
        geo = render.geometry_for_width(data.code, target_w, dpi)
    except render.RenderError as exc:
        raise LabelError(str(exc)) from exc

    if geo.total_mm > inner_w + 0.01:
        raise LabelError(
            f"the barcode needs {geo.total_mm:.1f} mm but the label has {inner_w:.1f} mm"
        )

    render.draw_symbol(
        c,
        data.code,
        x_mm=inner_x,
        y_mm=cursor,
        module_dots=geo.module_dots,
        dpi=dpi,
        height_mm=layout.bar_height_mm,
    )
    cursor += layout.bar_height_mm + 2.4

    # Human-readable code, centred under the bars.
    render.draw_text_centered(
        c,
        data.code,
        center_x_mm=x_mm + layout.width_mm / 2,
        y_mm=cursor,
        size_pt=layout.text_pt + 0.5,
        bold=True,
    )
    cursor += _line_mm(layout.text_pt + 0.5) + 0.4

    # Data rows, in one or two columns depending on what fits.
    rows = _data_rows(data)
    columns, _ = _rows_per_column(c, data, layout)
    if rows:
        per_column = -(-len(rows) // columns)
        column_gap = 3.0
        column_width = (inner_w - column_gap * (columns - 1)) / columns
        for column_index in range(columns):
            start = column_index * per_column
            chunk = rows[start : start + per_column]
            _draw_lines(
                c,
                [(text, layout.text_pt, False) for text in chunk],
                x_mm=inner_x + column_index * (column_width + column_gap),
                y_mm=cursor,
                max_width_mm=column_width,
                line_gap_mm=_line_mm(layout.text_pt),
            )
        cursor += per_column * _line_mm(layout.text_pt)

    if cursor - y_mm > layout.height_mm - layout.margin_mm + 0.5:
        raise LabelError(
            f"the label content needs {cursor - y_mm:.1f} mm but only "
            f"{layout.height_mm - layout.margin_mm:.1f} mm is available; "
            f"use a taller label or fewer data rows"
        )

    if cut_line:
        render.draw_rect(
            c,
            x_mm=x_mm,
            y_mm=y_mm,
            width_mm=layout.width_mm,
            height_mm=layout.height_mm,
            thickness_pt=0.25,
            grey=0.8,
            dash=(1.5, 2),
        )

    return geo


def _prepare(path: str, page_w: float, page_h: float) -> pdfcanvas.Canvas:
    c = pdfcanvas.Canvas(
        path,
        pagesize=(render.mm_to_points(page_w), render.mm_to_points(page_h)),
    )
    c.setTitle("Product labels")
    return c


def build_sheet(
    path: str,
    labels: list[LabelData],
    *,
    page_width_mm: float,
    page_height_mm: float,
    label_width_mm: float,
    label_height_mm: float,
    dpi: int,
    margin_mm: float = 2.0,
    bar_height_mm: float | None = None,
    gap_mm: float = 3.0,
    cut_lines: bool = True,
    page_heading: str = "",
) -> LabelLayout:
    """Lay many labels on sheets, repeating each label by its ``copies`` count."""
    if not labels:
        raise LabelError("no labels to print")
    if label_width_mm <= 2 * margin_mm or label_height_mm <= 2 * margin_mm:
        raise LabelError("label size is too small for its margins")

    expanded: list[LabelData] = []
    for label in labels:
        label.validate()
        expanded.extend([label] * label.copies)

    heading_mm = 8.0 if page_heading else 0.0
    usable_w = page_width_mm - 2 * gap_mm
    usable_h = page_height_mm - 2 * gap_mm - heading_mm

    per_row = int((usable_w + gap_mm) // (label_width_mm + gap_mm))
    per_col = int((usable_h + gap_mm) // (label_height_mm + gap_mm))
    if per_row < 1 or per_col < 1:
        raise LabelError(
            f"a {label_width_mm:.0f}x{label_height_mm:.0f} mm label does not fit a "
            f"{page_width_mm:.0f}x{page_height_mm:.0f} mm page"
        )
    per_page = per_row * per_col

    c = _prepare(path, page_width_mm, page_height_mm)
    layout = auto_fit(
        c,
        expanded[0],
        width_mm=label_width_mm,
        height_mm=label_height_mm,
        margin_mm=margin_mm,
        dpi=dpi,
    )
    if bar_height_mm is not None:
        layout = LabelLayout(
            width_mm=layout.width_mm,
            height_mm=layout.height_mm,
            margin_mm=layout.margin_mm,
            bar_height_mm=bar_height_mm,
            text_pt=layout.text_pt,
            title_pt=layout.title_pt,
        )

    for index, item in enumerate(expanded):
        slot = index % per_page
        if slot == 0:
            if index > 0:
                c.showPage()
            if page_heading:
                render.draw_text(
                    c,
                    page_heading,
                    x_mm=gap_mm,
                    y_mm=gap_mm + 3.5,
                    size_pt=8,
                    bold=True,
                    grey=0.4,
                )

        row, column = divmod(slot, per_row)
        x_mm = gap_mm + column * (label_width_mm + gap_mm)
        y_mm = gap_mm + heading_mm + row * (label_height_mm + gap_mm)

        draw_label(c, item, x_mm=x_mm, y_mm=y_mm, layout=layout, dpi=dpi, cut_line=cut_lines)

    c.showPage()
    c.save()
    return layout


def build_roll(
    path: str,
    labels: list[LabelData],
    *,
    paper_width_mm: float,
    label_width_mm: float,
    label_height_mm: float,
    dpi: int,
    margin_mm: float = 1.5,
    bar_height_mm: float | None = None,
) -> LabelLayout:
    """One label per page, page size = label size.

    A receipt printer advances paper by the page height, so the page must be
    exactly one label tall or every print wastes stock and shifts the next label.
    """
    if not labels:
        raise LabelError("no labels to print")
    if label_width_mm > paper_width_mm + 0.01:
        raise LabelError(
            f"the label is {label_width_mm:.0f} mm wide but the paper is "
            f"{paper_width_mm:.0f} mm"
        )

    expanded: list[LabelData] = []
    for label in labels:
        label.validate()
        expanded.extend([label] * label.copies)

    c = _prepare(path, label_width_mm, label_height_mm)
    layout = auto_fit(
        c,
        expanded[0],
        width_mm=label_width_mm,
        height_mm=label_height_mm,
        margin_mm=margin_mm,
        dpi=dpi,
    )
    if bar_height_mm is not None:
        layout = LabelLayout(
            width_mm=layout.width_mm,
            height_mm=layout.height_mm,
            margin_mm=layout.margin_mm,
            bar_height_mm=bar_height_mm,
            text_pt=layout.text_pt,
            title_pt=layout.title_pt,
        )

    for item in expanded:
        draw_label(c, item, x_mm=0.0, y_mm=0.0, layout=layout, dpi=dpi, cut_line=False)
        c.showPage()

    c.save()
    return layout


ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalise_date(value: str) -> str:
    """Accept YYYY-MM-DD and YYYYMMDD; return YYYY-MM-DD.

    Dates are printed as given. This only rewrites the one alternative form
    people type, so the label looks consistent.
    """
    text = value.strip()
    if not text:
        return ""
    if ISO_DATE.match(text):
        return text
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text
