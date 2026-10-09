"""Single source of truth for the ECE souvenir BOM.

Every generator (schematic, PCB, BOM) imports from here so part choices
change in one place. LCSC codes verified against the JLCPCB parts API on
2026-10-09; "lib" is the JLCPCB library type at that date.
"""

FP_R0402 = "Resistor_SMD:R_0402_1005Metric"
FP_C0402 = "Capacitor_SMD:C_0402_1005Metric"
FP_C0603 = "Capacitor_SMD:C_0603_1608Metric"
FP_LED0402 = "LED_SMD:LED_0402_1005Metric"
FP_SOIC8 = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"

# ref: (lib_id, value, footprint, LCSC, MPN, lib type, description)
PARTS = {
    "U1": ("Timer:TLC555xD", "TLC555CDR", FP_SOIC8, "C6986", "TLC555CDR", "extended",
           "TI LinCMOS 555 timer, 2-15 V, SOIC-8"),
    "R1": ("Device:R", "1M", FP_R0402, "C26083", "0402WGF1004TCE", "basic",
           "1 MOhm 1% 0402, timing VCC->DIS"),
    "R2": ("Device:R", "120k", FP_R0402, "C25750", "0402WGF1203TCE", "preferred",
           "120 kOhm 1% 0402, timing DIS->TH"),
    "C1": ("Device:C", "1u", FP_C0603, "C106248", "CC0603KRX7R7BB105", "extended",
           "1 uF 16 V X7R 0603, timing"),
    "C2": ("Device:C", "100n", FP_C0402, "C1525", "CL05B104KO5NNNC", "basic",
           "100 nF 16 V X7R 0402, U1 decoupling"),
    "C3": ("Device:C", "10n", FP_C0402, "C15195", "CL05B103KB5NNNC", "basic",
           "10 nF 50 V X7R 0402, CV filter"),
    "TP1": ("Connector:TestPoint", "VCC", "TestPoint:TestPoint_Pad_D2.0mm", "", "", "none",
            "Supply input pad (+)"),
    "TP2": ("Connector:TestPoint", "GND", "TestPoint:TestPoint_Pad_D2.0mm", "", "", "none",
            "Ground input pad (-)"),
    "TP3": ("Connector:TestPoint", "OUT", "TestPoint:TestPoint_Pad_D1.5mm", "", "", "none",
            "555 OUT / LED_SINK probe pad"),
}

LED = ("Device:LED", "Orange", FP_LED0402, "C965791", "XL-1005UOC", "extended",
       "Orange 605 nm 0402 LED (XINGLIGHT)")
RLED = ("Device:R", "3.3k", FP_R0402, "C25890", "0402WGF3301TCE", "basic",
        "3.3 kOhm 1% 0402, LED current limit")

for k in range(1, 15):
    PARTS[f"D{k}"] = LED
    PARTS[f"R{k + 2}"] = RLED
