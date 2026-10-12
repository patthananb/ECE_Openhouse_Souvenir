#!/usr/bin/env python3
"""Generate hardware/ece_souvenir.kicad_pcb (outline, placement, logo, rules).

Run with KiCad's bundled Python (needs `pcbnew`):
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 tools/gen_pcb.py

Coordinates: KiCad top-view mm, origin top-left. Bottom-side parts are given
in BOTTOM-VIEW coords (how the viewer reads "ECE") and mirrored with
x_top = BOARD - x_bv.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from parts import PARTS  # noqa: E402

KICAD = "/Applications/KiCad/KiCad.app/Contents"
KICAD_CLI = f"{KICAD}/MacOS/kicad-cli"
FP_DIR = f"{KICAD}/SharedSupport/footprints"
HW = os.path.normpath(os.path.join(HERE, "..", "hardware"))
SCH = os.path.join(HW, "ece_souvenir.kicad_sch")
PCB = os.path.join(HW, "ece_souvenir.kicad_pcb")
PRO = os.path.join(HW, "ece_souvenir.kicad_pro")
LOGO = os.path.normpath(os.path.join(HERE, "..", "art", "ece_logo_runs.json"))

BOARD = 30.0
CORNER_R = 1.0
HOLE = (27.0, 3.0)  # top view

# Board sits where it was placed on the drawing sheet in KiCad (user edit
# 2026-10-10); all local coordinates are relative to its top-left corner,
# and the grid / drill-place origins are set there so (0,0) stays top-left.
OFFSET = (111.1825, 56.0585)

MM = pcbnew.FromMM


def P(x, y):
    return pcbnew.VECTOR2I(MM(x + OFFSET[0]), MM(y + OFFSET[1]))


def bv(x, y):
    """bottom-view -> top-view coordinates"""
    return (BOARD - x, y)


# --- LED 7-segment table (bottom view), from the spec ------------------------
# ref: (x_bv, y, segment). Horizontal (a, g, d) at 0 deg, vertical (f, e) at 90 deg.
LEDS = {
    "D1": (7.0, 4.0, "a"), "D2": (4.5, 6.5, "f"), "D3": (7.0, 9.0, "g"),
    "D4": (4.5, 11.5, "e"), "D5": (7.0, 14.0, "d"),
    "D6": (15.0, 4.0, "a"), "D7": (12.5, 6.5, "f"), "D8": (12.5, 11.5, "e"),
    "D9": (15.0, 14.0, "d"),
    "D10": (23.0, 4.0, "a"), "D11": (20.5, 6.5, "f"), "D12": (23.0, 9.0, "g"),
    "D13": (20.5, 11.5, "e"), "D14": (23.0, 14.0, "d"),
}
# One current-limit resistor per digit (advisor review), vertical under the
# digit centre: anode pad up toward the LEDs, LED_PWR pad down to the bus.
DIGIT_R_Y = 17.0
DIGIT_R = {"R3": 8.0, "R4": 15.0, "R5": 23.0}  # E1 (shifted right to leave room for Q1), C, E2
# LED polarity for single-sided routing: cathodes on the left end of a/g/d
# (180 deg) and the top end of f/e (270 deg) all meet at each digit's inner
# left corner, where one GND trunk collects them; anodes fan out to the
# digit resistor. The spec's 0/90 deg puts cathodes on opposite sides.
LED_ROT_H, LED_ROT_V = 180, 270

# --- everything else (bottom view x_bv, y, orientation deg) ----------------
OTHERS = {
    # U1 at 270: pins 1-4 (GND, TRIG, OUT, RST) face up toward the LED field,
    # pins 5-8 (CV, THR, DIS, VCC) face the timing parts along the bottom edge.
    # Single-sided topology (see tools/route.py PREROUTES): TH and GND leave
    # under the body to its left end, VCC is a ring round the board edge.
    "U1": (15.0, 24.2, 270),
    "C2": (18.6, 25.7, 90),    # decoupling: centre 1.96 mm from pin 8, pad1 (VCC) at the pin-8 end
    "R2": (15.0, 28.75, 0),    # DIS (right) -> TH (left), under pins 7/6
    "R1": (18.6, 28.75, 0),    # DIS (left) -> VCC (right, up to the ring)
    "C1": (11.0, 23.7, 270),   # TH (top, TH lane end) -> GND (bottom, GND lane end): ~1 mm timing-cap loop
    "C3": (11.5, 27.05, 90),   # GND (top, from C1) -> CV (bottom, to pin 5)
    "TP1": (24.5, 28.6, 0),    # + on the VCC ring
    "TP2": (24.5, 24.6, 0),    # -
    "TP3": (12.8, 19.2, 0),    # OUT probe on the OUT run
    "R6": (9.9, 19.45, 0),     # Q1 base resistor
    "Q1": (4.55, 18.0, 0),     # PNP: C right to the LED_PWR bus, E/B left (clear of the 1 mm VCC ring)
}
# parts whose rotation is chosen so a given pad faces a direction:
# ref: (pad, axis, sign) -> that pad gets the smallest (sign -1) / largest (+1) coordinate
ORIENT = {"R6": ("2", 0, +1), "Q1": ("3", 0, +1)}
# bottom-silk labels: ref -> (text, dx, dy, size)
TP_LABELS = {"TP1": ("+", 2.4, 0.0, 1.2), "TP2": ("\u2212", 2.4, 0.0, 1.2), "TP3": ("OUT", 0.0, -2.5, 1.0)}


def export_netlist():
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "net.net")
        subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr",
                        "-o", out, SCH], check=True, capture_output=True)
        text = open(out).read()
    comps = {}
    for block in re.split(r"\(comp\s+\(ref ", text)[1:]:
        ref = re.match(r'"([^"]+)"', block).group(1)
        comps[ref] = re.search(r'\(tstamps "([^"]+)"\)\s*\)?\s*$', block.split("(libsource")[0]
                               ) or re.findall(r'\(tstamps "([^"]+)"\)', block)[-1]
        if not isinstance(comps[ref], str):
            comps[ref] = comps[ref].group(1)
    nets = {}
    for block in re.split(r"\(net\s+\(code", text)[1:]:
        name = re.search(r'\(name "([^"]*)"\)', block).group(1)
        for r, p in re.findall(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)', block):
            nets[(r, p)] = name
    return comps, nets


def add_outline(board):
    r, b = CORNER_R, BOARD
    segs = [((r, 0), (b - r, 0)), ((b, r), (b, b - r)), ((b - r, b), (r, b)), ((0, b - r), (0, r))]
    for a, c in segs:
        s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(P(*a))
        s.SetEnd(P(*c))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(MM(0.05))
        board.Add(s)
    k = r * (1 - 2 ** -0.5)
    arcs = [((0, r), (k, k), (r, 0)), ((b - r, 0), (b - k, k), (b, r)),
            ((b, b - r), (b - k, b - k), (b - r, b)), ((r, b), (k, b - k), (0, b - r))]
    for a, m, c in arcs:
        s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_ARC)
        s.SetArcGeometry(P(*a), P(*m), P(*c))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(MM(0.05))
        board.Add(s)


def add_logo(board):
    data = json.load(open(LOGO))
    poly = pcbnew.SHAPE_POLY_SET()
    for x0, y0, x1, y1 in data["rects"]:
        poly.NewOutline()
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            poly.Append(MM(x + OFFSET[0]), MM(y + OFFSET[1]))
    poly.Simplify()   # union of all pixel rectangles
    poly.Fracture()   # holes -> bridged single outlines (PCB_SHAPE polys can't hold holes)
    n = 0
    for i in range(poly.OutlineCount()):
        one = pcbnew.SHAPE_POLY_SET()
        one.AddOutline(poly.Outline(i))
        if one.Area() < MM(0.07) ** 2:  # drop anti-alias specks (< ~0.005 mm^2)
            continue
        s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_POLY)
        s.SetPolyShape(one)
        s.SetFilled(True)
        s.SetWidth(0)
        s.SetLayer(pcbnew.F_SilkS)
        board.Add(s)
        n += 1
    return n


def add_text(board, txt, x, y, layer, size=1.2, thick=0.18, mirrored=False):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(txt)
    t.SetPosition(P(x, y))
    t.SetLayer(layer)
    t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
    t.SetTextThickness(MM(thick))
    t.SetMirrored(mirrored)
    board.Add(t)


# JLCPCB-safe rules from the spec, written into the .kicad_pro after saving
RULES = {
    "min_clearance": 0.2,
    "min_track_width": 0.2,
    "min_via_diameter": 0.6,
    "min_through_hole_diameter": 0.3,
    "min_via_annular_width": 0.15,
    "min_copper_edge_clearance": 0.3,
    "min_hole_clearance": 0.25,
    "min_hole_to_hole": 0.5,
    "min_text_height": 1.0,
    "min_text_thickness": 0.15,
    "min_silk_clearance": 0.0,
    # GND pour is a supplementary return path: every pad also has a routed trace,
    # so one thermal spoke is enough (and easier to hand-solder) where the
    # router has boxed the other sides in.
    "min_resolved_spokes": 1,
}
NETCLASSES = {  # name: (track, clearance, via dia, via drill, net patterns)
    "Default": (0.2, 0.2, 0.6, 0.3, []),
    # LED_PWR carries the switched LED current: wide, low-inductance like the rails
    "Power": (0.3, 0.2, 0.6, 0.3, ["VCC", "GND", "/LED_PWR"]),
}


def apply_rules():
    pro = json.load(open(PRO))
    ds = pro["board"]["design_settings"]
    ds["rules"].update(RULES)
    ds["defaults"]["silk_line_width"] = 0.15
    ds["defaults"]["silk_text_thickness"] = 0.15
    ns = pro["net_settings"]
    template = next(c for c in ns["classes"] if c["name"] == "Default")
    classes = []
    for name, (tw, cl, vd, vdr, _) in NETCLASSES.items():
        c = dict(template, name=name, track_width=tw, clearance=cl, via_diameter=vd, via_drill=vdr)
        if name != "Default":
            c["priority"] = 0
        classes.append(c)
    ns["classes"] = classes
    ns["netclass_patterns"] = [{"netclass": n, "pattern": p}
                               for n, v in NETCLASSES.items() for p in v[4]]
    json.dump(pro, open(PRO, "w"), indent=2)
    open(PRO, "a").write("\n")


def place(fp, x_bv, y, angle):
    x, y = bv(x_bv, y)
    fp.SetPosition(P(x, y))
    if not fp.IsFlipped():
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
    fp.SetOrientationDegrees(angle)


def pad_bv(fp, num):
    pos = fp.FindPadByNumber(num).GetPosition()
    return (round(BOARD - (pcbnew.ToMM(pos.x) - OFFSET[0]), 3), round(pcbnew.ToMM(pos.y) - OFFSET[1], 3))


def build():
    comps, nets = export_netlist()
    board = pcbnew.NewBoard(PCB)
    board.SetCopperLayerCount(2)

    netinfo = {}
    for name in sorted(set(nets.values())):
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        netinfo[name] = ni

    fps = {}
    for ref in sorted(comps):
        lib_id, value, fpid, lcsc, mpn, _lt, desc = PARTS[ref]
        lib, name = fpid.split(":")
        fp = pcbnew.FootprintLoad(f"{FP_DIR}/{lib}.pretty", name)
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        fp.SetReference(ref)
        fp.SetValue(value)
        fp.SetPath(pcbnew.KIID_PATH("/" + comps[ref]))
        fp.SetSheetname("Root")
        fp.SetSheetfile("ece_souvenir.kicad_sch")
        for k, v in (("LCSC", lcsc), ("MPN", mpn), ("Description", desc)):
            if v:
                fp.SetField(k, v)
                f = fp.GetField(k)  # new fields default to visible silk
                f.SetVisible(False)
                f.SetLayer(pcbnew.F_Fab)
        fp.Reference().SetVisible(False)  # keep bottom silk clean; refs stay on Fab
        if ref[0] in "RCD":
            fp.Value().SetVisible(False)  # 0402 values only clutter the Fab drawing
        if ref.startswith(("TP", "H")):
            fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM
                             | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
        for pad in fp.Pads():
            net = nets.get((ref, pad.GetNumber()))
            if net:
                pad.SetNet(netinfo[net])
        board.Add(fp)
        fps[ref] = fp

    # standalone LEDs, then the per-digit resistors
    for ref, (x, y, seg) in LEDS.items():
        place(fps[ref], x, y, LED_ROT_H if seg in "agd" else LED_ROT_V)
    for ref, x in DIGIT_R.items():
        best = None
        for a in (90, 270):  # anode pad (2) up toward the digit
            place(fps[ref], x, DIGIT_R_Y, a)
            if best is None or pad_bv(fps[ref], "2")[1] < best[0]:
                best = (pad_bv(fps[ref], "2")[1], a)
        place(fps[ref], x, DIGIT_R_Y, best[1])

    for ref, (x, y, a) in OTHERS.items():
        if ref in ORIENT:
            pad, axis, sign = ORIENT[ref]
            a = max((0, 90, 180, 270), key=lambda r: (place(fps[ref], x, y, r),
                                                     sign * pad_bv(fps[ref], pad)[axis])[1])
        place(fps[ref], x, y, a)

    # keychain hole stays a top-side (unflipped) NPTH
    fps["H1"].SetPosition(P(*HOLE))

    ds = board.GetDesignSettings()
    ds.SetAuxOrigin(P(0, 0))   # drill/place origin = board top-left
    ds.SetGridOrigin(P(0, 0))

    add_outline(board)
    n_logo = add_logo(board)

    # bottom silkscreen labels for the pads (mirrored so they read from the bottom)
    for ref, (txt, dx, dy, size) in TP_LABELS.items():
        x, y, _ = OTHERS[ref]
        add_text(board, txt, *bv(x + dx, y + dy), pcbnew.B_SilkS, size=size, thick=0.2, mirrored=True)

    pcbnew.SaveBoard(PCB, board)
    apply_rules()
    return board, fps, n_logo


def report(fps):
    print("pad positions (bottom view):")
    for ref in sorted(fps, key=lambda r: (r.rstrip("0123456789"), int(re.sub(r"\D", "", r) or 0))):
        fp = fps[ref]
        pads = " ".join(f"{p.GetNumber()}:{pad_bv(fp, p.GetNumber())}:{p.GetNetname()}"
                        for p in fp.Pads() if p.GetNumber())
        print(f"  {ref:4s} rot {fp.GetOrientationDegrees():6.1f} {pads}")


if __name__ == "__main__":
    board, fps, n_logo = build()
    print(f"wrote {os.path.relpath(PCB)}; logo polygons: {n_logo}")
    if "-v" in sys.argv:
        report(fps)
