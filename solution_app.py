"""Window for Trigger and Pre-Trigger bottle labels.

Two kinds, three sizes, one label each at a time or a batch from a CSV. The
window refuses to print when the same code is used twice or one GTIN covers two
sizes, because either mistake makes the register unable to say which bottle was
filled.
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

from bcgen import solution
from bcgen.solution import SolutionError, SolutionLabel

PREVIEW_SCALE = 3.0


class SolutionWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Trigger and Pre-Trigger labels")
        self.resize(1240, 860)
        self._pdf_path: str | None = None
        self._queue: list[SolutionLabel] = []

        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.addWidget(self._build_form(), 0)
        outer.addWidget(self._build_preview(), 1)
        self.setStatusBar(QStatusBar())
        self._status("Fill the fields, then Add to batch. Repeat for each bottle.")

    # -- form ------------------------------------------------------------

    def _build_form(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(410)
        layout = QVBoxLayout(panel)

        bottle = QGroupBox("Bottle")
        form = QFormLayout(bottle)

        self.kind = QComboBox()
        self.kind.addItems(["trigger", "pretrigger"])
        form.addRow("Kind", self.kind)

        self.volume = QComboBox()
        self.volume.addItems([f"{v} mL" for v in solution.STANDARD_VOLUMES_ML])
        self.volume.setCurrentText("450 mL")
        form.addRow("Volume", self.volume)

        self.code = QLineEdit("IQEApeCg6t")
        self.code.setMaxLength(10)
        self.code.setPlaceholderText("10 characters, scan it")
        form.addRow("Bottle code", self.code)

        self.lot = QLineEdit("20250902")
        form.addRow("Lot", self.lot)

        self.produced = QLineEdit("2025-09-02")
        form.addRow("Produced", self.produced)

        self.expiry = QLineEdit("2027-04-14")
        form.addRow("Expiry", self.expiry)

        self.gtin = QLineEdit("06925912716570")
        self.gtin.setMaxLength(14)
        self.gtin.setPlaceholderText("14 digits")
        form.addRow("GTIN", self.gtin)

        self.internal = QLineEdit("003067")
        form.addRow("Internal (91)", self.internal)

        self.storage = QLineEdit("Store at 2-8 C")
        form.addRow("Storage", self.storage)

        self.copies = QSpinBox()
        self.copies.setRange(1, 999)
        form.addRow("Copies", self.copies)
        layout.addWidget(bottle)

        printing = QGroupBox("Printing")
        printing_form = QFormLayout(printing)
        self.dpi = QComboBox()
        self.dpi.addItems(["203", "300", "600"])
        self.dpi.setCurrentText("300")
        printing_form.addRow("dpi", self.dpi)

        self.label_w = QDoubleSpinBox()
        self.label_w.setRange(40.0, 190.0)
        self.label_w.setValue(90.0)
        self.label_w.setSuffix(" mm")
        printing_form.addRow("Label width", self.label_w)

        self.label_h = QDoubleSpinBox()
        self.label_h.setRange(20.0, 200.0)
        self.label_h.setValue(45.0)
        self.label_h.setSuffix(" mm")
        printing_form.addRow("Label height", self.label_h)

        self.with_dm = QComboBox()
        self.with_dm.addItems(["Yes", "No"])
        printing_form.addRow("GS1 DataMatrix", self.with_dm)
        layout.addWidget(printing)

        add = QPushButton("Add to batch")
        add.setMinimumHeight(34)
        add.clicked.connect(self._add)
        layout.addWidget(add)

        build = QPushButton("Build sheet")
        build.setMinimumHeight(34)
        build.clicked.connect(self._build)
        layout.addWidget(build)

        row = QHBoxLayout()
        clear = QPushButton("Clear batch")
        clear.clicked.connect(self._clear)
        save = QPushButton("Save PDF...")
        save.clicked.connect(self._save)
        row.addWidget(clear)
        row.addWidget(save)
        layout.addLayout(row)

        self.info = QPlainTextEdit()
        self.info.setReadOnly(True)
        self.info.setMaximumHeight(170)
        self.info.setStyleSheet("font-family: Menlo, monospace; font-size:11px;")
        layout.addWidget(self.info)
        layout.addStretch(1)
        return panel

    def _build_preview(self) -> QWidget:
        box = QGroupBox("Preview")
        box_layout = QVBoxLayout(box)
        self.preview = QLabel("Nothing built yet.")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(self.preview)
        scroll.setWidgetResizable(True)
        box_layout.addWidget(scroll)
        return box

    # -- behaviour -------------------------------------------------------

    def _status(self, message: str) -> None:
        self.statusBar().showMessage(message, 9000)

    def _current(self) -> SolutionLabel:
        return SolutionLabel(
            kind=self.kind.currentText(),
            code=self.code.text().strip(),
            volume_ml=int(self.volume.currentText().split()[0]),
            lot=self.lot.text().strip(),
            produced=self.produced.text().strip(),
            expiry=self.expiry.text().strip(),
            gtin=self.gtin.text().strip(),
            internal=self.internal.text().strip(),
            storage=self.storage.text().strip(),
            copies=self.copies.value(),
        )

    def _add(self) -> None:
        label = self._current()
        try:
            label.validate()
        except SolutionError as exc:
            QMessageBox.warning(self, "Check the bottle", str(exc))
            return
        self._queue.append(label)
        self._refresh_info()
        self._status(f"Added {label.kind_title()} {label.volume_text} - {label.code}")

    def _clear(self) -> None:
        self._queue.clear()
        self._refresh_info()
        self._status("Batch cleared.")

    def _refresh_info(self) -> None:
        if not self._queue:
            self.info.setPlainText("Batch is empty. Add bottles, then Build sheet.")
            return
        lines = [f"{len(self._queue)} bottle entries:"]
        for index, label in enumerate(self._queue, start=1):
            lines.append(
                f"  {index}. {label.kind_title():12} {label.volume_text:>7}  "
                f"{label.code}  lot {label.lot}"
            )
            lines.append(f"     {label.gs1_string()}")
        self.info.setPlainText("\n".join(lines))

    def _build(self) -> None:
        labels = list(self._queue)
        if not labels:
            # Nothing queued: build what is in the form, so a single label is one click.
            label = self._current()
            try:
                label.validate()
            except SolutionError as exc:
                QMessageBox.warning(self, "Check the bottle", str(exc))
                return
            labels = [label]

        dpi = int(self.dpi.currentText())
        fd, path = tempfile.mkstemp(suffix=".pdf", prefix="solution-")
        os.close(fd)

        try:
            problems = solution.build_solution_sheet(
                path,
                labels,
                label_width_mm=self.label_w.value(),
                label_height_mm=self.label_h.value(),
                dpi=dpi,
                with_datamatrix=self.with_dm.currentText() == "Yes",
            )
        except SolutionError as exc:
            QMessageBox.warning(self, "Cannot build", str(exc))
            return

        self._pdf_path = path
        self._show(path)

        if problems:
            QMessageBox.critical(
                self,
                "Review before printing",
                "The PDF was created, but these need fixing:\n\n"
                + "\n".join(f"- {p}" for p in problems),
            )
            self._status("Built, but the batch has problems.")
        else:
            self._status(f"Built {sum(l.copies for l in labels)} label(s).")

    def _show(self, path: str) -> None:
        try:
            import pypdfium2 as pdfium

            doc = pdfium.PdfDocument(path)
            try:
                image = doc[0].render(scale=PREVIEW_SCALE).to_pil()
            finally:
                doc.close()
            fd, png = tempfile.mkstemp(suffix=".png", prefix="solution-preview-")
            os.close(fd)
            image.save(png)
            self.preview.setPixmap(QPixmap(png))
        except Exception as exc:  # noqa: BLE001
            self.preview.setText(f"preview unavailable: {exc}")

    def _save(self) -> None:
        if not self._pdf_path:
            QMessageBox.information(self, "Nothing to save", "Build the sheet first.")
            return
        target, _ = QFileDialog.getSaveFileName(
            self, "Save labels", "solution-labels.pdf", "PDF (*.pdf)"
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
    window = SolutionWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
