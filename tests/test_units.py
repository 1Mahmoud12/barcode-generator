"""Unit checks for the encoder, layout and read verifier.

These are the fast checks that run without a printer or a scanner. The heavier
render-decode checks live in ``selftest.py``.
"""

from __future__ import annotations

import unittest

from bcgen import code128, generate, render, sheet


class EncoderTests(unittest.TestCase):
    def test_module_count_formula(self) -> None:
        for text in ("A", "iwUMArCYU", "AE_Check9", "         ", "~" * 20):
            self.assertEqual(
                code128.module_count(text),
                11 + 11 * len(text) + 11 + 13,
                f"wrong module count for {text!r}",
            )

    def test_start_and_stop_patterns(self) -> None:
        bits = code128.modules("A")
        self.assertTrue(bits.startswith("11010010000"), "missing Start B")
        self.assertTrue(bits.endswith("1100011101011"), "wrong stop pattern")

    def test_checksum_is_position_weighted(self) -> None:
        # Subset B values: 'A' is 33, 'B' is 34.
        # Checksum = start value + sum(position * value) for 1-based positions.
        checksum = (104 + 1 * 33 + 2 * 34) % 103
        self.assertEqual(checksum, 102)

        widths = code128.ELEMENT_WIDTHS[checksum]
        bits = []
        is_bar = 1
        for width in widths:
            bits.append(("1" if is_bar else "0") * int(width))
            is_bar ^= 1

        self.assertIn("".join(bits), code128.modules("AB"))

    def test_rejects_non_subset_b(self) -> None:
        for bad in ("é", "Ω", "\t", "\n", "\x00"):
            with self.assertRaises(code128.Code128Error):
                code128.modules(bad)

    def test_rejects_empty(self) -> None:
        with self.assertRaises(code128.Code128Error):
            code128.modules("")

    def test_bar_runs_are_contiguous(self) -> None:
        bars = code128.bars("iwUMArCYU", 4)
        self.assertGreater(len(bars), 0)
        for start, width in bars:
            self.assertGreater(width, 0)
            self.assertEqual(start % 4, 0, "bar does not start on a module boundary")
            self.assertEqual(width % 4, 0, "bar width is not a module multiple")


class GeometryTests(unittest.TestCase):
    def test_dot_size(self) -> None:
        self.assertAlmostEqual(render.dot_mm(600), 25.4 / 600, places=9)
        self.assertAlmostEqual(render.dot_mm(300), 25.4 / 300, places=9)

    def test_x_dimension_matches_dots(self) -> None:
        geo = render.geometry("iwUMArCYU", 6, 600)
        self.assertAlmostEqual(geo.x_mm, 6 * 25.4 / 600, places=9)
        self.assertEqual(geo.modules, 134)
        self.assertAlmostEqual(geo.symbol_mm, 134 * geo.x_mm, places=9)

    def test_quiet_zone_included_in_total(self) -> None:
        geo = render.geometry("iwUMArCYU", 4, 600)
        self.assertAlmostEqual(geo.total_mm, geo.symbol_mm + 20 * geo.x_mm, places=9)

    def test_snapping_lands_on_grid(self) -> None:
        for dpi in (300, 600):
            dot = render.dot_mm(dpi)
            for raw in (0.0, 7.3, 12.777, 99.999):
                snapped = render.snap_to_dot(raw, dpi)
                self.assertAlmostEqual(snapped / dot, round(snapped / dot), places=6)


class GenerateTests(unittest.TestCase):
    def test_reproducible_with_seed(self) -> None:
        a = generate.random_codes(10, seed=42)
        b = generate.random_codes(10, seed=42)
        self.assertEqual([c.text for c in a], [c.text for c in b])

    def test_different_seeds_differ(self) -> None:
        a = generate.random_codes(10, seed=1)
        b = generate.random_codes(10, seed=2)
        self.assertNotEqual([c.text for c in a], [c.text for c in b])

    def test_all_codes_are_distinct(self) -> None:
        codes = generate.random_codes(300, seed=7)
        self.assertEqual(len({c.text for c in codes}), 300)

    def test_length_honoured(self) -> None:
        for length in (4, 9, 16):
            codes = generate.random_codes(5, length=length, seed=3)
            for code in codes:
                self.assertEqual(len(code.text), length)

    def test_alphabet_respected(self) -> None:
        digits = generate.random_codes(20, alphabet="digits", seed=5)
        for code in digits:
            self.assertTrue(code.text.isdigit(), code.text)

    def test_every_code_is_encodable(self) -> None:
        for code in generate.random_codes(50, seed=11):
            code128.modules(code.text)

    def test_sequential_is_readable(self) -> None:
        codes = generate.sequential_codes(3)
        self.assertEqual([c.text for c in codes], ["T000001", "T000002", "T000003"])

    def test_edge_codes_are_encodable(self) -> None:
        for code in generate.edge_codes():
            code128.modules(code.text)


class LayoutTests(unittest.TestCase):
    def test_plan_fits_within_margins(self) -> None:
        codes = generate.random_codes(20, seed=1)
        for dots in (3, 4, 6, 8):
            plan = sheet.plan_page(codes, dots, 600)
            for cell in plan.cells:
                self.assertGreaterEqual(cell.x_mm, sheet.MARGIN_MM - 0.01)
                self.assertLessEqual(
                    cell.x_mm + plan.geo.total_mm,
                    render.A4_WIDTH_MM - sheet.MARGIN_MM + 0.01,
                )

    def test_larger_rungs_hold_fewer_cells(self) -> None:
        codes = generate.random_codes(60, seed=2)
        small = sheet.plan_page(codes, 3, 600)
        large = sheet.plan_page(codes, 10, 600)
        self.assertGreaterEqual(small.capacity, large.capacity)

    def test_oversized_symbol_is_refused(self) -> None:
        codes = generate.random_codes(1, seed=1)
        with self.assertRaises(sheet.SheetError):
            sheet.plan_page(codes, 200, 600)

    def test_cells_are_dot_aligned(self) -> None:
        codes = generate.random_codes(12, seed=4)
        plan = sheet.plan_page(codes, 5, 600)
        dot = render.dot_mm(600)
        for cell in plan.cells:
            self.assertAlmostEqual(cell.x_mm / dot, round(cell.x_mm / dot), places=5)
            self.assertAlmostEqual(cell.y_mm / dot, round(cell.y_mm / dot), places=5)


class VerifyTests(unittest.TestCase):
    def test_exact_match(self) -> None:
        from verify_read import Verdict

        self.assertTrue(Verdict("abc123", "abc123").exact)

    def test_first_difference(self) -> None:
        from verify_read import Verdict

        self.assertEqual(Verdict("abcdef", "abXdef").position, 2)

    def test_length_difference(self) -> None:
        from verify_read import Verdict

        verdict = Verdict("abc", "abcde")
        self.assertFalse(verdict.exact)
        self.assertEqual(verdict.position, 3)

    def test_lookalike_is_reported(self) -> None:
        from verify_read import Verdict

        text = Verdict("111111111", "lllllllll").describe()
        self.assertIn("look alike", text)


if __name__ == "__main__":
    unittest.main()
