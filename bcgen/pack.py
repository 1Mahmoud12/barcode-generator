"""Print the four pack items together on one sheet.

The four do not share a size or a symbology, so they cannot be laid out as a
uniform grid. They are stacked in labelled blocks instead, each block sized to
its own content:

* two Code 128 items (trigger, reagent) as wide bars with their text beneath
* two QR items (method, package) as squares, side by side when width allows

Every block is printed with its kind written above it, because the four are
scanned at different places and a mixed-up sheet is worse than no sheet.
"""

from __future__ import annotations

from dataclasses import dataclass

from reportlab.pdfgen import canvas as pdfcanvas

from . import kind, render
from .kind import Item, Kind, KindError

PAGE_MARGIN_MM = 8.0
BLOCK_GAP_MM = 4.0
KIND_LABEL_MM = 3.6
CAPTION_MM = 3.4
BAR_HEIGHT_MM = 14.0

# Default printed caps. A label is a few centimetres wide, not a page: without
# a cap the bars would stretch to the paper width and the QR to 95 mm.
DEFAULT_BAR_WIDTH_MM = 55.0
DEFAULT_QR_MM = 30.0

# A module finer than this on thermal stock loses its edge. Used to grow the QR
# square automatically when the payload is long.
MIN_QR_MODULE_DOTS = 3


@dataclass(frozen=True)
class Placement:
    """Where one item ended up, for reporting and for the self-check."""

    item: Item
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    module_dots: int


class PackError(ValueError):
    """Raised when the four items cannot be placed on the page."""


def _draw_kind_label(
    c: pdfcanvas.Canvas, kind_value: Kind, *, x_mm: float, y_mm: float
) -> None:
    render.draw_text(
        c,
        kind_value.title.upper(),
        x_mm=x_mm,
        y_mm=y_mm,
        size_pt=6.5,
        bold=True,
        grey=0.25,
    )
    render.draw_text(
        c,
        kind_value.symbology,
        x_mm=x_mm,
        y_mm=y_mm,
        size_pt=6.0,
        grey=0.55,
    )


def _draw_bars(
    c: pdfcanvas.Canvas,
    item: Item,
    *,
    x_mm: float,
    y_mm: float,
    max_width_mm: float,
    dpi: int,
) -> tuple[render.Geometry, float]:
    """Draw kind label, bars and the readable text. Returns geometry and height."""
    render.draw_text(
        c, item.kind.title.upper(), x_mm=x_mm, y_mm=y_mm, size_pt=6.5, bold=True, grey=0.25
    )
    render.draw_text(
        c,
        "Code 128",
        x_mm=x_mm + 22,
        y_mm=y_mm,
        size_pt=6.0,
        grey=0.55,
    )

    geo = render.geometry_for_width(item.text, max_width_mm, dpi)
    bar_top = y_mm + KIND_LABEL_MM
    render.draw_symbol(
        c,
        item.text,
        x_mm=x_mm,
        y_mm=bar_top,
        module_dots=geo.module_dots,
        dpi=dpi,
        height_mm=BAR_HEIGHT_MM,
    )
    caption_y = bar_top + BAR_HEIGHT_MM + CAPTION_MM
    render.draw_text(c, item.text, x_mm=x_mm, y_mm=caption_y, size_pt=7.5, bold=True)
    return geo, KIND_LABEL_MM + BAR_HEIGHT_MM + CAPTION_MM + 1.2


def _draw_qr_block(
    c: pdfcanvas.Canvas,
    item: Item,
    *,
    x_mm: float,
    y_mm: float,
    square_mm: float,
    dpi: int,
) -> tuple[int, float]:
    """Draw one QR block and return (module dots, block height)."""
    render.draw_text(
        c, item.kind.title.upper(), x_mm=x_mm, y_mm=y_mm, size_pt=6.5, bold=True, grey=0.25
    )
    render.draw_text(c, "QR", x_mm=x_mm + 22, y_mm=y_mm, size_pt=6.0, grey=0.55)

    dots = kind.qr_module_dots_for(item.text, square_mm, dpi)
    top = y_mm + KIND_LABEL_MM
    kind.draw_qr(c, item.text, x_mm=x_mm, y_mm=top, module_dots=dots, dpi=dpi)

    caption = item.text if len(item.text) <= 40 else item.text[:37] + "..."
    render.draw_text(
        c, caption, x_mm=x_mm, y_mm=top + square_mm + 2.2, size_pt=6.0, grey=0.2
    )
    return dots, KIND_LABEL_MM + square_mm + CAPTION_MM + 1.2


def build_pack_sheet(
    path: str,
    items: list[Item],
    *,
    page_width_mm: float = 210.0,
    page_height_mm: float = 297.0,
    dpi: int = 300,
    title: str = "Pack symbols",
    subtitle: str = "",
    qr_square_mm: float | None = None,
    bar_width_mm: float | None = None,
) -> list[Placement]:
    """Print the given items stacked on one or more pages.

    ``bar_width_mm`` and ``qr_square_mm`` cap the printed size. Without a cap the
    bars would stretch across the whole page, which is not a label anyone can
    stick on a bottle -- so the default is a realistic label width rather than the
    full page.
    """
    if not items:
        raise PackError("no items to print")

    for item in items:
        item.validate()

    bars = [i for i in items if not i.kind.is_two_dimensional]
    squares = [i for i in items if i.kind.is_two_dimensional]

    inner_w = page_width_mm - 2 * PAGE_MARGIN_MM
    usable_h = page_height_mm - 2 * PAGE_MARGIN_MM

    if bar_width_mm is None:
        bar_width_mm = min(DEFAULT_BAR_WIDTH_MM, inner_w)
    bar_width_mm = min(bar_width_mm, inner_w)

    if qr_square_mm is None:
        available = inner_w - BLOCK_GAP_MM * max(0, len(squares) - 1)
        wanted = DEFAULT_QR_MM
        for item in squares:
            modules = kind.qr_modules(item.text) + 2 * kind.qr_quiet_modules()
            # Grow until the *module* is printable, not until the square reaches a
            # nominal size. A 105-module symbol at 30 mm has a module of 0.27 mm,
            # which a thermal head will smear; the same module size on a 21-module
            # symbol would be 1.3 mm. Module size, not square size, decides whether
            # the code reads.
            needed = modules * MIN_QR_MODULE_DOTS * render.dot_mm(dpi)
            wanted = max(wanted, needed)
        qr_square_mm = min(wanted, available / max(1, len(squares)))

    bar_block_h = KIND_LABEL_MM + BAR_HEIGHT_MM + CAPTION_MM + 1.2
    qr_block_h = KIND_LABEL_MM + qr_square_mm + CAPTION_MM + 1.2

    needed = 12.0
    needed += bar_block_h * len(bars)
    needed += qr_block_h * (1 if squares else 0)
    if needed > usable_h:
        raise PackError(
            f"the items need about {needed:.0f} mm of height but the page gives "
            f"{usable_h:.0f} mm; reduce the QR square size"
        )

    c = pdfcanvas.Canvas(
        path,
        pagesize=(render.mm_to_points(page_width_mm), render.mm_to_points(page_height_mm)),
    )
    c.setTitle(title)

    render.draw_text(
        c, title, x_mm=PAGE_MARGIN_MM, y_mm=PAGE_MARGIN_MM + 4, size_pt=12, bold=True
    )
    if subtitle:
        render.draw_text(
            c, subtitle, x_mm=PAGE_MARGIN_MM, y_mm=PAGE_MARGIN_MM + 9, size_pt=7, grey=0.45
        )
    render.draw_text(
        c,
        "TEST SHEET - NOT FOR CLINICAL USE",
        x_mm=PAGE_MARGIN_MM,
        y_mm=PAGE_MARGIN_MM + 13.5,
        size_pt=7,
        bold=True,
        grey=0.35,
    )
    render.draw_rule(
        c,
        x_mm=PAGE_MARGIN_MM,
        y_mm=PAGE_MARGIN_MM + 16.5,
        width_mm=inner_w,
    )

    placements: list[Placement] = []
    cursor = PAGE_MARGIN_MM + 12.0

    for item in bars:
        geo, height = _draw_bars(
            c, item, x_mm=PAGE_MARGIN_MM, y_mm=cursor, max_width_mm=bar_width_mm, dpi=dpi
        )
        placements.append(
            Placement(
                item=item,
                x_mm=PAGE_MARGIN_MM,
                y_mm=cursor + KIND_LABEL_MM,
                width_mm=geo.total_mm,
                height_mm=BAR_HEIGHT_MM,
                module_dots=geo.module_dots,
            )
        )
        cursor += height + BLOCK_GAP_MM

    if squares:
        columns = len(squares)
        square_w = min(qr_square_mm, (inner_w - BLOCK_GAP_MM * (columns - 1)) / columns)
        if KIND_LABEL_MM + square_w + CAPTION_MM + 1.2 + cursor > usable_h + PAGE_MARGIN_MM:
            c.showPage()
            cursor = PAGE_MARGIN_MM
        for index, item in enumerate(squares):
            x_mm = PAGE_MARGIN_MM + index * (square_w + BLOCK_GAP_MM)
            dots, _ = _draw_qr_block(
                c, item, x_mm=x_mm, y_mm=cursor, square_mm=square_w, dpi=dpi
            )
            placements.append(
                Placement(
                    item=item,
                    x_mm=x_mm,
                    y_mm=cursor + KIND_LABEL_MM,
                    width_mm=kind.qr_size_mm(item.text, dots, dpi),
                    height_mm=kind.qr_size_mm(item.text, dots, dpi),
                    module_dots=dots,
                )
            )

    c.showPage()
    c.save()
    return placements


def four_standard_items(
    *,
    trigger: str,
    reagent: str,
    method_qr: str,
    package_qr: str,
) -> list[Item]:
    """The usual set: both short codes and both QR codes."""
    return [
        Item(Kind.TRIGGER, trigger),
        Item(Kind.REAGENT, reagent),
        Item(Kind.METHOD, method_qr),
        Item(Kind.PACKAGE, package_qr),
    ]
