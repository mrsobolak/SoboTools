"""Run with:  python -m pytest tests"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sobolak_repair.diagnose import diagnose, parse_m115, parse_tmc_tests, verify  # noqa: E402

M115 = ["FIRMWARE_NAME:Marlin 2.0.8.2 (Jul  6 2021 12:00:00) SOURCE_CODE_URL:github.com/"
        "MarlinFirmware/Marlin PROTOCOL_VERSION:1.0 MACHINE_TYPE:Ender-5 Pro EXTRUDER_COUNT:1 "
        "UUID:cede2a2f-41a2-4748-9b12-c55c62f367ff", "ok"]
UART_M503 = ["echo:; Stepper driver current:", "echo:  M906 X580 Y580 Z580", "ok"]


def scan(**kw):
    d = dict(connected=True, saw_binary=False, usb_family="ch340", usb_desc="CH340",
             boot=[], m115=M115, m122=[], m503=[], reboot=[])
    d.update(kw)
    return d


def m122(statuses):
    lines = ["\t\tX\tY\tZ\tE", "Enabled\t\tfalse\tfalse\tfalse\tfalse"]
    return lines + [f"Testing {a} connection... {s}" for a, s in statuses.items()] + ["ok"]


ALL_LOW = m122({a: "Error: All LOW" for a in "XYZE"})


def test_parse_m115():
    fw = parse_m115(M115)
    assert fw["FIRMWARE_NAME"].startswith("Marlin 2.0.8.2")
    assert fw["MACHINE_TYPE"] == "Ender-5 Pro"


def test_parse_tests():
    assert parse_tmc_tests(m122({"X": "Error: All HIGH", "Y": "OK"})) == {"X": "All HIGH", "Y": "OK"}


def test_stock_creality_all_fail_is_firmware_mismatch():
    d = diagnose(scan(m122=ALL_LOW, m503=UART_M503))
    assert d.verdict == "FIRMWARE_MISMATCH"
    assert d.flash_helps
    assert d.board_family == "creality_stm32"
    assert d.recommended == "creality_v422"


def test_board_named_in_firmware_wins():
    named = [M115[0].replace("MACHINE_TYPE:Ender-5 Pro", "MACHINE_TYPE:Ender-5 Pro 4.2.7"), "ok"]
    assert diagnose(scan(m115=named, m122=ALL_LOW)).recommended == "creality_v427"


def test_probe_in_settings_picks_bltouch_build():
    d = diagnose(scan(m122=ALL_LOW, m503=["echo:  M851 X-40.00 Y-13.00 Z-1.45", "ok"]))
    assert d.has_probe and d.recommended == "creality_v422_bltouch"


def test_dtr_reset_means_8bit_board():
    d = diagnose(scan(boot=["start", "echo:Marlin 2.0.1"], m122=ALL_LOW))
    assert d.board_family == "creality_avr" and d.recommended == "creality_v1"


def test_skr_board_all_fail_needs_power_check_and_board_choice():
    d = diagnose(scan(usb_family="stm32_native", m122=ALL_LOW))
    assert d.verdict == "ALL_DRIVERS_FAIL"
    assert d.board_family == "btt" and d.recommended is None
    assert "skr_mini_e3_v3" in d.candidates


def test_some_fail_is_hardware():
    d = diagnose(scan(m122=m122({"X": "OK", "Y": "OK", "Z": "Error: All LOW", "E": "OK"})))
    assert d.verdict == "SOME_DRIVERS_FAIL" and not d.flash_helps


def test_all_ok():
    assert diagnose(scan(m122=m122({a: "OK" for a in "XYZE"}))).verdict == "DRIVERS_OK_NOW"


def test_standalone_firmware_is_healthy():
    d = diagnose(scan(m122=['echo:Unknown command: "M122"', "ok"]))
    assert d.verdict == "HEALTHY" and d.severity == "ok"


def test_no_response_and_klipper():
    assert diagnose(dict(connected=False, saw_binary=False)).verdict == "NO_RESPONSE"
    k = diagnose(dict(connected=False, saw_binary=True, usb_family="ch340"))
    assert k.verdict == "KLIPPER" and k.flash_helps


def test_verify_after_flash():
    before = diagnose(scan(m122=ALL_LOW))
    new_fw = [M115[0].replace("2.0.8.2", "2.1.2.9"), "ok"]
    ok, _ = verify(before, diagnose(scan(m115=new_fw, m122=['echo:Unknown command: "M122"'])))
    assert ok
    ok, msg = verify(before, diagnose(scan(m122=ALL_LOW)))
    assert not ok and "did not change" in msg
