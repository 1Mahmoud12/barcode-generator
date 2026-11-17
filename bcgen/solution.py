"""The solution bottles: Trigger and Pre-Trigger.

These are not the same as the reagent cartridge. Their codes are **ten
characters**, not nine, and they carry no calibration curve -- the payload is six
bytes: an item identifier, a lot reference and a bottle serial. So a Trigger label
is a plain Code 128 plus human-readable data, and nothing on it needs the analyzer
to interpret a curve.

A bottle label also carries a separate **GS1 DataMatrix** with the GTIN,
production date, expiry and lot. That is the traceability code, read by a
different reader than the instrument. It is built with zint because GS1 requires a
real FNC1 and the pure-Python DataMatrix encoders do not emit one.

What this module does with the size (200/450/800 mL): it prints it as text. It
does **not** encode the size into the barcode, because the payload of a real
bottle code is already fixed by the manufacturer's scheme and injecting a size
would produce a code the instrument does not recognise.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from . import code128, kind, render

SOLUTION_KINDS = ("trigger", "pretrigger")

# Bottle sizes seen on the real packs.
STANDARD_VOLUMES_ML = (200, 450, 800)

# A Code 128 payload for these bottles is ten characters, which is 145 modules.
# Anything much longer will not fit a bottle label comfortably.
EXPECTED_CODE_LENGTH = 10


class SolutionError(ValueError):
    """Raised when a solution label cannot be built as asked."""


@dataclass
class SolutionLabel:
    """Everything printed on a Trigger or Pre-Trigger bottle label."""

    kind: str = "trigger"
    code: str = ""
    volume_ml: int = 450
    lot: str = ""
    produced: str = ""
    expiry: str = ""
    product: str = ""
    storage: str = "Store at 2-8 C"
    gtin: str = ""
    internal: str = ""
    notes: str = ""
    copies: int = 1

    def validate(self) -> None:
        if self.kind not in SOLUTION_KINDS:
            raise SolutionError(f"kind must be one of {SOLUTION_KINDS}, got {self.kind!r}")

        if not self.code.strip():
            raise SolutionError("the barcode text is empty")
        try:
            code128.module_count(self.code)
        except code128.Code128Error as exc:
            raise SolutionError(f"barcode text cannot be encoded: {exc}") from exc
        if len(self.code) != EXPECTED_CODE_LENGTH:
            raise SolutionError(
                f"a bottle code is {EXPECTED_CODE_LENGTH} characters on the real packs; "
                f"this one is {len(self.code)}. Check it was scanned, not retyped."
            )

        if self.volume_ml <= 0:
            raise SolutionError("volume must be a positive number of mL")

        if self.gtin and not re.fullmatch(r"\d{14}", self.gtin):
            raise SolutionError(
                "the GTIN must be exactly 14 digits (pad the 13-digit form with a "
                "leading zero)"
            )

        if not self.lot.strip():
            raise SolutionError("the lot is required: it is what links the bottle to a batch")

        if not self.expiry.strip():
            raise SolutionError("the expiry is required")

        for name, value in (
            ("product", self.product),
            ("notes", self.notes),
            ("lot", self.lot),
        ):
            if not value.isascii():
                raise SolutionError(f"{name} must be Latin characters only")

        if self.copies < 1:
            raise SolutionError("copies must be at least 1")

    # -- derived text ---------------------------------------------------

    @property
    def volume_text(self) -> str:
        return f"{self.volume_ml} mL"

    def kind_title(self) -> str:
        return "Trigger" if self.kind == "trigger" else "Pre-Trigger"

    def gs1_elements(self) -> list[tuple[str, str]]:
        """GS1 application identifiers, in the order they appear on the label.

        (01) GTIN, (11) production date, (17) expiry, (10) lot, (91) internal.
        Dates must be YYMMDD in the symbol, while the label prints them in full.
        """
        elements: list[tuple[str, str]] = []
        if self.gtin:
            elements.append(("01", self.gtin))
        if self.produced:
            elements.append(("11", to_gs1_date(self.produced)))
        if self.expiry:
            elements.append(("17", to_gs1_date(self.expiry)))
        elements.append(("10", self.lot))
        if self.internal:
            elements.append(("91", self.internal))
        return elements

    def gs1_string(self) -> str:
        """The bracketed form zint understands, e.g. ``[01]0692...[10]20251101``."""
        return "".join(f"[{ai}]{value}" for ai, value in self.gs1_elements())

    def human_gs1_lines(self) -> list[str]:
        """What a person reads: the AI in brackets, then the value."""
        return [f"({ai}) {value}" for ai, value in self.gs1_elements()]


def to_gs1_date(text: str) -> str:
    """YYYY-MM-DD or YYYYMMDD to the YYMMDD a GS1 symbol requires."""
    stripped = text.strip()
    if re.fullmatch(r"\d{6}", stripped):
        return stripped
    for pattern in ("%Y-%m-%d", "%Y%m%d", "%d-%m-%Y"):
        try:
            parsed = datetime.strptime(stripped, pattern).date()
        except ValueError:
            continue
        return parsed.strftime("%y%m%d")
    raise SolutionError(
        f"cannot read {text!r} as a date; use YYYY-MM-DD or YYYYMMDD"
    )


def zint_available() -> bool:
    return shutil.which("zint") is not None


def gs1_datamatrix_png(label: SolutionLabel, *, scale: int = 4) -> str:
    """Render the GS1 DataMatrix to a temporary PNG and return its path.

    zint is used because GS1 needs a real FNC1 immediately after the start
    character; encoders that just concatenate the digits produce a symbol that
    looks right and scans wrong -- the reader returns the AI names as literal text
    instead of parsing them.
    """
    if not zint_available():
        raise SolutionError(
            "zint is not installed. Install it with 'brew install zint' (macOS) or "
            "'choco install zint' (Windows). It is required for GS1 DataMatrix "
            "because the pure-Python encoders cannot emit FNC1."
        )

    payload = label.gs1_string()
    if not payload:
        raise SolutionError("no GS1 elements to encode")

    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    handle.close()
    path = handle.name

    command = [
        "zint",
        "--barcode=DATAMATRIX",
        "--gs1",
        "--quietzones",
        f"--scale={scale}",
        "--filetype=PNG",
        "-d", payload,
        "-o", path,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SolutionError(f"zint failed: {result.stderr.strip() or 'unknown error'}")
    return path


def verify_datamatrix(path: str, label: SolutionLabel) -> list[str]:
    """Read the PNG back and report any element that did not survive.

    A GS1 symbol is easy to get subtly wrong, so the built file is decoded and
    compared element by element rather than trusted.
    """
    try:
        import zxingcpp
        from PIL import Image
    except ImportError:
        return []

    problems: list[str] = []
    image = Image.open(path)
    results = zxingcpp.read_barcodes(image)
    if not results:
        return ["the GS1 DataMatrix did not decode at all"]

    found = results[0]
    symbol = found.bytes if getattr(found, "bytes", None) else b""
    text = "".join(chr(b) for b in symbol) if symbol else found.text

    # FNC1 appears as GS (0x1D) before a variable-length field; compare digits only.
    for ai, value in label.gs1_elements():
        token = f"{ai}{value}"
        if token not in text:
            problems.append(f"AI {ai} with value {value!r} is not in the decoded symbol")
    return problems


@dataclass(frozen=True)
class SolutionLayout:
    width_mm: float
    height_mm: float
    bar_height_mm: float
    title_pt: float
    text_pt: float


def draw_solution_label(
    c,
    label: SolutionLabel,
    *,
    x_mm: float,
    y_mm: float,
    layout: SolutionLayout,
    dpi: int,
    datamatrix_png: str | None = None,
) -> render.Geometry:
    """Draw one bottle label: title, size, code, then the data rows."""
    label.validate()

    inner_x = x_mm + 2.0
    inner_w = layout.width_mm - 4.0
    cursor = y_mm + 2.5

    # Title: what the bottle is, and how much it holds.
    render.draw_text(
        c,
        f"{label.kind_title()}  {label.volume_text}",
        x_mm=inner_x,
        y_mm=cursor,
        size_pt=layout.title_pt,
        bold=True,
    )
    cursor += layout.title_pt * 0.62

    # Barcode, sized to the label width.
    geo = render.geometry_for_width(label.code, inner_w, dpi)
    render.draw_symbol(
        c,
        label.code,
        x_mm=inner_x,
        y_mm=cursor,
        module_dots=geo.module_dots,
        dpi=dpi,
        height_mm=layout.bar_height_mm,
    )
    cursor += layout.bar_height_mm + 2.0

    render.draw_text_centered(
        c,
        label.code,
        center_x_mm=x_mm + layout.width_mm / 2,
        y_mm=cursor,
        size_pt=layout.text_pt + 0.5,
        bold=True,
    )
    cursor += (layout.text_pt + 0.5) * 0.62 + 0.5

    rows = [f"LOT {label.lot}", f"EXP {label.expiry}"]
    if label.produced:
        rows.append(f"MFG {label.produced}")
    if label.storage:
        rows.append(label.storage)
    if label.notes:
        rows.append(label.notes)

    for row in rows:
        render.draw_text(c, row, x_mm=inner_x, y_mm=cursor, size_pt=layout.text_pt)
        cursor += layout.text_pt * 0.62

    # The GS1 traceability square, on the right of the data block.
    if datamatrix_png:
        side_mm = min(15.0, layout.width_mm * 0.35)
        c.saveState()
        c.drawImage(
            datamatrix_png,
            render.mm_to_points(x_mm + layout.width_mm - side_mm - 2.0),
            render.mm_to_points(render.page_height_mm(c) - (y_mm + layout.height_mm - 0.5)),
            width=render.mm_to_points(side_mm),
            height=render.mm_to_points(side_mm),
            preserveAspectRatio=True,
            anchor="sw",
        )
        c.restoreState()

    return geo


def auto_layout(code: str, width_mm: float, height_mm: float, dpi: int) -> SolutionLayout:
    """Pick a bar height and text size that fit the label."""
    for title_pt in (9.0, 8.5, 8.0, 7.5):
        for text_pt in (7.0, 6.5, 6.0, 5.5, 5.0):
            for bar_mm in (14.0, 12.0, 11.0, 10.0, 9.0, 8.0, 7.0):
                fixed = 2.5 + title_pt * 0.62 + 2.0 + (text_pt + 0.5) * 0.62 + 0.5
                rows = 4
                needed = fixed + bar_mm + rows * text_pt * 0.62 + 2.0
                if needed <= height_mm:
                    return SolutionLayout(
                        width_mm=width_mm,
                        height_mm=height_mm,
                        bar_height_mm=bar_mm,
                        title_pt=title_pt,
                        text_pt=text_pt,
                    )
    raise SolutionError(
        f"a {width_mm:.0f}x{height_mm:.0f} mm label is too small for this data at "
        f"{dpi} dpi; use a taller label"
    )


def build_solution_sheet(
    path: str,
    labels: list[SolutionLabel],
    *,
    page_width_mm: float = 210.0,
    page_height_mm: float = 297.0,
    label_width_mm: float = 90.0,
    label_height_mm: float = 45.0,
    dpi: int = 300,
    with_datamatrix: bool = True,
    gap_mm: float = 4.0,
    cut_lines: bool = True,
    title: str = "Solution bottle labels",
) -> list[str]:
    """Lay the bottle labels on sheets and return any verification problems."""
    if not labels:
        raise SolutionError("no labels to print")

    from reportlab.pdfgen import canvas as pdfcanvas

    problems: list[str] = []
    expanded: list[SolutionLabel] = []
    for label in labels:
        label.validate()
        expanded.extend([label] * label.copies)

    # One code belongs to one bottle. The same code on a 200 mL and an 800 mL
    # bottle would make the register unable to say which was filled, and the two
    # sizes need different GTINs anyway.
    seen_codes: dict[str, SolutionLabel] = {}
    for label in labels:
        existing = seen_codes.get(label.code)
        if existing is not None:
            problems.append(
                f"the code {label.code!r} is used twice: "
                f"{existing.kind_title()} {existing.volume_text} and "
                f"{label.kind_title()} {label.volume_text}. Each bottle has its own code."
            )
        else:
            seen_codes[label.code] = label

    # One GTIN belongs to one size. Sharing a GTIN across sizes means a reader
    # cannot tell a 200 mL from an 800 mL.
    gtin_sizes: dict[str, set[int]] = {}
    for label in labels:
        if label.gtin:
            gtin_sizes.setdefault(label.gtin, set()).add(label.volume_ml)
    for gtin, sizes in gtin_sizes.items():
        if len(sizes) > 1:
            problems.append(
                f"the GTIN {gtin} is used for sizes "
                f"{', '.join(str(s) for s in sorted(sizes))} mL. Each size needs its "
                f"own GTIN, or a reader cannot tell them apart."
            )

    png_paths: dict[int, str] = {}
    if with_datamatrix:
        if not zint_available():
            raise SolutionError(
                "zint is required for the GS1 DataMatrix. Install it, or build with "
                "with_datamatrix=False to print only the Code 128."
            )
        for index, label in enumerate(labels):
            png_paths[index] = gs1_datamatrix_png(label)
            problems.extend(verify_datamatrix(png_paths[index], label))

    c = pdfcanvas.Canvas(
        path,
        pagesize=(render.mm_to_points(page_width_mm), render.mm_to_points(page_height_mm)),
    )
    c.setTitle(title)

    per_row = max(1, int((page_width_mm - gap_mm) // (label_width_mm + gap_mm)))
    per_col = max(1, int((page_height_mm - gap_mm) // (label_height_mm + gap_mm)))
    per_page = per_row * per_col

    cursor_index = 0
    for label_index, label in enumerate(labels):
        layout = auto_layout(label.code, label_width_mm, label_height_mm, dpi)
        for _ in range(label.copies):
            slot = cursor_index % per_page
            if slot == 0:
                if cursor_index > 0:
                    c.showPage()
                render.draw_text(
                    c, title, x_mm=gap_mm, y_mm=gap_mm + 3.0, size_pt=8, bold=True, grey=0.4
                )
            row, column = divmod(slot, per_row)
            x_mm = gap_mm + column * (label_width_mm + gap_mm)
            y_mm = gap_mm + 6.0 + row * (label_height_mm + gap_mm)

            draw_solution_label(
                c,
                label,
                x_mm=x_mm,
                y_mm=y_mm,
                layout=layout,
                dpi=dpi,
                datamatrix_png=png_paths.get(label_index),
            )
            if cut_lines:
                render.draw_rect(
                    c,
                    x_mm=x_mm,
                    y_mm=y_mm,
                    width_mm=label_width_mm,
                    height_mm=label_height_mm,
                    thickness_pt=0.25,
                    grey=0.8,
                    dash=(1.5, 2),
                )
            cursor_index += 1

    c.showPage()
    c.save()

    for png in png_paths.values():
        Path(png).unlink(missing_ok=True)

    return problems
