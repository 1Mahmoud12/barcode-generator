"""Checks for the Trigger and Pre-Trigger bottle labels.

Two claims need proving: the bottle code is drawn with its ten characters intact,
and the GS1 DataMatrix carries the right application identifiers with a real FNC1
so a reader parses them rather than returning them as literal text.
"""

from __future__ import annotations

import os
import tempfile
import unittest

import pypdfium2 as pdfium
import zxingcpp

from bcgen import solution
from bcgen.solution import SolutionError, SolutionLabel


def trigger(volume: int = 450, code: str = "IQEApeCg6t", gtin: str = "06925912716570") -> SolutionLabel:
    return SolutionLabel(
        kind="trigger",
        code=code,
        volume_ml=volume,
        lot="20250902",
        produced="2025-09-02",
        expiry="2027-04-14",
        gtin=gtin,
        internal="003067",
    )


class ValidationTests(unittest.TestCase):
    def test_valid_trigger(self) -> None:
        trigger().validate()

    def test_valid_pretrigger(self) -> None:
        SolutionLabel(
            kind="pretrigger", code="wEEPoNc1+4", volume_ml=800,
            lot="20220401", produced="2022-04-01", expiry="2023-04-12",
        ).validate()

    def test_unknown_kind(self) -> None:
        with self.assertRaises(SolutionError):
            SolutionLabel(kind="reagent", code="IQEApeCg6t", lot="L", expiry="2027-04-14").validate()

    def test_wrong_length_rejected(self) -> None:
        # Nine characters is a cartridge code, not a bottle code. Catching this
        # prevents a cartridge payload being printed on a trigger bottle.
        with self.assertRaises(SolutionError) as caught:
            trigger(code="iwUMArCYU").validate()
        self.assertIn("10", str(caught.exception))

    def test_empty_code(self) -> None:
        with self.assertRaises(SolutionError):
            trigger(code="").validate()

    def test_bad_gtin_length(self) -> None:
        with self.assertRaises(SolutionError):
            trigger(gtin="6925912716570").validate()

    def test_gtin_must_be_digits(self) -> None:
        with self.assertRaises(SolutionError):
            trigger(gtin="0692591271657X").validate()

    def test_lot_required(self) -> None:
        label = trigger()
        label.lot = ""
        with self.assertRaises(SolutionError):
            label.validate()

    def test_expiry_required(self) -> None:
        label = trigger()
        label.expiry = ""
        with self.assertRaises(SolutionError):
            label.validate()

    def test_zero_volume(self) -> None:
        with self.assertRaises(SolutionError):
            trigger(volume=0).validate()

    def test_non_latin_rejected(self) -> None:
        label = trigger()
        label.product = "محلول"
        with self.assertRaises(SolutionError):
            label.validate()


class Gs1Tests(unittest.TestCase):
    def test_date_conversion(self) -> None:
        self.assertEqual(solution.to_gs1_date("2027-04-14"), "270414")
        self.assertEqual(solution.to_gs1_date("20270414"), "270414")
        self.assertEqual(solution.to_gs1_date("270414"), "270414")

    def test_bad_date_raises(self) -> None:
        with self.assertRaises(SolutionError):
            solution.to_gs1_date("not a date")

    def test_elements_in_ai_order(self) -> None:
        ais = [ai for ai, _ in trigger().gs1_elements()]
        self.assertEqual(ais, ["01", "11", "17", "10", "91"])

    def test_bracketed_string_for_zint(self) -> None:
        text = trigger().gs1_string()
        self.assertTrue(text.startswith("[01]06925912716570"))
        self.assertIn("[17]270414", text)
        self.assertIn("[10]20250902", text)

    def test_human_readable_lines(self) -> None:
        lines = trigger().human_gs1_lines()
        self.assertIn("(01) 06925912716570", lines)
        self.assertIn("(17) 270414", lines)

    def test_optional_elements_omitted(self) -> None:
        label = SolutionLabel(
            kind="trigger", code="IQEApeCg6t", volume_ml=200,
            lot="L1", expiry="2027-04-14",
        )
        ais = [ai for ai, _ in label.gs1_elements()]
        self.assertNotIn("01", ais)
        self.assertNotIn("11", ais)
        self.assertIn("17", ais)


class ZintTests(unittest.TestCase):
    def setUp(self) -> None:
        if not solution.zint_available():
            self.skipTest("zint not installed")

    def test_datamatrix_decodes_with_ais(self) -> None:
        label = trigger()
        path = solution.gs1_datamatrix_png(label)
        try:
            self.assertEqual(solution.verify_datamatrix(path, label), [])
        finally:
            os.path.exists(path) and os.remove(path)

    def test_datamatrix_bytes_start_with_gtin(self) -> None:
        # The real test of FNC1: the decoded bytes must begin with the AI digits
        # directly, not with a literal "[01]" string.
        label = trigger()
        path = solution.gs1_datamatrix_png(label)
        try:
            from PIL import Image

            results = zxingcpp.read_barcodes(Image.open(path))
            self.assertTrue(results)
            payload = results[0].bytes
            self.assertEqual(payload[:2], b"01")
            self.assertIn(b"06925912716570", payload)
        finally:
            os.path.exists(path) and os.remove(path)


class LabelBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)

    def tearDown(self) -> None:
        if os.path.exists(self.path):
            os.remove(self.path)

    def _decode(self, dpi: int = 300) -> list[tuple[str, str]]:
        doc = pdfium.PdfDocument(self.path)
        try:
            image = doc[0].render(scale=dpi / 72).to_pil()
        finally:
            doc.close()
        return [(r.text, str(r.format).split(".")[-1]) for r in zxingcpp.read_barcodes(image)]

    def test_code128_decodes_all_three_sizes(self) -> None:
        labels = [
            trigger(200, "IQEApeCg6t", "06925912716570"),
            trigger(450, "IQEApfCg6t", "06925912716587"),
            trigger(800, "IQEApgCg6t", "06925912716594"),
        ]
        solution.build_solution_sheet(self.path, labels, dpi=300, with_datamatrix=False)
        codes = [text for text, fmt in self._decode() if "Code" in fmt]
        self.assertIn("IQEApeCg6t", codes)
        self.assertIn("IQEApfCg6t", codes)
        self.assertIn("IQEApgCg6t", codes)

    def test_duplicate_code_flagged(self) -> None:
        labels = [
            trigger(200, "IQEApeCg6t", "06925912716570"),
            trigger(450, "IQEApeCg6t", "06925912716587"),
        ]
        problems = solution.build_solution_sheet(self.path, labels, with_datamatrix=False)
        self.assertTrue(any("used twice" in p for p in problems))

    def test_shared_gtin_across_sizes_flagged(self) -> None:
        labels = [
            trigger(200, "IQEApeCg6t", "06925912716570"),
            trigger(450, "IQEApfCg6t", "06925912716570"),
        ]
        problems = solution.build_solution_sheet(self.path, labels, with_datamatrix=False)
        self.assertTrue(any("own GTIN" in p for p in problems))

    def test_same_gtin_same_size_is_fine(self) -> None:
        # Many bottles of one size share a GTIN; that is normal.
        labels = [
            trigger(450, "IQEApeCg6t", "06925912716570"),
            trigger(450, "IQEApfCg6t", "06925912716570"),
        ]
        problems = solution.build_solution_sheet(self.path, labels, with_datamatrix=False)
        self.assertEqual(problems, [])

    def test_copies_produce_pages(self) -> None:
        label = trigger()
        label.copies = 3
        solution.build_solution_sheet(
            self.path, [label], dpi=203, label_width_mm=90, label_height_mm=200,
            with_datamatrix=False,
        )
        doc = pdfium.PdfDocument(self.path)
        pages = len(doc)
        doc.close()
        self.assertGreaterEqual(pages, 1)

    def test_too_small_label_refused(self) -> None:
        with self.assertRaises(SolutionError):
            solution.build_solution_sheet(
                self.path, [trigger()], label_width_mm=40, label_height_mm=20,
                with_datamatrix=False,
            )

    def test_empty_list_refused(self) -> None:
        with self.assertRaises(SolutionError):
            solution.build_solution_sheet(self.path, [], with_datamatrix=False)


class LayoutTests(unittest.TestCase):
    def test_auto_layout_fits(self) -> None:
        layout = solution.auto_layout("IQEApeCg6t", 90.0, 45.0, 300)
        self.assertGreater(layout.bar_height_mm, 0)
        self.assertLessEqual(layout.bar_height_mm, 14.0)

    def test_smaller_label_gives_smaller_bar(self) -> None:
        big = solution.auto_layout("IQEApeCg6t", 90.0, 60.0, 300)
        small = solution.auto_layout("IQEApeCg6t", 90.0, 40.0, 300)
        self.assertGreaterEqual(big.bar_height_mm, small.bar_height_mm)

    def test_label_too_small_raises(self) -> None:
        with self.assertRaises(SolutionError):
            solution.auto_layout("IQEApeCg6t", 60.0, 32.0, 300)


if __name__ == "__main__":
    unittest.main()
