#!/usr/bin/env python3
"""Autoroute hardware/ece_souvenir.kicad_pcb: KiCad DSN export -> Konnect/Freerouting -> KiCad SES import.

Run with KiCad's bundled Python (needs `pcbnew`), KiCad GUI closed:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 tools/route.py [passes]

Why not Konnect's own export/apply tools: its Specctra profile only accepts
front-side footprints, rect/circle pads and straight-line outlines; this
board is bottom-side, roundrect pads, rounded corners. So KiCad's native
exporter/importer handle the file conversion and Konnect's
`route_specctra_dsn` drives Freerouting (local, headless).
"""
import math
import os
import re
import sys
import time

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import konnect_mcp  # noqa: E402

HW = os.path.normpath(os.path.join(HERE, "..", "hardware"))
PCB = os.path.join(HW, "ece_souvenir.kicad_pcb")
OUT = os.path.join(HW, "routing")
JRE = os.path.expanduser("~/.local/share/freerouting/jdk-25.0.4.1+1-jre/Contents/Home")
JAR = os.path.expanduser("~/.local/share/freerouting/freerouting-2.4.1.jar")

BOARD, CORNER_R = 30000, 1000      # um
EDGE_INSET = 100                   # Freerouting keeps 0.2 mm to the boundary; rules want 0.3 mm
# Single-sided: all copper on B.Cu with the parts; the top (logo) side stays
# bare. F.Cu is switched off for the router and vias are disabled. Crossings
# are solved by passing traces under the SOIC body or between 0603 pads.
AUTOROUTE = """    (autoroute_settings
      (fanout off) (autoroute on) (postroute on) (vias off)
      (via_costs 1000) (plane_via_costs 1000) (start_ripup_costs 100) (start_pass_no 1)
      (layer_rule F.Cu (active off) (preferred_direction horizontal)
        (preferred_direction_trace_costs 50.0) (against_preferred_direction_trace_costs 50.0))
      (layer_rule B.Cu (active on) (preferred_direction vertical)
        (preferred_direction_trace_costs 1.0) (against_preferred_direction_trace_costs 1.0))
    )
"""


def inset_boundary():
    """Rounded-rect outline shrunk by EDGE_INSET, as a DSN path (y negated)."""
    r = CORNER_R - EDGE_INSET
    lo, hi = CORNER_R, BOARD - CORNER_R
    pts = []
    for cx, cy, a0 in ((hi, lo, -90), (hi, hi, 0), (lo, hi, 90), (lo, lo, 180)):
        for k in range(9):
            a = math.radians(a0 + k * 90 / 8)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    pts.append(pts[0])
    return "(path pcb 0  " + "  ".join(f"{x:.1f} {-y:.1f}" for x, y in pts) + ")"


# Keepouts on every LED and LED resistor. With them on the 555 cluster too,
# Freerouting could not close C3->GND; relaxed there, it finds a planar route
# that still uses no pad gap. between_pad_crossings() reports any that appear.
UNDER_PART_OK = {"R1", "R2", "C1", "C2", "C3", "U1"}


def between_pad_crossings(board):
    """Foreign-net track segments passing between two pads of one part
    (both pads of a 2-pad part, or neighbouring SOIC pins): solder-bridge risks."""
    found = set()
    for fp in board.GetFootprints():
        pads = [p for p in fp.Pads() if p.GetNumber()]
        pairs = [(a, c) for i, a in enumerate(pads) for c in pads[i + 1:]
                 if len(pads) == 2 or math.hypot(a.GetPosition().x - c.GetPosition().x,
                                                 a.GetPosition().y - c.GetPosition().y) < 1.3e6]
        for a, c in pairs:
            box = pcbnew.BOX2I()
            box.Merge(a.GetBoundingBox())
            box.Merge(c.GetBoundingBox())
            for t in board.GetTracks():
                if t.GetClass() != "PCB_TRACK" or t.GetNetCode() in (a.GetNetCode(), c.GetNetCode()):
                    continue
                s, e = t.GetStart(), t.GetEnd()
                for k in range(81):
                    p = pcbnew.VECTOR2I(s.x + (e.x - s.x) * k // 80, s.y + (e.y - s.y) * k // 80)
                    if box.Contains(p) and not a.HitTest(p) and not c.HitTest(p):
                        found.add((fp.GetReference(), a.GetNumber(), c.GetNumber(), t.GetNetname()))
                        break
    return sorted(found)


def handsolder_keepouts(board):
    """DSN keepouts so no foreign trace runs between pads that get hand-soldered.

    Covers the gap between the two pads of every 2-pad part, and the gaps
    between neighbouring pins in each SOIC pad row (under-body routing is
    still allowed, entered from the chip ends). Returns DSN keepout lines.
    """
    um = lambda v: v / 1000.0  # noqa: E731  (KiCad nm -> DSN um)
    rects = []
    for fp in board.GetFootprints():
        if fp.GetReference() in UNDER_PART_OK:
            continue
        pads = [p for p in fp.Pads() if p.GetNumber()]
        boxes = [p.GetBoundingBox() for p in pads]
        pairs = []
        if len(pads) == 2:
            pairs = [(boxes[0], boxes[1])]
        elif len(pads) == 8:  # SOIC: neighbours within each row
            by_row = {}
            for b in boxes:
                by_row.setdefault(round(b.GetCenter().y if b.GetWidth() > b.GetHeight()
                                        else b.GetCenter().x, -4), []).append(b)
            for row in by_row.values():
                row.sort(key=lambda b: (b.GetCenter().x, b.GetCenter().y))
                pairs += list(zip(row, row[1:]))
        for a, b in pairs:
            x0, x1 = sorted([a.GetCenter().x, b.GetCenter().x])
            y0, y1 = sorted([a.GetCenter().y, b.GetCenter().y])
            if x1 - x0 > y1 - y0:   # pads side by side in x: gap spans x, height = pad height
                x0, x1 = min(a.GetRight(), b.GetRight()), max(a.GetLeft(), b.GetLeft())
                h = min(a.GetHeight(), b.GetHeight()) / 2
                yc = (a.GetCenter().y + b.GetCenter().y) / 2
                y0, y1 = yc - h, yc + h
            else:
                y0, y1 = min(a.GetBottom(), b.GetBottom()), max(a.GetTop(), b.GetTop())
                w = min(a.GetWidth(), b.GetWidth()) / 2
                xc = (a.GetCenter().x + b.GetCenter().x) / 2
                x0, x1 = xc - w, xc + w
            rects.append((um(x0), -um(y0), um(x1), -um(y1)))
    return ["    (keepout \"\" (polygon B.Cu 0  {0:.1f} {1:.1f}  {2:.1f} {1:.1f}  {2:.1f} {3:.1f}  "
            "{0:.1f} {3:.1f}  {0:.1f} {1:.1f}))\n".format(*r) for r in rects]


def export_dsn(board, dsn):
    assert pcbnew.ExportSpecctraDSN(board, dsn), "DSN export failed"
    text = open(dsn).read()
    text = re.sub(r"\(boundary\s*\(path pcb 0.*?\)\s*\)", "(boundary\n      " + inset_boundary() + "\n    )",
                  text, count=1, flags=re.S)
    # Order matters: Freerouting 2.4.1 silently drops the whole netlist when a
    # keepout precedes autoroute_settings inside (structure ...).
    text = text.replace("    (via ", AUTOROUTE + "".join(handsolder_keepouts(board)) + "    (via ", 1)
    open(dsn, "w").write(text)


def route(dsn, ses, passes):
    os.environ["JAVA_HOME"] = JRE
    os.environ["PATH"] = f"{JRE}/bin:" + os.environ["PATH"]
    c = konnect_mcp.Client()
    try:
        c.call("load_toolset", {"name": "integration"})
        r = c.call("route_specctra_dsn", {"dsn_path": dsn, "ses_output_path": ses, "jar_path": JAR, "max_passes": passes,
                                          "optimizer_enabled": True, "overall_timeout_seconds": 900})
    finally:
        c.close()
    print("route_specctra_dsn:", r)
    if r["isError"]:
        sys.exit(1)


def main():
    passes = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    os.makedirs(OUT, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dsn = os.path.join(OUT, f"ece_souvenir-{stamp}.dsn")
    ses = os.path.join(OUT, f"ece_souvenir-{stamp}.ses")

    board = pcbnew.LoadBoard(PCB)
    for t in list(board.GetTracks()):  # re-route from a clean slate
        board.Delete(t)
    export_dsn(board, dsn)
    route(dsn, ses, passes)
    assert pcbnew.ImportSpecctraSES(board, ses), "SES import failed"
    # Freerouting auto-necks traces down to 0.15 mm at some pads; restore the
    # net-class width (DRC afterwards proves clearances still hold).
    widened = 0
    for t in board.GetTracks():
        if t.GetClass() == "PCB_TRACK":
            want = board.GetDesignSettings().m_NetSettings.GetEffectiveNetClass(
                t.GetNetname()).GetTrackWidth()
            if t.GetWidth() < want:
                t.SetWidth(want)
                widened += 1
    print(f"widened {widened} neck-down segments to net-class width")
    pcbnew.SaveBoard(PCB, board)
    tracks = list(board.GetTracks())
    vias = [t for t in tracks if t.GetClass() == "PCB_VIA"]
    top = [t for t in tracks if t.GetClass() == "PCB_TRACK" and t.GetLayer() == pcbnew.F_Cu]
    bot = [t for t in tracks if t.GetClass() == "PCB_TRACK" and t.GetLayer() == pcbnew.B_Cu]
    mm = lambda ts: sum(t.GetLength() for t in ts) / 1e6  # noqa: E731
    print(f"imported {os.path.relpath(ses)}: {len(bot)} B.Cu segs ({mm(bot):.1f} mm), "
          f"{len(top)} F.Cu segs ({mm(top):.1f} mm), {len(vias)} vias")
    crossings = between_pad_crossings(board)
    print(f"between-pad crossings: {len(crossings)}", *crossings, sep="\n  ")


if __name__ == "__main__":
    main()
