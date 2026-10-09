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
# Make the top (logo) side expensive so Freerouting uses it only for crossings.
AUTOROUTE = """    (autoroute_settings
      (fanout off) (autoroute on) (postroute on) (vias on)
      (via_costs 30) (plane_via_costs 5) (start_ripup_costs 100) (start_pass_no 1)
      (layer_rule F.Cu (active on) (preferred_direction horizontal)
        (preferred_direction_trace_costs 4.0) (against_preferred_direction_trace_costs 6.0))
      (layer_rule B.Cu (active on) (preferred_direction vertical)
        (preferred_direction_trace_costs 1.0) (against_preferred_direction_trace_costs 1.6))
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


def export_dsn(board, dsn):
    assert pcbnew.ExportSpecctraDSN(board, dsn), "DSN export failed"
    text = open(dsn).read()
    text = re.sub(r"\(boundary\s*\(path pcb 0.*?\)\s*\)", "(boundary\n      " + inset_boundary() + "\n    )",
                  text, count=1, flags=re.S)
    text = text.replace("    (via ", AUTOROUTE + "    (via ", 1)
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


if __name__ == "__main__":
    main()
