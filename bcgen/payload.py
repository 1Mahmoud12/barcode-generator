"""Reproduce a long QR payload exactly as it was scanned.

Some pack QR codes carry a lot of data -- the calibration reagent code is 712
characters and encodes as a 105x105 symbol. Redrawing one is a *reproduction*
task: the text must come out byte for byte identical, or the analyzer reads
different numbers.

The rule this module enforces is the same one used for short codes: the caller
supplies the text, and the module proves the symbol round-trips. It never builds
a payload and never interprets one.

A structural reader is also provided, but only to *show* an operator what the
scanned text contains -- so they can confirm they scanned the right carton before
reprinting it. Nothing is derived from it and nothing is written back into it.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass

from . import kind
from .kind import KindError


class PayloadError(ValueError):
    """Raised when a payload is not what it claims to be."""


def looks_like_base64(text: str) -> bool:
    """True when the text decodes as standard base64 and re-encodes identically."""
    stripped = text.strip()
    if not stripped or len(stripped) % 4 != 0:
        return False
    if not all(c.isalnum() or c in "+/=" for c in stripped):
        return False
    try:
        raw = base64.b64decode(stripped, validate=True)
    except (binascii.Error, ValueError):
        return False
    return base64.b64encode(raw).decode() == stripped


def unbase64(text: str) -> str:
    """Decode base64 to text, keeping it readable rather than failing on oddities."""
    stripped = text.strip()
    try:
        raw = base64.b64decode(stripped, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PayloadError(f"not valid base64: {exc}") from exc
    return raw.decode("utf-8", errors="replace")


def reencode(text: str) -> str:
    """Re-encode decoded text back to base64, exactly as the pack carries it."""
    return base64.b64encode(text.encode("utf-8")).decode()


@dataclass(frozen=True)
class RoundTrip:
    """Proof that a payload survives encoding and decoding unchanged."""

    payload: str
    decoded: str
    reencoded: str

    @property
    def exact(self) -> bool:
        return self.reencoded == self.payload

    def describe(self) -> str:
        if self.exact:
            return (
                f"payload {len(self.payload)} characters, round-trips exactly "
                f"({len(self.decoded)} characters decoded)"
            )
        return "round trip FAILED - the payload would not reprint identically"


def round_trip(payload: str) -> RoundTrip:
    """Check that base64 decoding and re-encoding returns the original text."""
    decoded = unbase64(payload)
    return RoundTrip(payload=payload, decoded=decoded, reencoded=reencode(decoded))


@dataclass(frozen=True)
class Structure:
    """What the scanned text appears to contain, shown for confirmation only."""

    header: list[str]
    sections: list[str]

    @property
    def lot(self) -> str:
        return self.header[3] if len(self.header) > 3 else ""

    @property
    def expiry(self) -> str:
        return self.header[4] if len(self.header) > 4 else ""

    @property
    def assay_code(self) -> str:
        return self.header[1] if len(self.header) > 1 else ""

    @property
    def identifier(self) -> str:
        return self.header[2] if len(self.header) > 2 else ""

    def summary(self) -> list[str]:
        lines = [
            f"header fields: {len(self.header)}",
            f"assay code: {self.assay_code}",
            f"identifier: {self.identifier}",
            f"lot: {self.lot}",
            f"expiry: {self.expiry}",
            f"sections: {len(self.sections)}",
        ]
        return lines


def structure(payload: str) -> Structure:
    """Split the decoded text into its obvious top-level parts.

    The separators (``,`` inside the header, ``$`` between sections, ``|`` inside
    a section) are what the manufacturer used. They are displayed so an operator
    can compare against the printed label; no field is given a meaning here.
    """
    decoded = unbase64(payload) if looks_like_base64(payload) else payload
    chunks = decoded.split("$")
    header = chunks[0].split(",") if chunks else []
    return Structure(header=header, sections=chunks[1:])


def check_reproducible(payload: str) -> list[str]:
    """Return a list of problems that would stop this payload from reprinting.

    Empty list means it is safe to draw: it is base64-clean, round-trips, and fits
    in a QR at error correction level M.
    """
    problems: list[str] = []
    if not payload.strip():
        problems.append("the payload is empty")
        return problems

    if looks_like_base64(payload):
        if not round_trip(payload).exact:
            problems.append("base64 round trip does not reproduce the original text")
    elif not payload.isprintable():
        problems.append("the payload contains control characters a QR cannot carry")

    try:
        kind.qr_modules(payload)
    except KindError as exc:
        problems.append(str(exc))

    return problems


def min_square_mm(payload: str, dpi: int, module_dots: int = 2) -> float:
    """Smallest printed side that still gives ``module_dots`` per module."""
    modules = kind.qr_modules(payload) + 2 * kind.qr_quiet_modules()
    from . import render

    return modules * module_dots * render.dot_mm(dpi)
