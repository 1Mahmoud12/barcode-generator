"""The single window the operator opens.

Each of the four tools already exists as its own window with its own tests. Rather
than rewrite them here, this window **hosts** their existing widgets as tabs. A fix
made in `label_app.py` therefore shows up here automatically; there is no second
copy to keep in sync, which is the usual way a hosted UI drifts from its parts.

Tab order follows the work, not the code:

    Batch      lot, expiry, product, operator   (also curve, pack, register)
    Labels     full product label, roll or sheet
    Bottles    Trigger / Pre-Trigger, 200 / 450 / 800 mL, GS1 DataMatrix
    Pack       the four pack symbols
    Test sheet the graded sheet for measuring an instrument
    About      what this does and what it refuses to do

`batch_app.py` already contains curve, pack and register as tabs of its own, so the
Batch tab is the full production path; the others are the focused tools.
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

APP_TITLE = "IVD pack tooling"
APP_VERSION = "1.0"

ABOUT_TEXT = """WHAT THIS DOES

Prints barcodes and labels for IVD reagent packs, with every bar a whole number of
printer dots so a thermal or laser printer cannot distort the symbol.

  Batch       lot, expiry, product, operator; then curve, pack symbols and register
  Labels      full product label, one per roll page or many per A4 sheet
  Bottles     Trigger and Pre-Trigger labels, 200 / 450 / 800 mL, with GS1 DataMatrix
  Pack        the four pack symbols: trigger, reagent, method QR, package QR
  Test sheet  graded sheet for measuring what an instrument can actually read

WHAT IT REFUSES TO DO

It never invents a payload. Every code comes from you, typed or scanned from the
pack. It does not decode a manufacturer's payload into meaning, and does not build
one. A calibration curve here is fitted from calibrators you measured and entered.

BEFORE YOU TRUST A PRINT

1. Print at 100% / Actual size. Never "fit to page".
2. On the test sheet, the 50 mm bar must measure 50 mm with a ruler. If it does
   not, the printer scaled the page and no measurement on that sheet is valid.
3. Every symbol is decoded again before the file is handed to you. If one does not
   read back as its own text, the tool refuses to give you the file.

REQUIREMENTS

zint is required for GS1 DataMatrix and for the GS1 codes on bottle labels:

    Windows:   choco install zint
    macOS:     brew install zint

Everything else is bundled.
"""


class AboutPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        heading = QLabel(f"{APP_TITLE} {APP_VERSION}")
        font = QFont()
        font.setPointSize(15)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        body = QTextEdit()
        body.setReadOnly(True)
        body.setPlainText(ABOUT_TEXT)
        body.setStyleSheet(
            "QTextEdit { font-family: Consolas, Menlo, monospace; font-size: 11px; }"
        )
        layout.addWidget(body, 1)


def _host(window: QMainWindow, title: str) -> QWidget:
    """Take the widget out of a tool window so it can live in a tab.

    The hosted window is kept alive by holding a reference on the returned widget,
    otherwise Python would collect it and the tab would go blank.
    """
    page = window.centralWidget()
    page.setProperty("hosted_window", True)
    page._hosted = window  # keep the source window alive for its callbacks
    page.setWindowTitle(title)
    return page


def build_window() -> QMainWindow:
    """Assemble the tabbed window.

    Imports happen inside this function so that opening the Batch tab does not pay
    for loading every other tool, and so an error in one tool cannot stop the
    window from appearing.
    """
    window = QMainWindow()
    window.setWindowTitle(f"{APP_TITLE} {APP_VERSION}")
    window.resize(1400, 940)

    tabs = QTabWidget()
    tabs.setDocumentMode(True)

    from batch_app import BatchWindow

    tabs.addTab(_host(BatchWindow(), "Batch"), "Batch")

    try:
        from label_app import LabelWindow

        tabs.addTab(_host(LabelWindow(), "Labels"), "Labels")
    except Exception as exc:  # noqa: BLE001 - one broken tab must not hide the rest
        tabs.addTab(_error_tab("Labels", exc), "Labels")

    try:
        from solution_app import SolutionWindow

        tabs.addTab(_host(SolutionWindow(), "Bottles"), "Bottles")
    except Exception as exc:  # noqa: BLE001
        tabs.addTab(_error_tab("Bottles", exc), "Bottles")

    try:
        from pack_app import PackWindow

        tabs.addTab(_host(PackWindow(), "Pack"), "Pack")
    except Exception as exc:  # noqa: BLE001
        tabs.addTab(_error_tab("Pack", exc), "Pack")

    try:
        from app import MainWindow as SheetWindow

        tabs.addTab(_host(SheetWindow(), "Test sheet"), "Test sheet")
    except Exception as exc:  # noqa: BLE001
        tabs.addTab(_error_tab("Test sheet", exc), "Test sheet")

    tabs.addTab(AboutPanel(), "About")
    window.setCentralWidget(tabs)

    window.statusBar().showMessage(
        "Print at 100% / Actual size. Check the 50 mm bar on the test sheet first.",
        20000,
    )

    help_menu = window.menuBar().addMenu("Help")
    about_action = QAction("About", window)
    about_action.triggered.connect(lambda: tabs.setCurrentIndex(tabs.count() - 1))
    help_menu.addAction(about_action)

    window._tabs = tabs
    return window


def _error_tab(name: str, error: Exception) -> QWidget:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    label = QLabel(
        f"The {name} tab could not load.\n\n{type(error).__name__}: {error}\n\n"
        f"The other tabs still work. This usually means a missing dependency; "
        f"run 'pip install -r requirements.txt' and start again."
    )
    label.setWordWrap(True)
    layout.addWidget(label)
    layout.addStretch(1)
    return panel


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setApplicationVersion(APP_VERSION)
    window = build_window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
