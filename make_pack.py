"""Print the four pack symbols from the command line.

The four items are independent: each takes its own text and nothing is derived
from anything else.

    python make_pack.py --out pack.pdf \
        --trigger IQEApeCg6t \
        --reagent iwUMArCYU \
        --method "TSH;Cal1;Lot20250902" \
        --package IQEA35yQjQ

Any subset works. Leave one out and only the others are printed, which is useful
when a single label needs replacing.
"""

from __future__ import annotations

import argparse
import sys

from bcgen import kind, pack, render
from bcgen.kind import Item, Kind, KindError


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Print trigger, method, package and reagent symbols.")
    p.add_argument("--out", default="pack.pdf", help="output PDF path")
    p.add_argument("--dpi", type=int, default=300, choices=[203, 300, 600])
    p.add_argument("--page", default="a4", choices=["a4", "roll58", "roll76"])
    p.add_argument("--trigger", help="trigger bottle code (Code 128)")
    p.add_argument("--reagent", help="reagent cartridge code (Code 128)")
    p.add_argument("--method", dest="method_qr", help="method QR text")
    p.add_argument("--package", dest="package_qr", help="package QR text")
    p.add_argument("--qr-square", type=float, default=None, help="QR side in mm")
    p.add_argument("--title", default="Pack symbols")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    items: list[Item] = []
    if args.trigger:
        items.append(Item(Kind.TRIGGER, args.trigger))
    if args.reagent:
        items.append(Item(Kind.REAGENT, args.reagent))
    if args.method_qr:
        items.append(Item(Kind.METHOD, args.method_qr))
    if args.package_qr:
        items.append(Item(Kind.PACKAGE, args.package_qr))

    if not items:
        print("give at least one of --trigger --reagent --method --package", file=sys.stderr)
        return 2

    pages = {
        "a4": (210.0, 297.0),
        "roll58": (58.0, 120.0),
        "roll76": (76.0, 120.0),
    }
    page_w, page_h = pages[args.page]

    try:
        for item in items:
            item.validate()
        placements = pack.build_pack_sheet(
            args.out,
            items,
            page_width_mm=page_w,
            page_height_mm=page_h,
            dpi=args.dpi,
            title=args.title,
            qr_square_mm=args.qr_square,
        )
    except KindError as exc:
        print(f"cannot encode: {exc}", file=sys.stderr)
        return 2
    except pack.PackError as exc:
        print(f"cannot lay out: {exc}", file=sys.stderr)
        return 2
    except render.RenderError as exc:
        print(f"cannot render: {exc}", file=sys.stderr)
        return 2

    print(f"wrote {args.out} ({args.dpi} dpi, {page_w:.0f}x{page_h:.0f} mm)")
    for placement in placements:
        text = placement.item.text
        shown = text if len(text) <= 48 else f"{text[:45]}... ({len(text)} chars)"
        print(f"  {placement.item.kind.title:8} {shown}")
        print(f"           {kind.describe(placement.item, dpi=args.dpi, width_mm=placement.width_mm)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
