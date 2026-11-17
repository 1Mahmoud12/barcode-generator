# Building on Windows

PyInstaller bundles the Python interpreter of the machine it runs on. A build
started on macOS therefore produces a macOS program, not a `.exe`. The `.exe` has to
be produced **on Windows**.

## What to bring to the Windows machine

Two options. The first is easier; the second needs no network.

### Option A: clone from GitHub

```
git clone https://github.com/1Mahmoud12/barcode-generator.git
cd barcode-generator
```

### Option B: copy the folder

Copy `~/Projects/barcode-generator` to the Windows machine, **excluding** `.venv`,
`build` and `dist`. Those three hold macOS binaries and must not be reused.

On Windows the folder needs only:

```
main_app.py   app.py   label_app.py   pack_app.py   solution_app.py   batch_app.py
bcgen/        tests/   requirements.txt   build.spec   build_windows.bat   selftest.py
```

## Build

1. Install Python 3.11 or newer from <https://python.org>. During setup tick
   **"Add python.exe to PATH"**.
2. Install zint, needed for the GS1 DataMatrix on bottle labels:
   ```
   choco install zint
   ```
   If you do not have Chocolatey, download `zint.exe` from <https://zint.org.uk>
   and put it somewhere on `PATH`.
3. Double-click `build_windows.bat`.

The script does six things and stops at the first failure:

1. checks Python is on `PATH`
2. creates `.venv`
3. installs `requirements.txt` plus PyInstaller
4. **runs `selftest.py`** — if any generated symbol does not decode back to its own
   text, the build stops here and nothing is packaged
5. reports whether zint was found (a warning, not a failure)
6. packages into `dist\IVDPackTooling\`

## Result

```
dist\IVDPackTooling\IVDPackTooling.exe
dist\IVDPackTooling\_internal\...
```

About 130-200 MB, mostly Qt. Copy the **whole `IVDPackTooling` folder**, not the
`.exe` alone: the executable needs the `_internal` folder beside it.

On the target machine, `zint.exe` must be on `PATH` for the GS1 tabs. Everything
else is bundled, so Python does not need to be installed there.

## When something goes wrong

**"python was not found"** — Python is installed but not on `PATH`. Reinstall and
tick the PATH box, or add it manually to the environment variables.

**"The self-check failed"** — the build is refused on purpose. Run
`python selftest.py` in the venv and read the failure; a packaged build is only
offered when every symbol decodes correctly.

**Antivirus flags the exe** — expected for unsigned PyInstaller output. The spec
already disables UPX compression, which is the usual trigger. Signing the binary
with an organisation certificate is the only real fix.

**The window closes immediately** — rebuild with `console=True` in `build.spec` to
see the traceback, or run the app from a terminal:
`dist\IVDPackTooling\IVDPackTooling.exe`

**GS1 tabs refuse to build** — zint is not on `PATH`. Run `zint --version` in a
fresh `cmd` window to confirm.
