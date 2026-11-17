"""Windows-friendly desktop window for the barcode measurement sheet.

The window has one job: let someone pick how many codes, what alphabet, what
printer resolution and what bar widths, then look at the result and export the
PDF. Everything that decides correctness lives in :mod:`bcgen`; this file only
collects input and shows output.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from bcgen import render, sheet
from bcgen.generate import (
    DEFAULT_LENGTH,
    GenerationError,
    edge_codes,
    random_codes,
    sequential_codes,
)

DPI_CHOICES = (300, 600, 1200)
DEFAULT_RUNGS = "3,4,5,6,8,10,12"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Barcode measurement sheet")
        self.resize(1180, 820)
        self._pdf_path: str | None = None
        self._preview_path: str | None = None

        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)

        outer.addWidget(self._build_controls(), 0)
        outer.addWidget(self._build_preview(), 1)

        self.setStatusBar(QStatusBar())
        self._status("Choose settings, then press Build sheet.")

    # -- construction ----------------------------------------------------

    def _build_controls(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(340)
        layout = QVBoxLayout(panel)

        source_box = QGroupBox("Codes")
        source_form = QFormLayout(source_box)
        self.source_mode = QComboBox()
        self.source_mode.addItems(
            ["Generated (random)", "Sequential", "Edge cases", "From file"]
        )
        self.source_mode.currentIndexChanged.connect(self._on_mode_changed)
        source_form.addRow("Source", self.source_mode)

        self.count = QSpinBox()
        self.count.setRange(1, 400)
        self.count.setValue(24)
        source_form.addRow("How many", self.count)

        self.alphabet = QComboBox()
        self.alphabet.addItems(["mixed", "upper", "lower", "digits", "symbols"])
        source_form.addRow("Alphabet", self.alphabet)

        self.length = QSpinBox()
        self.length.setRange(4, 30)
        self.length.setValue(DEFAULT_LENGTH)
        source_form.addRow("Length", self.length)

        self.seed = QSpinBox()
        self.seed.setRange(0, 999_999)
        self.seed.setValue(0)
        source_form.addRow("Seed", self.seed)

        self.file_row = QWidget()
        file_layout = QHBoxLayout(self.file_row)
        file_layout.setContentsMargins(0, 0, 0, 0)
        self.file_path = QLineEdit()
        self.file_path.setPlaceholderText("one payload per line")
        browse = QPushButton("...")
        browse.setFixedWidth(32)
        browse.clicked.connect(self._pick_file)
        file_layout.addWidget(self.file_path)
        file_layout.addWidget(browse)
        source_form.addRow("File", self.file_row)
        self.file_row.setVisible(False)
        layout.addWidget(source_box)

        print_box = QGroupBox("Printer")
        print_form = QFormLayout(print_box)
        self.dpi = QComboBox()
        self.dpi.addItems([str(d) for d in DPI_CHOICES])
        self.dpi.setCurrentText("600")
        print_form.addRow("Resolution", self.dpi)

        self.rungs = QLineEdit(DEFAULT_RUNGS)
        print_form.addRow("Bar widths (dots)", self.rungs)

        self.title = QLineEdit("Barcode reader measurement sheet")
        print_form.addRow("Title", self.title)
        layout.addWidget(print_box)

        self.build_button = QPushButton("Build sheet")
        self.build_button.setMinimumHeight(34)
        self.build_button.clicked.connect(self._build)
        layout.addWidget(self.build_button)

        button_row = QHBoxLayout()
        self.save_button = QPushButton("Save PDF...")
        self.save_button.clicked.connect(self._save_pdf)
        self.save_button.setEnabled(False)
        self.selftest_button = QPushButton("Run self-check")
        self.selftest_button.clicked.connect(self._run_selftest)
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.selftest_button)
        layout.addLayout(button_row)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("color:#444; font-size:11px;")
        layout.addWidget(self.summary)

        layout.addStretch(1)
        return panel

    def _build_preview(self) -> QWidget:
        box = QGroupBox("Preview")
        layout = QVBoxLayout(box)
        self.page_select = QComboBox()
        self.page_select.setEnabled(False)
        self.page_select.currentIndexChanged.connect(self._render_preview)
        layout.addWidget(self.page_select)

        self.preview = QLabel("No sheet built yet.")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(600, 700)
        scroll = QScrollArea()
        scroll.setWidget(self.preview)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll, 1)
        return box

    # -- helpers ---------------------------------------------------------

    def _status(self, message: str) -> None:
        self.statusBar().showMessage(message, 8000)

    def _on_mode_changed(self) -> None:
        is_file = self.source_mode.currentText() == "From file"
        self.file_row.setVisible(is_file)
        uses_count = self.source_mode.currentText() in ("Generated (random)", "Sequential")
        self.count.setEnabled(uses_count)
        uses_alphabet = self.source_mode.currentText() == "Generated (random)"
        self.alphabet.setEnabled(uses_alphabet)
        self.length.setEnabled(uses_alphabet)
        self.seed.setEnabled(uses_alphabet)

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Payloads file", "", "Text (*.txt);;All files (*)")
        if path:
            self.file_path.setText(path)

    def _collect_codes(self):
        mode = self.source_mode.currentText()
        if mode == "Generated (random)":
            return random_codes(
                self.count.value(),
                length=self.length.value(),
                alphabet=self.alphabet.currentText(),
                seed=self.seed.value(),
            )
        if mode == "Sequential":
            return sequential_codes(self.count.value())
        if mode == "Edge cases":
            return edge_codes()
        path = self.file_path.text().strip()
        if not path or not os.path.exists(path):
            raise GenerationError("choose a payload file first")
        with open(path, encoding="utf-8") as handle:
            texts = [line.strip() for line in handle if line.strip() and not line.startswith("#")]
        if not texts:
            raise GenerationError("the payload file is empty")
        from bcgen.generate import TestCode

        return [TestCode(t, f"file-{i + 1:03d}") for i, t in enumerate(texts)]

    # -- actions ---------------------------------------------------------

    def _build(self) -> None:
        try:
            codes = self._collect_codes()
            rungs = [int(x) for x in self.rungs.text().split(",") if x.strip()]
            if not rungs:
                raise GenerationError("bar widths list is empty")
            dpi = int(self.dpi.currentText())

            fd, path = tempfile.mkstemp(suffix=".pdf", prefix="barcode-sheet-")
            os.close(fd)
            plans = sheet.build_sheet(
                path, codes, rungs=rungs, dpi=dpi, title=self.title.text() or "Sheet"
            )
        except (GenerationError, sheet.SheetError, render.RenderError) as exc:
            QMessageBox.warning(self, "Cannot build sheet", str(exc))
            return
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot build sheet", f"check settings: {exc}")
            return

        self._pdf_path = path
        self.save_button.setEnabled(True)

        self.page_select.blockSignals(True)
        self.page_select.clear()
        for index, plan in enumerate(plans, start=1):
            self.page_select.addItem(
                f"page {index}: {plan.module_dots} dots, X={plan.geo.x_mm:.3f} mm, "
                f"{len(plan.cells)} codes"
            )
        self.page_select.blockSignals(False)
        self.page_select.setEnabled(True)

        lines = [
            f"{len(codes)} codes, {len(plans)} pages, {dpi} dpi",
            f"output: {os.path.basename(path)}",
        ]
        for index, plan in enumerate(plans, start=1):
            lines.append(
                f"  p{index}: {plan.geo.describe()}, symbol {plan.geo.symbol_mm:.1f} mm, "
                f"grid {plan.columns}x{plan.rows}"
            )
        self.summary.setText("\n".join(lines))
        self._render_preview()
        self._status(f"Built {len(plans)} pages.")

    def _render_preview(self) -> None:
        if not self._pdf_path:
            return
        index = max(0, self.page_select.currentIndex())
        try:
            import pypdfium2 as pdfium

            doc = pdfium.PdfDocument(self._pdf_path)
            try:
                page = doc[index]
                image = page.render(scale=140 / 72).to_pil()
            finally:
                doc.close()
            fd, path = tempfile.mkstemp(suffix=".png", prefix="barcode-preview-")
            os.close(fd)
            image.save(path)
            self._preview_path = path
            self.preview.setPixmap(QPixmap(path))
        except Exception as exc:  # preview must never break the build
            self.preview.setText(f"preview unavailable: {exc}")

    def _save_pdf(self) -> None:
        if not self._pdf_path:
            return
        target, _ = QFileDialog.getSaveFileName(
            self, "Save sheet", "barcode-sheet.pdf", "PDF (*.pdf)"
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

    def _run_selftest(self) -> None:
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "selftest.py")
        try:
            completed = subprocess.run(
                [sys.executable, script],
                capture_output=True,
                text=True,
                timeout=600,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            QMessageBox.warning(self, "Self-check failed to start", str(exc))
            return
        tail = completed.stdout.strip().splitlines()[-14:]
        text = "\n".join(tail)
        if completed.returncode == 0:
            QMessageBox.information(self, "Self-check passed", text)
        else:
            QMessageBox.critical(self, "Self-check failed", text or completed.stderr)
        self._status("Self-check done.")


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
