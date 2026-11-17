"""Compare what the reader produced with what the sheet carries.

A scanner can beep and still be wrong. This tool does the comparison the eye
skips: it checks length, then every character in order, and it flags the pairs
that are easy to confuse at a glance (0/O, 1/l/I, 5/S, 8/B, rn/m) because those
are the readings people wrongly accept as correct.

Usage
-----
Compare one reading against one expected payload:

    python verify_read.py --expect x1Fh+zm9t --got x1Fh+zm9t

Several readings at once, one per line as ``expected<TAB>observed``:

    python verify_read.py --file readings.tsv

The exit status is 0 only when every line matched exactly.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

# Pairs that look alike in most sans fonts and on a worn label.
LOOKALIKE_GROUPS = ("0O", "1lI", "5S", "8B", "2Z", "6G", "9g", "rn", "vv", "cl")


def _lookalike_partners(char: str) -> str:
    for group in LOOKALIKE_GROUPS:
        if char in group:
            return group
    return ""


@dataclass(frozen=True)
class Verdict:
    expected: str
    observed: str

    @property
    def exact(self) -> bool:
        return self.expected == self.observed

    @property
    def position(self) -> int | None:
        """0-based index of the first difference, or None when identical."""
        if self.exact:
            return None
        for index, (a, b) in enumerate(zip(self.expected, self.observed)):
            if a != b:
                return index
        return min(len(self.expected), len(self.observed))

    def describe(self) -> str:
        if self.exact:
            return f"MATCH   {self.expected!r}"

        lines = [f"MISMATCH expected {self.expected!r} got {self.observed!r}"]

        if len(self.expected) != len(self.observed):
            lines.append(
                f"  length differs: expected {len(self.expected)} characters, "
                f"got {len(self.observed)}"
            )

        index = self.position
        if index is not None and index < len(self.expected) and index < len(self.observed):
            a = self.expected[index]
            b = self.observed[index]
            lines.append(f"  first difference at position {index + 1}: expected {a!r}, got {b!r}")
            if a in _lookalike_partners(b) or b in _lookalike_partners(a):
                lines.append(
                    f"  these two look alike ({a!r}/{b!r}); compare with the printed text "
                    f"character by character before accepting the read"
                )

        lines.append("  expected: " + " ".join(self.expected))
        lines.append("  observed: " + " ".join(self.observed))
        lines.append("  marker  : " + " ".join(
            "^" if i == index else " " for i in range(len(self.expected))
        ))
        return "\n".join(lines)


def parse_lines(raw: list[str]) -> list[Verdict]:
    verdicts: list[Verdict] = []
    for line in raw:
        text = line.rstrip("\n")
        if not text.strip() or text.lstrip().startswith("#"):
            continue
        if "\t" in text:
            expected, observed = text.split("\t", 1)
        elif "," in text:
            expected, observed = text.split(",", 1)
        else:
            raise SystemExit(f"cannot read line (expected<TAB>observed): {text!r}")
        verdicts.append(Verdict(expected.strip(), observed.strip()))
    return verdicts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check scanner readings against payloads.")
    parser.add_argument("--expect", help="the payload printed on the sheet")
    parser.add_argument("--got", help="the text the reader produced")
    parser.add_argument("--file", help="file of expected<TAB>observed lines")
    args = parser.parse_args(argv)

    if args.file:
        with open(args.file, encoding="utf-8") as handle:
            verdicts = parse_lines(handle.readlines())
    elif args.expect is not None and args.got is not None:
        verdicts = [Verdict(args.expect, args.got)]
    else:
        parser.print_help()
        return 2

    if not verdicts:
        print("no readings to check")
        return 2

    print()
    for verdict in verdicts:
        print(verdict.describe())
        print()
    failures = sum(1 for v in verdicts if not v.exact)
    print(
        f"{len(verdicts) - failures}/{len(verdicts)} matched exactly, "
        f"{failures} did not"
    )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
