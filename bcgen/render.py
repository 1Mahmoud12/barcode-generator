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
    top_pt = round(mm_to_points(A4_HEIGHT_MM - snap_to_dot(y_mm, dpi)) / dot_pt) * dot_pt
    bottom_pt = round(mm_to_points(A4_HEIGHT_MM - snap_to_dot(y_mm + height_mm, dpi)) / dot_pt) * dot_pt
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
    c.drawString(mm_to_points(x_mm), mm_to_points(A4_HEIGHT_MM - y_mm), text)
    c.restoreState()


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
    y_pt = mm_to_points(A4_HEIGHT_MM - y_mm)
    c.line(mm_to_points(x_mm), y_pt, mm_to_points(x_mm + width_mm), y_pt)
    c.restoreState()
