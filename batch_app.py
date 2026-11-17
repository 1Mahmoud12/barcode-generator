"""One window that ties the work together: build the symbols, fit the curve, keep the register.

The three parts are independent and can be used separately from the command line.
Putting them in one window is about the operator's sequence, which is always the
same:

1. Prepare the batch: lot, expiry, product.
2. Fit the calibration curve from the calibrators that were measured.
3. Build the pack symbols (trigger, reagent, method, package).
4. Record what was printed.

Step 4 is not optional bookkeeping. It is what makes step 3 safe: without a
register there is no way to notice that one code was printed on two lots.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date

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
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from bcgen import calib, kind, pack, payload, register, render
from bcgen.kind import Item, Kind, KindError
from bcgen.register import Entry, Register, RegisterError

DEFAULT_REGISTER = os.path.join(os.path.expanduser("~"), "barcode-register.csv")


class BatchWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pack production - curve, symbols, register")
        self.resize(1320, 900)
        self._pdf_path: str | None = None
        self._fit: calib.FitResult | None = None

        tabs = QTabWidget()
        tabs.addTab(self._batch_tab(), "Batch")
        tabs.addTab(self._curve_tab(), "Calibration curve")
        tabs.addTab(self._symbols_tab(), "Symbols")
        tabs.addTab(self._register_tab(), "Register")
        self.setCentralWidget(tabs)
        self.setStatusBar(QStatusBar())
        self._status("Start with the batch details, then fit the curve.")

    # -- batch -----------------------------------------------------------

    def _batch_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)

        box = QGroupBox("Batch")
        form = QFormLayout(box)
        self.product = QLineEdit("LH")
        form.addRow("Product", self.product)
        self.lot = QLineEdit("20250902")
        form.addRow("Lot", self.lot)
        self.expiry = QLineEdit("2027-04-14")
        form.addRow("Expiry", self.expiry)
        self.operator = QLineEdit(os.environ.get("USERNAME") or os.environ.get("USER") or "")
        form.addRow("Operator", self.operator)
        self.units = QSpinBox()
        self.units.setRange(1, 5000)
        self.units.setValue(24)
        form.addRow("Units in batch", self.units)
        layout.addWidget(box, 0)

        notes = QGroupBox("What this window checks")
        notes_layout = QVBoxLayout(notes)
        label = QLabel(
            "The register links every printed code to its lot. It refuses to record the "
            "same code twice, and it refuses a code that already belongs to another lot.\n\n"
            "That is the failure worth preventing: a cartridge carrying one lot's "
            "calibration, counted against another lot's record."
        )
        label.setWordWrap(True)
        notes_layout.addWidget(label)
        notes_layout.addStretch(1)
        layout.addWidget(notes, 1)
        return page

    # -- curve -----------------------------------------------------------

    def _curve_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        top = QHBoxLayout()
        form_box = QGroupBox("Calibrators measured")
        form = QFormLayout(form_box)

        self.model_choice = QComboBox()
        self.model_choice.addItems(["Auto (4PL or 5PL)", "4PL", "5PL"])
        form.addRow("Model", self.model_choice)

        self.pin_blank = QComboBox()
        self.pin_blank.addItems(["Pin blank to measured", "Let the fitter move it"])
        form.addRow("Zero calibrator", self.pin_blank)

        self.recovery_low = QDoubleSpinBox()
        self.recovery_low.setRange(50.0, 100.0)
        self.recovery_low.setValue(calib.DEFAULT_RECOVERY_LOW)
        self.recovery_low.setSuffix(" %")
        form.addRow("Recovery low", self.recovery_low)

        self.recovery_high = QDoubleSpinBox()
        self.recovery_high.setRange(100.0, 150.0)
        self.recovery_high.setValue(calib.DEFAULT_RECOVERY_HIGH)
        self.recovery_high.setSuffix(" %")
        form.addRow("Recovery high", self.recovery_high)
        top.addWidget(form_box, 0)

        table_box = QGroupBox("Points (concentration, signal)")
        table_layout = QVBoxLayout(table_box)
        self.points_table = QTableWidget(0, 3)
        self.points_table.setHorizontalHeaderLabels(["Concentration", "Signal", "Label"])
        self.points_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        table_layout.addWidget(self.points_table)
        row_buttons = QHBoxLayout()
        add_row = QPushButton("Add row")
        add_row.clicked.connect(lambda: self._add_point_row())
        remove_row = QPushButton("Remove row")
        remove_row.clicked.connect(self._remove_point_row)
        load_csv = QPushButton("Load CSV...")
        load_csv.clicked.connect(self._load_points)
        row_buttons.addWidget(add_row)
        row_buttons.addWidget(remove_row)
        row_buttons.addWidget(load_csv)
        row_buttons.addStretch(1)
        table_layout.addLayout(row_buttons)
        top.addWidget(table_box, 1)
        layout.addLayout(top)

        fit_row = QHBoxLayout()
        fit_button = QPushButton("Fit curve")
        fit_button.setMinimumHeight(34)
        fit_button.clicked.connect(self._fit_curve)
        fit_row.addWidget(fit_button)

        back_label = QLabel("Signal")
        self.back_signal = QLineEdit()
        self.back_signal.setPlaceholderText("measured signal to convert back")
        back_button = QPushButton("Back-calculate")
        back_button.clicked.connect(self._back_calculate)
        fit_row.addWidget(back_label)
        fit_row.addWidget(self.back_signal, 1)
        fit_row.addWidget(back_button)
        layout.addLayout(fit_row)

        self.curve_report = QPlainTextEdit()
        self.curve_report.setReadOnly(True)
        self.curve_report.setStyleSheet("font-family: Menlo, monospace; font-size:11px;")
        layout.addWidget(self.curve_report, 1)

        self._seed_points()
        return page

    def _seed_points(self) -> None:
        for _ in range(6):
            self._add_point_row()

    def _add_point_row(self, concentration: str = "", signal: str = "", label: str = "") -> None:
        row = self.points_table.rowCount()
        self.points_table.insertRow(row)
        for column, text in enumerate((concentration, signal, label)):
            self.points_table.setItem(row, column, QTableWidgetItem(text))

    def _remove_point_row(self) -> None:
        row = self.points_table.currentRow()
        if row >= 0:
            self.points_table.removeRow(row)

    def _load_points(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Calibrators CSV", "", "CSV (*.csv)")
        if not path:
            return
        try:
            points = calib.read_points_csv(path)
        except calib.CalibrationError as exc:
            QMessageBox.warning(self, "Cannot read CSV", str(exc))
            return
        self.points_table.setRowCount(0)
        for point in points:
            self._add_point_row(
                f"{point.concentration:g}", f"{point.signal:g}", point.label
            )
        self._status(f"Loaded {len(points)} calibrators.")

    def _collect_points(self) -> list[calib.Point]:
        points: list[calib.Point] = []
        for row in range(self.points_table.rowCount()):
            conc_item = self.points_table.item(row, 0)
            sig_item = self.points_table.item(row, 1)
            label_item = self.points_table.item(row, 2)
            conc_text = (conc_item.text() if conc_item else "").strip()
            sig_text = (sig_item.text() if sig_item else "").strip()
            if not conc_text and not sig_text:
                continue
            try:
                points.append(
                    calib.Point(
                        concentration=float(conc_text),
                        signal=float(sig_text),
                        label=(label_item.text() if label_item else "") or f"C{row + 1}",
                    )
                )
            except ValueError as exc:
                raise calib.CalibrationError(f"row {row + 1}: {exc}") from exc
        return points

    def _fit_curve(self) -> None:
        try:
            points = self._collect_points()
        except calib.CalibrationError as exc:
            QMessageBox.warning(self, "Check the points", str(exc))
            return

        choice = self.model_choice.currentText()
        pin = self.pin_blank.currentText().startswith("Pin")

        try:
            if choice.startswith("Auto"):
                result = calib.best_fit(points, pin_blank=pin)
            elif choice.startswith("4PL"):
                result = calib.fit(points, model="4pl", pin_blank=pin)
            else:
                result = calib.fit(points, model="5pl", pin_blank=pin)
        except calib.CalibrationError as exc:
            QMessageBox.warning(self, "Cannot fit", str(exc))
            return

        self._fit = result
        low, high = self.recovery_low.value(), self.recovery_high.value()
        text = result.report(low, high)

        # A fit can pass recovery and still be the wrong shape. Say so plainly,
        # because a plausible-looking curve is the dangerous outcome.
        problems = calib.plausible(result, points)
        if problems:
            text += "\n\nSHAPE WARNINGS - review before using this curve:"
            text += "\n" + "\n".join(f"  - {p}" for p in problems)

        self.curve_report.setPlainText(text)
        if problems:
            self._status("Fit done, but the curve shape needs review.")
        else:
            self._status(
                "Fit done: " + ("PASS" if result.recoveries_ok(low, high) else "REVIEW the points")
            )

    def _back_calculate(self) -> None:
        if not self._fit:
            QMessageBox.information(self, "No curve", "Fit a curve first.")
            return
        text = self.back_signal.text().strip()
        if not text:
            return
        try:
            value = float(text)
        except ValueError:
            QMessageBox.warning(self, "Not a number", f"{text!r} is not a number.")
            return
        concentration = calib.back_calculate(self._fit, value)
        if concentration != concentration:  # nan
            answer = "outside the curve's range"
        elif concentration == float("inf"):
            answer = "at or above saturation"
        else:
            answer = f"{concentration:.4g}"
        self.curve_report.appendPlainText(f"\nsignal {value:g} -> concentration {answer}")

    # -- symbols ---------------------------------------------------------

    def _symbols_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)

        panel = QWidget()
        panel.setFixedWidth(420)
        side = QVBoxLayout(panel)

        codes = QGroupBox("Codes to print")
        form = QFormLayout(codes)
        self.trigger = QLineEdit("IQEApeCg6t")
        form.addRow("Trigger", self.trigger)
        self.reagent = QLineEdit("iwUMArCYU")
        form.addRow("Reagent", self.reagent)
        self.method_qr = QLineEdit("TSH;Cal1")
        form.addRow("Method QR", self.method_qr)
        self.package_qr = QLineEdit("")
        self.package_qr.setPlaceholderText("scan the pack QR")
        form.addRow("Package QR", self.package_qr)
        side.addWidget(codes)

        settings = QGroupBox("Printing")
        settings_form = QFormLayout(settings)
        self.dpi = QComboBox()
        self.dpi.addItems(["203", "300", "600"])
        self.dpi.setCurrentText("300")
        settings_form.addRow("dpi", self.dpi)
        self.bar_width = QDoubleSpinBox()
        self.bar_width.setRange(15.0, 190.0)
        self.bar_width.setValue(pack.DEFAULT_BAR_WIDTH_MM)
        self.bar_width.setSuffix(" mm")
        settings_form.addRow("Max bar width", self.bar_width)
        self.qr_square = QDoubleSpinBox()
        self.qr_square.setRange(10.0, 120.0)
        self.qr_square.setValue(pack.DEFAULT_QR_MM)
        self.qr_square.setSuffix(" mm")
        settings_form.addRow("QR square", self.qr_square)
        side.addWidget(settings)

        build = QPushButton("Build and record")
        build.setMinimumHeight(36)
        build.clicked.connect(self._build_symbols)
        side.addWidget(build)

        save = QPushButton("Save PDF...")
        save.clicked.connect(self._save_pdf)
        side.addWidget(save)

        self.symbol_info = QPlainTextEdit()
        self.symbol_info.setReadOnly(True)
        self.symbol_info.setMaximumHeight(150)
        self.symbol_info.setStyleSheet("font-size:11px;")
        side.addWidget(self.symbol_info)
        side.addStretch(1)
        layout.addWidget(panel, 0)

        preview_box = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_box)
        self.preview = QLabel("Nothing built yet.")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(self.preview)
        scroll.setWidgetResizable(True)
        preview_layout.addWidget(scroll)
        layout.addWidget(preview_box, 1)
        return page

    def _collect_items(self) -> list[Item]:
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

    def _build_symbols(self) -> None:
        items = self._collect_items()
        if not items:
            QMessageBox.information(self, "Nothing to print", "Fill at least one code.")
            return

        package_text = self.package_qr.text().strip()
        if package_text:
            problems = payload.check_reproducible(package_text)
            if problems:
                QMessageBox.critical(
                    self,
                    "Package payload will not reproduce",
                    "Do not print until this is fixed:\n\n" + "\n".join(f"- {p}" for p in problems),
                )
                return

        dpi = int(self.dpi.currentText())
        fd, path = tempfile.mkstemp(suffix=".pdf", prefix="pack-")
        os.close(fd)

        try:
            placements = pack.build_pack_sheet(
                path,
                items,
                dpi=dpi,
                bar_width_mm=self.bar_width.value(),
                qr_square_mm=self.qr_square.value(),
            )
        except (KindError, pack.PackError, render.RenderError) as exc:
            QMessageBox.warning(self, "Cannot build", str(exc))
            return

        self._pdf_path = path
        self._show_preview(path)

        lines = []
        for placement in placements:
            shown = placement.item.text
            if len(shown) > 44:
                shown = f"{shown[:41]}... ({len(shown)} chars)"
            lines.append(f"{placement.item.kind.title}: {shown}")
            lines.append(
                f"   {kind.describe(placement.item, dpi=dpi, width_mm=placement.width_mm)}"
            )
        self.symbol_info.setPlainText("\n".join(lines))

        self._record(items, dpi)
        self._refresh_register()
        self._status(f"Built {len(placements)} symbols.")

    def _show_preview(self, path: str) -> None:
        try:
            import pypdfium2 as pdfium

            doc = pdfium.PdfDocument(path)
            try:
                image = doc[0].render(scale=2.0).to_pil()
            finally:
                doc.close()
            fd, png = tempfile.mkstemp(suffix=".png", prefix="pack-preview-")
            os.close(fd)
            image.save(png)
            self.preview.setPixmap(QPixmap(png))
        except Exception as exc:  # noqa: BLE001
            self.preview.setText(f"preview unavailable: {exc}")

    def _record(self, items: list[Item], dpi: int) -> None:
        register_path = self._register_path()
        book = Register.load(register_path)
        recorded = 0
        warnings: list[str] = []
        for item in items:
            entry = Entry(
                event="print",
                kind=item.kind.value,
                code=item.text,
                lot=self.lot.text().strip(),
                expiry=self.expiry.text().strip(),
                product=self.product.text().strip(),
                cells=1,
                dpi=dpi,
                source=self._pdf_path or "",
                operator=self.operator.text().strip(),
            )
            try:
                warnings.extend(str(w) for w in book.add(entry))
                recorded += 1
            except RegisterError as exc:
                QMessageBox.critical(
                    self,
                    "Not recorded",
                    f"The {item.kind.title} code was not added to the register:\n\n{exc}",
                )
        if recorded:
            self._status(f"Recorded {recorded} entries in {register_path}")
        if warnings:
            QMessageBox.warning(self, "Register warnings", "\n".join(warnings))

    def _save_pdf(self) -> None:
        if not self._pdf_path:
            return
        target, _ = QFileDialog.getSaveFileName(
            self, "Save symbols", "pack.pdf", "PDF (*.pdf)"
        )
        if not target:
            return
        with open(self._pdf_path, "rb") as src, open(target, "wb") as dst:
            dst.write(src.read())
        self._status(f"Saved {target}")

    # -- register --------------------------------------------------------

    def _register_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        row = QHBoxLayout()
        self.register_path = QLineEdit(DEFAULT_REGISTER)
        browse = QPushButton("...")
        browse.setFixedWidth(32)
        browse.clicked.connect(self._pick_register)
        reload_button = QPushButton("Reload")
        reload_button.clicked.connect(self._refresh_register)
        check_button = QPushButton("Check lot mixing")
        check_button.clicked.connect(self._check_mixing)
        row.addWidget(QLabel("Register file"))
        row.addWidget(self.register_path, 1)
        row.addWidget(browse)
        row.addWidget(reload_button)
        row.addWidget(check_button)
        layout.addLayout(row)

        self.register_table = QTableWidget(0, 8)
        self.register_table.setHorizontalHeaderLabels(
            ["time", "event", "kind", "lot", "expiry", "product", "length", "operator"]
        )
        self.register_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        layout.addWidget(self.register_table, 1)

        self.register_report = QPlainTextEdit()
        self.register_report.setReadOnly(True)
        self.register_report.setMaximumHeight(110)
        self.register_report.setStyleSheet("font-size:11px;")
        layout.addWidget(self.register_report)
        return page

    def _register_path(self) -> str:
        path = self.register_path.text().strip() if hasattr(self, "register_path") else ""
        return path or DEFAULT_REGISTER

    def _pick_register(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Register CSV", self.register_path.text(), "CSV (*.csv)"
        )
        if path:
            self.register_path.setText(path)
            self._refresh_register()

    def _refresh_register(self) -> None:
        book = Register.load(self._register_path())
        self.register_table.setRowCount(0)
        for entry in book.entries[-500:]:
            row = self.register_table.rowCount()
            self.register_table.insertRow(row)
            values = (
                entry.timestamp,
                entry.event,
                entry.kind,
                entry.lot,
                entry.expiry,
                entry.product,
                str(entry.length),
                entry.operator,
            )
            for column, text in enumerate(values):
                self.register_table.setItem(row, column, QTableWidgetItem(text))
        self.register_report.setPlainText("\n".join(book.summary()))

    def _check_mixing(self) -> None:
        book = Register.load(self._register_path())
        conflicts = register.find_lot_mixing(book)
        if not conflicts:
            self.register_report.setPlainText(
                "\n".join(book.summary()) + "\n\nno code appears under more than one lot"
            )
            return
        lines = book.summary() + [""] + [str(c) for c in conflicts]
        self.register_report.setPlainText("\n".join(lines))
        QMessageBox.critical(
            self,
            "Lot mixing found",
            "\n".join(str(c) for c in conflicts[:8]),
        )

    def _status(self, message: str) -> None:
        self.statusBar().showMessage(message, 9000)


def main() -> int:
    app = QApplication(sys.argv)
    window = BatchWindow()
    window.show()
    window._refresh_register()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
