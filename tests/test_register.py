"""Checks for the print register.

The register exists to catch one specific mistake: a code that belongs to one lot
being printed on a pack counted against another lot. These tests pin that down,
plus the audit properties (append-only, reproducible fingerprints).
"""

from __future__ import annotations

import os
import tempfile
import unittest

from bcgen import register
from bcgen.register import Entry, Register, RegisterError, code_fingerprint


class FingerprintTests(unittest.TestCase):
    def test_stable_for_same_code(self) -> None:
        self.assertEqual(code_fingerprint("iwUMArCYU"), code_fingerprint("iwUMArCYU"))

    def test_differs_for_different_codes(self) -> None:
        self.assertNotEqual(code_fingerprint("iwUMArCYU"), code_fingerprint("iwUMArCYV"))

    def test_short_enough_to_print(self) -> None:
        self.assertEqual(len(code_fingerprint("x")), 16)

    def test_long_payload_does_not_leak(self) -> None:
        long_code = "R" * 712
        fingerprint = code_fingerprint(long_code)
        self.assertNotIn("R" * 10, fingerprint)
        self.assertEqual(len(fingerprint), 16)


class RegisterTestBase(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        os.remove(self.path)
        self.book = Register.load(self.path)

    def tearDown(self) -> None:
        if os.path.exists(self.path):
            os.remove(self.path)

    def entry(self, **overrides) -> Entry:
        base = dict(
            event="print",
            kind="reagent",
            code="iwUMArCYU",
            lot="20250902",
            expiry="2027-04-14",
            product="LH",
            operator="tester",
        )
        base.update(overrides)
        return Entry(**base)


class AppendTests(RegisterTestBase):
    def test_first_entry_written(self) -> None:
        self.book.add(self.entry())
        self.assertTrue(os.path.exists(self.path))
        self.assertEqual(len(self.book.entries), 1)

    def test_header_written_once(self) -> None:
        self.book.add(self.entry())
        self.book.add(self.entry(code="IQEApeCg6t", kind="trigger"))
        with open(self.path, encoding="utf-8") as handle:
            header_count = sum(1 for line in handle if line.startswith("timestamp,"))
        self.assertEqual(header_count, 1)

    def test_reload_round_trip(self) -> None:
        self.book.add(self.entry(code="iwUMArCYU", lot="L1", operator="op1"))
        reloaded = Register.load(self.path)
        self.assertEqual(len(reloaded.entries), 1)
        self.assertEqual(reloaded.entries[0].lot, "L1")
        self.assertEqual(reloaded.entries[0].operator, "op1")

    def test_timestamp_filled(self) -> None:
        entry = self.entry()
        self.book.add(entry)
        self.assertTrue(entry.timestamp)

    def test_fingerprint_filled(self) -> None:
        entry = self.entry()
        self.book.add(entry)
        self.assertEqual(entry.code_sha, code_fingerprint("iwUMArCYU"))


class ConflictTests(RegisterTestBase):
    def test_same_code_twice_as_print_refused(self) -> None:
        self.book.add(self.entry())
        with self.assertRaises(RegisterError) as caught:
            self.book.add(self.entry())
        self.assertIn("already printed", str(caught.exception))

    def test_same_code_as_reprint_allowed(self) -> None:
        self.book.add(self.entry())
        self.book.add(self.entry(event="reprint", notes="label damaged"))
        reprints = [e for e in self.book.entries if e.event == "reprint"]
        self.assertEqual(len(reprints), 1)

    def test_same_code_other_lot_refused(self) -> None:
        self.book.add(self.entry(lot="20250902"))
        with self.assertRaises(RegisterError) as caught:
            self.book.add(self.entry(lot="20260101"))
        message = str(caught.exception)
        self.assertIn("20250902", message)
        self.assertIn("20260101", message)

    def test_same_code_other_product_warns(self) -> None:
        self.book.add(self.entry(product="LH"))
        warnings = self.book.add(
            self.entry(event="reprint", product="TSH"), allow_warnings=True
        )
        self.assertTrue(warnings)
        self.assertTrue(any("reported for" in str(w) or "was recorded" in str(w) for w in warnings))

    def test_warning_can_be_refused(self) -> None:
        self.book.add(self.entry(product="LH"))
        with self.assertRaises(RegisterError):
            self.book.add(
                self.entry(event="reprint", product="TSH"), allow_warnings=False
            )

    def test_voided_entry_does_not_block(self) -> None:
        self.book.add(self.entry())
        self.book.add(self.entry(event="void", notes="voided"))
        # A fresh print after a void is still refused, because the original print
        # remains in the record; that is intentional.
        with self.assertRaises(RegisterError):
            self.book.add(self.entry())

    def test_empty_code_refused(self) -> None:
        with self.assertRaises(RegisterError):
            self.book.add(self.entry(code=""))

    def test_unknown_event_refused(self) -> None:
        with self.assertRaises(RegisterError):
            self.book.add(self.entry(event="deleted"))

    def test_unknown_kind_refused(self) -> None:
        with self.assertRaises(RegisterError):
            self.book.add(self.entry(kind="bottle"))

    def test_different_codes_same_lot_allowed(self) -> None:
        self.book.add(self.entry(code="AAAA111", lot="L1"))
        self.book.add(self.entry(code="BBBB222", lot="L1"))
        self.assertEqual(len(self.book.entries), 2)


class QueryTests(RegisterTestBase):
    def test_for_lot(self) -> None:
        self.book.add(self.entry(code="A1", lot="L1"))
        self.book.add(self.entry(code="B2", lot="L2"))
        self.assertEqual(len(self.book.for_lot("L1")), 1)

    def test_for_code(self) -> None:
        self.book.add(self.entry(code="A1"))
        self.assertEqual(len(self.book.for_code("A1")), 1)
        self.assertEqual(len(self.book.for_code("ZZ")), 0)

    def test_lots_sorted(self) -> None:
        self.book.add(self.entry(code="A1", lot="L2"))
        self.book.add(self.entry(code="B2", lot="L1"))
        self.assertEqual(self.book.lots(), ["L1", "L2"])

    def test_summary_counts(self) -> None:
        self.book.add(self.entry(code="A1"))
        self.book.add(self.entry(code="B2", kind="trigger"))
        summary = "\n".join(self.book.summary())
        self.assertIn("entries: 2", summary)
        self.assertIn("reagent", summary)
        self.assertIn("trigger", summary)


class LotMixingTests(RegisterTestBase):
    def test_clean_register_has_no_conflicts(self) -> None:
        self.book.add(self.entry(code="A1", lot="L1"))
        self.book.add(self.entry(code="B2", lot="L1"))
        self.assertEqual(register.find_lot_mixing(self.book), [])

    def test_detects_code_under_two_lots(self) -> None:
        self.book.add(Entry(event="print", kind="reagent", code="SAME1", lot="L1"))
        # Append directly, bypassing the per-entry check, to simulate a hand edit.
        with open(self.path, "a", newline="", encoding="utf-8") as handle:
            import csv

            writer = csv.DictWriter(handle, fieldnames=register.FIELDS)
            writer.writerow(
                {
                    "timestamp": "2026-01-01T00:00:00",
                    "event": "print",
                    "kind": "reagent",
                    "code": "SAME1",
                    "code_sha": code_fingerprint("SAME1"),
                    "length": 5,
                    "lot": "L2",
                    "expiry": "",
                    "product": "",
                    "cells": "1",
                    "dpi": "300",
                    "source": "",
                    "operator": "",
                    "notes": "",
                }
            )
        book = Register.load(self.path)
        conflicts = register.find_lot_mixing(book)
        self.assertEqual(len(conflicts), 1)
        self.assertIn("L1", str(conflicts[0]))
        self.assertIn("L2", str(conflicts[0]))

    def test_voided_entries_ignored(self) -> None:
        self.book.add(Entry(event="print", kind="reagent", code="X1", lot="L1"))
        self.book.add(Entry(event="void", kind="reagent", code="X1", lot="L2"))
        self.assertEqual(register.find_lot_mixing(self.book), [])


if __name__ == "__main__":
    unittest.main()
