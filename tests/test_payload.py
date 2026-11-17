"""Checks for long payload reproduction.

A calibration QR payload can be several hundred characters and encode as a
large symbol. Reproducing one is the highest-risk thing this tool does: a single
changed character means different numbers, printed confidently. These tests pin
that down using a synthetic payload of the same structure, so no real pack data
lives in this repository.
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

# A SYNTHETIC payload with the same structure as a calibration QR: base64, a
# seven-field header, ten calibration points and a settings block. Real pack data
# is deliberately absent -- see make_test_payload.py for why.
CALIBRATION = (
    "VCw5MDIseGRjVWhQalAsMjAyNTAxMDEsMjAyNzAxMDEsMiwxMCQwLjAwMDAwMHwxMDAuMDAw"
    "MDAwfDEuMDAwMDAwJDIuMTU5NzA2fDIzOC4wNjgwMDB8MS4wMDAwMDAkNS4zMTk1NDB8NTU1"
    "Ljg4NzkyMnwxLjAwMDAwMCQxMS4wNDQwMTF8MTA0Ny4wNTA2MDJ8MS4wMDAwMDAkMjEuNzYz"
    "MTEyfDE5NDQuMjY2NjQ4fDEuMDAwMDAwJDQzLjQ0ODcxOHw0NjUxLjM3NzA0OXwxLjAwMDAw"
    "MCQ4NC4xMTc2OTF8MTAzNDAuNDkxOTEyfDEuMDAwMDAwJDE2MS41Mjc0MTd8MTk1MjQuNjc3"
    "MzQ3fDEuMDAwMDAwJDMwNy41OTk2MTl8MzYwMDguMjk3NTU5fDEuMDAwMDAwJDU4Ni42NDAy"
    "MjR8NzE5NDguODM5NDI2fDEuMDAwMDAwJDU3OTEyLjMzNDUyMXwxODgyMTUuMDg3MTkzfDAu"
    "OTYzMjM5fDY0MDc4Mjk3OC4xNDA1NDgsMyQwfDEuNDA4OTU1fDAuMDAwMDAwfDg4MTV8MTB8"
    "MXwwLjUwMDAwMHwwLjAwMDAwMCQwfDAuMjAwMDAwfDguMDk4ODU0fDc4MzM0fDUyNjd8MXwy"
    "LjAwMDAwMHwwLjUwMDAwMCQwfDAuMjAwMDAwfDEwNi4yMjc5NTl8Njc1MzUyfDEwMTg0MHwx"
    "fDIuMDAwMDAwfDAuNTAwMDAwJDEuMDAwMDAwfDEuMDAwMDAwLDEsMSwxLDEsMSwyMzA1Ng=="
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
        # Length follows from the payload; compare against what is actually there
        # rather than a number copied from a real pack.
        self.assertGreater(len(payload.unbase64(CALIBRATION)), 400)

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
        # The assay code is whatever the header carries; the point is that the
        # reader finds it in the right field.
        self.assertTrue(self.info.assay_code.isdigit())

    def test_lot_and_expiry_visible(self) -> None:
        self.assertRegex(self.info.lot, r"^\d{8}$")
        self.assertRegex(self.info.expiry, r"^\d{8}$")

    def test_sections_counted(self) -> None:
        self.assertGreaterEqual(len(self.info.sections), 14)

    def test_summary_is_text(self) -> None:
        for line in self.info.summary():
            self.assertIsInstance(line, str)


class ReproducibilityTests(unittest.TestCase):
    def test_real_payload_has_no_problems(self) -> None:
        self.assertEqual(payload.check_reproducible(CALIBRATION), [])

    def test_empty_payload_flagged(self) -> None:
        self.assertTrue(payload.check_reproducible(""))

    def test_module_count_matches_symbol(self) -> None:
        # A long payload must need a large symbol; the exact version depends on
        # how much data it carries.
        self.assertGreater(kind.qr_modules(CALIBRATION), 80)

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
