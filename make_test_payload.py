"""Build a synthetic payload with the same shape as a calibration QR.

The real payload behind these tests is a manufacturer's calibration curve. It is
deliberately not stored in this repository: it describes another company's product,
and a public repository is not the place for it.

What the tests actually need is not that specific data but its *shape* -- a long
base64 string whose decoded form is comma/pipe delimited with a header, ten
calibration points and a trailing settings block. This builder produces exactly
that from invented numbers, so every structural property is exercised while no real
data is present.

Run it to regenerate the constant used by the tests:

    python make_test_payload.py
"""

from __future__ import annotations

import base64
import random


def calibration_like_payload(seed: int = 0) -> str:
    """A base64 payload with a calibration QR's structure, from invented numbers."""
    rng = random.Random(seed)

    # Header: record type, assay code, identifier, lot, expiry, two constants.
    identifier = base64.b64encode(bytes(rng.randrange(256) for _ in range(6))).decode().rstrip("=")
    header = f"T,{rng.randrange(100, 999)},{identifier},20250101,20270101,2,10"

    # Ten calibration points: concentration, signal, weight.
    points = []
    concentration = 0.0
    signal = 100.0
    for _ in range(10):
        weight = 1.0
        points.append(f"{concentration:.6f}|{signal:.6f}|{weight:.6f}")
        concentration = round(concentration * 1.9 + rng.uniform(0.5, 2.5), 6)
        signal = round(signal * rng.uniform(1.8, 2.4), 6)

    # Asymmetric trailing section, as the real format has.
    tail = (
        f"{signal * 0.4:.6f}|{signal * 1.3:.6f}|{rng.uniform(0.9, 1.1):.6f}"
        f"|{rng.uniform(1e6, 1e9):.6f},3"
    )

    settings = [
        f"0|{rng.uniform(1, 3):.6f}|0.000000|{rng.randrange(1000, 9999)}|10|1|0.500000|0.000000",
        f"0|0.200000|{rng.uniform(5, 12):.6f}|{rng.randrange(10000, 99999)}"
        f"|{rng.randrange(1000, 9999)}|1|2.000000|0.500000",
        f"0|0.200000|{rng.uniform(100, 200):.6f}|{rng.randrange(100000, 999999)}"
        f"|{rng.randrange(100000, 200000)}|1|2.000000|0.500000",
        f"1.000000|1.000000,1,1,1,1,1,{rng.randrange(20000, 40000)}",
    ]

    decoded = "$".join([header] + points + [tail] + settings)
    return base64.b64encode(decoded.encode()).decode()


def constant_block(payload: str, width: int = 72) -> str:
    """Format a payload as a Python string constant, wrapped for readability."""
    chunks = [payload[i : i + width] for i in range(0, len(payload), width)]
    body = "\n".join(f'    "{chunk}"' for chunk in chunks)
    return f"CALIBRATION = (\n{body}\n)"


if __name__ == "__main__":
    payload = calibration_like_payload()
    print(f"# {len(payload)} characters")
    print(constant_block(payload))
