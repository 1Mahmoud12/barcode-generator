"""Command-line entry point.

Two workflows:

* ``--generate`` builds synthetic codes and prints the measurement sheet. This
  is the "create a barcode from scratch" path: the payload is made by us, so a
  successful scan proves the whole chain end to end.
* ``--codes-file`` reads payloads from a text file, one per line, for when the
  codes to be measured are known in advance.

Examples
--------
Print a ladder of widths for 24 synthetic codes at 600 dpi:

    python make_sheet.py --generate 24 --dpi 600 --out sheet.pdf

Measure specific payloads:

    python make_sheet.py --codes-file payloads.txt --dpi 300
"""

from __future__ import annotations

import argparse
import sys

from bcgen import render, sheet
from bcgen.generate import (
    DEFAULT_LENGTH,
    GenerationError,
    edge_codes,
    random_codes,
    sequential_codes,
)


def _read_codes_file(path: str) -> list[str]:
    out: list[str] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            out.append(text)
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Build an A4 sheet of Code 128 symbols for scanner measurement.",
    )
    p.add_argument("--out", default="barcode-sheet.pdf", help="output PDF path")
    p.add_argument("--dpi", type=int, default=600, help="printer resolution (300 or 600)")
    p.add_argument(
        "--rungs",
        default="3,4,5,6,8,10,12",
        help="comma separated bar widths in printer dots",
    )
    p.add_argument("--title", default="Barcode reader measurement sheet")

    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--generate",
        type=int,
        metavar="N",
        help=f"make N synthetic codes of {DEFAULT_LENGTH} characters",
    )
    source.add_argument("--codes-file", help="file with one payload per line")
    source.add_argument(
        "--sequential",
        type=int,
        metavar="N",
        help="make N readable codes T000001, T000002, ...",
    )
    source.add_argument(
        "--edge", action="store_true", help="include the Subset B edge-case payloads"
    )

    p.add_argument(
        "--alphabet",
        default="mixed",
        choices=["mixed", "upper", "lower", "digits", "symbols"],
        help="character class for generated codes",
    )
    p.add_argument("--length", type=int, default=DEFAULT_LENGTH, help="payload length")
    p.add_argument("--seed", type=int, default=0, help="random seed for reproducible runs")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        from bcgen.generate import TestCode

        if args.generate:
            codes = random_codes(
                args.generate,
                length=args.length,
                alphabet=args.alphabet,
                seed=args.seed,
            )
        elif args.sequential:
            codes = sequential_codes(args.sequential)
        elif args.edge:
            codes = edge_codes()
        else:
            texts = _read_codes_file(args.codes_file)
            if not texts:
                print(f"no payloads found in {args.codes_file}", file=sys.stderr)
                return 2
            codes = [TestCode(t, f"file-{i + 1:03d}") for i, t in enumerate(texts)]

        rungs = [int(x) for x in args.rungs.split(",") if x.strip()]
        if not rungs:
            print("no bar widths given", file=sys.stderr)
            return 2

        plans = sheet.build_sheet(
            args.out,
            codes,
            rungs=rungs,
            dpi=args.dpi,
            title=args.title,
        )
    except GenerationError as exc:
        print(f"cannot generate codes: {exc}", file=sys.stderr)
        return 2
    except sheet.SheetError as exc:
        print(f"cannot lay out sheet: {exc}", file=sys.stderr)
        return 2
    except render.RenderError as exc:
        print(f"cannot render: {exc}", file=sys.stderr)
        return 2

    print(f"wrote {args.out}")
    print(f"  {len(codes)} codes, {len(plans)} pages, {args.dpi} dpi")
    for plan in plans:
        print(
            f"  page {plans.index(plan) + 1}: {plan.module_dots} dots "
            f"= {plan.geo.x_mm:.3f} mm per module, "
            f"{len(plan.cells)} symbols "
            f"({plan.columns}x{plan.rows} grid)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
