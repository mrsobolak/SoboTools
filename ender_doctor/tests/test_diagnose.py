"""Run with:  py -m pytest tests   (or just: py tests/test_diagnose.py)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scanner import diagnose, parse_m115, parse_tmc_tests  # noqa: E402

CH340 = "CH340 USB chip (stock Creality board: 1.1.x or 4.2.x)"
M115 = ["FIRMWARE_NAME:Marlin 2.0.8.2 (Jul  6 2021 12:00:00) SOURCE_CODE_URL:github.com/MarlinFirmware/Marlin "
        "PROTOCOL_VERSION:1.0 MACHINE_TYPE:Ender-5 Pro EXTRUDER_COUNT:1 UUID:cede2a2f-41a2-4748-9b12-c55c62f367ff",
        "ok"]


def base(**kw):
    d = dict(connected=True, saw_binary=False, usb_desc=CH340, boot=[], m115=M115,
             m122=[], m503=[], fw=parse_m115(M115))
    d.update(kw)
    return d


def m122(status_by_axis):
    lines = ["\t\tX\tY\tZ\tE", "Enabled\t\tfalse\tfalse\tfalse\tfalse"]
    lines += [f"Testing {a} connection... {s}" for a, s in status_by_axis.items()]
    return lines + ["ok"]


def test_parse_m115():
    fw = parse_m115(M115)
    assert fw["FIRMWARE_NAME"].startswith("Marlin 2.0.8.2")
    assert fw["MACHINE_TYPE"] == "Ender-5 Pro"


def test_parse_tests():
    t = parse_tmc_tests(m122({"X": "Error: All HIGH", "Y": "OK"}))
    assert t == {"X": "All HIGH", "Y": "OK"}


def test_all_fail_stock_board_is_firmware_mismatch():
    d = base(m122=m122({a: "Error: All HIGH" for a in "XYZE"}),
             m503=["echo:; Stepper driver current:", "echo:  M906 X580 Y580 Z580", "ok"])
    verdict, _ = diagnose(d)
    assert verdict == "FIRMWARE_MISMATCH_LIKELY"


def test_all_fail_other_board():
    d = base(usb_desc="STM32 native USB", m122=m122({a: "Error: All HIGH" for a in "XYZE"}))
    assert diagnose(d)[0] == "ALL_DRIVERS_FAIL"


def test_some_fail():
    d = base(m122=m122({"X": "OK", "Y": "OK", "Z": "Error: All LOW", "E": "OK"}))
    assert diagnose(d)[0] == "SOME_DRIVERS_FAIL"


def test_all_ok():
    assert diagnose(base(m122=m122({a: "OK" for a in "XYZE"})))[0] == "DRIVERS_OK_NOW"


def test_standalone_firmware():
    d = base(m122=['echo:Unknown command: "M122"', "ok"])
    assert diagnose(d)[0] == "DRIVERS_STANDALONE"


def test_no_response_and_klipper():
    assert diagnose(dict(connected=False, saw_binary=False))[0] == "NO_RESPONSE"
    assert diagnose(dict(connected=False, saw_binary=True))[0] == "KLIPPER_OR_WRONG_BAUD"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
