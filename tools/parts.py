"""Single source of truth for the ECE souvenir BOM.

Every generator (schematic, PCB, BOM) imports from here so part choices
change in one place. LCSC codes verified against the JLCPCB parts API on
2026-10-09; "lib" is the JLCPCB library type at that date.

Board is HAND-SOLDERED: nothing smaller than 0603, KiCad *_HandSolder
footprints (longer pads). JLC basic/extended no longer drives choices.
"""

FP_R0603 = "Resistor_SMD:R_0603_1608Metric_Pad0.98x0.95mm_HandSolder"
FP_C0603 = "Capacitor_SMD:C_0603_1608Metric_Pad1.08x0.95mm_HandSolder"
FP_LED0603 = "LED_SMD:LED_0603_1608Metric_Pad1.05x0.95mm_HandSolder"
FP_SOIC8 = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"

# ref: (lib_id, value, footprint, LCSC, MPN, lib type, description)
PARTS = {
    "U1": ("Timer:TLC555xD", "TLC555CDR", FP_SOIC8, "C6986", "TLC555CDR", "extended",
           "TI LinCMOS 555 timer, 2-15 V, SOIC-8"),
    "R1": ("Device:R", "1M", FP_R0603, "C22935", "0603WAF1004T5E", "basic",
           "1 MOhm 1% 0603, timing VCC->DIS"),
    "R2": ("Device:R", "120k", FP_R0603, "C25808", "0603WAF1203T5E", "basic",
           "120 kOhm 1% 0603, timing DIS->TH"),
    "C1": ("Device:C", "1u", FP_C0603, "C106248", "CC0603KRX7R7BB105", "extended",
           "1 uF 16 V X7R 0603, timing"),
    "C2": ("Device:C", "100n", FP_C0603, "C14663", "CC0603KRX7R9BB104", "basic",
           "100 nF 50 V X7R 0603, U1 decoupling"),
    "C3": ("Device:C", "10n", FP_C0603, "C57112", "0603B103K500NT", "basic",
           "10 nF 50 V X7R 0603, CV filter"),
    "TP1": ("Connector:TestPoint", "VCC", "TestPoint:TestPoint_Pad_D2.0mm", "", "", "none",
            "Supply input pad (+)"),
    "TP2": ("Connector:TestPoint", "GND", "TestPoint:TestPoint_Pad_D2.0mm", "", "", "none",
            "Ground input pad (-)"),
    "TP3": ("Connector:TestPoint", "OUT", "TestPoint:TestPoint_Pad_D1.5mm", "", "", "none",
            "555 OUT / LED_SINK probe pad"),
    "H1": ("Mechanical:MountingHole", "Keychain", "MountingHole:MountingHole_2.5mm", "", "", "none",
           "2.5 mm NPTH keychain hole"),
}

LED = ("Device:LED", "Orange", FP_LED0603, "C965800", "XL-1608UOC-06", "extended",
       "Orange 605 nm 0603 LED (XINGLIGHT)")
RLED = ("Device:R", "3.3k", FP_R0603, "C22978", "0603WAF3301T5E", "basic",
        "3.3 kOhm 1% 0603, LED current limit")

for k in range(1, 15):
    PARTS[f"D{k}"] = LED
    PARTS[f"R{k + 2}"] = RLED
