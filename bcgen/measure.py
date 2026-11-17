"""Measure the printed symbol itself, straight from the rendered page.

Decoding tells us "the scanner could read it". This module answers a different
question: "did every module really get the same width on paper?" A symbol can
decode while still having uneven bars -- that is exactly the condition that
fails later on a different printer or at a different angle.

The measurement works by rasterising a page at the printer resolution and
reading the run lengths of dark and light pixels along one scan line.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

import pypdfium2 as pdfium
from PIL import Image

from bcgen import code128


@dataclass(frozen=True)
class RunStats:
    """Width statistics for the modules inside one symbol."""

    modules: int
    bars: int
    widths: list[int]
    expected_module_dots: int

    @property
    def distinct(self) -> list[int]:
        return sorted(set(self.widths))

    @property
    def uniform(self) -> bool:
        """True when every element width is a whole multiple of one module width."""
        if not self.widths:
            return False
        unit = self.expected_module_dots
        return all(w % unit == 0 for w in self.widths)

    @property
    def module_estimate(self) -> float:
        return statistics.median(self.widths) if self.widths else 0.0

    def describe(self) -> str:
        return (
            f"{self.bars} bars, widths in dots {self.distinct}, "
            f"module={self.expected_module_dots} dots, "
            f"all multiples: {'yes' if self.uniform else 'NO'}"
        )


def _row_profile(image: Image.Image, y: int) -> list[tuple[int, int]]:
    """Run-length encode one scan line as [(width, is_dark), ...]."""
    grey = image.convert("L")
    width, _ = grey.size
    pixels = grey.load()

    runs: list[tuple[int, int]] = []
    current_dark = pixels[0, y] < 128
    count = 0
    for x in range(width):
        is_dark = pixels[x, y] < 128
        if is_dark == current_dark:
            count += 1
        else:
            runs.append((count, int(current_dark)))
            current_dark = is_dark
            count = 1
    runs.append((count, int(current_dark)))
    return runs


def measure_symbol(
    image: Image.Image,
    *,
    text: str,
    module_dots: int,
    quiet_modules: int = 10,
) -> RunStats:
    """Measure element widths of the symbol in ``image``.

    The image must contain exactly one symbol with its quiet zones, rendered at
    one dot per printer dot.
    """
    width, height = image.size
    y = height // 2
    runs = _row_profile(image, y)

    # Strip leading and trailing white; anything left is the symbol.
    while runs and runs[0][1] == 0:
        runs.pop(0)
    while runs and runs[-1][1] == 0:
        runs.pop()
    if not runs:
        raise ValueError("no dark run found in scan line")

    widths = [w for w, _ in runs]
    bars = sum(1 for _, dark in runs if dark)
    return RunStats(
        modules=code128.module_count(text),
        bars=bars,
        widths=widths,
        expected_module_dots=module_dots,
    )


def measure_page(
    path: str,
    page_index: int,
    *,
    expected_module_dots: int,
    dpi: int,
) -> list[tuple[int, int, int, int]]:
    """Return candidate bar clusters on a page as (x, y, w, h) boxes.

    Used only for diagnostics: shows how many separate dark regions the page
    contains so a mis-laid-out page is obvious.
    """
    doc = pdfium.PdfDocument(path)
    try:
        page = doc[page_index]
        image = page.render(scale=1.0).to_pil()
    finally:
        doc.close()
    return _components(image)


def _components(image: Image.Image) -> list[tuple[int, int, int, int]]:
    grey = image.convert("L")
    width, height = grey.size
    pixels = grey.load()
    seen = bytearray(width * height)
    boxes: list[tuple[int, int, int, int]] = []

    for sy in range(height):
        for sx in range(width):
            idx = sy * width + sx
            if seen[idx] or pixels[sx, sy] >= 128:
                continue
            stack = [(sx, sy)]
            seen[idx] = 1
            minx = maxx = sx
            miny = maxy = sy
            size = 0
            while stack:
                x, y = stack.pop()
                size += 1
                if x < minx:
                    minx = x
                if x > maxx:
                    maxx = x
                if y < miny:
                    miny = y
                if y > maxy:
                    maxy = y
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < width and 0 <= ny < height:
                        nidx = ny * width + nx
                        if not seen[nidx] and pixels[nx, ny] < 128:
                            seen[nidx] = 1
                            stack.append((nx, ny))
            if size > 40:
                boxes.append((minx, miny, maxx - minx + 1, maxy - miny + 1))
    return boxes
