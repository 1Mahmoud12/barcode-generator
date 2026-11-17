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
bcgen/render.py      dot-exact bar drawing, grid snapping
bcgen/sheet.py       A4 page layout
bcgen/measure.py     measures printed element widths in pixels
bcgen/results.py     observation log and smallest-working-size query
make_sheet.py        command line
app.py               window
selftest.py          render, decode, compare
verify_read.py       compare a scanner reading with the printed payload
tests/test_units.py  unit checks
samples/             pre-built sheets for 300 and 600 dpi
```

## What this tool does not do

- It does not generate codes that mean anything to any analyzer. Payloads are
  synthetic.
- It does not model, decode or imitate any manufacturer's encoding.
- It does not read or print real pack data.
