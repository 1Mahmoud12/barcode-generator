"""Self-check: render, rasterise, decode, compare.

This is the part that makes a measurement trustworthy. If the PDF contains a
symbol that does not decode back to its own text, then a failed scan on the
analyzer tells us nothing -- it might be our printing, not the instrument.

Rasterising at the target dpi and decoding with zxing-cpp reproduces what an
imager sees. A mismatch is reported with the exact payload so it can be fixed
before anything is printed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import pypdfium2 as pdfium
import zxingcpp
from PIL import Image

from bcgen import code128, render, sheet
from bcgen.generate import TestCode


@dataclass(frozen=True)
class DecodeResult:
    payload: str
    expected: str
    decoded: str | None
    symbology: str

    @property
    def ok(self) -> bool:
        return self.decoded == self.expected


def decode_image(image: Image.Image) -> list[tuple[str, str]]:
    """Return [(text, format), ...] for every symbol found in the image."""
    results = zxingcpp.read_barcodes(image)
    return [(r.text, str(r.format).split(".")[-1]) for r in results]


def check_text(text: str, module_dots: int, dpi: int) -> DecodeResult:
    """Render a single symbol at the given size, decode it, compare."""
    geo = render.geometry(text, module_dots, dpi)
    img = Image.new("L", (geo.total_dots, int(dpi * 0.6)), 255)
    dot_px = module_dots
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    offset = render.QUIET_ZONE_MODULES * module_dots
    for start, width in code128.bars(text, module_dots):
        draw.rectangle(
            [offset + start, 0, offset + start + width - 1, img.height - 1], fill=0
        )
    found = decode_image(img)
    decoded = found[0][0] if found else None
    fmt = found[0][1] if found else "-"
    return DecodeResult(payload=text, expected=text, decoded=decoded, symbology=fmt)


def check_pdf(path: str, dpi: int) -> list[DecodeResult]:
    """Rasterise every page of the PDF at ``dpi`` and decode every symbol."""
    results: list[DecodeResult] = []
    doc = pdfium.PdfDocument(path)
    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            image = page.render(scale=dpi / 72).to_pil()
            for text, fmt in decode_image(image):
                results.append(
                    DecodeResult(payload=text, expected=text, decoded=text, symbology=fmt)
                )
    finally:
        doc.close()
    return results


def run_default_checks() -> int:
    """Entry point used by ``python selftest.py``. Returns a process exit code."""
    dpi_values = (300, 600)
    payloads = [
        "iwUMArCYU",
        "CeXDgVBWA",
        "a+b/cDeFg",
        "AE_Check9",
        "000000000",
        "~!~!~!~!~",
        "         ",
    ]
    failures: list[str] = []

    print("encoder width check")
    for text in payloads:
        count = code128.module_count(text)
        expected = 11 + 11 * len(text) + 11 + 13
        status = "ok" if count == expected else "MISMATCH"
        print(f"  {text!r:14} modules={count:3d} expected={expected:3d} {status}")
        if count != expected:
            failures.append(f"{text!r}: {count} modules, expected {expected}")

    print("\nround-trip decode check")
    for dpi in dpi_values:
        for dots in (3, 4, 5, 6, 8):
            for text in payloads:
                result = check_text(text, dots, dpi)
                flag = "ok" if result.ok else "FAIL"
                if not result.ok:
                    failures.append(
                        f"{text!r} at {dots} dots/{dpi} dpi decoded {result.decoded!r}"
                    )
                print(
                    f"  {dpi} dpi {dots} dots  {text!r:12} -> "
                    f"{result.decoded!r:12} {result.symbology:8} {flag}"
                )

    print("\nelement width uniformity check")
    from PIL import Image, ImageDraw

    from bcgen import measure

    for dots in (3, 4, 5, 6, 8, 10):
        for text in ("AE_Check9", "iwUMArCYU", "         "):
            geo = render.geometry(text, dots, 600)
            img = Image.new("L", (geo.total_dots, 120), 255)
            draw = ImageDraw.Draw(img)
            offset = render.QUIET_ZONE_MODULES * dots
            for start, width in code128.bars(text, dots):
                draw.rectangle([offset + start, 0, offset + start + width - 1, 119], fill=0)
            stats = measure.measure_symbol(img, text=text, module_dots=dots)
            flag = "ok" if stats.uniform else "UNEVEN"
            print(f"  {dots} dots {text!r:12} widths={stats.distinct} {flag}")
            if not stats.uniform:
                failures.append(f"{text!r} at {dots} dots has uneven element widths")

    print("\nsheet build and decode check")
    codes = [TestCode(t, f"t{i}") for i, t in enumerate(payloads)]
    for dpi in dpi_values:
        path = f"/tmp/selftest-sheet-{dpi}.pdf"
        plans = sheet.build_sheet(
            path,
            codes,
            rungs=[3, 4, 5, 6, 8, 10],
            dpi=dpi,
            title="Self-check sheet",
        )
        decoded = [r.decoded for r in check_pdf(path, dpi)]
        cell_count = sum(len(p.cells) for p in plans)
        stray = [d for d in decoded if d not in {c.code.text for p in plans for c in p.cells}]
        print(
            f"  {dpi} dpi: {len(plans)} pages, {cell_count} cells, "
            f"{len(decoded)} symbols decoded, {len(stray)} stray"
        )
        if len(decoded) != cell_count:
            failures.append(
                f"{dpi} dpi: decoded {len(decoded)} symbols but printed {cell_count} cells"
            )
        for stray_text in stray:
            failures.append(f"{dpi} dpi: stray reading {stray_text!r}")
        for plan in plans:
            for cell in plan.cells:
                if cell.code.text not in decoded:
                    failures.append(
                        f"{dpi} dpi page {plan.module_dots}dot: {cell.code.text!r} did not decode"
                    )

    print()
    if failures:
        print(f"FAILED - {len(failures)} problem(s)")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run_default_checks())
