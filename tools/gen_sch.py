#!/usr/bin/env python3
"""Generate hardware/ece_souvenir.kicad_sch from tools/parts.py.

Writes KiCad 9 format (20250114); run `kicad-cli sch upgrade` afterwards to
bring it to the installed KiCad's native format. Every pin gets a short wire
stub ending in a net label or power symbol, so connectivity is explicit and
checkable from the exported netlist.
"""
import math
import os
import re
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))
from parts import DIGITS, PARTS  # noqa: E402

KICAD_SYM = os.environ.get(
    "KICAD_SYMBOL_DIR",
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols")
PROJECT = "ece_souvenir"
OUT = os.path.join(os.path.dirname(__file__), "..", "hardware", f"{PROJECT}.kicad_sch")
ROOT_UUID = "6c3e6f0e-5b1a-4c55-9e0e-ece500000001"
STUB = 2.54

# Deterministic UUIDs keep diffs stable between regenerations.
_NS = uuid.UUID("0b7f9d2e-0000-4000-8000-ece500000000")


def uid(*key):
    return str(uuid.uuid5(_NS, "/".join(map(str, key))))


def grab_symbol(lib, name):
    text = open(f"{KICAD_SYM}/{lib}.kicad_sym").read()
    i = text.index(f'\t(symbol "{name}"\n') + 1
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    raise ValueError(name)


def lib_symbol(lib_id):
    """Return (flattened symbol text for lib_symbols, {pin: (x, y, angle)})."""
    lib, name = lib_id.split(":")
    body = grab_symbol(lib, name)
    m = re.search(r'\(extends "([^"]+)"\)', body)
    if m:  # flatten derived symbol onto its parent's graphics/pins
        parent = grab_symbol(lib, m.group(1))
        props = re.findall(r'\t\t\(property .*?\n\t\t\)', body, re.S)
        ptext = re.sub(r'\t\t\(property .*?\n\t\t\)\n', "", parent, flags=re.S)
        ptext = ptext.replace(f'"{m.group(1)}', f'"{name}')
        head, rest = ptext.split("\n", 1)
        # properties must precede unit sub-symbols
        k = rest.index(f'\t\t(symbol "{name}_')
        ptext = head + "\n" + rest[:k] + "\n".join(props) + "\n" + rest[k:]
        body = ptext
    pins = {}
    for pm in re.finditer(r'\(pin \w+ \w+\s*\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\).*?\(number "(\w+)"',
                          body, re.S):
        pins[pm.group(4)] = (float(pm.group(1)), float(pm.group(2)), int(pm.group(3)))
    body = body.replace(f'(symbol "{name}"', f'(symbol "{lib_id}"', 1)
    return body, pins


def rot(x, y, a):
    r = math.radians(a)
    return (x * math.cos(r) - y * math.sin(r), x * math.sin(r) + y * math.cos(r))


def snap(v):
    return round(v / 0.01) * 0.01


class Sheet:
    def __init__(self):
        self.libs = {}
        self.items = []
        self.pwr_n = 0

    def _lib(self, lib_id):
        if lib_id not in self.libs:
            self.libs[lib_id] = lib_symbol(lib_id)
        return self.libs[lib_id]

    def pin_info(self, sym, pin):
        """Screen position of a pin end and the outward direction (unit vector)."""
        _, pins = self._lib(sym["lib_id"])
        px, py, pa = pins[pin]
        rx, ry = rot(px, py, sym["angle"])
        pos = (snap(sym["x"] + rx), snap(sym["y"] - ry))
        # pin angle points from the connection end into the body; outward is opposite
        dx, dy = rot(math.cos(math.radians(pa)), math.sin(math.radians(pa)), sym["angle"])
        return pos, (-round(dx), round(dy))

    def symbol(self, ref, lib_id, x, y, angle=0, value=None, footprint="", fields=None,
               ref_off=(2.54, -1.27), val_off=(2.54, 1.27), hide_val=False, in_bom=None):
        self._lib(lib_id)
        if in_bom is None:
            in_bom = not ref.startswith("#")
        sym = dict(ref=ref, lib_id=lib_id, x=x, y=y, angle=angle)
        props = [("Reference", ref, ref_off, ref.startswith("#")),
                 ("Value", value, val_off, hide_val),
                 ("Footprint", footprint, (0, 0), True),
                 ("Datasheet", "", (0, 0), True)]
        for k, v in (fields or {}).items():
            props.append((k, v, (0, 0), True))
        ptxt = ""
        for k, v, (ox, oy), hide in props:
            just = "(justify left)" if k in ("Reference", "Value") and not ref.startswith("#") else ""
            fa = 90 if angle in (90, 270) else 0  # keeps field text horizontal on rotated parts
            ptxt += (f'\t\t(property "{k}" "{v}"\n\t\t\t(at {snap(x + ox)} {snap(y + oy)} {fa})\n'
                     f'\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n'
                     f'\t\t\t\t{just}\n\t\t\t\t{"(hide yes)" if hide else ""}\n\t\t\t)\n\t\t)\n')
        _, pins = self.libs[lib_id]
        pin_txt = "".join(f'\t\t(pin "{p}"\n\t\t\t(uuid "{uid(ref, "pin", p)}")\n\t\t)\n' for p in pins)
        self.items.append(
            f'\t(symbol\n\t\t(lib_id "{lib_id}")\n\t\t(at {x} {y} {angle})\n\t\t(unit 1)\n'
            f'\t\t(exclude_from_sim no)\n\t\t(in_bom {"yes" if in_bom else "no"})\n'
            f'\t\t(on_board {"no" if ref.startswith("#") else "yes"})\n\t\t(dnp no)\n'
            f'\t\t(uuid "{uid(ref)}")\n{ptxt}{pin_txt}'
            f'\t\t(instances\n\t\t\t(project "{PROJECT}"\n\t\t\t\t(path "/{ROOT_UUID}"\n'
            f'\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)')
        return sym

    def part(self, ref, x, y, angle=0, **kw):
        lib_id, value, fp, lcsc, mpn, lib_type, desc = PARTS[ref]
        fields = {k: v for k, v in (("Description", desc), ("LCSC", lcsc), ("MPN", mpn)) if v}
        # test pads and the keychain hole are bare copper/drill, not BOM items
        return self.symbol(ref, lib_id, x, y, angle, value, fp, fields,
                           in_bom=lib_type != "none", **kw)

    def wire(self, a, b):
        self.items.append(f'\t(wire\n\t\t(pts\n\t\t\t(xy {a[0]} {a[1]}) (xy {b[0]} {b[1]})\n\t\t)\n'
                          f'\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n'
                          f'\t\t(uuid "{uid("w", a, b)}")\n\t)')

    def power(self, net, pos, out):
        self.pwr_n += 1
        ref = f"#PWR{self.pwr_n:02d}"
        # VCC/PWR_FLAG graphics point +y (lib), GND points -y; rotate to face outward
        up = {(0, -1): 0, (0, 1): 180, (-1, 0): 90, (1, 0): 270}
        down = {(0, 1): 0, (0, -1): 180, (1, 0): 90, (-1, 0): 270}
        a = (down if net == "GND" else up)[out]
        vx, vy = rot(0, 3.81 if net != "GND" else -3.81, a)  # value text beyond the graphic
        self.symbol(ref, f"power:{net}", pos[0], pos[1], a, net,
                    ref_off=(0, 6.35), val_off=(snap(vx), snap(-vy)))

    def flag(self, net, pos):
        self.pwr_n += 1
        self.symbol(f"#FLG{self.pwr_n:02d}", "power:PWR_FLAG", pos[0], pos[1], 0,
                    "PWR_FLAG", ref_off=(0, -1.905), val_off=(0, -3.81))

    def label(self, net, pos, out):
        a = {(1, 0): 0, (0, -1): 90, (-1, 0): 180, (0, 1): 270}[out]
        just = "left bottom" if a in (0, 90) else "right bottom"
        self.items.append(f'\t(label "{net}"\n\t\t(at {pos[0]} {pos[1]} {a})\n\t\t(effects\n'
                          f'\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify {just})\n\t\t)\n'
                          f'\t\t(uuid "{uid("lbl", net, pos)}")\n\t)')

    def connect(self, sym, pin, net):
        pos, out = self.pin_info(sym, pin)
        end = (snap(pos[0] + out[0] * STUB), snap(pos[1] + out[1] * STUB))
        self.wire(pos, end)
        if net in ("VCC", "GND"):
            self.power(net, end, out)
        else:
            self.label(net, end, out)

    def connect_via(self, sym, pin, net, path):
        """Like connect(), but routes the stub through relative (dx, dy) steps."""
        pos, _ = self.pin_info(sym, pin)
        for dx, dy in path:
            nxt = (snap(pos[0] + dx), snap(pos[1] + dy))
            self.wire(pos, nxt)
            out = ((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))
            pos = nxt
        if net in ("VCC", "GND"):
            self.power(net, pos, out)
        else:
            self.label(net, pos, out)

    def join(self, sym_a, pin_a, sym_b, pin_b):
        self.wire(self.pin_info(sym_a, pin_a)[0], self.pin_info(sym_b, pin_b)[0])

    def text(self, s, x, y, size=1.27):
        s = s.replace('"', '\\"').replace("\n", "\\n")
        self.items.append(f'\t(text "{s}"\n\t\t(at {x} {y} 0)\n\t\t(effects\n'
                          f'\t\t\t(font\n\t\t\t\t(size {size} {size})\n\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)\n'
                          f'\t\t(uuid "{uid("txt", s)}")\n\t)')

    def render(self):
        libs = "\n".join(t for t, _ in self.libs.values())
        libs = "\n".join("\t" + ln[1:] if ln.startswith("\t") else ln for ln in libs.split("\n"))
        return (f'(kicad_sch\n\t(version 20250114)\n\t(generator "eeschema")\n\t(generator_version "9.0")\n'
                f'\t(uuid "{ROOT_UUID}")\n\t(paper "A4")\n\t(title_block\n'
                f'\t\t(title "KMUTNB ECE Souvenir - ECE blinker")\n\t\t(date "2026-10-09")\n\t\t(rev "A")\n'
                f'\t\t(company "KMUTNB ECE")\n\t\t(comment 1 "CMOS 555 astable, 14 orange LEDs sink to OUT (lit when OUT low)")\n'
                f'\t)\n\t(lib_symbols\n{libs}\n\t)\n' + "\n".join(self.items) +
                f'\n\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)\n\t(embedded_fonts no)\n)\n')


def build():
    s = Sheet()
    G = 2.54

    # --- 555 core -----------------------------------------------------------
    u1 = s.part("U1", 40 * G, 30 * G, ref_off=(-10.16, -8.89), val_off=(2.54, 10.16))
    s.connect(u1, "1", "GND")
    s.connect(u1, "8", "VCC")
    s.connect_via(u1, "4", "VCC", [(-2 * G, 0), (0, -3 * G)])  # clear of DIS label
    s.connect(u1, "7", "DIS")
    s.connect(u1, "6", "TH")
    s.connect(u1, "2", "TH")
    s.connect(u1, "5", "CV")
    s.connect(u1, "3", "OUT")

    # timing network, left of U1
    for ref, x, top, bot in (("R1", 18, "VCC", "DIS"), ("R2", 23, "DIS", "TH"), ("C1", 28, "TH", "GND")):
        sym = s.part(ref, x * G, 30 * G)
        s.connect(sym, "1", top)
        s.connect(sym, "2", bot)

    # CV filter and decoupling, right of U1
    for ref, x, top in (("C3", 52, "CV"), ("C2", 57, "VCC")):
        sym = s.part(ref, x * G, 30 * G)
        s.connect(sym, "1", top)
        s.connect(sym, "2", "GND")

    # test pads
    for ref, x, net in (("TP1", 66, "VCC"), ("TP2", 71, "GND"), ("TP3", 76, "OUT")):
        sym = s.part(ref, x * G, 29 * G, ref_off=(2.54, -3.81), val_off=(2.54, -1.27))
        s.connect(sym, "1", net)

    s.part("H1", 76 * G, 38 * G, ref_off=(2.54, -1.27), val_off=(2.54, 1.27))

    # power flags so ERC sees VCC/GND driven (power enters via test pads)
    for net, x in (("VCC", 84), ("GND", 92)):
        p0, p1 = (x * G, 29 * G), ((x + 3) * G, 29 * G)
        s.power(net, p0, (0, -1) if net == "VCC" else (0, 1))
        s.wire(p0, p1)
        s.flag(net, p1)

    # --- LED driver: PNP high-side switch, on while OUT is LOW ----------------
    # Q1 rotated 180 deg: emitter up to VCC, collector down to the LEDs, base on the right
    q1 = s.part("Q1", 20 * G, 44 * G, angle=180, ref_off=(-11.43, -1.27), val_off=(-11.43, 1.27))
    r6 = s.part("R6", 26 * G, 44 * G, angle=90, ref_off=(-1.27, -2.54), val_off=(-1.27, 3.81))
    s.connect(r6, "2", "OUT")
    s.join(r6, "1", q1, "1")         # base resistor -> B
    s.connect(q1, "2", "VCC")        # E
    s.connect(q1, "3", "LED_PWR")    # C

    # --- one current-limit resistor per digit, LEDs in parallel to GND --------
    x = 30
    for digit, (rref, leds) in DIGITS.items():
        r = s.part(rref, (x + 2 * len(leds)) * G, 48 * G)
        s.connect(r, "1", "LED_PWR")
        s.connect(r, "2", f"A_{digit}")
        for k in leds:
            d = s.part(f"D{k}", x * G, 58 * G, angle=90, ref_off=(-4.445, 0.635), val_off=(-4.445, 2.54),
                       hide_val=True)
            s.connect(d, "2", f"A_{digit}")   # anode
            s.connect(d, "1", "GND")          # cathode
            x += 5
        x += 4

    s.text("Astable 555. Q1 (PNP) turns on while OUT is LOW (discharge phase).\n"
           "t_on  = 0.693 * R2 * C1          = 83 ms\n"
           "t_off = 0.693 * (R1 + R2) * C1   = 776 ms\n"
           "f = 1.16 Hz, LED duty 9.7 %\n"
           "I_digit = (VCC - Vce_sat - Vf) / R:  E (orange) 680R, C (white) 220R\n"
           "  orange ~0.4 mA @3.3 V ... ~0.9 mA @5 V, white ~0.7 ... 2.6 mA per LED (shared, unballasted)\n"
           "Q1 base: (VCC - Veb) / 3.3k = 0.8 ... 1.3 mA, forced beta ~9-15 at <= 20 mA",
           12 * G, 14 * G)
    s.text("D1-D14 placed on BOTTOM side spelling \"ECE\" (7-segment layout).", 30 * G, 66 * G)
    return s


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w").write(build().render())
    print("wrote", os.path.relpath(OUT))
