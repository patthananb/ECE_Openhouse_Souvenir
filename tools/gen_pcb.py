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

MM = pcbnew.FromMM


def P(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


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
# LEDs stand alone in the digit area. Their 3.3 k resistors form one row of
# vertical 0603s (1.6 mm pitch) between the digits and the 555, grouped
# under the digit they feed so anode traces stay short and uncrossed.
R_ROW_Y = 17.6
R_ROW = {  # resistor: x (bottom view); pad toward the LEDs = anode side
    # Single-sided order: f and e anodes leave their digit downward on the
    # left, d/g/a anodes through the channel on the digit's right (nested,
    # d innermost), so the row reads f e d g a per digit and nothing crosses.
    "R4": 3.0, "R6": 4.6, "R7": 6.2, "R5": 7.8, "R3": 9.4,        # E1: f e d g a
    "R9": 12.2, "R10": 13.8, "R11": 15.4, "R8": 17.0,              # C:  f e d a
    "R13": 20.2, "R15": 21.8, "R16": 23.4, "R14": 25.0, "R12": 26.6,  # E2: f e d g a
}
# LED polarity for single-sided routing: cathodes on the left end of a/g/d
# (180 deg) and the top end of f/e (270 deg) all meet at each digit's inner
# left corner, where one LED_SINK trunk collects them. The spec's 0/90 deg puts
# cathodes on opposite sides and forces sink/anode crossings on one layer.
LED_ROT_H, LED_ROT_V = 180, 270

# --- everything else (bottom view x_bv, y, orientation deg) ----------------
OTHERS = {
    # U1 at 270: pins 1-4 (GND, TRIG, OUT, RST) face up toward the LED field,
    # pins 5-8 (CV, THR, DIS, VCC) face the timing parts along the bottom edge.
    "U1": (15.0, 24.2, 270),
    "C2": (18.6, 25.7, 90),    # decoupling: centre 1.96 mm from pin 8, pad1 (VCC) at the pin-8 end
    "R2": (15.0, 28.75, 0),    # DIS -> TH, under pins 7/6
    "R1": (18.4, 28.75, 0),    # VCC -> DIS (DIS pad next to R2 DIS pad)
    "C1": (11.6, 28.75, 0),    # TH -> GND
    "C3": (11.2, 25.0, 90),    # CV (pin 5) -> GND
    "TP1": (4.0, 26.4, 0),     # +
    "TP2": (7.6, 26.4, 0),     # -
    "TP3": (25.6, 26.0, 0),    # OUT probe
}


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
            poly.Append(MM(x), MM(y))
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
}
NETCLASSES = {  # name: (track, clearance, via dia, via drill, net patterns)
    "Default": (0.2, 0.2, 0.6, 0.3, []),
    "Power": (0.3, 0.2, 0.6, 0.3, ["VCC", "GND"]),
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
    return (round(BOARD - pcbnew.ToMM(pos.x), 3), round(pcbnew.ToMM(pos.y), 3))


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

    # standalone LEDs, then the resistor row
    for ref, (x, y, seg) in LEDS.items():
        place(fps[ref], x, y, LED_ROT_H if seg in "agd" else LED_ROT_V)
    for ref, x in R_ROW.items():
        best = None
        for a in (90, 270):  # put pin 2 (anode side) on the LED side of the row
            place(fps[ref], x, R_ROW_Y, a)
            if best is None or pad_bv(fps[ref], "2")[1] < best[0]:
                best = (pad_bv(fps[ref], "2")[1], a)
        place(fps[ref], x, R_ROW_Y, best[1])

    for ref, (x, y, a) in OTHERS.items():
        place(fps[ref], x, y, a)

    # keychain hole stays a top-side (unflipped) NPTH
    fps["H1"].SetPosition(P(*HOLE))

    add_outline(board)
    n_logo = add_logo(board)

    # bottom silkscreen labels for the pads (mirrored so they read from the bottom)
    tp_lbl = {"TP1": "+", "TP2": "−", "TP3": "OUT"}
    for ref, txt in tp_lbl.items():
        x, y, _ = OTHERS[ref]
        size = 1.0 if ref == "TP3" else 1.2
        add_text(board, txt, *bv(x, y + 2.1), pcbnew.B_SilkS,
                 size=size, thick=0.2, mirrored=True)

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
