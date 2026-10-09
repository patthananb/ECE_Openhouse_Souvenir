#!/usr/bin/env python3
"""Rasterise art/ece_logo.png into silkscreen pixel runs (mm, top-view coords).

Silkscreen is one colour, so every non-white pixel (black, orange, grey) is
ink. The image is upsampled 2x before thresholding so the staircase edges are
~14 um, well below silkscreen print resolution. Output: art/ece_logo_runs.json,
consumed by tools/gen_pcb.py (which runs under KiCad's Python, without PIL).

Usage: python3 tools/logo_trace.py [width_mm] [x0_mm] [y0_mm]
"""
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "art", "ece_logo.png")
OUT = os.path.join(HERE, "..", "art", "ece_logo_runs.json")
UPSAMPLE = 2
THRESHOLD = 0.15  # darkness = 1 - min(R,G,B)/255; light grey (~170) reads ~0.33


def main():
    width_mm = float(sys.argv[1]) if len(sys.argv) > 1 else 24.0
    x0_mm = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    y0_mm = float(sys.argv[3]) if len(sys.argv) > 3 else 6.0

    rgb = np.asarray(Image.open(SRC).convert("RGB")).astype(np.float32)
    dark = 1.0 - rgb.min(axis=2) / 255.0
    ys, xs = np.nonzero(dark > THRESHOLD)
    dark = dark[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = dark.shape
    big = Image.fromarray((dark * 255).astype(np.uint8)).resize(
        (w * UPSAMPLE, h * UPSAMPLE), Image.LANCZOS)
    ink = np.asarray(big) > THRESHOLD * 255
    mm_per_px = width_mm / ink.shape[1]

    # horizontal runs, then merge identical runs in consecutive rows into rectangles
    rects, open_runs = [], {}
    for y in range(ink.shape[0] + 1):
        row = ink[y] if y < ink.shape[0] else np.zeros(ink.shape[1], bool)
        d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
        runs = set(zip(np.nonzero(d == 1)[0].tolist(), np.nonzero(d == -1)[0].tolist()))
        for run in list(open_runs):
            if run not in runs:
                rects.append((open_runs.pop(run), y, *run))
        for run in runs:
            open_runs.setdefault(run, y)
    out = [[round(x0_mm + xa * mm_per_px, 4), round(y0_mm + ya * mm_per_px, 4),
            round(x0_mm + xb * mm_per_px, 4), round(y0_mm + yb * mm_per_px, 4)]
           for ya, yb, xa, xb in rects]
    json.dump({"source": "art/ece_logo.png", "width_mm": width_mm,
               "height_mm": round(ink.shape[0] * mm_per_px, 3), "origin_mm": [x0_mm, y0_mm],
               "mm_per_px": mm_per_px, "rects": out}, open(OUT, "w"))
    print(f"{len(out)} rects, {width_mm} x {ink.shape[0] * mm_per_px:.2f} mm at "
          f"({x0_mm}, {y0_mm}), {mm_per_px * 1000:.1f} um/px -> {os.path.relpath(OUT)}")


if __name__ == "__main__":
    main()
