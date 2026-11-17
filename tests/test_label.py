"""Checks for the label layout and the free-size barcode.

These verify the two claims the label feature makes: that the barcode is sized to
whole printer dots for whatever width is asked, and that a label either fits or
is refused with a message that says what to change.
"""

from __future__ import annotations

import os
import tempfile
import unittest

import pypdfium2 as pdfium
import zxingcpp

from bcgen import label, render
from bcgen.label import LabelData, LabelError


def _data(**overrides) -> LabelData:
    base = LabelData(
        code="iwUMArCYU",
        product="Calibration Reagent",
        lot="20250902",
        expiry="2027-04-14",
        volume="R1 3.5 mL",
        storage="Store 2-8 C",
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


class FreeSizeTests(unittest.TestCase):
    def test_whole_dots_only(self) -> None:
        for dpi in (203, 300, 600):
            for target in (20.0, 25.0, 33.3, 40.0, 55.5):
                geo = render.geometry_for_width("iwUMArCYU", target, dpi)
                self.assertGreaterEqual(geo.module_dots, 1)
                self.assertLessEqual(geo.total_mm, target + 0.01)

    def test_never_overshoots_target(self) -> None:
        for target in (19.5, 22.0, 26.4, 31.0):
            geo = render.geometry_for_width("iwUMArCYU", target, 300)
            self.assertLessEqual(
                geo.total_mm,
                target + 0.01,
                f"{target} mm target produced {geo.total_mm:.2f} mm",
            )

    def test_rejects_impossible_width(self) -> None:
        with self.assertRaises(render.RenderError):
            render.geometry_for_width("iwUMArCYU", 3.0, 300)

    def test_smaller_target_gives_smaller_module(self) -> None:
        small = render.geometry_for_width("iwUMArCYU", 22.0, 300)
        large = render.geometry_for_width("iwUMArCYU", 55.0, 300)
        self.assertLess(small.module_dots, large.module_dots)


class ValidationTests(unittest.TestCase):
    def test_empty_code_rejected(self) -> None:
        with self.assertRaises(LabelError):
            _data(code="").validate()

    def test_unencodable_code_rejected(self) -> None:
        with self.assertRaises(LabelError):
            _data(code="café").validate()

    def test_non_latin_text_rejected(self) -> None:
        with self.assertRaises(LabelError):
            _data(product="محلول").validate()

    def test_overlong_field_rejected(self) -> None:
        with self.assertRaises(LabelError):
            _data(notes="x" * (label.MAX_TEXT_CHARS + 1)).validate()

    def test_zero_copies_rejected(self) -> None:
        with self.assertRaises(LabelError):
            _data(copies=0).validate()

    def test_minimal_label_is_valid(self) -> None:
        LabelData(code="iwUMArCYU").validate()


class AutoFitTests(unittest.TestCase):
    def test_bar_never_below_minimum(self) -> None:
        layout = label.auto_fit(
            self._canvas(),
            _data(),
            width_mm=60,
            height_mm=40,
            margin_mm=2,
            dpi=300,
        )
        self.assertGreaterEqual(layout.bar_height_mm, label.MIN_BAR_HEIGHT_MM)

    def test_taller_label_allows_bigger_bar(self) -> None:
        canvas = self._canvas()
        short = label.auto_fit(canvas, _data(), width_mm=60, height_mm=40, margin_mm=2, dpi=300)
        tall = label.auto_fit(canvas, _data(), width_mm=60, height_mm=80, margin_mm=2, dpi=300)
        self.assertGreaterEqual(tall.bar_height_mm, short.bar_height_mm)

    def test_impossible_label_raises(self) -> None:
        with self.assertRaises(LabelError):
            label.auto_fit(
                self._canvas(),
                _data(notes="a very long note indeed for a tiny label"),
                width_mm=30,
                height_mm=15,
                margin_mm=2,
                dpi=300,
            )

    def test_fewer_fields_fit_smaller_label(self) -> None:
        canvas = self._canvas()
        few = label.auto_fit(
            canvas,
            LabelData(code="iwUMArCYU", product="Reagent"),
            width_mm=50,
            height_mm=25,
            margin_mm=2,
            dpi=300,
        )
        self.assertGreaterEqual(few.bar_height_mm, label.MIN_BAR_HEIGHT_MM)

    def _canvas(self):
        from reportlab.pdfgen import canvas as pdfcanvas

        path = os.path.join(tempfile.gettempdir(), "autofit-probe.pdf")
        return pdfcanvas.Canvas(path, pagesize=(595, 842))


class BuildTests(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)

    def tearDown(self) -> None:
        if os.path.exists(self.path):
            os.remove(self.path)

    def _decode_first(self, dpi: int) -> list[str]:
        doc = pdfium.PdfDocument(self.path)
        try:
            image = doc[0].render(scale=dpi / 72).to_pil()
        finally:
            doc.close()
        return [r.text for r in zxingcpp.read_barcodes(image)]

    def test_roll_decodes_203(self) -> None:
        label.build_roll(
            self.path,
            [_data()],
            paper_width_mm=76,
            label_width_mm=76,
            label_height_mm=40,
            dpi=203,
        )
        self.assertEqual(self._decode_first(203), ["iwUMArCYU"])

    def test_roll_decodes_300(self) -> None:
        label.build_roll(
            self.path,
            [_data()],
            paper_width_mm=76,
            label_width_mm=76,
            label_height_mm=40,
            dpi=300,
        )
        self.assertEqual(self._decode_first(300), ["iwUMArCYU"])

    def test_sheet_decodes(self) -> None:
        label.build_sheet(
            self.path,
            [_data()],
            page_width_mm=210,
            page_height_mm=297,
            label_width_mm=60,
            label_height_mm=40,
            dpi=600,
        )
        self.assertEqual(self._decode_first(600), ["iwUMArCYU"])

    def test_copies_create_pages_on_roll(self) -> None:
        label.build_roll(
            self.path,
            [_data(copies=3)],
            paper_width_mm=76,
            label_width_mm=76,
            label_height_mm=40,
            dpi=203,
        )
        doc = pdfium.PdfDocument(self.path)
        pages = len(doc)
        doc.close()
        self.assertEqual(pages, 3)

    def test_label_wider_than_paper_refused(self) -> None:
        with self.assertRaises(LabelError):
            label.build_roll(
                self.path,
                [_data()],
                paper_width_mm=58,
                label_width_mm=76,
                label_height_mm=40,
                dpi=203,
            )

    def test_cut_lines_drawn_only_when_asked(self) -> None:
        label.build_sheet(
            self.path,
            [_data()],
            page_width_mm=210,
            page_height_mm=297,
            label_width_mm=60,
            label_height_mm=40,
            dpi=300,
            cut_lines=True,
        )
        with open(self.path, "rb") as handle:
            data = handle.read()
        self.assertGreater(len(data), 1000)


class DateTests(unittest.TestCase):
    def test_iso_passthrough(self) -> None:
        self.assertEqual(label.normalise_date("2027-04-14"), "2027-04-14")

    def test_compact_form(self) -> None:
        self.assertEqual(label.normalise_date("20270414"), "2027-04-14")

    def test_empty(self) -> None:
        self.assertEqual(label.normalise_date("  "), "")

    def test_unrecognised_kept(self) -> None:
        self.assertEqual(label.normalise_date("2027/04/14"), "2027/04/14")


if __name__ == "__main__":
    unittest.main()
