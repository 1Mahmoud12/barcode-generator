"""Window for printing complete product labels at a chosen size.

Two paper models, because they behave differently on real hardware:

* **Sheet** -- many labels per page with cut guides, for A4 sticker stock.
* **Roll** -- one label per page on a receipt printer. The page height is the
  label height, because the printer feeds exactly one page per job.

The barcode size is chosen automatically to fill the label width, and the bar
height is reduced only as far as the data needs. That keeps the symbol as large
as the label allows instead of using a fixed size that may not fit.
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
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from bcgen import label, render

PREVIEW_SCALE = 4.0


def _mm_box(value: float, low: float = 5.0, high: float = 300.0) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(1)
    box.setSingleStep(1.0)
    box.setSuffix(" mm")
    box.setValue(value)
    return box


class LabelWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Print product labels")
        self.resize(1240, 860)
        self._pdf_path: str | None = None

        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.addWidget(self._build_form(), 0)
        outer.addWidget(self._build_preview(), 1)
        self.setStatusBar(QStatusBar())
        self._status("Fill the fields, then press Preview.")

    # -- form ------------------------------------------------------------

    def _build_form(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(400)
        layout = QVBoxLayout(panel)

        data_box = QGroupBox("Label content")
        form = QFormLayout(data_box)
        self.code = QLineEdit("iwUMArCYU")
        self.code.setPlaceholderText("text carried by the bars")
        form.addRow("Barcode text", self.code)

        self.product = QLineEdit("Calibration Reagent")
        form.addRow("Product", self.product)

        self.volume = QLineEdit("R1 3.5 mL")
        form.addRow("Volume", self.volume)

        self.lot = QLineEdit("20250902")
        form.addRow("Lot", self.lot)

        self.expiry = QLineEdit("2027-04-14")
        form.addRow("Expiry", self.expiry)

        self.produced = QLineEdit("")
        self.produced.setPlaceholderText("optional")
        form.addRow("Produced", self.produced)

        self.storage = QLineEdit("Store 2-8 C")
        form.addRow("Storage", self.storage)

        self.notes = QLineEdit("")
        self.notes.setPlaceholderText("optional")
        form.addRow("Notes", self.notes)

        self.copies = QSpinBox()
        self.copies.setRange(1, 500)
        form.addRow("Copies", self.copies)
        layout.addWidget(data_box)

        paper_box = QGroupBox("Paper")
        paper_form = QFormLayout(paper_box)
        self.paper_mode = QComboBox()
        self.paper_mode.addItems(["Roll (receipt printer)", "Sheet (A4 sticker)"])
        self.paper_mode.currentIndexChanged.connect(self._on_paper_changed)
        paper_form.addRow("Mode", self.paper_mode)

        self.dpi = QComboBox()
        self.dpi.addItems(["203", "300"])
        self.dpi.setCurrentText("203")
        paper_form.addRow("Printer dpi", self.dpi)

        self.label_w = _mm_box(76.0)
        paper_form.addRow("Label width", self.label_w)
        self.label_h = _mm_box(40.0)
        paper_form.addRow("Label height", self.label_h)

        self.page_w = _mm_box(210.0)
        paper_form.addRow("Page width", self.page_w)
        self.page_h = _mm_box(297.0)
        paper_form.addRow("Page height", self.page_h)
        layout.addWidget(paper_box)

        bar_box = QGroupBox("Barcode height")
        bar_form = QFormLayout(bar_box)
        self.bar_mode = QComboBox()
        self.bar_mode.addItems(["Automatic (fit the data)", "Fixed"])
        self.bar_mode.currentIndexChanged.connect(self._on_bar_mode)
        bar_form.addRow("Height", self.bar_mode)
        self.bar_height = _mm_box(10.0, low=label.MIN_BAR_HEIGHT_MM, high=60.0)
        self.bar_height.setEnabled(False)
        bar_form.addRow("Fixed height", self.bar_height)
        layout.addWidget(bar_box)

        self.preview_button = QPushButton("Preview")
        self.preview_button.setMinimumHeight(36)
        self.preview_button.clicked.connect(self._preview)
        layout.addWidget(self.preview_button)

        self.save_button = QPushButton("Save PDF...")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save)
        layout.addWidget(self.save_button)

        self.info = QPlainTextEdit()
        self.info.setReadOnly(True)
        self.info.setMaximumHeight(120)
        self.info.setStyleSheet("font-size:11px;")
        layout.addWidget(self.info)

        layout.addStretch(1)
        self._on_paper_changed()
        return panel

    def _build_preview(self) -> QWidget:
        box = QGroupBox("Preview")
        layout = QVBoxLayout(box)
        self.preview_label = QLabel("Nothing to show yet.")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(self.preview_label)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll, 1)
        return box

    # -- behaviour -------------------------------------------------------

    def _status(self, message: str) -> None:
        self.statusBar().showMessage(message, 8000)

    def _on_paper_changed(self) -> None:
        is_sheet = self.paper_mode.currentText().startswith("Sheet")
        self.page_w.setVisible(is_sheet)
        self.page_h.setVisible(is_sheet)
        if is_sheet:
            self.label_w.setValue(60.0)
            self.label_h.setValue(40.0)
            self.dpi.setCurrentText("300")
        else:
            self.label_w.setValue(76.0)
            self.label_h.setValue(40.0)
            self.dpi.setCurrentText("203")

    def _on_bar_mode(self) -> None:
        self.bar_height.setEnabled(self.bar_mode.currentText() == "Fixed")

    def _collect(self) -> label.LabelData:
        return label.LabelData(
            code=self.code.text().strip(),
            product=self.product.text().strip(),
            lot=self.lot.text().strip(),
            expiry=label.normalise_date(self.expiry.text()),
            produced=label.normalise_date(self.produced.text()),
            volume=self.volume.text().strip(),
            storage=self.storage.text().strip(),
            notes=self.notes.text().strip(),
            copies=self.copies.value(),
        )

    def _preview(self) -> None:
        data = self._collect()
        dpi = int(self.dpi.currentText())
        fixed = (
            self.bar_height.value() if self.bar_mode.currentText() == "Fixed" else None
        )

        fd, path = tempfile.mkstemp(suffix=".pdf", prefix="labels-")
        os.close(fd)

        try:
            if self.paper_mode.currentText().startswith("Roll"):
                layout = label.build_roll(
                    path,
                    [data],
                    paper_width_mm=self.label_w.value(),
                    label_width_mm=self.label_w.value(),
                    label_height_mm=self.label_h.value(),
                    dpi=dpi,
                    bar_height_mm=fixed,
                )
            else:
                layout = label.build_sheet(
                    path,
                    [data],
                    page_width_mm=self.page_w.value(),
                    page_height_mm=self.page_h.value(),
                    label_width_mm=self.label_w.value(),
                    label_height_mm=self.label_h.value(),
                    dpi=dpi,
                    bar_height_mm=fixed,
                    page_heading="Product labels",
                )
        except label.LabelError as exc:
            QMessageBox.warning(self, "Cannot build label", str(exc))
            return
        except render.RenderError as exc:
            QMessageBox.warning(self, "Cannot build label", str(exc))
            return

        self._pdf_path = path
        self.save_button.setEnabled(True)
        self._show_page(path, 0)

        geo = render.geometry_for_width(data.code, layout.width_mm - 2 * layout.margin_mm, dpi)
        lines = [
            f"bar {layout.bar_height_mm:.0f} mm high, text {layout.text_pt:.1f} pt",
            f"barcode {geo.module_dots} dots = X {geo.x_mm:.3f} mm, "
            f"{geo.total_mm:.1f} mm wide",
            f"{data.copies} label(s)",
        ]
        if geo.x_mm < label.MIN_X_MM:
            lines.append(
                f"warning: X is below {label.MIN_X_MM} mm - thermal printers usually "
                f"cannot hold this; use a wider label or a higher dpi"
            )
        self.info.setPlainText("\n".join(lines))
        self._status("Preview built.")

    def _show_page(self, path: str, index: int) -> None:
        try:
            import pypdfium2 as pdfium

            doc = pdfium.PdfDocument(path)
            try:
                page = doc[min(index, len(doc) - 1)]
                image = page.render(scale=PREVIEW_SCALE).to_pil()
            finally:
                doc.close()
            fd, png = tempfile.mkstemp(suffix=".png", prefix="labels-preview-")
            os.close(fd)
            image.save(png)
            self.preview_label.setPixmap(QPixmap(png))
        except Exception as exc:  # noqa: BLE001 - preview must not break printing
            self.preview_label.setText(f"preview unavailable: {exc}")

    def _save(self) -> None:
        if not self._pdf_path:
            return
        target, _ = QFileDialog.getSaveFileName(
            self, "Save labels", "labels.pdf", "PDF (*.pdf)"
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
    window = LabelWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
