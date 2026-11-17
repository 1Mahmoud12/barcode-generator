"""Keep a register of what was printed, so a mistake is found before the lab uses it.

Three things go wrong when labels are made by hand:

1. The wrong code is printed on a pack -- a cartridge carrying another lot's
   calibration.
2. Two different items end up sharing one code, so the instrument reads one and
   the record says another.
3. A label is reprinted long after the fact with no trace of who did it or from
   which source.

This module is a small, local, append-only register that answers those three. It
stores codes, lots and symbols -- never calibration curves, never patient data.

The register is deliberately boring: a CSV beside the program, one row per label,
readable in any spreadsheet, and diffable in git. If it ever becomes corrupt, the
worst outcome is a lost audit trail, not a wrong result.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .kind import Kind

FIELDS = (
    "timestamp",
    "event",
    "kind",
    "code",
    "code_sha",
    "length",
    "lot",
    "expiry",
    "product",
    "cells",
    "dpi",
    "source",
    "operator",
    "notes",
)


class RegisterError(ValueError):
    """Raised when an entry would break the register's guarantees."""


def code_fingerprint(code: str) -> str:
    """Short stable hash of a code, so the register never needs the raw secret.

    A calibration payload is long and sensitive. Storing its hash is enough to
    detect a change or a duplicate, and means a shared register file does not leak
    a manufacturer's data.
    """
    return hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]


@dataclass
class Entry:
    """One label event: printed, reprinted, or voided."""

    event: str
    kind: str
    code: str
    lot: str = ""
    expiry: str = ""
    product: str = ""
    cells: int = 1
    dpi: int = 0
    source: str = ""
    operator: str = ""
    notes: str = ""
    timestamp: str = ""
    code_sha: str = ""
    length: int = 0

    def finalise(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not self.code_sha:
            self.code_sha = code_fingerprint(self.code)
        if not self.length:
            self.length = len(self.code)

    def as_row(self) -> dict[str, object]:
        self.finalise()
        return {name: getattr(self, name) for name in FIELDS}


@dataclass
class Conflict:
    """A reason an entry cannot be accepted as-is."""

    severity: str  # "error" or "warning"
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.message}"


@dataclass
class Register:
    """An append-only CSV of label events."""

    path: Path
    entries: list[Entry] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "Register":
        target = Path(path)
        register = cls(path=target)
        if not target.exists():
            return register
        with target.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if not row.get("code"):
                    continue
                try:
                    cells = int(row.get("cells") or 1)
                except ValueError:
                    cells = 1
                try:
                    dpi = int(row.get("dpi") or 0)
                except ValueError:
                    dpi = 0
                try:
                    length = int(row.get("length") or 0)
                except ValueError:
                    length = 0
                register.entries.append(
                    Entry(
                        event=row.get("event", ""),
                        kind=row.get("kind", ""),
                        code=row.get("code", ""),
                        lot=row.get("lot", ""),
                        expiry=row.get("expiry", ""),
                        product=row.get("product", ""),
                        cells=cells,
                        dpi=dpi,
                        source=row.get("source", ""),
                        operator=row.get("operator", ""),
                        notes=row.get("notes", ""),
                        timestamp=row.get("timestamp", ""),
                        code_sha=row.get("code_sha", ""),
                        length=length,
                    )
                )
        return register

    # -- checks ---------------------------------------------------------

    def check(self, entry: Entry) -> list[Conflict]:
        """Every reason this entry should not be accepted silently."""
        conflicts: list[Conflict] = []

        if not entry.code.strip():
            conflicts.append(Conflict("error", "the code is empty"))
            return conflicts

        if entry.event not in ("print", "reprint", "void"):
            conflicts.append(
                Conflict("error", f"unknown event {entry.event!r}; use print, reprint or void")
            )

        try:
            Kind(entry.kind)
        except ValueError:
            conflicts.append(Conflict("error", f"unknown kind {entry.kind!r}"))

        # A void is a correction: it cancels a previous mistake. It must always be
        # recordable, even when the entry it cancels was itself wrong -- refusing it
        # would leave a bad row with no way to mark it.
        if entry.event == "void":
            return conflicts

        # One code belongs to one item. If a code was already registered under a
        # different lot or product, reusing it copies one item's meaning onto
        # another -- the exact failure that produces a wrong patient result.
        for previous in self.entries:
            if code_fingerprint(previous.code) != code_fingerprint(entry.code):
                continue
            if previous.event == "void":
                continue
            if entry.event == "print":
                conflicts.append(
                    Conflict(
                        "error",
                        f"this exact code was already printed on "
                        f"{previous.timestamp or 'an earlier entry'} "
                        f"({previous.kind}, lot {previous.lot or '?'}); "
                        f"use 'reprint' to record a replacement",
                    )
                )
            if previous.lot and entry.lot and previous.lot != entry.lot:
                conflicts.append(
                    Conflict(
                        "error",
                        f"this code carries lot {previous.lot} but the new entry says "
                        f"{entry.lot}",
                    )
                )
            if previous.product and entry.product and previous.product != entry.product:
                conflicts.append(
                    Conflict(
                        "warning",
                        f"this code was recorded for {previous.product!r}, now "
                        f"{entry.product!r}",
                    )
                )

        # Two different codes for the same lot is normal (many bottles per lot),
        # so that is not flagged. One code for two lots is the serious case above.
        return conflicts

    def add(self, entry: Entry, *, allow_warnings: bool = True) -> list[Conflict]:
        """Validate and append. Returns conflicts; raises only on errors."""
        conflicts = self.check(entry)
        errors = [c for c in conflicts if c.severity == "error"]
        if errors:
            raise RegisterError("; ".join(str(c) for c in errors))
        warnings = [c for c in conflicts if c.severity == "warning"]
        if warnings and not allow_warnings:
            raise RegisterError("; ".join(str(c) for c in warnings))

        entry.finalise()
        self.entries.append(entry)
        self._append_row(entry)
        return warnings

    def _append_row(self, entry: Entry) -> None:
        new_file = not self.path.exists() or self.path.stat().st_size == 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerow(entry.as_row())

    # -- queries --------------------------------------------------------

    def for_lot(self, lot: str) -> list[Entry]:
        return [e for e in self.entries if e.lot == lot and e.event != "void"]

    def for_code(self, code: str) -> list[Entry]:
        fingerprint = code_fingerprint(code)
        return [e for e in self.entries if e.code_sha == fingerprint]

    def lots(self) -> list[str]:
        return sorted({e.lot for e in self.entries if e.lot})

    def summary(self) -> list[str]:
        printed = [e for e in self.entries if e.event == "print"]
        reprinted = [e for e in self.entries if e.event == "reprint"]
        voided = [e for e in self.entries if e.event == "void"]
        by_kind: dict[str, int] = {}
        for entry in printed:
            by_kind[entry.kind] = by_kind.get(entry.kind, 0) + 1

        lines = [
            f"entries: {len(self.entries)}",
            f"printed: {len(printed)}   reprinted: {len(reprinted)}   voided: {len(voided)}",
            f"lots: {len(self.lots())}",
        ]
        for kind_value in sorted(by_kind):
            lines.append(f"  {kind_value}: {by_kind[kind_value]}")
        return lines


def find_lot_mixing(register: Register) -> list[Conflict]:
    """Report any code that appears under more than one lot.

    This is a register-wide sweep rather than a per-entry check, because the
    second entry may have been added before the first lot was known.
    """
    seen: dict[str, set[str]] = {}
    examples: dict[str, str] = {}
    for entry in register.entries:
        if entry.event == "void" or not entry.lot:
            continue
        fingerprint = entry.code_sha or code_fingerprint(entry.code)
        seen.setdefault(fingerprint, set()).add(entry.lot)
        examples.setdefault(fingerprint, entry.code)

    conflicts: list[Conflict] = []
    for fingerprint, lots in seen.items():
        if len(lots) > 1:
            shown = examples[fingerprint]
            short = shown if len(shown) <= 32 else shown[:29] + "..."
            conflicts.append(
                Conflict(
                    "error",
                    f"code {short} appears under lots {', '.join(sorted(lots))}",
                )
            )
    return conflicts
