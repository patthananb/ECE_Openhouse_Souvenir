#!/usr/bin/env python3
"""Cost estimate for three build options at several quantities.

  1. Full assembly  - JLCPCB fab + Economic PCBA (parts bought by JLC)
  2. DIY            - JLCPCB bare PCB + parts from LCSC (MOQs respected), hand soldered
  3. Bare PCB only  - JLCPCB bare PCB, no parts

Part prices are fetched live (JLCPCB parts API for assembly, LCSC product API
for retail MOQ/ladders). Fab/assembly fees and the bare-PCB price model are
constants below: check them against the live quote at cart.jlcpcb.com.

Usage: python3 tools/cost_estimate.py [qty ...]     (default 10 100 300)
"""
import json
import math
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parts import PARTS  # noqa: E402

# --- assumptions (USD) --------------------------------------------------------
# JLCPCB Economic PCBA fee schedule (jlcpcb.com/help/article/pcb-assembly-price, late 2025)
PCBA_SETUP, PCBA_STENCIL, PCBA_PER_JOINT, EXT_PART_FEE = 8.00, 1.50, 0.0017, 3.00
# Bare 30x30 mm 2-layer FR4 1.6 mm, white mask, lead-free HASL: (low, high) per order.
# 5 pcs = $4.00 on the live quote (2026-10-12, green/HASL default); larger qty modelled.
PCB_FAB = {10: (5, 9), 50: (8, 14), 100: (11, 20), 300: (22, 40), 500: (32, 55)}
SHIP_JLC = (12, 32)    # JLCPCB -> Thailand: Global Standard Direct ... DHL Express DDP ($31.44 seen)
SHIP_LCSC = (8, 25)    # LCSC -> Thailand, separate parcel
ATTRITION = lambda n, small: math.ceil(n * 0.05) + 3 if small else 0  # noqa: E731  JLC loss allowance


def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def jlc_prices(code):
    d = post("https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList",
             {"keyword": code, "currentPage": 1, "pageSize": 5, "searchSource": "search"})
    for c in (d.get("data") or {}).get("componentPageInfo", {}).get("list") or []:
        if c["componentCode"] == code:
            tiers = sorted((p["startNumber"], float(p["productPrice"])) for p in c["componentPrices"])
            return c["componentLibraryType"], tiers
    raise KeyError(code)


def lcsc_prices(code):
    r = get(f"https://wmsc.lcsc.com/ftps/wm/product/detail?productCode={code}")["result"]
    tiers = sorted((p["ladder"], float(p["usdPrice"])) for p in r["productPriceList"])
    return r["minBuyNumber"], tiers


def tier_price(tiers, n):
    p = tiers[0][1]
    for start, price in tiers:
        if n >= start:
            p = price
    return p


def bom():
    lines = {}
    for ref, (_lib, value, fp, lcsc, mpn, _lt, _d) in PARTS.items():
        if lcsc:
            lines.setdefault(lcsc, {"mpn": mpn, "value": value, "fp": fp, "refs": []})["refs"].append(ref)
    return lines


def joints(lines):
    pads = {"SOIC-8": 8, "SOT-23": 3}
    total = 0
    for ln in lines.values():
        n = next((v for k, v in pads.items() if k in ln["fp"]), 2)
        total += n * len(ln["refs"])
    return total


def main():
    qtys = [int(a) for a in sys.argv[1:]] or [10, 100, 300]
    lines = bom()
    for code, ln in lines.items():
        ln["jlc_type"], ln["jlc"] = jlc_prices(code)
        ln["moq"], ln["lcsc"] = lcsc_prices(code)
    ext = [c for c, ln in lines.items() if ln["jlc_type"] == "expand"]
    nj = joints(lines)
    print(f"BOM: {len(lines)} lines, {sum(len(l['refs']) for l in lines.values())} parts, "
          f"{nj} solder joints/board, {len(ext)} JLC extended parts {ext}")
    print(f"{'line':10s} {'MPN':20s} {'qty':>3s} {'JLC $/pc':>9s} {'LCSC MOQ':>8s} {'LCSC $/pc':>9s}")
    for code, ln in lines.items():
        print(f"{code:10s} {ln['mpn'][:20]:20s} {len(ln['refs']):3d} {ln['jlc'][0][1]:9.4f} "
              f"{ln['moq']:8d} {ln['lcsc'][0][1]:9.4f}")
    rows = []
    for n in qtys:
        fab = PCB_FAB.get(n) or min(PCB_FAB.items(), key=lambda kv: abs(kv[0] - n))[1]
        parts_jlc = 0.0
        parts_lcsc = 0.0
        for code, ln in lines.items():
            need = n * len(ln["refs"])
            small = "SOIC" not in ln["fp"] and "SOT" not in ln["fp"]
            buy = need + ATTRITION(need, small)
            parts_jlc += buy * tier_price(ln["jlc"], buy)
            spare = math.ceil(need * 0.1) + 2       # DIY: 10 % + 2 spares for dropped 0603s
            q = max(need + spare, ln["moq"])
            q = math.ceil(q / ln["moq"]) * ln["moq"]
            parts_lcsc += q * tier_price(ln["lcsc"], q)
        pcba = PCBA_SETUP + PCBA_STENCIL + nj * n * PCBA_PER_JOINT + EXT_PART_FEE * len(ext)
        v1 = [fab[i] + pcba + parts_jlc + SHIP_JLC[i] for i in (0, 1)]
        v2 = [fab[i] + parts_lcsc + SHIP_JLC[i] + SHIP_LCSC[i] for i in (0, 1)]
        v3 = [fab[i] + SHIP_JLC[i] for i in (0, 1)]
        rows.append((n, fab, pcba, parts_jlc, parts_lcsc, v1, v2, v3))
    print("\nqty | PCB fab | PCBA fees | parts@JLC | parts@LCSC | 1 full assembly | 2 DIY | 3 bare PCB  (USD, incl. shipping)")
    for n, fab, pcba, pj, pl, v1, v2, v3 in rows:
        f = lambda v: f"{v[0]:.0f}-{v[1]:.0f} ({v[0] / n:.2f}-{v[1] / n:.2f}/pc)"  # noqa: E731
        print(f"{n:4d} | {fab[0]}-{fab[1]} | {pcba:.2f} | {pj:.2f} | {pl:.2f} | {f(v1)} | {f(v2)} | {f(v3)}")


if __name__ == "__main__":
    main()
