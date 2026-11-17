"""Code 128 Subset B encoder, written from the canonical element-width table.

The encoder works in *modules* only. Converting modules to device dots is the
job of the renderer, so that every bar width can be forced to a whole number of
printer dots.

Reference: ISO/IEC 15417. Each symbol is 11 modules made of 6 elements
(bar, space, bar, space, bar, space) whose widths sum to 11. The stop symbol
is 13 modules made of 7 elements.
"""

from __future__ import annotations

# Value -> six element widths (bar first). Values 0..102 are data characters,
# 103..105 are Start A/B/C, 106 is the stop symbol.
ELEMENT_WIDTHS: tuple[str, ...] = (
    "212222", "222122", "222221", "121223", "121322", "131222",
    "122213", "122312", "132212", "221213", "221312", "231212",
    "112232", "122132", "122231", "113222", "123122", "123221",
    "223211", "221132", "221231", "213212", "223112", "312131",
    "311222", "321122", "321221", "312212", "322112", "322211",
    "212123", "212321", "232121", "111323", "131123", "131321",
    "112313", "132113", "132311", "211313", "231113", "231311",
    "112133", "112331", "132131", "113123", "113321", "133121",
    "313121", "211331", "231131", "213113", "213311", "213131",
    "311123", "311321", "331121", "312113", "312311", "332111",
    "314111", "221411", "431111", "111224", "111422", "121124",
    "121421", "141122", "141221", "112214", "112412", "122114",
    "122411", "142112", "142211", "241211", "221114", "413111",
    "241112", "134111", "111242", "121142", "121241", "114212",
    "124112", "124211", "411212", "421112", "421211", "212141",
    "214121", "412121", "111143", "111341", "131141", "114113",
    "114311", "411113", "411311", "113141", "114131", "311141",
    "411131", "211412", "211214", "211232", "2331112",
)

START_A = 103
START_B = 104
START_C = 105
STOP = 106

# Subset B covers ASCII 32..126, mapped to values 0..94.
_SUBSET_B_FIRST = 32
_SUBSET_B_LAST = 126


class Code128Error(ValueError):
    """Raised when the text cannot be carried by Code 128 Subset B."""


def _subset_b_value(char: str) -> int:
    code = ord(char)
    if not _SUBSET_B_FIRST <= code <= _SUBSET_B_LAST:
        raise Code128Error(
            f"character {char!r} (U+{code:04X}) is outside Code 128 Subset B "
            f"(printable ASCII 32..126)"
        )
    return code - _SUBSET_B_FIRST


def _pattern_to_runs(pattern: str) -> list[tuple[int, int]]:
    """Turn a module pattern like '212222' into [(width_modules, is_bar), ...]."""
    runs: list[tuple[int, int]] = []
    is_bar = 1
    for digit in pattern:
        runs.append((int(digit), is_bar))
        is_bar ^= 1
    return runs


def modules(text: str) -> str:
    """Return the full symbol as a string of '1' (bar) and '0' (space) modules."""
    if not text:
        raise Code128Error("empty text")

    values = [START_B] + [_subset_b_value(ch) for ch in text]

    # Checksum: start value plus each data value weighted by its 1-based position.
    checksum = values[0]
    for position, value in enumerate(values[1:], start=1):
        checksum += position * value
    checksum %= 103
    values.append(checksum)
    values.append(STOP)

    bits: list[str] = []
    for value in values:
        pattern = ELEMENT_WIDTHS[value]
        for width, is_bar in _pattern_to_runs(pattern):
            bits.append(("1" if is_bar else "0") * width)
    return "".join(bits)


def bars(text: str, module_dots: int = 1) -> list[tuple[int, int]]:
    """Return the symbol as [(start_dot, width_dots), ...] for the bars only.

    ``module_dots`` is how many device dots one module occupies. Because every
    module becomes the same whole number of dots, all bars land on exact dot
    boundaries -- this is what keeps X-dimension uniform and printable.
    """
    if module_dots < 1:
        raise Code128Error("module_dots must be >= 1")

    runs: list[tuple[int, int]] = []
    offset_modules = 0
    for value in _symbol_values(text):
        for width_modules, is_bar in _pattern_to_runs(ELEMENT_WIDTHS[value]):
            if is_bar:
                runs.append((offset_modules * module_dots, width_modules * module_dots))
            offset_modules += width_modules
    return runs


def _symbol_values(text: str) -> list[int]:
    if not text:
        raise Code128Error("empty text")
    values = [START_B] + [_subset_b_value(ch) for ch in text]
    checksum = values[0]
    for position, value in enumerate(values[1:], start=1):
        checksum += position * value
    values.append(checksum % 103)
    values.append(STOP)
    return values


def module_count(text: str) -> int:
    """Total symbol width in modules (data + checksum + stop)."""
    return sum(sum(int(d) for d in ELEMENT_WIDTHS[v]) for v in _symbol_values(text))


def text_modules(text: str) -> int:
    """Width in modules of the bars only, excluding quiet zones."""
    return module_count(text)


def symbol_width_mm(text: str, x_mm: float) -> float:
    """Printed width in millimetres for a given X-dimension, quiet zones excluded."""
    return module_count(text) * x_mm
