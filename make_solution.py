"""Print Trigger and Pre-Trigger bottle labels from the command line.

One label per `--label` block, or a CSV with one bottle per row.

    python make_solution.py --out trigger.pdf \
        --set kind=trigger --set volume=450 --set code=IQEApeCg6t \
        --set lot=20250902 --set produced=2025-09-02 --set expiry=2027-04-14 \
        --set gtin=06925912716570

Several sizes in one run, each with its own code and GTIN:

    python make_solution.py --out all.pdf --csv bottles.csv
"""

from __future__ import annotations

import argparse
import csv
import sys

from bcgen import solution
from bcgen.solution import SolutionError, SolutionLabel

FIELDS = (
    "kind",
    "code",
    "volume_ml",
    "lot",
    "produced",
    "expiry",
    "product",
    "storage",
    "gtin",
    "internal",
    "notes",
    "copies",
)


def _parse_size(text: str) -> tuple[float, float]:
    try:
        width, height = text.lower().split("x")
        return float(width), float(height)
    except ValueError:
        raise SystemExit(f"label size must look like 90x45, got {text!r}") from None


def _apply(label: SolutionLabel, assignment: str) -> None:
    if "=" not in assignment:
        raise SystemExit(f"--set needs key=value, got {assignment!r}")
    key, value = assignment.split("=", 1)
    key = key.strip()
    if key not in FIELDS:
        raise SystemExit(f"unknown field {key!r}; choose from {', '.join(FIELDS)}")
    value = value.strip()
    if key == "volume_ml":
        setattr(label, "volume_ml", int(value))
    elif key == "copies":
        setattr(label, "copies", int(value))
    else:
        setattr(label, key, value)


def _labels_from_csv(path: str) -> list[SolutionLabel]:
    labels: list[SolutionLabel] = []
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            cleaned = {k: (v or "").strip() for k, v in row.items() if k in FIELDS}
            if not cleaned.get("code"):
                continue
            if cleaned.get("volume_ml"):
                try:
                    cleaned["volume_ml"] = int(cleaned["volume_ml"])
                except ValueError:
                    raise SystemExit(f"volume_ml must be a number, got {cleaned['volume_ml']!r}")
            if cleaned.get("copies"):
                try:
                    cleaned["copies"] = int(cleaned["copies"])
                except ValueError:
                    cleaned["copies"] = 1
            labels.append(SolutionLabel(**cleaned))
    return labels


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print Trigger and Pre-Trigger bottle labels."
    )
    parser.add_argument("--out", default="solution-labels.pdf")
    parser.add_argument("--dpi", type=int, default=300, choices=[203, 300, 600])
    parser.add_argument("--label-size", default="90x45", help="label size in mm, e.g. 90x45")
    parser.add_argument("--page", default="a4", choices=["a4", "roll76", "roll58"])
    parser.add_argument("--csv", help="CSV with one bottle per row")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument(
        "--no-datamatrix",
        action="store_true",
        help="print only the Code 128 (GS1 DataMatrix needs zint)",
    )
    args = parser.parse_args(argv)

    if args.csv:
        labels = _labels_from_csv(args.csv)
        if not labels:
            raise SystemExit(f"no rows with a code in {args.csv}")
    else:
        label = SolutionLabel()
        for assignment in args.set:
            _apply(label, assignment)
        labels = [label]

    pages = {"a4": (210.0, 297.0), "roll76": (76.0, 200.0), "roll58": (58.0, 200.0)}
    page_w, page_h = pages[args.page]
    label_w, label_h = _parse_size(args.label_size)

    try:
        problems = solution.build_solution_sheet(
            args.out,
            labels,
            page_width_mm=page_w,
            page_height_mm=page_h,
            label_width_mm=label_w,
            label_height_mm=label_h,
            dpi=args.dpi,
            with_datamatrix=not args.no_datamatrix,
        )
    except SolutionError as exc:
        print(f"cannot build labels: {exc}", file=sys.stderr)
        return 2

    total = sum(label.copies for label in labels)
    print(f"wrote {args.out}: {total} label(s), {args.dpi} dpi, {label_w:.0f}x{label_h:.0f} mm")
    for label in labels:
        layout = solution.auto_layout(label.code, label_w, label_h, args.dpi)
        line = (
            f"  {label.kind_title():12} {label.volume_text:>7}  code {label.code}  "
            f"bar {layout.bar_height_mm:.0f} mm"
        )
        print(line)

    if problems:
        print()
        print("REVIEW - these need fixing before printing:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print()
    print("GS1 elements:")
    for label in labels:
        print(f"  {label.kind_title()} {label.volume_text}: {label.gs1_string()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
