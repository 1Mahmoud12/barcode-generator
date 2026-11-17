"""Checks for the calibration curve fitter.

The fitter exists to turn the operator's own measurements into a curve they can
defend. These tests use synthetic data generated from known parameters, so the
correct answer is known: a correct fitter must recover those parameters.
"""

from __future__ import annotations

import math
import random
import unittest

from bcgen import calib
from bcgen.calib import Point


def four_pl(a: float, b: float, c: float, d: float, x: float) -> float:
    if x <= 0:
        return a
    return d + (a - d) / (1 + (x / c) ** b)


def five_pl(a: float, b: float, c: float, d: float, g: float, x: float) -> float:
    if x <= 0:
        return a
    return d + (a - d) / ((1 + (x / c) ** b) ** g)


TRUE_4PL = dict(a=200.0, b=0.9, c=50.0, d=650000.0)
TRUE_5PL = dict(a=150.0, b=1.1, c=42.0, d=800000.0, g=0.92)

CONCENTRATIONS = [0, 1.25, 6.56, 16.99, 33.74, 68.85, 107.83, 175.48, 215.35, 267.77]


def clean_4pl_points() -> list[Point]:
    return [
        Point(x, four_pl(**TRUE_4PL, x=x), label=f"C{i + 1}")
        for i, x in enumerate(CONCENTRATIONS)
    ]


def noisy_5pl_points(seed: int = 7, sigma: float = 0.012) -> list[Point]:
    rng = random.Random(seed)
    xs = [0, 2.0, 7.5, 20.0, 45.0, 90.0, 150.0, 240.0, 320.0]
    return [
        Point(x, five_pl(**TRUE_5PL, x=x) * (1 + rng.gauss(0, sigma)), label=f"C{i + 1}")
        for i, x in enumerate(xs)
    ]


class ExactRecoveryTests(unittest.TestCase):
    def test_recovers_known_parameters(self) -> None:
        result = calib.fit(clean_4pl_points(), model="4pl")
        for name, expected in TRUE_4PL.items():
            got = getattr(result.params, name)
            self.assertAlmostEqual(
                got, expected, places=3, msg=f"{name} was {got}, expected {expected}"
            )

    def test_perfect_data_recovers_all_points(self) -> None:
        result = calib.fit(clean_4pl_points(), model="4pl")
        for recovery in result.measured_recoveries():
            self.assertAlmostEqual(recovery, 100.0, places=4)

    def test_blank_is_reported_as_blank_not_percent(self) -> None:
        result = calib.fit(clean_4pl_points(), model="4pl")
        self.assertTrue(math.isnan(result.recoveries[0]))

    def test_blank_pinned_by_default(self) -> None:
        result = calib.fit(clean_4pl_points(), model="4pl")
        self.assertTrue(result.blank_pinned)
        self.assertEqual(result.blank_residual(), 0.0)

    def test_r_squared_is_one_on_exact_data(self) -> None:
        result = calib.fit(clean_4pl_points(), model="4pl")
        self.assertAlmostEqual(result.r_squared, 1.0, places=6)


class BlankPinningTests(unittest.TestCase):
    def test_unpinned_blank_drifts(self) -> None:
        pinned = calib.fit(noisy_5pl_points(), model="4pl", pin_blank=True)
        free = calib.fit(noisy_5pl_points(), model="4pl", pin_blank=False)
        self.assertTrue(pinned.blank_pinned)
        self.assertFalse(free.blank_pinned)
        self.assertAlmostEqual(pinned.params.a, 149.539, places=2)
        self.assertNotAlmostEqual(free.params.a, pinned.params.a, places=1)

    def test_pinned_blank_gives_sensible_low_recoveries(self) -> None:
        pinned = calib.fit(noisy_5pl_points(), model="4pl", pin_blank=True)
        self.assertTrue(pinned.recoveries_ok())

    def test_no_blank_point_still_fits(self) -> None:
        points = [p for p in clean_4pl_points() if p.concentration > 0]
        result = calib.fit(points, model="4pl")
        self.assertFalse(result.blank_pinned)
        self.assertGreater(result.r_squared, 0.99)


class BackCalculationTests(unittest.TestCase):
    def test_back_calculation_is_accurate(self) -> None:
        result = calib.fit(noisy_5pl_points(), model="4pl")
        for concentration in (12.0, 60.0, 200.0):
            signal = five_pl(**TRUE_5PL, x=concentration)
            recovered = calib.back_calculate(result, signal)
            error = abs(recovered - concentration) / concentration * 100
            self.assertLess(error, 6.0, f"{concentration} recovered as {recovered:.2f}")

    def test_inverse_of_predict_returns_input(self) -> None:
        result = calib.fit(clean_4pl_points(), model="4pl")
        for concentration in (5.0, 50.0, 150.0):
            signal = result.params.predict(concentration)
            self.assertAlmostEqual(result.params.inverse(signal), concentration, places=6)

    def test_back_calculation_outside_curve_is_nan(self) -> None:
        result = calib.fit(clean_4pl_points(), model="4pl")
        self.assertTrue(math.isnan(calib.back_calculate(result, -1e9)))

    def test_signal_at_curve_floor_is_zero_concentration(self) -> None:
        # y = a is the zero calibrator, which is a real answer, not a failure.
        result = calib.fit(clean_4pl_points(), model="4pl")
        self.assertEqual(result.params.inverse(result.params.a), 0.0)

    def test_signal_above_saturation_is_infinite(self) -> None:
        result = calib.fit(clean_4pl_points(), model="4pl")
        self.assertTrue(math.isinf(result.params.inverse(result.params.d)))


class ValidationTests(unittest.TestCase):
    def test_too_few_points(self) -> None:
        with self.assertRaises(calib.CalibrationError):
            calib.fit(clean_4pl_points()[:3], model="4pl")

    def test_five_pl_needs_five(self) -> None:
        with self.assertRaises(calib.CalibrationError):
            calib.fit(clean_4pl_points()[:4], model="5pl")

    def test_bad_model_name(self) -> None:
        with self.assertRaises(calib.CalibrationError):
            calib.fit(clean_4pl_points(), model="3pl")

    def test_negative_concentration(self) -> None:
        with self.assertRaises(calib.CalibrationError):
            Point(-1.0, 100.0).validate()

    def test_duplicate_concentrations(self) -> None:
        points = [Point(0, 10.0), Point(5, 100.0), Point(5, 120.0), Point(10, 200.0)]
        with self.assertRaises(calib.CalibrationError):
            calib.fit(points, model="4pl")

    def test_flat_signals(self) -> None:
        points = [Point(x, 500.0) for x in (0, 1, 2, 3)]
        with self.assertRaises(calib.CalibrationError):
            calib.fit(points, model="4pl")


class PlausibilityTests(unittest.TestCase):
    def test_degenerate_5pl_is_flagged(self) -> None:
        # Large g with large c is the classic degeneracy: good residuals, wrong curve.
        params = calib.Params(a=197.0, b=0.82, c=312.0, d=563000.0, g=4.25, model="5pl")
        result = calib.FitResult(params=params, points=clean_4pl_points())
        problems = calib.plausible(result, clean_4pl_points())
        self.assertTrue(any("inflection" in p for p in problems))
        self.assertTrue(any("asymmetry" in p for p in problems))

    def test_sane_4pl_is_not_flagged(self) -> None:
        result = calib.fit(clean_4pl_points(), model="4pl")
        self.assertEqual(calib.plausible(result, clean_4pl_points()), [])

    def test_negative_slope_flagged(self) -> None:
        params = calib.Params(a=200.0, b=-1.0, c=50.0, d=650000.0, model="4pl")
        result = calib.FitResult(params=params, points=clean_4pl_points())
        self.assertTrue(any("slope" in p for p in calib.plausible(result, clean_4pl_points())))

    def test_flat_curve_flagged(self) -> None:
        params = calib.Params(a=500.0, b=1.0, c=50.0, d=500.0, model="4pl")
        result = calib.FitResult(params=params, points=clean_4pl_points())
        self.assertTrue(any("span" in p for p in calib.plausible(result, clean_4pl_points())))


class ModelSelectionTests(unittest.TestCase):
    def test_chooses_4pl_for_four_parameter_data(self) -> None:
        result = calib.best_fit(clean_4pl_points())
        self.assertEqual(result.params.model, "4pl")

    def test_rejects_degenerate_5pl_in_favour_of_4pl(self) -> None:
        # This is the failure that motivated the guard: the 5PL has a lower RMSE
        # but a c outside the data, so its answers between points would be wrong.
        rng = random.Random(11)
        points = [
            Point(x, four_pl(**TRUE_4PL, x=x) * (1 + rng.gauss(0, 0.01)), label=f"C{i + 1}")
            for i, x in enumerate(CONCENTRATIONS)
        ]
        result = calib.best_fit(points)
        self.assertEqual(result.params.model, "4pl")
        self.assertLess(result.params.c, 200.0)

    def test_chooses_4pl_when_asymmetry_is_within_noise(self) -> None:
        result = calib.best_fit(noisy_5pl_points())
        self.assertEqual(result.params.model, "4pl")

    def test_chooses_5pl_when_asymmetry_is_strong(self) -> None:
        rng = random.Random(3)
        xs = [0, 1, 4, 12, 30, 70, 150, 300, 500]
        points = [
            Point(x, five_pl(100.0, 1.4, 30.0, 900000.0, 0.55, x) * (1 + rng.gauss(0, 0.008)),
                  label=f"C{i + 1}")
            for i, x in enumerate(xs)
        ]
        result = calib.best_fit(points)
        self.assertEqual(result.params.model, "5pl")
        self.assertLess(result.params.g, 0.9)

    def test_report_mentions_key_numbers(self) -> None:
        report = calib.fit(clean_4pl_points(), model="4pl").report()
        self.assertIn("R^2", report)
        self.assertIn("RMSE", report)
        self.assertIn("recovery", report)
        self.assertIn("blank", report)


class CsvTests(unittest.TestCase):
    def test_reads_valid_csv(self) -> None:
        import os
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("concentration,signal,label\n")
                handle.write("0,200,C1\n")
                handle.write("50,300000,C2\n")
            points = calib.read_points_csv(path)
            self.assertEqual(len(points), 2)
            self.assertEqual(points[1].label, "C2")
        finally:
            os.remove(path)

    def test_missing_columns_rejected(self) -> None:
        import os
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("conc,sig\n0,200\n")
            with self.assertRaises(calib.CalibrationError):
                calib.read_points_csv(path)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
