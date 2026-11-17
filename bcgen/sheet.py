"""Build the A4 measurement sheet.

One page per bar width. Keeping a single X-dimension per page means every
symbol on that page is printed at the same size, so a page either scans or it
does not -- which turns a fuzzy "does it work" into a clean yes/no per size.

Each cell carries the payload in plain text beside the bars. That is what makes
a scan verifiable: the scanner must return exactly those characters, and the
operator can see at a glance whether it did.
"""

from __future__ import annotations

from dataclasses import dataclass

from reportlab.pdfgen import canvas as pdfcanvas

from . import render
from .generate import TestCode

MARGIN_MM = 10.0
BAR_HEIGHT_MM = 15.0
CAPTION_MM = 9.0
CELL_GAP_MM = 5.0
HEADER_MM = 26.0
FOOTER_MM = 14.0
SCALE_BAR_MM = 50.0


@dataclass(frozen=True)
class Cell:
    code: TestCode
    column: int
    row: int
    x_mm: float
    y_mm: float


@dataclass(frozen=True)
class PagePlan:
    module_dots: int
    geo: render.Geometry
    columns: int
    rows: int
    cells: list[Cell]

    @property
    def capacity(self) -> int:
        return self.columns * self.rows


class SheetError(ValueError):
    """Raised when a page cannot hold even one symbol."""


def _cell_box_mm(geo: render.Geometry) -> tuple[float, float]:
    width = geo.total_mm + CELL_GAP_MM
    height = BAR_HEIGHT_MM + CAPTION_MM + CELL_GAP_MM
    return width, height

def plan_page(codes: list[TestCode], module_dots: int, dpi: int) -> PagePlan:
    if not codes:
        raise SheetError("no codes to lay out")

    geo = render.geometry(codes[0].text, module_dots, dpi)
    usable_w = render.A4_WIDTH_MM - 2 * MARGIN_MM
    usable_h = render.A4_HEIGHT_MM - HEADER_MM - FOOTER_MM

    cell_w, cell_h = _cell_box_mm(geo)
    columns = int(usable_w // cell_w)
    rows = int(usable_h // cell_h)
    if columns < 1 or rows < 1:
        raise SheetError(
            f"a symbol at {geo.describe()} is {geo.total_mm:.1f} mm wide and does not "
            f"fit the {usable_w:.0f} mm usable width"
        )

    cells: list[Cell] = []
    for index, code in enumerate(codes[: columns * rows]):
        row, column = divmod(index, columns)
        cells.append(
            Cell(
                code=code,
                column=column,
                row=row,
                x_mm=render.snap_to_dot(MARGIN_MM + column * cell_w, dpi),
                y_mm=render.snap_to_dot(HEADER_MM + row * cell_h, dpi),
            )
        )
    return PagePlan(module_dots=module_dots, geo=geo, columns=columns, rows=rows, cells=cells)


def _draw_header(
    c: pdfcanvas.Canvas,
    *,
    page_no: int,
    page_total: int,
    plan: PagePlan,
    title: str,
    subtitle: str,
) -> None:
    geo = plan.geo
    render.draw_text(
        c, title, x_mm=MARGIN_MM, y_mm=MARGIN_MM + 3.5, size_pt=11, bold=True
    )
    render.draw_text(
        c,
        f"page {page_no}/{page_total}   bar width {geo.module_dots} dot"
        f"{'s' if geo.module_dots != 1 else ''} at {geo.dpi} dpi"
        f"   X = {geo.x_mm:.3f} mm   symbol {geo.symbol_mm:.1f} mm",
        x_mm=MARGIN_MM,
        y_mm=MARGIN_MM + 9.5,
        size_pt=8,
    )
    if subtitle:
        render.draw_text(
            c, subtitle, x_mm=MARGIN_MM, y_mm=MARGIN_MM + 14.5, size_pt=7, grey=0.4
        )
    render.draw_text(
        c,
        "SYNTHETIC CODES - NOT FOR CLINICAL USE",
        x_mm=MARGIN_MM,
        y_mm=MARGIN_MM + 19.5,
        size_pt=7,
        bold=True,
        grey=0.35,
    )
    render.draw_rule(
        c, x_mm=MARGIN_MM, y_mm=HEADER_MM - 3, width_mm=render.A4_WIDTH_MM - 2 * MARGIN_MM
    )


def _draw_footer(c: pdfcanvas.Canvas, page_no: int) -> None:
    y = render.A4_HEIGHT_MM - FOOTER_MM + 4
    render.draw_text(
        c,
        f"Print at 100% / Actual size. The bar below must measure exactly "
        f"{SCALE_BAR_MM:.0f} mm with a ruler; if it does not, the printer scaled "
        f"the page and no measurement is valid.",
        x_mm=MARGIN_MM,
        y_mm=y,
        size_pt=6.5,
        grey=0.3,
    )
    # Physical scale reference.
    c.saveState()
    c.setFillColorRGB(0, 0, 0)
    c.setStrokeColorRGB(0, 0, 0)
    h_pt = render.mm_to_points(2.0)
    y_pt = render.mm_to_points(render.A4_HEIGHT_MM - (y + 6))
    x_pt = render.mm_to_points(MARGIN_MM)
    c.rect(x_pt, y_pt, render.mm_to_points(SCALE_BAR_MM), h_pt, stroke=0, fill=1)
    c.restoreState()
    render.draw_text(
        c, f"{SCALE_BAR_MM:.0f} mm", x_mm=MARGIN_MM + SCALE_BAR_MM + 2, y_mm=y + 8, size_pt=7
    )
    render.draw_text(
        c, f"p.{page_no}", x_mm=render.A4_WIDTH_MM - MARGIN_MM - 8, y_mm=y + 8, size_pt=7, grey=0.4
    )


def _draw_cell(c: pdfcanvas.Canvas, cell: Cell, plan: PagePlan, page_no: int) -> None:
    render.draw_symbol(
        c,
        cell.code.text,
        x_mm=cell.x_mm,
        y_mm=cell.y_mm,
        module_dots=plan.module_dots,
        dpi=plan.geo.dpi,
        height_mm=BAR_HEIGHT_MM,
    )
    caption_y = cell.y_mm + BAR_HEIGHT_MM + 3.2
    render.draw_text(
        c,
        f"{page_no}.{cell.row + 1}.{cell.column + 1}",
        x_mm=cell.x_mm,
        y_mm=caption_y,
        size_pt=5.5,
        grey=0.5,
    )
    render.draw_text(
        c,
        cell.code.text,
        x_mm=cell.x_mm,
        y_mm=caption_y + 3.6,
        size_pt=7.5,
        bold=True,
    )


def build_sheet(
    path: str,
    codes: list[TestCode],
    *,
    rungs: list[int],
    dpi: int,
    title: str = "Barcode reader measurement sheet",
    subtitle: str = "",
) -> list[PagePlan]:
    """Write the PDF and return the page plans, for reporting and self-check."""
    if not codes:
        raise SheetError("no codes supplied")
    if not rungs:
        raise SheetError("no bar widths supplied")

    plans: list[PagePlan] = []
    for module_dots in rungs:
        plans.append(plan_page(codes, module_dots, dpi))

    c = pdfcanvas.Canvas(path, pagesize=(
        render.mm_to_points(render.A4_WIDTH_MM),
        render.mm_to_points(render.A4_HEIGHT_MM),
    ))
    c.setTitle(title)

    for page_no, plan in enumerate(plans, start=1):
        _draw_header(
            c,
            page_no=page_no,
            page_total=len(plans),
            plan=plan,
            title=title,
            subtitle=subtitle,
        )
        for cell in plan.cells:
            _draw_cell(c, cell, plan, page_no)
        _draw_footer(c, page_no)
        c.showPage()

    c.save()
    return plans
