# Barcode measurement sheet

Builds an A4 PDF of Code 128 symbols so you can measure what a scanner actually
reads, and at what size. Codes are **synthesized by this tool** — never copied
from a pack — so a successful scan proves the whole chain works: our encoder,
our printer, our paper, the reader.

## Why one bar width per page

A Code 128 symbol is 11 modules wide per character plus start, check and stop.
For nine characters that is always **134 modules**. The number that decides
whether a scanner can read it is not the symbol width but the **X-dimension**:
the width of one module.

The failure mode people hit is printing a module as a fractional number of
printer dots. Then some modules come out one dot wider than others and the
symbol is quietly malformed. This tool avoids that by expressing every bar width
as a **whole number of printer dots**, and by snapping every symbol origin to the
dot grid. One page per bar width means a page either scans or it does not.

## Sizes you get

At 600 dpi one dot is 0.0423 mm:

| Bar width | X-dimension | 9-char symbol |
|---|---|---|
| 3 dots | 0.127 mm | 17.0 mm |
| 4 dots | 0.169 mm | 22.7 mm |
| 5 dots | 0.212 mm | 28.4 mm |
| 6 dots | 0.254 mm | 34.0 mm |
| 8 dots | 0.339 mm | 45.4 mm |
| 10 dots | 0.423 mm | 56.7 mm |
| 12 dots | 0.508 mm | 68.1 mm |

At 300 dpi one dot is 0.0847 mm, so 3 dots is 0.254 mm — the usual starting
point. Check your printer's actual resolution before trusting a table: 300 dpi
and 600 dpi differ by a factor of two in X-dimension for the same dot count.

## Running it

```
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

Window:

```
python app.py
```

Command line:

```
python make_sheet.py --generate 24 --dpi 600 --out sheet.pdf
python make_sheet.py --sequential 40 --dpi 300
python make_sheet.py --edge --dpi 600 --out edges.pdf
python make_sheet.py --codes-file payloads.txt --dpi 600
```

`--generate` makes random payloads from the chosen alphabet with a fixed seed, so
the same seed always gives the same codes and a run can be repeated.

## The four pack symbols

A pack carries four different symbols and they are not interchangeable:

| Item | Symbology | Where it goes | Payload |
|---|---|---|---|
| Trigger | Code 128 | Trigger bottle, printed vertically | 10 characters |
| Reagent | Code 128 | Cartridge label | 9 characters |
| Method | QR | Manufacturer's method sheet | opaque text |
| Package | QR | Outer carton | opaque text |

```
python pack_app.py                       # window
python make_pack.py --out pack.pdf \
    --trigger IQEApeCg6t \
    --reagent iwUMArCYU \
    --method "TSH;Cal1;Lot20250902" \
    --package IQEA35yQjQ
```

Any subset works -- leave a field empty and that symbol is not printed.

Both short codes are Code 128 Subset B, which is forced by the payload: the codes
carry lower case letters and `+`/`/`, and Code 39 cannot represent either.

**QR is forced to a full symbol, never Micro QR.** `segno` picks Micro QR for
short text by default, and many fixed-mount readers do not decode it. The tool
passes `micro=False` so the shortest payload still produces a 21x21 symbol.

### Size caps

Bars default to 55 mm and QR squares to 30 mm, not the full page width. Without a
cap the trigger bar stretches to 181 mm on A4, which is a poster rather than a
label. Override with `--qr-square` or the max-bar-width field in the window.

## Long payloads: the calibration QR

The package QR on a calibration carton is **712 characters**, which encodes as a
**105x105** symbol. Two things matter here and neither is obvious:

**1. The payload is base64 and must be reproduced byte for byte.** Base64 has no
error tolerance for a hand copy: one wrong character silently changes a number in
the calibration data. Always scan the QR rather than retyping it, and use
*Check package payload* before printing.

**2. Module size governs readability, not square size.** A 105-module symbol
printed at 28 mm has a module of 0.27 mm. On 203 dpi thermal paper that smears.
The tool therefore sizes by *dots per module* and grows the square until the
module is at least 3 printer dots:

| dpi | module | printed square |
|---|---|---|
| 203 | 0.375 mm | 42.4 mm |
| 300 | 0.254 mm | 28.7 mm |
| 600 | 0.254 mm | 28.7 mm |

At 203 dpi the square grows to 42 mm on purpose. Shrinking it to match 300 dpi
would look neater and read worse.

### Checking a scanned payload

```
python - <<'EOF'
from bcgen import payload
text = open("scanned.txt").read().strip()
print(payload.round_trip(text).describe())
for line in payload.structure(text).summary():
    print(" ", line)
print(payload.check_reproducible(text))
EOF
```

`round_trip` decodes the base64 and re-encodes it, and reports whether the result
is identical to what was scanned. `structure` prints the top-level fields so you
can compare against the printed label -- the lot and expiry are visible in the
header, which is a fast way to confirm you scanned the right carton.

The decoded fields are **shown, never used**. Nothing is derived from them and
nothing is written back into the payload.


## Trigger and Pre-Trigger bottles

These are a separate family from the reagent cartridge and are easy to confuse
with it:

| | Bottle (Trigger / Pre-Trigger) | Cartridge |
|---|---|---|
| Code length | **10 characters** | 9 characters |
| Code content | six bytes: item, lot, serial | nine bytes |
| Carries a curve | **no** | yes, in the package QR |
| Second code | GS1 DataMatrix (traceability) | none |

The length difference is a real safeguard, not a detail: the tool refuses a
9-character payload on a bottle label, so a cartridge code cannot be printed onto
a trigger bottle by mistake.

```
python solution_app.py                 # window
python make_solution.py --out trigger.pdf \
    --set kind=trigger --set volume_ml=450 --set code=IQEApeCg6t \
    --set lot=20250902 --set produced=2025-09-02 --set expiry=2027-04-14 \
    --set gtin=06925912716570 --set internal=003067
```

### Sizes and GTIN

Sizes are 200, 450 and 800 mL. The size is printed as text; it is **not** encoded
into the Code 128, because the payload of a bottle code is fixed by the scheme and
injecting a size would produce a code the instrument does not recognise.

What distinguishes a 200 mL from an 800 mL is the **GTIN** in the GS1 DataMatrix.
Each size needs its own. The builder refuses two situations:

- the **same bottle code used twice** across the batch
- **one GTIN covering two sizes**, because then a reader cannot tell them apart

Both are refused rather than warned, because either one makes the register unable
to say which bottle was filled.

### Why zint is required

The GS1 DataMatrix needs a real **FNC1** immediately after the start character.
Without it a reader returns the application identifiers as literal text like
`(01)0692...` instead of parsing them as fields. The pure-Python DataMatrix
encoders available for Python do not emit FNC1 (reportlab's is also hardcoded to a
single 44x44 symbol), so GS1 symbols are generated with
[zint](https://zint.org.uk):

```
brew install zint        # macOS
choco install zint       # Windows
```

Every GS1 symbol is decoded again after building and checked element by element
before the file is offered. `--no-datamatrix` prints only the Code 128 if zint is
not available.

## Fitting your own calibration curve

A curve fitted from your own measurements is the only one that can honestly
describe your product. `calib.py` does that and nothing else: input is a table of
concentrations and the signals you observed, output is a curve plus the evidence.

```
python fit_curve.py samples/calibrators.csv --signal 300000 --csv-out params.csv
```

CSV format: `concentration,signal[,weight,label]`.

### The model

4PL or 5PL, the standards for immunoassay:

```
4PL:  y = d + (a - d) / (1 + (x / c) ** b)
5PL:  y = d + (a - d) / (1 + (x / c) ** b) ** g
```

`a` is the response at zero, `d` at saturation, `c` the inflection point, `b` the
slope, `g` the asymmetry (`g = 1` makes the 5PL identical to the 4PL).

### Three guards that matter

**1. The blank is pinned by default.** The zero calibrator's measured signal
defines `a`. Letting the solver move `a` freely produces a negative value that
fits the middle better and reports nonsense at the low end. Pinning it is what
keeps low-end results honest.

**2. A 5PL must earn its extra parameter.** An asymmetry within 5% of 1 is doing
nothing, so the 4PL wins rather than chasing a rounding difference.

**3. A 5PL must also be believable in shape.** This is the one that matters most.
On a truly 4PL dataset, a 5PL can reach a lower RMSE by pairing a large `g` with a
large `c` -- the two cancel out and the curve passes near every calibrator while
describing the wrong shape between them. The tell-tale is an inflection point
outside the measured range, which means every sample result would be an
extrapolation. `plausible()` reports this, `best_fit()` rejects it, and the window
prints the warning rather than hiding it.

### Recovery is the acceptance test

For each calibrator, the *measured* signal is run back through the curve and the
resulting concentration compared with the one that was made. That is not
circular -- it uses the measurement, not the fit -- and it is what a reviewer will
ask about. Default acceptance is 80-120%.

```
   point         conc         signal         fitted        resid  recovery%
---------------------------------------------------------------------------
      C1       0.0000       197.5519       197.5519       0.0000      blank
      C2       1.2500     22958.9874     21714.1769   -1244.8105     106.53
```

The blank is marked `blank`, not a percentage: there is no concentration to
recover a percentage of, so it is judged by its residual instead.

### Signals outside the curve

`back_calculate` returns `nan` for a signal below the curve and `inf` above
saturation. It does **not** return zero. That distinction matters: a saturated
sample reported as zero concentration looks like a valid result and nobody would
question it.

## Keeping the register

```
python - <<'EOF'
from bcgen.register import Register, Entry
book = Register.load("register.csv")
book.add(Entry(event="print", kind="reagent", code="iwUMArCYU",
               lot="20250902", expiry="2027-04-14", product="LH"))
EOF
```

A local append-only CSV, one row per label event. It exists to catch one mistake:
a code that belongs to one lot printed on a pack counted against another lot.

Rules it enforces:

- The same code cannot be `print`ed twice. Use `reprint` to record a replacement.
- The same code cannot appear under two lots. That is the failure that produces a
  wrong patient result.
- A `void` is always accepted, even for an inconsistent entry, because a
  correction must never be blocked.

`find_lot_mixing()` sweeps the whole file, catching a mix that was introduced
before either lot was known.

The register stores codes and lots. It stores the **hash** of a code as well, so a
shared file does not leak a manufacturer's payload.

## Printing complete labels

`label_app.py` prints a whole product label -- product name, volume, lot, expiry,
storage and notes -- with the barcode sized to the label width.

```
python label_app.py
```

Two paper models, because the hardware differs:

- **Roll** -- one label per page, page size equal to the label. This is what a
  receipt printer needs: it feeds exactly one page per job, so the page must be
  one label tall or every print wastes stock.
- **Sheet** -- many labels per page with dashed cut guides, for A4 sticker stock.

The barcode is **not** given a fixed size. It is sized to fill the label's inner
width, as a whole number of printer dots, and the bar height shrinks only as far
as the data needs (never below 6 mm).

### The size steps you actually get

One printer dot is 0.125 mm at 203 dpi and 0.0423 mm at 300 dpi. Because a module
must be a whole number of dots, asking for an arbitrary width snaps to whatever
fits:

| Printer | Achievable X-dimension |
|---|---|
| 203 dpi (receipt) | 0.125, 0.250, 0.375, 0.500 mm ... |
| 300 dpi | 0.085, 0.127, 0.169, 0.254 mm ... |

On 76 mm receipt paper a nine-character code lands on **0.375 mm** (57.8 mm wide),
and on 58 mm paper on **0.250 mm** (38.5 mm wide). Both are comfortably readable.
A 300 dpi label printer reaches 0.254 mm for the same label, which leaves room for
longer payloads.

### What fits on a label

Height is the constraint, not width. Six data rows at a 6 mm bar need about 34 mm,
so a 50x25 mm label carries roughly three rows. Leave a field empty and it is not
printed -- that is the intended way to fit a small label. If even the minimum does
not fit, the build is refused with the height it would need, rather than printing
a clipped label.


## Printing

1. Open the PDF in a viewer and print at **100% / Actual size**. Turn off
   "Fit to page", "Shrink to fit" and any "scale to margins" option.
2. On the printed page, measure the thick 50 mm bar at the bottom with a ruler.
   If it is not 50 mm, the printer scaled the page — every measurement on that
   sheet is invalid, so fix the setting and print again.
3. Use matte paper. Glossy stock reflects the scanner's light and fails for
   reasons unrelated to bar width.

## Measuring on the instrument

For each page, take the sheet to the reader and try several codes on it. Record
the page's bar width and whether the read was correct. The payload is printed
under each symbol, so "read correctly" means the reader returned exactly those
characters — not merely that it beeped.

A scanner can beep on a wrong read. `verify_read.py` does the character-by-character
comparison for you and flags the pairs that look alike:

```
python verify_read.py --expect x1Fh+zm9t --got x1Fh+zm9t
python verify_read.py --expect AE_Check9 --got '`E_Check9'
```

```
MATCH   'x1Fh+zm9t'
1/1 matched exactly, 0 did not
```

```
MISMATCH expected 'AE_Check9' got '`E_Check9'
  first difference at position 1: expected 'A', got '`'
  expected: A E _ C h e c k 9
  observed: ` E _ C h e c k 9
  marker  : ^
```

For a whole session, put the readings in a file, one `expected<TAB>observed` per
line, and run `python verify_read.py --file readings.tsv`. The exit status is
non-zero if anything differs, so it can gate a script.

Suggested record:

| page | dots | X (mm) | codes tried | reads correct | notes |
|---|---|---|---|---|---|
| 1 | 3 | 0.254 | 5 | 0 | |
| 2 | 4 | 0.339 | 5 | 4 | one misread |

The answer you are after is the **smallest page that reads flawlessly**. Anything
below it is not worth designing around.

## Self-check

```
python selftest.py
```

This runs four independent checks:

- **Width arithmetic** — every payload's module count matches `11 + 11n + 11 + 13`.
- **Round trip** — each symbol is rasterised and decoded with zxing-cpp; the
  decoded text must equal the payload exactly, including spaces and symbols.
- **Uniform elements** — the printed bars are measured in pixels and every
  element width must be a whole multiple of the module width.
- **Whole sheet** — every page of a generated PDF is rasterised and decoded, and
  the number of successful reads must equal the number of printed cells, with no
  stray readings.

The self-check is what separates "our symbol is wrong" from "the instrument
cannot read a correct symbol". Run it before drawing any conclusion from a failed
scan.

Unit checks (fast, no rendering):

```
python -m unittest discover -s tests
```

## Files

```
bcgen/code128.py     encoder, element width table, checksum
bcgen/generate.py    synthetic payloads
bcgen/kind.py        the four pack items, QR matrix and drawing
bcgen/pack.py        four-symbol sheet layout
bcgen/payload.py     long base64 payload round-trip and structure display
bcgen/calib.py       4PL/5PL fit, recovery, plausibility guards
bcgen/solution.py    Trigger and Pre-Trigger bottle labels with GS1 DataMatrix
bcgen/register.py    append-only print register with lot-mixing detection
bcgen/render.py      dot-exact bar drawing, free sizing, grid snapping
bcgen/sheet.py       A4 test-sheet layout
bcgen/label.py       full product label, roll and sheet
bcgen/measure.py     measures printed element widths in pixels
bcgen/results.py     observation log and smallest-working-size query
make_sheet.py        command line for test sheets
make_labels.py       command line for product labels
make_pack.py         command line for the four pack symbols
make_solution.py     command line for Trigger / Pre-Trigger bottle labels
fit_curve.py         command line for calibration fitting
app.py               window for test sheets
label_app.py         window for product labels
pack_app.py          window for the four pack symbols
solution_app.py      window for Trigger / Pre-Trigger labels
batch_app.py         window tying batch, curve, symbols and register together
selftest.py          render, decode, compare
verify_read.py       compare a scanner reading with the printed payload
tests/               unit, label and pack checks
samples/             pre-built sheets, labels and pack symbols
```

## What this tool does not do

- It does not generate codes that mean anything to any analyzer. Payloads are
  synthetic.
- It does not model, decode or imitate any manufacturer's encoding.
- It does not read or print real pack data.
