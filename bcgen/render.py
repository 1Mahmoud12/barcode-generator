"""Render Code 128 symbols to a PDF page with dot-exact bar widths.

The whole point of this module is that bar positions are computed in *device
dots* and only then converted to PDF points. A module is therefore always a
whole number of printer dots, so a 300 dpi printer cannot distort the symbol by
rounding some modules wider than others.

PDF points are 1/72 inch, so one dot at ``dpi`` is ``72 / dpi`` points.
"""

from __future__ import annotations

from dataclasses import dataclass

from reportlab.pdfgen import canvas as pdfcanvas

from . import code128

MM_PER_INCH = 25.4
POINTS_PER_INCH = 72.0

A4_WIDTH_MM = 210.0
A4_HEIGHT_MM = 297.0

# Quiet zone of 10 X-dimensions on each side, per ISO/IEC 15417.
QUIET_ZONE_MODULES = 10


class RenderError(ValueError):
    """Raised when a symbol does not fit the requested space."""


def page_height_mm(c: pdfcanvas.Canvas) -> float:
    """Height of the current page, so drawing is not tied to one paper size."""
    size = getattr(c, "_pagesize", None)
    if not size:
        return A4_HEIGHT_MM
    return size[1] * MM_PER_INCH / POINTS_PER_INCH


def page_width_mm(c: pdfcanvas.Canvas) -> float:
    size = getattr(c, "_pagesize", None)
    if not size:
        return A4_WIDTH_MM
    return size[0] * MM_PER_INCH / POINTS_PER_INCH


def dots_per_mm(dpi: int) -> float:
    return dpi / MM_PER_INCH


def dot_mm(dpi: int) -> float:
    """Physical size of one printer dot in millimetres."""
    return MM_PER_INCH / dpi


def mm_to_points(mm: float) -> float:
    return mm * POINTS_PER_INCH / MM_PER_INCH


def snap_to_dot(mm: float, dpi: int) -> float:
    """Round a length to the nearest whole printer dot.

    Bar origins must land on the device grid. If a symbol starts half a dot off,
    the first bar rasterises one dot wider and the decoder can misread it.
    """
    d = dot_mm(dpi)
    return round(mm / d) * d


@dataclass(frozen=True)
class Geometry:
    """Resolved size of one symbol for a given printer resolution."""

    dpi: int
    module_dots: int
    modules: int

    @property
    def x_mm(self) -> float:
        return self.module_dots * dot_mm(self.dpi)

    @property
    def symbol_mm(self) -> float:
        return self.modules * self.x_mm

    @property
    def total_mm(self) -> float:
        return (self.modules + 2 * QUIET_ZONE_MODULES) * self.x_mm

    @property
    def total_dots(self) -> int:
        return (self.modules + 2 * QUIET_ZONE_MODULES) * self.module_dots

    def describe(self) -> str:
        return f"{self.module_dots}d/{self.dpi} = {self.x_mm:.3f} mm"


def geometry(text: str, module_dots: int, dpi: int) -> Geometry:
    if module_dots < 1:
        raise RenderError("module_dots must be >= 1")
    if dpi < 72:
        raise RenderError("dpi must be >= 72")
    return Geometry(dpi=dpi, module_dots=module_dots, modules=code128.module_count(text))


def module_dots_for_width(text: str, target_mm: float, dpi: int) -> int:
    """Largest whole-dot bar width whose symbol plus quiet zones fits ``target_mm``.

    Sizes are always whole dots, so asking for "30 mm" gives the closest width
    that is actually printable rather than a fraction the printer would round.
    """
    if target_mm <= 0:
        raise RenderError("target width must be positive")
    modules = code128.module_count(text)
    if modules <= 0:
        raise RenderError("empty symbol")
    per_module_mm = target_mm / (modules + 2 * QUIET_ZONE_MODULES)
    module_dots = int(per_module_mm / dot_mm(dpi))
    if module_dots < 1:
        raise RenderError(
            f"{target_mm:.1f} mm is too narrow for {len(text)} characters at {dpi} dpi; "
            f"the narrowest possible symbol is "
            f"{(modules + 2 * QUIET_ZONE_MODULES) * dot_mm(dpi):.1f} mm"
        )
    return module_dots


def geometry_for_width(text: str, target_mm: float, dpi: int) -> Geometry:
    """Geometry that fills ``target_mm`` as closely as whole dots allow."""
    return geometry(text, module_dots_for_width(text, target_mm, dpi), dpi)


def ladder(dpi: int, module_dots: tuple[int, ...] = (3, 4, 5, 6, 8, 10, 12)) -> list[int]:
    """The bar-width rungs to print, smallest first."""
    return sorted({int(d) for d in module_dots if int(d) >= 1})


def draw_symbol(
    c: pdfcanvas.Canvas,
    text: str,
    *,
    x_mm: float,
    y_mm: float,
    module_dots: int,
    dpi: int,
    height_mm: float,
) -> Geometry:
    """Draw one symbol with its top-left corner at (x_mm, y_mm) in page space.

    ``y_mm`` is measured from the top of the page. Bars grow downwards.
    """
    geo = geometry(text, module_dots, dpi)

    dot_pt = mm_to_points(dot_mm(dpi))
    bars = code128.bars(text, module_dots)

    # Snap the symbol origin to the device grid, then keep every offset a whole
    # number of dots from it. Without this the leading bar can rasterise wider.
    x_pt = round(mm_to_points(snap_to_dot(x_mm, dpi)) / dot_pt) * dot_pt

    # Baseline: y measured from top, PDF y grows upwards.
    page_h = page_height_mm(c)
    top_pt = round(mm_to_points(page_h - snap_to_dot(y_mm, dpi)) / dot_pt) * dot_pt
    bottom_pt = round(mm_to_points(page_h - snap_to_dot(y_mm + height_mm, dpi)) / dot_pt) * dot_pt
    left_dots = QUIET_ZONE_MODULES * module_dots

    c.saveState()
    c.setFillColorRGB(0, 0, 0)
    for start_dots, width_dots in bars:
        x0 = x_pt + (left_dots + start_dots) * dot_pt
        c.rect(x0, bottom_pt, width_dots * dot_pt, top_pt - bottom_pt, stroke=0, fill=1)
    c.restoreState()

    return geo


def draw_text(
    c: pdfcanvas.Canvas,
    text: str,
    *,
    x_mm: float,
    y_mm: float,
    size_pt: float = 7.0,
    bold: bool = False,
    grey: float = 0.0,
) -> None:
    c.saveState()
    c.setFillColorRGB(grey, grey, grey)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size_pt)
    c.drawString(mm_to_points(x_mm), mm_to_points(page_height_mm(c) - y_mm), text)
    c.restoreState()


def draw_text_centered(
    c: pdfcanvas.Canvas,
    text: str,
    *,
    center_x_mm: float,
    y_mm: float,
    size_pt: float = 7.0,
    bold: bool = False,
    grey: float = 0.0,
) -> None:
    width_mm = text_width_mm(c, text, size_pt, bold)
    draw_text(
        c,
        text,
        x_mm=center_x_mm - width_mm / 2,
        y_mm=y_mm,
        size_pt=size_pt,
        bold=bold,
        grey=grey,
    )


def text_width_mm(
    c: pdfcanvas.Canvas, text: str, size_pt: float = 7.0, bold: bool = False
) -> float:
    """Width of a string in millimetres, for centring and fitting checks."""
    font = "Helvetica-Bold" if bold else "Helvetica"
    width_pt = c.stringWidth(text, font, size_pt)
    return width_pt * MM_PER_INCH / POINTS_PER_INCH


def draw_rule(
    c: pdfcanvas.Canvas,
    *,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    thickness_pt: float = 0.4,
    grey: float = 0.6,
) -> None:
    c.saveState()
    c.setStrokeColorRGB(grey, grey, grey)
    c.setLineWidth(thickness_pt)
    y_pt = mm_to_points(page_height_mm(c) - y_mm)
    c.line(mm_to_points(x_mm), y_pt, mm_to_points(x_mm + width_mm), y_pt)
    c.restoreState()


def draw_rect(
    c: pdfcanvas.Canvas,
    *,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    height_mm: float,
    thickness_pt: float = 0.3,
    grey: float = 0.75,
    dash: tuple[float, float] | None = None,
) -> None:
    """Outline a box in page space, with ``y_mm`` measured from the top."""
    c.saveState()
    c.setStrokeColorRGB(grey, grey, grey)
    c.setLineWidth(thickness_pt)
    if dash:
        c.setDash(dash, 0)
    page_h = page_height_mm(c)
    c.rect(
        mm_to_points(x_mm),
        mm_to_points(page_h - y_mm - height_mm),
        mm_to_points(width_mm),
        mm_to_points(height_mm),
        stroke=1,
        fill=0,
    )
    c.restoreState()
