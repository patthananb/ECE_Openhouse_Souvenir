#!/usr/bin/env python3
"""Export the schematic netlist with kicad-cli and diff it against the spec.

Usage: python3 tools/check_netlist.py   (exit 0 = netlist matches spec)
"""
import os
import re
import subprocess
import sys
import tempfile

KICAD_CLI = os.environ.get("KICAD_CLI", "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")
SCH = os.path.join(os.path.dirname(__file__), "..", "hardware", "ece_souvenir.kicad_sch")

EXPECTED = {
    "VCC": {"U1.8", "U1.4", "R1.1", "C2.1", "TP1.1", "Q1.2"},
    "GND": {"U1.1", "C1.2", "C3.2", "C2.2", "TP2.1"} | {f"D{k}.1" for k in range(1, 15)},
    "DIS": {"U1.7", "R1.2", "R2.1"},
    "TH": {"U1.6", "U1.2", "R2.2", "C1.1"},
    "CV": {"U1.5", "C3.1"},
    "OUT": {"U1.3", "TP3.1", "R6.2"},
    "LED_PWR": {"Q1.3", "R3.1", "R4.1", "R5.1"},
    "A_E1": {"R3.2"} | {f"D{k}.2" for k in range(1, 6)},
    "A_C": {"R4.2"} | {f"D{k}.2" for k in range(6, 10)},
    "A_E2": {"R5.2"} | {f"D{k}.2" for k in range(10, 15)},
}
# plus the unnamed base net: R6 pin 1 -> Q1 base
BRANCHES = {frozenset({"R6.1", "Q1.1"})}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "net.net")
        subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr",
                        "-o", out, SCH], check=True, capture_output=True)
        text = open(out).read()
    nets = {}
    for block in re.split(r"\(net\s+\(code", text)[1:]:
        name = re.search(r'\(name "([^"]*)"\)', block).group(1).lstrip("/")
        nets[name] = {f"{r}.{p}" for r, p in re.findall(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)', block)}

    ok = True
    for name, pins in EXPECTED.items():
        got = nets.pop(name, set())
        if got != pins:
            ok = False
            print(f"MISMATCH {name}: missing {sorted(pins - got)} extra {sorted(got - pins)}")
    rest = {frozenset(p) for p in nets.values()}
    if rest != BRANCHES:
        ok = False
        print("BRANCH nets differ:", sorted(map(sorted, rest ^ BRANCHES)))
    print(f"{len(EXPECTED)} named nets + {len(BRANCHES)} unnamed net: {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
