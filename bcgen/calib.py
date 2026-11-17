"""Fit a calibration curve to your own measured calibrator data.

This module exists because a curve fitted from measurements you made, on your own
material, with your own instrument, is the only curve that can honestly describe
your product. It does not read, infer or borrow any manufacturer's numbers: the
input is a table of concentrations and the signals you observed, and nothing else.

The model is 4PL (four-parameter logistic) or 5PL, the standards for
immunoassay:

    4PL:  y = d + (a - d) / (1 + (x / c) ** b)
    5PL:  y = d + (a - d) / (1 + (x / c) ** b) ** g

with

    a  response at zero concentration
    d  response at saturating concentration
    c  concentration at the inflection point
    b  slope (steepness)
    g  asymmetry (5PL only, g = 1 reduces to 4PL)

Acceptance is judged by **recovery**: for each calibrator, take the signal you
actually measured, run it back through the fitted curve, and see what
concentration comes out. That concentration must land close to the one you put
in. This is not circular -- it uses the measured signal, not the fitted one --
and it is the check a reviewer will ask about.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# Recovery outside this band usually means the top or bottom of the curve is not
# defined by the data, or a calibrator was mis-pipetted.
DEFAULT_RECOVERY_LOW = 80.0
DEFAULT_RECOVERY_HIGH = 120.0


class CalibrationError(ValueError):
    """Raised when the data cannot support a fit."""


@dataclass(frozen=True)
class Point:
    """One calibrator: the concentration you made, and the signal you measured."""

    concentration: float
    signal: float
    weight: float = 1.0
    label: str = ""

    def validate(self) -> None:
        if self.concentration < 0:
            raise CalibrationError(f"negative concentration in {self.label or 'a point'}")
        if not math.isfinite(self.signal):
            raise CalibrationError(f"signal is not a finite number in {self.label or 'a point'}")
        if self.weight <= 0:
            raise CalibrationError(f"weight must be positive in {self.label or 'a point'}")


@dataclass(frozen=True)
class Params:
    """Fitted curve parameters."""

    a: float
    b: float
    c: float
    d: float
    g: float = 1.0
    model: str = "4pl"

    def predict(self, x: float) -> float:
        return _predict(self, x)

    def inverse(self, y: float) -> float:
        """Concentration for a given signal, or nan when outside the curve."""
        return _inverse(self, y)

    def as_dict(self) -> dict[str, float | str]:
        return {
            "model": self.model,
            "a": self.a,
            "b": self.b,
            "c": self.c,
            "d": self.d,
            "g": self.g,
        }

    def describe(self) -> list[str]:
        return [
            f"model: {self.model.upper()}",
            f"a (response at zero): {self.a:.6g}",
            f"b (slope):            {self.b:.6g}",
            f"c (inflection):       {self.c:.6g}",
            f"d (saturation):       {self.d:.6g}",
        ] + ([f"g (asymmetry):        {self.g:.6g}"] if self.model == "5pl" else [])


def _predict(p: Params, x: float) -> float:
    if x <= 0:
        return p.a
    try:
        ratio = (x / p.c) ** p.b
    except (OverflowError, ZeroDivisionError):
        return p.d
    denom = 1.0 + ratio
    if p.model == "5pl":
        denom = denom ** p.g
    if not math.isfinite(denom) or denom == 0:
        return p.d
    return p.d + (p.a - p.d) / denom


def _inverse(p: Params, y: float) -> float:
    """Analytic inverse of the logistic, so back-calculation is exact.

    Returns nan when the signal lies outside the curve's range. That matters: a
    saturated or impossible signal must not be reported as concentration zero,
    because a real analyzer would show a result and nobody would question it.
    """
    if not math.isfinite(y):
        return float("nan")

    # The curve lives between a and d. Outside that band there is no concentration.
    # The endpoints themselves are valid: y = a is the zero calibrator.
    low, high = sorted((p.a, p.d))
    span = high - low
    margin = max(abs(span) * 1e-12, 1e-12)
    if y < low - margin or y > high + margin:
        return float("nan")
    if y <= low:
        return 0.0
    if y >= high:
        return float("inf")

    numerator = p.a - p.d
    denominator = y - p.d
    if denominator == 0 or numerator == 0:
        return float("nan")
    ratio = numerator / denominator
    if ratio <= 0:
        return float("nan")
    try:
        if p.model == "5pl":
            inner = ratio ** (1.0 / p.g) - 1.0
        else:
            inner = ratio - 1.0
        if inner <= 0:
            return float("nan")
        return p.c * inner ** (1.0 / p.b)
    except (ValueError, OverflowError, ZeroDivisionError):
        return float("nan")


@dataclass
class FitResult:
    """A fitted curve together with the evidence that it describes the data."""

    params: Params
    points: list[Point]
    fitted: list[float] = field(default_factory=list)
    residuals: list[float] = field(default_factory=list)
    recoveries: list[float] = field(default_factory=list)
    iterations: int = 0
    converged: bool = False
    blank_pinned: bool = False

    @property
    def r_squared(self) -> float:
        observed = np.array([p.signal for p in self.points], dtype=float)
        if observed.size == 0:
            return float("nan")
        mean = observed.mean()
        ss_tot = float(((observed - mean) ** 2).sum())
        if ss_tot == 0:
            return 1.0
        ss_res = float((np.array(self.residuals, dtype=float) ** 2).sum())
        return 1.0 - ss_res / ss_tot

    @property
    def rmse(self) -> float:
        if not self.residuals:
            return float("nan")
        return float(np.sqrt(np.mean(np.array(self.residuals, dtype=float) ** 2)))

    def measured_recoveries(self) -> list[float]:
        """Recoveries excluding the blank, which has no percentage to recover."""
        return [r for r in self.recoveries if not math.isnan(r)]

    def worst_recovery_deviation(self) -> float:
        values = self.measured_recoveries()
        if not values:
            return float("nan")
        return max(abs(r - 100.0) for r in values)

    def recoveries_ok(
        self, low: float = DEFAULT_RECOVERY_LOW, high: float = DEFAULT_RECOVERY_HIGH
    ) -> bool:
        values = self.measured_recoveries()
        return bool(values) and all(low <= r <= high for r in values)

    def blank_residual(self) -> float:
        """How far the curve sits from the measured blank signal."""
        for index, point in enumerate(self.points):
            if point.concentration == 0 and index < len(self.residuals):
                return self.residuals[index]
        return float("nan")

    def table(self) -> list[tuple[str, float, float, float, float, float]]:
        """(label, concentration, signal, fitted, residual, recovery) per point."""
        rows = []
        for index, point in enumerate(self.points):
            rows.append(
                (
                    point.label or f"C{index + 1}",
                    point.concentration,
                    point.signal,
                    self.fitted[index] if index < len(self.fitted) else float("nan"),
                    self.residuals[index] if index < len(self.residuals) else float("nan"),
                    self.recoveries[index] if index < len(self.recoveries) else float("nan"),
                )
            )
        return rows

    def report(self, low: float = DEFAULT_RECOVERY_LOW, high: float = DEFAULT_RECOVERY_HIGH) -> str:
        lines = list(self.params.describe())
        lines.append("")
        lines.append(
            f"points: {len(self.points)}   iterations: {self.iterations}   "
            f"converged: {'yes' if self.converged else 'no'}"
        )
        if self.blank_pinned:
            lines.append(
                "blank: pinned to the measured zero-calibrator signal "
                f"(a = {self.params.a:.6g})"
            )
        lines.append(f"R^2: {self.r_squared:.6f}   RMSE: {self.rmse:.6g}")
        lines.append("")
        header = (
            f"{'point':>8} {'conc':>12} {'signal':>14} {'fitted':>14} "
            f"{'resid':>12} {'recovery%':>10}"
        )
        lines.append(header)
        lines.append("-" * len(header))
        for label, conc, sig, fit, resid, rec in self.table():
            if math.isnan(rec):
                shown, flag = "     blank", ""
            else:
                shown = f"{rec:10.2f}"
                flag = "" if low <= rec <= high else "  <-- outside"
            lines.append(
                f"{label:>8} {conc:12.4f} {sig:14.4f} {fit:14.4f} {resid:12.4f} {shown}{flag}"
            )
        lines.append("")
        verdict = "PASS" if self.recoveries_ok(low, high) else "REVIEW"
        lines.append(
            f"recovery acceptance {low:.0f}-{high:.0f}% on measured points: {verdict} "
            f"(worst deviation {self.worst_recovery_deviation():.2f}%)"
        )
        blank = self.blank_residual()
        if not math.isnan(blank):
            lines.append(f"blank residual: {blank:+.4f} (curve vs measured zero signal)")
        return "\n".join(lines)


def _initial_guess(points: list[Point], model: str) -> np.ndarray:
    ordered = sorted(points, key=lambda p: p.concentration)
    xs = np.array([p.concentration for p in ordered], dtype=float)
    ys = np.array([p.signal for p in ordered], dtype=float)

    # The zero calibrator is the anchor for 'a'. If the model is allowed to
    # extrapolate 'a' freely it drifts to a negative number that fits the curved
    # part better, and then every reported recovery at the low end is wrong.
    a0 = float(ys[0])
    d0 = float(ys[-1]) * 1.15 if ys[-1] != 0 else 1.0
    positive = xs[xs > 0]
    c0 = float(np.exp(np.mean(np.log(positive)))) if positive.size else 1.0

    slope = 1.0

    if abs(d0 - a0) < 1e-12:
        d0 = a0 + 1.0

    guess = [a0, slope, c0, d0]
    if model == "5pl":
        guess.append(1.0)
    return np.array(guess, dtype=float)


def _zero_point_index(points: list[Point]) -> int | None:
    for index, point in enumerate(points):
        if point.concentration == 0:
            return index
    return None


def fit_calibration(
    points: list[Point],
    *,
    model: str = "4pl",
    max_iterations: int = 200,
    tolerance: float = 1e-10,
    pin_blank: bool = True,
) -> FitResult:
    """Least-squares fit, with the blank handled honestly.

    Immunoassay curves are usually fitted with the zero calibrator included, but
    its measured signal is what defines ``a`` -- the response at zero. Letting the
    solver move ``a`` away from the measured blank produces a curve that fits the
    middle better and reports nonsense at the bottom of the range.

    When ``pin_blank`` is set and a zero calibrator exists, ``a`` is held at its
    measured signal and only ``b``, ``c``, ``d`` (and ``g``) are fitted. The blank
    then recovers exactly, by construction, and the remaining points are tested on
    their own merit.
    """
    if model not in ("4pl", "5pl"):
        raise CalibrationError("model must be '4pl' or '5pl'")
    if len(points) < 4:
        raise CalibrationError(
            f"a {model.upper()} needs at least 4 calibrators, got {len(points)}"
        )
    if model == "5pl" and len(points) < 5:
        raise CalibrationError("a 5PL needs at least 5 calibrators")
    for point in points:
        point.validate()

    ordered = sorted(points, key=lambda p: p.concentration)
    xs = np.array([p.concentration for p in ordered], dtype=float)
    ys = np.array([p.signal for p in ordered], dtype=float)
    ws = np.array([p.weight for p in ordered], dtype=float)

    if len(set(xs.tolist())) < len(xs):
        raise CalibrationError("two calibrators share the same concentration")
    if len(set(ys.tolist())) < 2:
        raise CalibrationError("all signals are identical; no curve to fit")

    blank_index = _zero_point_index(ordered)
    free_a = not (pin_blank and blank_index is not None)

    def expand(theta_free: np.ndarray) -> np.ndarray:
        """Map the free parameters onto the full parameter vector."""
        if free_a:
            return theta_free
        return np.insert(theta_free, 0, ys[blank_index])  # type: ignore[index]

    theta_full = _initial_guess(ordered, model)
    if not free_a:
        theta_full[0] = ys[blank_index]  # type: ignore[index]
        theta = np.delete(theta_full, 0)
    else:
        theta = theta_full

    residual = _residual_vector(expand(theta), xs, ys, ws, model)
    cost = float(residual @ residual)
    lam = 1e-2
    iterations = 0
    converged = False

    for iterations in range(1, max_iterations + 1):
        jacobian = np.zeros((xs.size, theta.size), dtype=float)
        for column in range(theta.size):
            step = max(abs(theta[column]) * 1e-6, 1e-9)
            shifted = theta.copy()
            shifted[column] += step
            jacobian[:, column] = (
                _residual_vector(expand(shifted), xs, ys, ws, model) - residual
            ) / step

        gradient = jacobian.T @ residual
        normal = jacobian.T @ jacobian

        improved = False
        for _ in range(12):
            damped = normal + lam * np.diag(np.maximum(np.diag(normal), 1e-12))
            try:
                delta = np.linalg.solve(damped, -gradient)
            except np.linalg.LinAlgError:
                lam *= 10.0
                continue

            candidate = theta + delta
            candidate_residual = _residual_vector(expand(candidate), xs, ys, ws, model)
            candidate_cost = float(candidate_residual @ candidate_residual)

            if math.isfinite(candidate_cost) and candidate_cost <= cost:
                relative = (cost - candidate_cost) / max(cost, 1e-30)
                theta, residual, cost = candidate, candidate_residual, candidate_cost
                lam = max(lam / 3.0, 1e-12)
                improved = True
                if relative < tolerance:
                    converged = True
                break
            lam *= 8.0

        if converged:
            break
        if not improved:
            converged = True
            break

    params = _unpack(expand(theta), model)
    fitted = [_predict(params, float(x)) for x in xs]
    residuals = [float(f - y) for f, y in zip(fitted, ys)]

    # Recovery uses the *measured* signal, which is what makes it a real check.
    recoveries: list[float] = []
    for point in ordered:
        back = _inverse(params, point.signal)
        if point.concentration == 0:
            # A zero calibrator has no concentration to recover to a percentage of.
            # It is judged by whether the curve passes through it, i.e. residual.
            recoveries.append(float("nan"))
        elif math.isnan(back):
            recoveries.append(float("nan"))
        else:
            recoveries.append(back / point.concentration * 100.0)

    return FitResult(
        params=params,
        points=ordered,
        fitted=fitted,
        residuals=residuals,
        recoveries=recoveries,
        iterations=iterations,
        converged=converged,
        blank_pinned=not free_a,
    )


def _unpack(theta: np.ndarray, model: str) -> Params:
    if model == "5pl":
        a, b, c, d, g = theta
        return Params(a=float(a), b=float(b), c=float(abs(c)) or 1e-9, d=float(d),
                      g=float(abs(g)) or 1e-9, model="5pl")
    a, b, c, d = theta
    return Params(a=float(a), b=float(b), c=float(abs(c)) or 1e-9, d=float(d), model="4pl")


def _residual_vector(theta: np.ndarray, xs: np.ndarray, ys: np.ndarray,
                     weights: np.ndarray, model: str) -> np.ndarray:
    params = _unpack(theta, model)
    model_values = np.array([_predict(params, float(x)) for x in xs], dtype=float)
    return (model_values - ys) * np.sqrt(weights)


def fit(
    points: list[Point],
    *,
    model: str = "4pl",
    max_iterations: int = 200,
    tolerance: float = 1e-10,
    pin_blank: bool = True,
) -> FitResult:
    """Fit a curve. Thin alias for :func:`fit_calibration`.

    Kept as a short name because callers read better as ``calib.fit(points)``.
    """
    return fit_calibration(
        points,
        model=model,
        max_iterations=max_iterations,
        tolerance=tolerance,
        pin_blank=pin_blank,
    )


def plausible(result: FitResult, points: list[Point]) -> list[str]:
    """Reasons a fitted curve should not be trusted, in plain words.

    A fit can score well on the calibrators and still be nonsense. The classic
    failure is parameter degeneracy in the 5PL: a large ``g`` paired with a large
    ``c`` can cancel out and produce a curve that passes near every calibrator
    while describing the wrong shape between them. The tell-tale is an inflection
    point outside the measured range, which means every sample result would be an
    extrapolation.

    These are warnings, not refusals -- the operator may have a reason -- but a
    curve that trips them should not be adopted without a second look.
    """
    problems: list[str] = []
    concentrations = [p.concentration for p in points if p.concentration > 0]
    if not concentrations:
        return problems

    low, high = min(concentrations), max(concentrations)
    c = result.params.c

    if c < low / 10.0 or c > high * 10.0:
        problems.append(
            f"inflection point c = {c:.4g} is far outside the measured range "
            f"({low:g} to {high:g}); results across the range would be extrapolated"
        )

    if result.params.model == "5pl":
        g = result.params.g
        if g < 0.33 or g > 3.0:
            problems.append(
                f"asymmetry g = {g:.4g} is far from 1; a 5PL with a large g paired "
                f"with a large c can fit the calibrators while describing the wrong "
                f"curve between them"
            )
        if c > high:
            problems.append(
                f"inflection c = {c:.4g} lies beyond the highest calibrator "
                f"({high:g}); the top of the curve is not supported by data"
            )

    if result.params.b <= 0:
        problems.append(f"slope b = {result.params.b:.4g} is not positive; the curve "
                        f"would not increase with concentration")

    span = abs(result.params.d - result.params.a)
    if span == 0:
        problems.append("the curve has no span between a and d")

    return problems


def best_fit(points: list[Point], **kwargs) -> FitResult:
    """Fit both models when the data allows, and keep the defensible one.

    A 5PL is only chosen when it earns its extra parameter. Two guards:

    * An asymmetry within a few percent of 1 is doing nothing, so the simpler
      model wins rather than chasing a rounding difference.
    * A 5PL that fits better but produces an implausible shape is rejected. Better
      residuals on the calibrators do not compensate for a curve that would give
      wrong answers between them.
    """
    four = fit(points, model="4pl", **kwargs)
    if len(points) < 5:
        return four

    try:
        five = fit(points, model="5pl", **kwargs)
    except CalibrationError:
        return four

    if not (math.isfinite(five.rmse) and math.isfinite(four.rmse)):
        return four

    # An asymmetry close to 1 means the extra parameter does nothing.
    if abs(five.params.g - 1.0) < 0.05:
        return four

    # Only accept the 5PL when it genuinely improves the fit.
    if four.rmse > 0 and five.rmse < four.rmse * 0.90:
        # ... and only when its shape is believable, and no less believable than
        # the 4PL's.
        if len(plausible(five, points)) <= len(plausible(four, points)):
            return five

    return four


def back_calculate(result: FitResult, signal: float) -> float:
    """Concentration for a measured signal, using the fitted curve."""
    return _inverse(result.params, signal)


def read_points_csv(path: str) -> list[Point]:
    """Load calibrators from CSV with columns concentration,signal[,weight,label]."""
    import csv

    points: list[Point] = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise CalibrationError("the CSV has no header row")
        names = {name.strip().lower() for name in reader.fieldnames}
        if not {"concentration", "signal"} <= names:
            raise CalibrationError("the CSV needs 'concentration' and 'signal' columns")

        for row_number, row in enumerate(reader, start=2):
            cleaned = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            if not cleaned.get("concentration") and not cleaned.get("signal"):
                continue
            try:
                points.append(
                    Point(
                        concentration=float(cleaned["concentration"]),
                        signal=float(cleaned["signal"]),
                        weight=float(cleaned.get("weight") or 1.0),
                        label=cleaned.get("label", ""),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise CalibrationError(f"row {row_number}: {exc}") from exc
    if not points:
        raise CalibrationError("no calibrator rows found")
    return points
