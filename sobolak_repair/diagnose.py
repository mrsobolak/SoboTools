"""Turn raw scan data into a diagnosis and a repair plan. No I/O in here."""

import re
from dataclasses import dataclass, field

# Firmware images (see firmware/build_firmware.py) grouped by board family.
CREALITY_STM32 = ["creality_v422", "creality_v427", "creality_v422_bltouch"]
CREALITY_AVR = ["creality_v1"]
BTT = ["skr_mini_e3_v2", "skr_mini_e3_v3", "skr_mini_e3_v1_2"]
ALL_TARGETS = CREALITY_STM32 + BTT + CREALITY_AVR

# How each family takes new firmware.
FLASH_METHOD = {
    "creality_stm32": "sd_unique",  # any new .bin name on the SD card
    "btt": "sd_firmware_bin",       # must be named firmware.bin
    "creality_avr": "usb_avrdude",  # over USB, needs a bootloader
}


@dataclass
class Diagnosis:
    verdict: str
    title: str
    severity: str                   # ok | info | warn | error
    summary: str
    findings: list = field(default_factory=list)   # (severity, text)
    board_family: str = "unknown"   # creality_stm32 | creality_avr | btt | klipper | unknown
    board_text: str = "Unknown"
    candidates: list = field(default_factory=list)
    recommended: str = None
    flash_helps: bool = False
    has_probe: bool = False
    firmware: dict = field(default_factory=dict)


def parse_m115(lines):
    info = {}
    for line in lines:
        if "FIRMWARE_NAME" not in line:
            continue
        for key in ("FIRMWARE_NAME", "SOURCE_CODE_URL", "PROTOCOL_VERSION",
                    "MACHINE_TYPE", "EXTRUDER_COUNT", "UUID"):
            m = re.search(key + r":(.*?)(?=\s[A-Z_]{4,}:|$)", line)
            if m:
                info[key] = m.group(1).strip()
    return info


def parse_tmc_tests(lines):
    """Marlin prints 'Testing X connection... OK' (or 'Error: All LOW' / 'Error: All HIGH')
    at startup and at the end of M122. On UART drivers 'All LOW' means no reply at all.
    Returns {axis: status}."""
    results = {}
    for line in lines:
        m = re.search(r"Testing\s+(\S+)\s+connection\.*\s*(.*)", line)
        if m:
            status = re.sub(r"^Error:\s*", "", m.group(2).strip()) or "?"
            results[m.group(1)] = status
    return results


def identify_board(data, has_probe):
    """Best guess at the mainboard from USB chip, boot behaviour and firmware name."""
    fam = data.get("usb_family", "unknown")
    reset_on_open = any(l == "start" or l.startswith("echo:Marlin") for l in data.get("boot", []))
    names = " ".join(data.get("m115", []))
    if fam == "stm32_native":
        return ("btt", "BigTreeTech SKR Mini E3 (version printed on the board)", BTT, None)
    if fam == "klipper":
        return ("klipper", "Board running Klipper (native USB)", ALL_TARGETS, None)
    if fam in ("ch340", "ftdi"):
        if reset_on_open:
            return ("creality_avr", "Creality 1.1.x (8-bit ATmega1284P)", CREALITY_AVR,
                    "creality_v1")
        # Marlin example builds put the board in MACHINE_TYPE, e.g. "Ender-5 Pro 4.2.2".
        if "4.2.7" in names:
            return ("creality_stm32", "Creality 4.2.7 (named in current firmware)",
                    CREALITY_STM32, "creality_v427")
        rec = "creality_v422_bltouch" if has_probe else "creality_v422"
        text = ("Creality 4.2.2 (named in current firmware)" if "4.2.2" in names
                else "Creality 4.2.x (32-bit) - 4.2.2 or 4.2.7, check the board label")
        return ("creality_stm32", text, CREALITY_STM32, rec)
    return ("unknown", "Unknown board", ALL_TARGETS, None)


def diagnose(data):
    if not data.get("connected"):
        if data.get("saw_binary"):
            fam, text, cands, rec = identify_board(data, False)
            return Diagnosis(
                "KLIPPER", "Printer is running Klipper", "warn",
                "The board answers in Klipper's binary language instead of G-code. Klipper "
                "needs a Raspberry Pi to work. Flashing Marlin makes the printer work on its own.",
                [("warn", "Binary data received at every baud rate.")],
                fam if fam != "unknown" else "klipper", text, cands, rec, flash_helps=True)
        return Diagnosis(
            "NO_RESPONSE", "Printer did not answer", "error",
            "Nothing answered on this port. Check that it is the right port, that no other "
            "program (Cura, Pronterface, OctoPrint) is using it, and that the printer is on.",
            [("error", "No reply at 115200 or 250000 baud.")])

    fw = parse_m115(data["m115"])
    every = data["boot"] + data["m122"] + data.get("reboot", [])
    m503 = data["m503"]
    has_probe = any(re.match(r"^(echo:)?\s*M851\b", l) for l in m503)
    uart_settings = any(re.match(r"^(echo:)?\s*M906\b", l) for l in m503)
    boot_error = any("TMC CONNECTION ERROR" in l.upper() for l in every)
    m122_unknown = any("Unknown command" in l and "M122" in l for l in data["m122"])
    tests = parse_tmc_tests(every)
    bad = {a: s for a, s in tests.items() if s.upper() != "OK"}
    fam, board_text, cands, rec = identify_board(data, has_probe)

    findings = [("info", f"Firmware: {fw.get('FIRMWARE_NAME', 'unknown')}")]
    if "MACHINE_TYPE" in fw:
        findings.append(("info", f"Machine name in firmware: {fw['MACHINE_TYPE']}"))
    findings.append(("info", f"USB chip: {data.get('usb_desc', '?')}"))
    findings.append(("info", f"Board (best guess): {board_text}"))
    if has_probe:
        findings.append(("info", "Firmware is set up for a bed probe (BLTouch / CR Touch)."))
    if uart_settings:
        findings.append(("info", "Firmware stores driver current settings (M906), so it is "
                                 "built to talk to the drivers over UART."))
    if boot_error:
        findings.append(("error", "Firmware reported TMC CONNECTION ERROR."))
    for axis, status in tests.items():
        findings.append(("ok" if status.upper() == "OK" else "error", f"Driver {axis}: {status}"))

    common = dict(findings=findings, board_family=fam, board_text=board_text,
                  candidates=cands, recommended=rec, has_probe=has_probe, firmware=fw)

    if m122_unknown and not boot_error:
        return Diagnosis(
            "HEALTHY", "No driver problem found", "ok",
            "This firmware runs the drivers in standalone mode, which is correct for a stock "
            "Creality board. It cannot produce a TMC connection error.", **common)

    if not tests:
        return Diagnosis(
            "UNKNOWN", "Could not read driver status", "warn",
            "The printer answered, but did not report driver tests. Save the report and "
            "send it in so the raw output can be checked by hand.", **common)

    if not bad:
        return Diagnosis(
            "DRIVERS_OK_NOW", "Drivers answer right now", "info",
            "All drivers answered. If the error appears at power-on, the board probably "
            "starts before the 24 V power is ready, or it was powered by USB alone. Turn "
            "the printer on before plugging in USB.", **common)

    if len(bad) < len(tests):
        return Diagnosis(
            "SOME_DRIVERS_FAIL", "Some drivers are not answering", "error",
            f"Only {', '.join(bad)} fail. That points at hardware: a damaged driver chip, "
            "a loose jumper or a bad solder joint. New firmware is unlikely to fix it; the "
            "board probably needs replacing.", **common)

    if fam == "creality_stm32" or fam == "creality_avr":
        return Diagnosis(
            "FIRMWARE_MISMATCH", "Wrong firmware for this board", "error",
            "Every driver fails, on a stock Creality board. Those boards run the drivers in "
            "standalone mode with no data wire, so firmware that tries to talk to them always "
            "fails. Installing the correct firmware fixes this.", flash_helps=True, **common)

    return Diagnosis(
        "ALL_DRIVERS_FAIL", "No driver is answering", "error",
        "Every driver fails. Either the 24 V power is off (check the power switch and cord), "
        "or the firmware was built for a different board revision. If power is fine, "
        "installing firmware for the exact board version fixes this.", flash_helps=True,
        **common)


def verify(before, after):
    """After a flash: did the problem go away? Returns (success, message)."""
    if after.verdict in ("HEALTHY", "DRIVERS_OK_NOW"):
        return True, "The driver error is gone. The printer is repaired."
    if after.verdict == "NO_RESPONSE":
        return False, ("The printer no longer answers. The firmware may be for the wrong "
                       "board, or the port changed. Try scanning again.")
    if after.firmware.get("FIRMWARE_NAME") == before.firmware.get("FIRMWARE_NAME"):
        return False, ("The firmware did not change, so the printer did not take the update. "
                       "Check the SD card steps (FAT32 card, file in the top folder, power "
                       "fully off before inserting).")
    return False, f"New firmware is running, but: {after.title.lower()}."
