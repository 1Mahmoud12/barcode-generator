"""Generate test codes that are valid Code 128 payloads but carry no meaning.

This module exists so that a scanner can be measured without touching any real
pack data. Codes are built from an explicit alphabet and a seeded random source,
so a run is reproducible and every code is known to be synthetic.

The generator deliberately does NOT model any manufacturer's encoding.  The
produced strings have the same *shape* as the codes on real packs (nine
characters drawn from the Code 128 Subset B alphabet) so that bar width, count
and density match -- nothing more.
"""

from __future__ import annotations

import random
import string
from dataclasses import dataclass

# Nine characters is what the packs carry; keeping the length equal keeps the
# module count equal, which is what the width measurements depend on.
DEFAULT_LENGTH = 9

UPPER = string.ascii_uppercase
LOWER = string.ascii_lowercase
DIGITS = string.digits
SYMBOLS = "+/"

ALPHABETS: dict[str, str] = {
    "mixed": UPPER + LOWER + DIGITS + SYMBOLS,
    "upper": UPPER + DIGITS,
    "lower": LOWER + DIGITS,
    "digits": DIGITS,
    "symbols": UPPER + LOWER + DIGITS + SYMBOLS,
}


class GenerationError(ValueError):
    """Raised when a request cannot be satisfied."""


@dataclass(frozen=True)
class TestCode:
    """One synthesized payload and the reason it was chosen."""

    text: str
    label: str

    def __str__(self) -> str:
        return self.text


def _validate(length: int, alphabet: str) -> None:
    if length < 1:
        raise GenerationError("length must be >= 1")
    if length * 11 + 35 > 60:
        # Not a hard limit of the symbology, just a guard: longer payloads stop
        # being comparable to the nine-character pack codes.
        pass
    if not alphabet:
        raise GenerationError("alphabet must not be empty")


def random_codes(
    count: int,
    *,
    length: int = DEFAULT_LENGTH,
    alphabet: str = "mixed",
    seed: int | None = 0,
    prefix: str = "",
) -> list[TestCode]:
    """Return ``count`` distinct synthetic codes drawn from ``alphabet``."""
    _validate(length, ALPHABETS.get(alphabet, alphabet))
    if count < 1:
        raise GenerationError("count must be >= 1")

    pool = ALPHABETS.get(alphabet, alphabet)
    if prefix:
        pool = ALPHABETS["mixed"]
    rng = random.Random(seed)

    seen: set[str] = set()
    out: list[TestCode] = []
    attempts = 0
    limit = count * 200 + 1000
    while len(out) < count and attempts < limit:
        attempts += 1
        body = "".join(rng.choice(pool) for _ in range(length - len(prefix)))
        text = prefix + body
        if text in seen:
            continue
        seen.add(text)
        out.append(TestCode(text, f"random-{len(out) + 1:03d}"))

    if len(out) < count:
        raise GenerationError(
            f"could not draw {count} distinct codes from a {len(pool)}-symbol alphabet"
        )
    return out


def all_lengths_code(length: int) -> TestCode:
    """A single code that exercises upper, lower, digit and symbol in one symbol."""
    if length < 4:
        raise GenerationError("length must be >= 4 to cover every class")
    body = ["A", "z", "5", "+"]
    rest = (UPPER + LOWER + DIGITS + SYMBOLS)
    body += [rest[i % len(rest)] for i in range(length - 4)]
    return TestCode("".join(body[:length]), "classes")


def sequential_codes(count: int, *, prefix: str = "T", width: int = 6) -> list[TestCode]:
    """Readable codes for labelling cells by hand: T000001, T000002, ..."""
    if count < 1:
        raise GenerationError("count must be >= 1")
    return [TestCode(f"{prefix}{i:0{width}d}", f"seq-{i:03d}") for i in range(1, count + 1)]


def edge_codes() -> list[TestCode]:
    """Payloads at the edges of Subset B, used to prove nothing is being adapted."""
    return [
        TestCode(" " * 9, "all-spaces"),
        TestCode("~" * 9, "all-tilde"),
        TestCode("!" * 9, "all-bang"),
        TestCode("+ + + + +", "mixed-symbols"),
        TestCode("000000000", "all-zeros"),
        TestCode("OOOOOOOOO", "lookalike-O"),
        TestCode("lllllllll", "lookalike-l"),
        TestCode("111111111", "lookalike-1"),
    ]
