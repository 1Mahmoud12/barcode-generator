"""The four items a pack carries, each with its own symbol.

A pack is not one barcode. It is several, and they are not interchangeable:

* **Trigger** -- the trigger solution bottle. A short free text code, printed
  vertically on the bottle, read by the instrument's fixed reader.
* **Method** -- the assay method. A QR code from the manufacturer's sheet, scanned
  once into the software. Its content is opaque text; nothing here interprets it.
* **Package** -- the outer box. A QR code on the carton.
* **Reagent** -- the cartridge inside. A short code on the label wrapped round the
  cartridge.

Both short codes are Code 128 Subset B in practice (the payload contains lower
case and ``+``/``/``), and both QR items are plain text. Nothing in this module
derives one from another or reads meaning into any of them.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

import segno

from . import code128, render


class Kind(str, enum.Enum):
    """Which of the four items a symbol belongs to."""

    TRIGGER = "trigger"
    METHOD = "method"
    PACKAGE = "package"
    REAGENT = "reagent"

    @property
    def symbology(self) -> str:
        return "QR" if self.is_two_dimensional else "Code 128"

    @property
    def is_two_dimensional(self) -> bool:
        return self in (Kind.METHOD, Kind.PACKAGE)

    @property
    def title(self) -> str:
        return {
            Kind.TRIGGER: "Trigger",
            Kind.METHOD: "Method",
            Kind.PACKAGE: "Package",
            Kind.REAGENT: "Reagent",
        }[self]

    @property
    def default_length(self) -> int:
        # Trigger codes on real bottles are ten characters, cartridge codes nine.
        return 10 if self is Kind.TRIGGER else 9


class KindError(ValueError):
    """Raised when a payload cannot be drawn for the requested kind."""


@dataclass(frozen=True)
class Item:
    """One symbol to print: what it is, and the exact text it must carry."""

    kind: Kind
    text: str
    note: str = ""

    def validate(self) -> None:
        if not self.text:
            raise KindError(f"{self.kind.title}: the text is empty")
        if self.kind.is_two_dimensional:
            if not self.text.isprintable():
                raise KindError(
                    f"{self.kind.title}: the text contains characters a QR cannot carry"
                )
            return
        try:
            code128.module_count(self.text)
        except code128.Code128Error as exc:
            raise KindError(f"{self.kind.title}: {exc}") from exc


def qr_matrix(text: str, *, error: str = "m") -> list[list[bool]]:
    """Return a full QR symbol as rows of booleans, dark being True.

    ``micro=False`` matters: segno would otherwise pick a Micro QR for short
    text, and many fixed-mount readers do not decode Micro QR at all.
    """
    if not text:
        raise KindError("cannot encode empty text as QR")
    symbol = segno.make(text, error=error, micro=False, boost_error=False)
    return [[bool(cell) for cell in row] for row in symbol.matrix]


def qr_modules(text: str, *, error: str = "m") -> int:
    """Side length of the QR symbol in modules, excluding the quiet zone."""
    matrix = qr_matrix(text, error=error)
    return len(matrix)


def qr_quiet_modules() -> int:
    """Quiet zone required round a QR symbol, in modules (ISO/IEC 18004)."""
    return 4


def draw_qr(
    c,
    text: str,
    *,
    x_mm: float,
    y_mm: float,
    module_dots: int,
    dpi: int,
    error: str = "m",
) -> int:
    """Draw a QR symbol, one module = ``module_dots`` printer dots.

    Returns the side length in modules (quiet zone included) so the caller can
    lay out the next item without guessing.
    """
    if module_dots < 1:
        raise KindError("module size must be at least one printer dot")

    from reportlab.pdfgen import canvas as pdfcanvas  # noqa: F401  (typing only)

    matrix = qr_matrix(text, error=error)
    side = len(matrix)
    quiet = qr_quiet_modules()
    total = side + 2 * quiet

    dot_pt = render.mm_to_points(render.dot_mm(dpi))
    x_pt = round(render.mm_to_points(render.snap_to_dot(x_mm, dpi)) / dot_pt) * dot_pt
    page_h = render.page_height_mm(c)
    top_pt = round(render.mm_to_points(page_h - render.snap_to_dot(y_mm, dpi)) / dot_pt) * dot_pt

    c.saveState()
    c.setFillColorRGB(0, 0, 0)
    for row_index, row in enumerate(matrix):
        for column_index, dark in enumerate(row):
            if not dark:
                continue
            px = x_pt + (quiet + column_index) * module_dots * dot_pt
            py = top_pt - (quiet + row_index + 1) * module_dots * dot_pt
            c.rect(
                px,
                py,
                module_dots * dot_pt,
                module_dots * dot_pt,
                stroke=0,
                fill=1,
            )
    c.restoreState()
    return total


def qr_size_mm(text: str, module_dots: int, dpi: int, *, error: str = "m") -> float:
    """Printed side of a QR symbol including its quiet zone, in millimetres."""
    modules = qr_modules(text, error=error) + 2 * qr_quiet_modules()
    return modules * module_dots * render.dot_mm(dpi)


def qr_module_dots_for(
    text: str, target_mm: float, dpi: int, *, error: str = "m"
) -> int:
    """Largest whole-dot module size whose QR fits ``target_mm``."""
    if target_mm <= 0:
        raise KindError("target size must be positive")
    modules = qr_modules(text, error=error) + 2 * qr_quiet_modules()
    per_module = target_mm / modules
    dots = int(per_module / render.dot_mm(dpi))
    if dots < 1:
        raise KindError(
            f"{target_mm:.1f} mm is too small for a {qr_modules(text, error=error)}x"
            f"{qr_modules(text, error=error)} QR at {dpi} dpi; "
            f"it needs at least {modules * render.dot_mm(dpi):.1f} mm"
        )
    return dots


def describe(item: Item, *, dpi: int, width_mm: float) -> str:
    """One line summarising what will be printed, for logs and the UI."""
    item.validate()
    if item.kind.is_two_dimensional:
        dots = qr_module_dots_for(item.text, width_mm, dpi)
        side = qr_size_mm(item.text, dots, dpi)
        return (
            f"{item.kind.title}: QR {qr_modules(item.text)}x{qr_modules(item.text)}, "
            f"module {dots} dots = {dots * render.dot_mm(dpi):.3f} mm, "
            f"{side:.1f} mm square"
        )
    dots = render.module_dots_for_width(item.text, width_mm, dpi)
    geo = render.geometry(item.text, dots, dpi)
    return (
        f"{item.kind.title}: Code 128, {geo.modules} modules, "
        f"module {dots} dots = {geo.x_mm:.3f} mm, {geo.total_mm:.1f} mm wide"
    )
