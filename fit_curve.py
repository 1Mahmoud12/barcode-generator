"""Fit a calibration curve from the command line.

Input is a CSV of what you measured: concentration and the signal you observed.

    python fit_curve.py calibrators.csv
    python fit_curve.py calibrators.csv --model 5pl --csv-out params.csv

Nothing here assumes any manufacturer's numbers. The output is your curve, from
your measurements, and the recovery table is the evidence for it.
"""

from __future__ import annotations

import argparse
import csv
import sys

from bcgen import calib


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fit a 4PL or 5PL calibration curve to measured calibrators."
    )
    parser.add_argument("points", help="CSV with columns concentration,signal[,weight,label]")
    parser.add_argument(
        "--model",
        default="auto",
        choices=["auto", "4pl", "5pl"],
        help="auto picks the simpler model unless the 5PL clearly fits better",
    )
    parser.add_argument(
        "--free-blank",
        action="store_true",
        help="let the fitter move 'a' instead of pinning it to the measured zero",
    )
    parser.add_argument("--low", type=float, default=calib.DEFAULT_RECOVERY_LOW)
    parser.add_argument("--high", type=float, default=calib.DEFAULT_RECOVERY_HIGH)
    parser.add_argument("--csv-out", help="write the fitted parameters to this CSV")
    parser.add_argument(
        "--signal", type=float, action="append", default=[],
        help="extra signal values to convert back to concentration",
    )
    args = parser.parse_args(argv)

    try:
        points = calib.read_points_csv(args.points)
        pin = not args.free_blank
        if args.model == "auto":
            result = calib.best_fit(points, pin_blank=pin)
        else:
            result = calib.fit(points, model=args.model, pin_blank=pin)
    except calib.CalibrationError as exc:
        print(f"cannot fit: {exc}", file=sys.stderr)
        return 2

    print(result.report(args.low, args.high))

    if args.signal:
        print()
        print("back-calculated concentrations:")
        for signal in args.signal:
            value = calib.back_calculate(result, signal)
            if value != value:
                shown = "outside the curve"
            elif value == float("inf"):
                shown = "at or above saturation"
            else:
                shown = f"{value:.6g}"
            print(f"  signal {signal:>14.4f} -> {shown}")

    if args.csv_out:
        with open(args.csv_out, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["parameter", "value"])
            for name, value in result.params.as_dict().items():
                writer.writerow([name, value])
            writer.writerow(["r_squared", f"{result.r_squared:.8f}"])
            writer.writerow(["rmse", f"{result.rmse:.8f}"])
            writer.writerow(["blank_pinned", str(result.blank_pinned)])
        print(f"\nparameters written to {args.csv_out}")

    return 0 if result.recoveries_ok(args.low, args.high) else 1


if __name__ == "__main__":
    sys.exit(main())
