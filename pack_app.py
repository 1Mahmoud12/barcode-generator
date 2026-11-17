"""Window for the four pack symbols.

Four fields, four symbols, one page. Each field is independent: nothing is
derived, nothing is validated against the others. The point is to type or scan
what is on the pack and get the same characters back on paper.
"""

from __future__ import annotations

import os
import sys
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from bcgen import kind, pack, payload, render
from bcgen.kind import Item, Kind, KindError

PREVIEW_SCALE = 2.2


def _size_box(value: float, low: float, high: float, suffix: str = " mm") -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(1)
    box.setSingleStep(1.0)
    box.setSuffix(suffix)
    box.setValue(value)
    return box


class PackWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pack symbols - trigger, method, package, reagent")
        self.resize(1260, 880)
        self._pdf_path: str | None = None

        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.addWidget(self._build_form(), 0)
        outer.addWidget(self._build_preview(), 1)
        self.setStatusBar(QStatusBar())
        self._status("Enter the four codes, then press Build.")

    def _build_form(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(430)
        layout = QVBoxLayout(panel)

        codes = QGroupBox("The four symbols")
        form = QFormLayout(codes)

        self.trigger = QLineEdit("IQEApeCg6t")
        self.trigger.setMaxLength(10)
        form.addRow("Trigger (Code 128)", self.trigger)

        self.reagent = QLineEdit("iwUMArCYU")
        self.reagent.setMaxLength(9)
        form.addRow("Reagent (Code 128)", self.reagent)

        self.method_qr = QLineEdit("TSH;Cal1;Lot20250902")
        form.addRow("Method (QR)", self.method_qr)

        self.package_qr = QLineEdit("IQEA35yQjQ")
        form.addRow("Package (QR)", self.package_qr)

        self.verify_button = QPushButton("Check package payload")
        self.verify_button.clicked.connect(self._check_payload)
        form.addRow("", self.verify_button)
        layout.addWidget(codes)

        size_box = QGroupBox("Printed size")
        size_form = QFormLayout(size_box)
        self.dpi = QComboBox()
        self.dpi.addItems(["203", "300", "600"])
        self.dpi.setCurrentText("300")
        size_form.addRow("Printer dpi", self.dpi)

        self.bar_width = _size_box(pack.DEFAULT_BAR_WIDTH_MM, 15.0, 190.0)
        size_form.addRow("Max bar width", self.bar_width)

        self.qr_square = _size_box(pack.DEFAULT_QR_MM, 10.0, 120.0)
        size_form.addRow("QR square", self.qr_square)

        self.page_size = QComboBox()
        self.page_size.addItems(["A4 (210x297)", "Roll 76 mm", "Roll 58 mm"])
        size_form.addRow("Page", self.page_size)
        layout.addWidget(size_box)

        build = QPushButton("Build sheet")
        build.setMinimumHeight(36)
        build.clicked.connect(self._build)
        layout.addWidget(build)

        self.save_button = QPushButton("Save PDF...")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save)
        layout.addWidget(self.save_button)

        self.info = QPlainTextEdit()
        self.info.setReadOnly(True)
        self.info.setMaximumHeight(150)
        self.info.setStyleSheet("font-size:11px;")
        layout.addWidget(self.info)

        layout.addStretch(1)
        return panel

    def _build_preview(self) -> QWidget:
        box = QGroupBox("Preview")
        layout = QVBoxLayout(box)
        self.preview = QLabel("Nothing built yet.")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(self.preview)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll, 1)
        return box

    def _status(self, message: str) -> None:
        self.statusBar().showMessage(message, 8000)

    def _collect(self) -> list[Item]:
        items: list[Item] = []
        if self.trigger.text().strip():
            items.append(Item(Kind.TRIGGER, self.trigger.text().strip()))
        if self.reagent.text().strip():
            items.append(Item(Kind.REAGENT, self.reagent.text().strip()))
        if self.method_qr.text().strip():
            items.append(Item(Kind.METHOD, self.method_qr.text().strip()))
        if self.package_qr.text().strip():
            items.append(Item(Kind.PACKAGE, self.package_qr.text().strip()))
        return items

    def _check_payload(self) -> None:
        """Show what the package payload is, and prove it reprints identically."""
        text = self.package_qr.text().strip()
        if not text:
            QMessageBox.information(self, "Nothing to check", "The package field is empty.")
            return

        problems = payload.check_reproducible(text)
        lines: list[str] = []

        if payload.looks_like_base64(text):
            trip = payload.round_trip(text)
            lines.append(trip.describe())
            info = payload.structure(text)
            lines.append("")
            lines.append("decoded structure (shown for comparison only):")
            lines.extend("  " + line for line in info.summary())
            lines.append("")
            lines.append(f"  decoded text starts: {trip.decoded[:70]}...")
        else:
            lines.append(f"plain text, {len(text)} characters")
            try:
                lines.append(f"QR: {kind.qr_modules(text)}x{kind.qr_modules(text)} modules")
            except KindError as exc:
                lines.append(f"QR: {exc}")

        lines.append("")
        if problems:
            lines.append("PROBLEMS:")
            lines.extend("  - " + p for p in problems)
        else:
            lines.append("OK - safe to print")

        self.info.setPlainText("\n".join(lines))
        if problems:
            self._status("Payload has problems; see the details.")
        else:
            self._status("Payload verified.")

    def _page(self) -> tuple[float, float]:
        choice = self.page_size.currentText()
        if choice.startswith("Roll 76"):
            return 76.0, 160.0
        if choice.startswith("Roll 58"):
            return 58.0, 160.0
        return 210.0, 297.0

    def _build(self) -> None:
        items = self._collect()
        if not items:
            QMessageBox.information(self, "Nothing to print", "Fill at least one field.")
            return

        page_w, page_h = self._page()
        dpi = int(self.dpi.currentText())

        fd, path = tempfile.mkstemp(suffix=".pdf", prefix="pack-")
        os.close(fd)

        try:
            placements = pack.build_pack_sheet(
                path,
                items,
                page_width_mm=page_w,
                page_height_mm=page_h,
                dpi=dpi,
                bar_width_mm=self.bar_width.value(),
                qr_square_mm=self.qr_square.value(),
            )
        except KindError as exc:
            QMessageBox.warning(self, "Cannot encode", str(exc))
            return
        except pack.PackError as exc:
            QMessageBox.warning(self, "Cannot lay out", str(exc))
            return
        except render.RenderError as exc:
            QMessageBox.warning(self, "Cannot render", str(exc))
            return

        # A long QR is the easiest thing to get subtly wrong, so prove every
        # symbol in the built file decodes back to the text that went in.
        mismatches = self._read_back(path, dpi, items)
        if mismatches:
            detail = "\n".join(mismatches[:6])
            QMessageBox.critical(
                self,
                "Built file does not read back correctly",
                "The PDF was generated but a symbol does not decode to its own text. "
                "Do not print this file.\n\n" + detail,
            )
            return

        self._pdf_path = path
        self.save_button.setEnabled(True)
        self._show(path)

        lines: list[str] = []
        for placement in placements:
            try:
                lines.append(
                    kind.describe(
                        placement.item, dpi=dpi, width_mm=placement.width_mm
                    )
                )
            except KindError as exc:
                lines.append(f"{placement.item.kind.title}: {exc}")
        self.info.setPlainText("\n".join(lines))
        self._status(f"Built {len(placements)} symbols.")

    def _read_back(self, path: str, dpi: int, items: list[Item]) -> list[str]:
        """Decode the built page and report any symbol that is not exact."""
        try:
            import pypdfium2 as pdfium
            import zxingcpp
        except ImportError:
            return []

        expected = {item.text for item in items}
        problems: list[str] = []
        try:
            doc = pdfium.PdfDocument(path)
            try:
                image = doc[0].render(scale=dpi / 72).to_pil()
            finally:
                doc.close()
            found = {r.text for r in zxingcpp.read_barcodes(image)}
        except Exception as exc:  # noqa: BLE001 - never block printing on a reader bug
            return [f"read-back unavailable: {exc}"]

        for text in expected:
            if text not in found:
                shown = text if len(text) <= 40 else text[:37] + "..."
                problems.append(f"not read back: {shown}")
        for text in found - expected:
            shown = text if len(text) <= 40 else text[:37] + "..."
            problems.append(f"unexpected reading: {shown}")
        return problems

    def _show(self, path: str) -> None:
        try:
            import pypdfium2 as pdfium

            doc = pdfium.PdfDocument(path)
            try:
                image = doc[0].render(scale=PREVIEW_SCALE).to_pil()
            finally:
                doc.close()
            fd, png = tempfile.mkstemp(suffix=".png", prefix="pack-preview-")
            os.close(fd)
            image.save(png)
            self.preview.setPixmap(QPixmap(png))
        except Exception as exc:  # noqa: BLE001 - preview must not block printing
            self.preview.setText(f"preview unavailable: {exc}")

    def _save(self) -> None:
        if not self._pdf_path:
            return
        target, _ = QFileDialog.getSaveFileName(
            self, "Save pack sheet", "pack.pdf", "PDF (*.pdf)"
        )
        if not target:
            return
        try:
            with open(self._pdf_path, "rb") as src, open(target, "wb") as dst:
                dst.write(src.read())
        except OSError as exc:
            QMessageBox.warning(self, "Could not save", str(exc))
            return
        self._status(f"Saved {target}")


def main() -> int:
    app = QApplication(sys.argv)
    window = PackWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
