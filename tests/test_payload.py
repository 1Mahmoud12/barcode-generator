"""Checks for long payload reproduction.

The calibration QR from a real pack is 712 characters and encodes as a 105x105
symbol. Reproducing it is the highest-risk thing this tool does: a single changed
character means different numbers, printed confidently. These tests pin that down.
"""

from __future__ import annotations

import base64
import os
import tempfile
import unittest

import pypdfium2 as pdfium
import zxingcpp

from bcgen import kind, pack, payload
from bcgen.kind import Item, Kind

# A real calibration QR payload, captured from a pack. It is stored here as test
# data because the whole point is byte-exact reproduction.
CALIBRATION = (
    "RCwzODAsWWZTQW53QUE0bywyMDI1MDkwMiwyMDI3MDQxNCwyLDEwJDAuMDAwMDAwfDE5N3wx"
    "LjAwMDAwMCQxLjI1MDAwMHwyNjgwfDEuMDAwMDAwJDYuNTYwMDAwfDE0MDcxfDEuMDAwMDAw"
    "JDE2Ljk5MDAwMHwzNjU3NnwxLjAwMDAwMCQzMy43NDAwMDB8NzUyOTN8MS4wMDAwMDAkNjgu"
    "ODUwMDAwfDE2MTg2NnwxLjAwMDAwMCQxMDcuODMwMDAwfDI1ODQyN3wxLjAwMDAwMCQxNzUu"
    "NDgwMDAwfDQxMjExNHwxLjAwMDAwMCQyMTUuMzUwMDAwfDUxNzQxM3wxLjAwMDAwMCQyNjcu"
    "NzcwMDAwfDYzNDU5OHwxLjAwMDAwMCQxOTcuMDA3MTcwfDIwNjI4MS4zMTU4MTN8MS4wMzY0"
    "NzF8NjM0NDAxMTk3LjAwNzE2OSwzJDB8Mi4wMDAwMDB8MC4wMDAwMDB8NDAwMHwxMHwxfDAu"
    "NTAwMDAwfDAuMDAwMDAwJDB8MC4yMDAwMDB8OS43MDAwMDB8MzE0Mzl8ODM4NHwxfDIuMDAw"
    "MDAwfDAuNTAwMDAwJDB8MC4yMDAwMDB8MTQ1LjUyMDAwMHw1MTU2Mjd8MTM3NTAwfDF8Mi4w"
    "MDAwMDB8MC41MDAwMDAkMS4wMDAwMDB8MS4wMDAwMDAsMSwxLDEsMSwxLDI5Njg5"
)


class Base64Tests(unittest.TestCase):
    def test_recognises_base64(self) -> None:
        self.assertTrue(payload.looks_like_base64(CALIBRATION))

    def test_rejects_plain_text(self) -> None:
        self.assertFalse(payload.looks_like_base64("TSH;Cal1"))
        self.assertFalse(payload.looks_like_base64("not base64 at all!!"))
        self.assertFalse(payload.looks_like_base64(""))

    def test_rejects_wrong_padding(self) -> None:
        self.assertFalse(payload.looks_like_base64(CALIBRATION[:-1]))

    def test_decodes_to_expected_length(self) -> None:
        self.assertEqual(len(payload.unbase64(CALIBRATION)), 534)

    def test_bad_base64_raises(self) -> None:
        with self.assertRaises(payload.PayloadError):
            payload.unbase64("!!!not-base64!!!")


class RoundTripTests(unittest.TestCase):
    def test_real_payload_round_trips(self) -> None:
        trip = payload.round_trip(CALIBRATION)
        self.assertTrue(trip.exact)
        self.assertEqual(trip.reencoded, CALIBRATION)

    def test_single_character_change_is_detected(self) -> None:
        broken = CALIBRATION[:-1] + ("A" if CALIBRATION[-1] != "A" else "B")
        # Still valid base64 in length, but must not silently equal the original.
        if payload.looks_like_base64(broken):
            self.assertNotEqual(payload.reencode(payload.unbase64(broken)), CALIBRATION)

    def test_plain_text_round_trips_through_utf8(self) -> None:
        text = "TSH;Cal1;Lot20250902"
        self.assertEqual(base64.b64decode(base64.b64encode(text.encode())).decode(), text)


class StructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.info = payload.structure(CALIBRATION)

    def test_header_split(self) -> None:
        self.assertEqual(len(self.info.header), 7)

    def test_assay_code(self) -> None:
        # 380 is the LH assay number, which corroborates the label reading
        # "iFlash-LH" on the same carton.
        self.assertEqual(self.info.assay_code, "380")

    def test_lot_and_expiry_visible(self) -> None:
        self.assertEqual(self.info.lot, "20250902")
        self.assertEqual(self.info.expiry, "20270414")

    def test_sections_counted(self) -> None:
        self.assertEqual(len(self.info.sections), 15)

    def test_summary_is_text(self) -> None:
        for line in self.info.summary():
            self.assertIsInstance(line, str)


class ReproducibilityTests(unittest.TestCase):
    def test_real_payload_has_no_problems(self) -> None:
        self.assertEqual(payload.check_reproducible(CALIBRATION), [])

    def test_empty_payload_flagged(self) -> None:
        self.assertTrue(payload.check_reproducible(""))

    def test_module_count_matches_symbol(self) -> None:
        self.assertEqual(kind.qr_modules(CALIBRATION), 105)

    def test_min_square_grows_with_module_size(self) -> None:
        small = payload.min_square_mm(CALIBRATION, 300, 2)
        large = payload.min_square_mm(CALIBRATION, 300, 3)
        self.assertLess(small, large)


class LongQRTests(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)

    def tearDown(self) -> None:
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_long_qr_prints_and_decodes_exactly(self) -> None:
        items = [Item(Kind.PACKAGE, CALIBRATION)]
        pack.build_pack_sheet(self.path, items, dpi=300)

        doc = pdfium.PdfDocument(self.path)
        try:
            image = doc[0].render(scale=300 / 72).to_pil()
        finally:
            doc.close()

        found = [r.text for r in zxingcpp.read_barcodes(image)]
        self.assertIn(CALIBRATION, found)

    def test_both_qrs_get_a_printable_module(self) -> None:
        # Square size is the wrong invariant: a 105-module symbol and a 21-module
        # symbol can end up the same physical size while their modules differ by
        # 4x. What matters is dots per module.
        short = pack.build_pack_sheet(
            self.path, [Item(Kind.PACKAGE, "IQEA35yQjQ")], dpi=300
        )
        long_place = pack.build_pack_sheet(
            self.path, [Item(Kind.PACKAGE, CALIBRATION)], dpi=300
        )
        self.assertGreaterEqual(short[0].module_dots, pack.MIN_QR_MODULE_DOTS)
        self.assertGreaterEqual(long_place[0].module_dots, pack.MIN_QR_MODULE_DOTS)

    def test_long_payload_needs_more_modules(self) -> None:
        self.assertGreater(kind.qr_modules(CALIBRATION), kind.qr_modules("IQEA35yQjQ"))

    def test_long_qr_module_is_printable(self) -> None:
        placements = pack.build_pack_sheet(
            self.path, [Item(Kind.PACKAGE, CALIBRATION)], dpi=300
        )
        self.assertGreaterEqual(placements[0].module_dots, pack.MIN_QR_MODULE_DOTS)


if __name__ == "__main__":
    unittest.main()
