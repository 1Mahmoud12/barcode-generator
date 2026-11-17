"""Print product labels from the command line.

Useful for batches: one ``--label`` block per product, or a CSV whose columns
are the field names.

Examples
--------
One label on 76 mm receipt paper:

    python make_labels.py --roll 76 --out labels.pdf \
        --set code=iwUMArCYU --set product="Calibration Reagent" \
        --set lot=20250902 --set expiry=2027-04-14 --set volume="R1 3.5 mL"

A sheet of 60x40 mm labels on A4:

    python make_labels.py --sheet 60x40 --out sheet.pdf --csv products.csv
"""

from __future__ import annotations

import argparse
import csv
import sys

from bcgen import label, render
from bcgen.label import LabelData, LabelError

FIELD_NAMES = (
    "code",
    "product",
    "lot",
    "expiry",
    "produced",
    "volume",
    "storage",
    "notes",
    "copies",
)


def _parse_size(text: str) -> tuple[float, float]:
    try:
        width, height = text.lower().split("x")
        return float(width), float(height)
    except ValueError:
        raise SystemExit(f"size must look like 60x40, got {text!r}") from None


def _labels_from_csv(path: str) -> list[LabelData]:
    labels: list[LabelData] = []
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            cleaned = {k: (v or "").strip() for k, v in row.items() if k in FIELD_NAMES}
            if "code" not in cleaned or not cleaned["code"]:
                continue
            copies = cleaned.pop("copies", "1") or "1"
            try:
                cleaned["copies"] = int(copies)
            except ValueError:
                cleaned["copies"] = 1
            labels.append(LabelData(**cleaned))
    return labels


def _apply_setting(label_data: LabelData, assignment: str) -> None:
    if "=" not in assignment:
        raise SystemExit(f"--set needs key=value, got {assignment!r}")
    key, value = assignment.split("=", 1)
    key = key.strip()
    if key not in FIELD_NAMES:
        raise SystemExit(f"unknown field {key!r}; choose from {', '.join(FIELD_NAMES)}")
    if key == "copies":
        setattr(label_data, key, int(value))
    elif key in ("expiry", "produced"):
        setattr(label_data, key, label.normalise_date(value))
    else:
        setattr(label_data, key, value.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print product labels.")
    parser.add_argument("--out", default="labels.pdf")
    parser.add_argument("--dpi", type=int, default=203, help="203 for receipt, 300 for label")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--csv", help="CSV file with one product per row")
    parser.add_argument("--bar-height", type=float, default=None, help="fixed bar height in mm")
    parser.add_argument("--no-cut-lines", action="store_true")

    paper = parser.add_mutually_exclusive_group(required=True)
    paper.add_argument("--roll", type=float, metavar="WIDTH_MM", help="receipt paper width")
    paper.add_argument("--sheet", metavar="WxH", help="label size on A4, e.g. 60x40")

    args = parser.parse_args(argv)

    if args.csv:
        labels = _labels_from_csv(args.csv)
        if not labels:
            raise SystemExit(f"no rows with a code column in {args.csv}")
    else:
        data = LabelData()
        for assignment in args.set:
            _apply_setting(data, assignment)
        labels = [data]

    try:
        if args.roll:
            layout = label.build_roll(
                args.out,
                labels,
                paper_width_mm=args.roll,
                label_width_mm=args.roll,
                label_height_mm=40.0,
                dpi=args.dpi,
                bar_height_mm=args.bar_height,
            )
            total = sum(item.copies for item in labels)
            print(f"wrote {args.out}: {total} label(s) on {args.roll:.0f} mm roll")
        else:
            width, height = _parse_size(args.sheet)
            layout = label.build_sheet(
                args.out,
                labels,
                page_width_mm=210.0,
                page_height_mm=297.0,
                label_width_mm=width,
                label_height_mm=height,
                dpi=args.dpi,
                bar_height_mm=args.bar_height,
                cut_lines=not args.no_cut_lines,
                page_heading="Product labels",
            )
            print(f"wrote {args.out}: labels of {width:.0f}x{height:.0f} mm on A4")
    except LabelError as exc:
        print(f"cannot build labels: {exc}", file=sys.stderr)
        return 2
    except render.RenderError as exc:
        print(f"cannot render: {exc}", file=sys.stderr)
        return 2

    print(
        f"  bar {layout.bar_height_mm:.0f} mm, text {layout.text_pt:.1f} pt, "
        f"dpi {args.dpi}"
    )
    first = labels[0]
    inner = layout.width_mm - 2 * layout.margin_mm
    geo = render.geometry_for_width(first.code, inner, args.dpi)
    print(
        f"  barcode {geo.module_dots} dots -> X {geo.x_mm:.3f} mm, "
        f"{geo.total_mm:.1f} mm wide of {inner:.1f} mm available"
    )
    if geo.x_mm < label.MIN_X_MM:
        print(
            f"  warning: X below {label.MIN_X_MM} mm; a thermal printer will struggle",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
