"""Record what the reader did with each page.

A measurement is only useful if it is written down in a form that can be
compared later. One row per (page, bar width, code) keeps the raw observations
and lets the smallest readable size be derived instead of guessed.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, fields
from pathlib import Path

FIELDS = (
    "timestamp",
    "dpi",
    "module_dots",
    "x_mm",
    "symbol_mm",
    "payload",
    "cell_id",
    "read_ok",
    "attempts",
    "distance_cm",
    "notes",
)


@dataclass
class Observation:
    timestamp: str
    dpi: int
    module_dots: int
    x_mm: float
    symbol_mm: float
    payload: str
    cell_id: str
    read_ok: bool
    attempts: int = 1
    distance_cm: float | None = None
    notes: str = ""

    def as_row(self) -> dict[str, object]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def append(path: str | Path, observation: Observation) -> None:
    """Append one observation, writing the header if the file is new."""
    target = Path(path)
    new = not target.exists() or target.stat().st_size == 0
    with target.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new:
            writer.writeheader()
        row = observation.as_row()
        row["read_ok"] = "yes" if observation.read_ok else "no"
        writer.writerow(row)


def smallest_working_size(path: str | Path) -> dict[str, object] | None:
    """Return the smallest X-dimension where every attempt succeeded.

    Returns ``None`` when the log has no fully successful size yet.
    """
    target = Path(path)
    if not target.exists():
        return None

    by_size: dict[tuple[int, float], list[dict[str, str]]] = {}
    with target.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                key = (int(row["dpi"]), float(row["x_mm"]))
            except (KeyError, TypeError, ValueError):
                continue
            by_size.setdefault(key, []).append(row)

    for (dpi, x_mm), rows in sorted(by_size.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        successes = sum(1 for r in rows if str(r.get("read_ok", "")).lower() in {"yes", "true", "1"})
        if rows and successes == len(rows):
            return {
                "dpi": dpi,
                "x_mm": x_mm,
                "observations": len(rows),
                "module_dots": rows[0].get("module_dots", ""),
            }
    return None
