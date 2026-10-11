#!/usr/bin/env python3
"""EMI / routing-geometry audit for hardware/ece_souvenir.kicad_pcb.

Run with KiCad's bundled Python (needs `pcbnew`):
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 tools/emi_check.py

Checks (exit 1 if any FAIL):
  - bends: track corners of 90 deg (right angle) or sharper (acute / acid trap)
  - stubs: track ends attached to nothing (antenna stubs)
  - edge:  copper closer than EDGE_MIN_MM to the board outline
Reports (info): T-junction count, track width per net, total length per net.
"""
import math
import os
import sys
from collections import defaultdict

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.normpath(os.path.join(HERE, "..", "hardware", "ece_souvenir.kicad_pcb"))
EDGE_MIN_MM = float(os.environ.get("EDGE_MIN_MM", "1.0"))
MM = pcbnew.ToMM


def key(p):
    return (round(p.x / 1000), round(p.y / 1000))  # 1 um grid


def bend_deg(a, v, b):
    """Direction change at v when going a -> v -> b (0 = straight, 90 = right angle)."""
    d1 = (v[0] - a[0], v[1] - a[1])
    d2 = (b[0] - v[0], b[1] - v[1])
    n1, n2 = math.hypot(*d1), math.hypot(*d2)
    if n1 == 0 or n2 == 0:
        return 0.0
    c = max(-1.0, min(1.0, (d1[0] * d2[0] + d1[1] * d2[1]) / (n1 * n2)))
    return math.degrees(math.acos(c))


def audit(board):
    pads_by_net = defaultdict(list)
    for fp in board.GetFootprints():
        for p in fp.Pads():
            pads_by_net[p.GetNetCode()].append(p)
    segs = [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"]
    vias = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]

    ends = defaultdict(list)          # (net, point) -> segments touching it
    for s in segs:
        for p in (s.GetStart(), s.GetEnd()):
            ends[(s.GetNetCode(), key(p))].append(s)

    def in_pad(net, pt):
        v = pcbnew.VECTOR2I(pt[0] * 1000, pt[1] * 1000)
        return any(p.HitTest(v) for p in pads_by_net[net])

    def on_other_track(net, pt, exclude):
        v = pcbnew.VECTOR2I(pt[0] * 1000, pt[1] * 1000)
        return any(t.GetNetCode() == net and t not in exclude and t.HitTest(v)
                   for t in segs) or any(t.GetNetCode() == net and t.HitTest(v) for t in vias)

    bends, tees, stubs = [], 0, []
    for (net, pt), ss in ends.items():
        if len(ss) == 2 and not in_pad(net, pt):
            a = [key(x) for x in (ss[0].GetStart(), ss[0].GetEnd()) if key(x) != pt][0]
            b = [key(x) for x in (ss[1].GetStart(), ss[1].GetEnd()) if key(x) != pt][0]
            ang = bend_deg(a, pt, b)
            if ang >= 89.5:
                bends.append((round(ang), ss[0].GetNetname(), pt))
        elif len(ss) >= 3:
            tees += 1
        elif len(ss) == 1 and not in_pad(net, pt) and not on_other_track(net, pt, ss):
            stubs.append((ss[0].GetNetname(), pt))

    # copper-to-edge distance (track segments and pads)
    edge = board.GetBoardEdgesBoundingBox()
    poly = pcbnew.SHAPE_POLY_SET()
    board.GetBoardPolygonOutlines(poly, False)
    outline = poly.Outline(0)
    worst = []
    for s in segs:
        # convex outline: distance-to-edge along a segment is concave, so the
        # minimum sits at an endpoint
        d = min(outline.Distance(s.GetStart(), True), outline.Distance(s.GetEnd(), True)) - s.GetWidth() / 2
        worst.append((MM(d), s.GetNetname()))
    worst.sort()

    widths, lengths = defaultdict(set), defaultdict(float)
    for s in segs:
        widths[s.GetNetname()].add(round(MM(s.GetWidth()), 3))
        lengths[s.GetNetname()] += MM(s.GetLength())
    return bends, tees, stubs, worst, widths, lengths, len(vias), edge


def main():
    board = pcbnew.LoadBoard(PCB)
    bends, tees, stubs, worst, widths, lengths, nvias, edge = audit(board)
    ox, oy = edge.GetLeft(), edge.GetTop()
    loc = lambda p: f"({30 - (p[0] * 1000 - ox) / 1e6:.2f}, {(p[1] * 1000 - oy) / 1e6:.2f}) bv"  # noqa: E731
    right = [b for b in bends if b[0] < 91]
    acute = [b for b in bends if b[0] >= 91]
    print(f"bends: {len(right)} right-angle, {len(acute)} acute (>90 deg turn); T-junctions: {tees}; vias: {nvias}")
    for ang, net, pt in sorted(bends, key=lambda b: (b[1], b[2]))[:60]:
        print(f"  {ang:3d} deg  {net:12s} {loc(pt)}")
    print(f"stubs: {len(stubs)}")
    for net, pt in stubs:
        print(f"  {net:12s} {loc(pt)}")
    close = [w for w in worst if w[0] < EDGE_MIN_MM]
    print(f"copper-to-edge: min {worst[0][0]:.2f} mm ({worst[0][1]}); "
          f"{len(close)} segments closer than {EDGE_MIN_MM} mm "
          f"(nets: {sorted({n for _, n in close})})")
    print("nets: width mm / length mm")
    for n in sorted(lengths):
        print(f"  {n:12s} {sorted(widths[n])} {lengths[n]:6.1f}")
    fail = bool(right or acute or stubs or close)
    print("EMI geometry:", "FAIL" if fail else "PASS")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
