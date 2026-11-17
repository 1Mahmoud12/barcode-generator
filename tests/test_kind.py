"""Checks for the four pack symbol kinds.

The important claims to prove: each kind produces the right symbology, QR is a
full symbol rather than a Micro QR, and every kind decodes back to its exact
text at the sizes the tool actually prints.
"""

from __future__ import annotations

import os
import tempfile
import unittest

import pypdfium2 as pdfium
import zxingcpp

from bcgen import kind, pack, render
from bcgen.kind import Item, Kind, KindError


class KindTests(unittest.TestCase):
    def test_symbology_per_kind(self) -> None:
        self.assertEqual(Kind.TRIGGER.symbology, "Code 128")
        self.assertEqual(Kind.REAGENT.symbology, "Code 128")
        self.assertEqual(Kind.METHOD.symbology, "QR")
        self.assertEqual(Kind.PACKAGE.symbology, "QR")

    def test_two_dimensional_flags(self) -> None:
        self.assertFalse(Kind.TRIGGER.is_two_dimensional)
        self.assertFalse(Kind.REAGENT.is_two_dimensional)
        self.assertTrue(Kind.METHOD.is_two_dimensional)
        self.assertTrue(Kind.PACKAGE.is_two_dimensional)

    def test_default_lengths_match_packs(self) -> None:
        self.assertEqual(Kind.TRIGGER.default_length, 10)
        self.assertEqual(Kind.REAGENT.default_length, 9)


class ValidationTests(unittest.TestCase):
    def test_empty_rejected(self) -> None:
        with self.assertRaises(KindError):
            Item(Kind.TRIGGER, "").validate()

    def test_non_encodable_bar_code_rejected(self) -> None:
        with self.assertRaises(KindError):
            Item(Kind.REAGENT, "café").validate()

    def test_qr_accepts_punctuation(self) -> None:
        Item(Kind.METHOD, "TSH;Cal1;Lot20250902").validate()

    def test_bar_accepts_subset_b(self) -> None:
        Item(Kind.TRIGGER, "IQEApeCg6t").validate()
        Item(Kind.REAGENT, "a+b/cDeFg").validate()


class QRTests(unittest.TestCase):
    def test_full_qr_not_micro(self) -> None:
        # A Micro QR for 'TEST' would be 11 or 13 modules; a full one is 21.
        self.assertEqual(kind.qr_modules("TEST"), 21)

    def test_square_matrix(self) -> None:
        matrix = kind.qr_matrix("iwUMArCYU")
        self.assertEqual(len(matrix), len(matrix[0]))

    def test_modules_grow_with_text(self) -> None:
        small = kind.qr_modules("A")
        large = kind.qr_modules("x" * 120)
        self.assertLess(small, large)

    def test_quiet_zone_is_four(self) -> None:
        self.assertEqual(kind.qr_quiet_modules(), 4)

    def test_size_mm_includes_quiet_zone(self) -> None:
        modules = kind.qr_modules("iwUMArCYU") + 2 * kind.qr_quiet_modules()
        dots = 4
        expected = modules * dots * render.dot_mm(300)
        self.assertAlmostEqual(kind.qr_size_mm("iwUMArCYU", dots, 300), expected, places=6)

    def test_impossible_size_rejected(self) -> None:
        with self.assertRaises(KindError):
            kind.qr_module_dots_for("iwUMArCYU", 1.0, 203)

    def test_module_dots_grow_with_target(self) -> None:
        small = kind.qr_module_dots_for("iwUMArCYU", 20.0, 300)
        large = kind.qr_module_dots_for("iwUMArCYU", 40.0, 300)
        self.assertLess(small, large)


class DecodeTests(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)

    def tearDown(self) -> None:
        if os.path.exists(self.path):
            os.remove(self.path)

    def _decoded(self, dpi: int) -> list[tuple[str, str]]:
        doc = pdfium.PdfDocument(self.path)
        try:
            image = doc[0].render(scale=dpi / 72).to_pil()
        finally:
            doc.close()
        return [(str(r.text), str(r.format).split(".")[-1]) for r in zxingcpp.read_barcodes(image)]

    def _four(self) -> list[Item]:
        return pack.four_standard_items(
            trigger="IQEApeCg6t",
            reagent="iwUMArCYU",
            method_qr="TSH;Cal1;Lot20250902",
            package_qr="IQEA35yQjQ",
        )

    def test_all_four_decode_at_300(self) -> None:
        pack.build_pack_sheet(self.path, self._four(), dpi=300)
        decoded = dict(self._decoded(300))
        self.assertIn("IQEApeCg6t", decoded)
        self.assertIn("iwUMArCYU", decoded)
        self.assertIn("TSH;Cal1;Lot20250902", decoded)
        self.assertIn("IQEA35yQjQ", decoded)

    def test_formats_are_correct(self) -> None:
        pack.build_pack_sheet(self.path, self._four(), dpi=300)
        decoded = dict(self._decoded(300))
        self.assertIn("Code 128", decoded["IQEApeCg6t"])
        self.assertIn("Code 128", decoded["iwUMArCYU"])
        self.assertIn("QR", decoded["TSH;Cal1;Lot20250902"])
        self.assertIn("QR", decoded["IQEA35yQjQ"])

    def test_all_four_decode_at_203(self) -> None:
        pack.build_pack_sheet(self.path, self._four(), dpi=203)
        decoded = dict(self._decoded(203))
        self.assertEqual(len(decoded), 4)

    def test_single_item_prints(self) -> None:
        pack.build_pack_sheet(self.path, [Item(Kind.REAGENT, "iwUMArCYU")], dpi=300)
        decoded = dict(self._decoded(300))
        self.assertEqual(list(decoded), ["iwUMArCYU"])

    def test_caps_are_respected(self) -> None:
        placements = pack.build_pack_sheet(
            self.path,
            self._four(),
            dpi=300,
            bar_width_mm=40.0,
            qr_square_mm=20.0,
        )
        for placement in placements:
            if placement.item.kind.is_two_dimensional:
                self.assertLessEqual(placement.width_mm, 20.05)
            else:
                self.assertLessEqual(placement.width_mm, 40.05)

    def test_roll_page_narrower(self) -> None:
        pack.build_pack_sheet(
            self.path,
            self._four(),
            page_width_mm=76.0,
            page_height_mm=160.0,
            dpi=203,
        )
        decoded = dict(self._decoded(203))
        self.assertEqual(len(decoded), 4)

    def test_empty_list_refused(self) -> None:
        with self.assertRaises(pack.PackError):
            pack.build_pack_sheet(self.path, [], dpi=300)


class FourItemsTests(unittest.TestCase):
    def test_order_and_kinds(self) -> None:
        items = pack.four_standard_items(
            trigger="A123456789",
            reagent="iwUMArCYU",
            method_qr="M",
            package_qr="P",
        )
        self.assertEqual(
            [i.kind for i in items],
            [Kind.TRIGGER, Kind.REAGENT, Kind.METHOD, Kind.PACKAGE],
        )

    def test_texts_preserved_exactly(self) -> None:
        items = pack.four_standard_items(
            trigger="IQEApeCg6t",
            reagent="a+b/cDeFg",
            method_qr="Keep Case;And=Symbols",
            package_qr="IQEA35yQjQ",
        )
        self.assertEqual(items[0].text, "IQEApeCg6t")
        self.assertEqual(items[1].text, "a+b/cDeFg")
        self.assertEqual(items[2].text, "Keep Case;And=Symbols")


if __name__ == "__main__":
    unittest.main()
