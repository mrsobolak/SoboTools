"""
Tim Cheese Scanner - Ender 5 Pro diagnostic tool.

Plug a printer into this computer over USB, run this script, and it will:
  1. find the printer's COM port
  2. figure out the baud rate and what firmware it is running
  3. ask the stepper drivers how they are doing (M122)
  4. dump the saved settings (M503)
  5. write everything to a report file and print a plain-English diagnosis

It only sends read-only commands, except the optional reboot (--reboot),
which restarts the printer so we can capture its startup messages.
"""

import argparse
import datetime
import os
import re
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("pyserial is not installed. Run:  py -m pip install pyserial")
    sys.exit(1)


BAUD_RATES = [115200, 250000]

# Known USB IDs (VID, PID) -> what that usually means on an Ender.
KNOWN_USB = {
    (0x1A86, 0x7523): "CH340 USB chip (stock Creality board: 1.1.x or 4.2.x)",
    (0x0483, 0x5740): "STM32 native USB (likely an upgraded board, e.g. BTT SKR Mini E3)",
    (0x1D50, 0x614E): "Klipper native USB",
    (0x0403, 0x6001): "FTDI USB chip (older or third-party board)",
}

REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")


# --------------------------------------------------------------------------
# Serial helpers
# --------------------------------------------------------------------------

def describe_port(p):
    known = KNOWN_USB.get((p.vid, p.pid)) if p.vid is not None else None
    return known or (p.description or "unknown device")


def find_ports():
    ports = list(list_ports.comports())
    # Put likely printers first.
    ports.sort(key=lambda p: (0 if (p.vid, p.pid) in KNOWN_USB else 1, p.device))
    return ports


def read_for(ser, seconds, quiet=None):
    """Read lines for up to `seconds`. If `quiet` is set, stop early once
    nothing has arrived for that many seconds. Returns (lines, raw_bytes)."""
    lines, raw = [], b""
    end = time.time() + seconds
    last = time.time()
    buf = b""
    while time.time() < end:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            raw += chunk
            buf += chunk
            last = time.time()
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                lines.append(line.decode("utf-8", "replace").strip())
        elif quiet is not None and time.time() - last > quiet:
            break
    if buf.strip():
        lines.append(buf.decode("utf-8", "replace").strip())
    return lines, raw


def send(ser, cmd, timeout=8.0):
    """Send a G-code command and collect its reply up to the final 'ok'."""
    ser.reset_input_buffer()
    ser.write((cmd + "\n").encode("ascii"))
    ser.flush()
    lines = []
    end = time.time() + timeout
    buf = b""
    while time.time() < end:
        chunk = ser.read(ser.in_waiting or 1)
        if not chunk:
            continue
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            text = line.decode("utf-8", "replace").strip()
            if not text:
                continue
            lines.append(text)
            if text.startswith("ok"):
                return lines
            if "busy" in text:
                end = time.time() + timeout  # printer is alive, keep waiting
    return lines


def looks_binary(raw):
    if len(raw) < 8:
        return False
    printable = sum(1 for b in raw if 32 <= b < 127 or b in (9, 10, 13))
    return printable / len(raw) < 0.7


def connect(port, log):
    """Try each baud rate until the printer answers M115.
    Returns (serial, baud, boot_lines, m115_lines, saw_binary)."""
    saw_binary = False
    for baud in BAUD_RATES:
        log(f"  trying {baud} baud...")
        try:
            ser = serial.Serial(port, baud, timeout=0.2)
        except serial.SerialException as e:
            log(f"  could not open {port}: {e}")
            return None, None, [], [], False
        # Opening the port resets older (8-bit) boards; give them time to boot
        # and capture whatever they print while starting up.
        boot, raw = read_for(ser, 6.0, quiet=2.5)
        if looks_binary(raw):
            saw_binary = True
        m115 = send(ser, "M115", timeout=4.0)
        if any("FIRMWARE_NAME" in l or l.startswith("ok") for l in m115):
            return ser, baud, boot, m115, saw_binary
        _, raw = read_for(ser, 0.5)
        if looks_binary(raw):
            saw_binary = True
        ser.close()
    return None, None, [], [], saw_binary


# --------------------------------------------------------------------------
# Diagnosis
# --------------------------------------------------------------------------

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
    """Parse Marlin's 'Testing X connection... OK / Error: ...' lines.
    Returns {axis: 'OK' | 'All HIGH' | 'All LOW' | 'Bad response' | other}."""
    results = {}
    for line in lines:
        m = re.search(r"Testing\s+(\S+)\s+connection\.*\s*(.*)", line)
        if m:
            status = m.group(2).strip()
            status = re.sub(r"^Error:\s*", "", status) or "?"
            results[m.group(1)] = status
    return results


def diagnose(data):
    """Turn raw scan data into a list of (severity, message) findings and
    a one-line verdict. Kept free of serial I/O so it can be tested."""
    findings = []
    usb = data.get("usb_desc", "")
    if not data.get("connected"):
        if data.get("saw_binary"):
            verdict = "KLIPPER_OR_WRONG_BAUD"
            findings.append(("!", "The board sends binary data instead of text. It is most "
                                  "likely running Klipper firmware, which needs a Raspberry "
                                  "Pi/host to work. Reflashing Marlin would make it standalone."))
        else:
            verdict = "NO_RESPONSE"
            findings.append(("!", "The printer did not answer at any baud rate. Possible causes: "
                                  "board has no working firmware, wrong COM port, or another "
                                  "program (Cura, Pronterface, OctoPrint) is using the port."))
        return verdict, findings

    all_text = data["boot"] + data["m115"] + data["m122"] + data["m503"] + data.get("reboot", [])
    fw = data["fw"]
    findings.append(("i", f"Firmware: {fw.get('FIRMWARE_NAME', 'unknown')}"))
    if "MACHINE_TYPE" in fw:
        findings.append(("i", f"Machine type reported by firmware: {fw['MACHINE_TYPE']}"))
    findings.append(("i", f"USB chip: {usb}"))

    boot_error = any("TMC CONNECTION ERROR" in l.upper() for l in all_text)
    m122_unknown = any("Unknown command" in l and "M122" in l for l in data["m122"])
    uart_settings = any(re.match(r"^(echo:)?\s*M906\b", l) for l in data["m503"])
    tests = parse_tmc_tests(data["m122"] + data["boot"] + data.get("reboot", []))
    bad = {a: s for a, s in tests.items() if s.upper() != "OK"}

    if boot_error:
        findings.append(("!", "Firmware printed 'TMC CONNECTION ERROR'."))
    if uart_settings:
        findings.append(("i", "Firmware stores TMC current settings (M906), so it is built to "
                              "TALK to the drivers over UART."))

    if m122_unknown:
        verdict = "DRIVERS_STANDALONE"
        findings.append(("i", "This firmware treats the drivers as standalone (M122 not "
                              "supported). It should NOT produce a TMC connection error. If the "
                              "screen still shows one, the error is coming from somewhere else "
                              "(e.g. a different firmware on the screen itself) - send the report."))
        return verdict, findings

    if not tests:
        verdict = "UNKNOWN"
        findings.append(("?", "M122 answered but no driver connection test lines were found. "
                              "Send this report so the raw output can be checked by hand."))
        return verdict, findings

    for axis, status in tests.items():
        findings.append(("i" if status.upper() == "OK" else "!", f"Driver {axis}: {status}"))

    if not bad:
        verdict = "DRIVERS_OK_NOW"
        findings.append(("i", "All drivers answered right now. If the error shows up at power-on, "
                              "the board probably starts before the 24V motor power is ready, "
                              "or it was powered by USB alone. Try: power on with USB unplugged."))
    elif len(bad) == len(tests):
        stock_board = "CH340" in usb
        if stock_board:
            verdict = "FIRMWARE_MISMATCH_LIKELY"
            findings.append(("!", "EVERY driver fails, on what looks like a stock Creality board. "
                                  "Stock Ender 5 Pro boards wire the drivers in standalone mode, "
                                  "with no UART data line, so firmware that tries to talk to them "
                                  "always fails. Fix: flash firmware built with *_STANDALONE drivers."))
        else:
            verdict = "ALL_DRIVERS_FAIL"
            findings.append(("!", "EVERY driver fails. Either the motor power (24V) is off, or the "
                                  "firmware's driver/pin settings don't match this board."))
        findings.append(("?", "Before reflashing: make sure the printer's power switch is ON and "
                              "it is plugged into the wall, then run the scan again. Drivers with "
                              "no 24V power can't answer, which looks exactly like this."))
    else:
        verdict = "SOME_DRIVERS_FAIL"
        findings.append(("!", f"Only some drivers fail ({', '.join(bad)}). That usually means a "
                              "damaged driver chip, a loose/missing UART jumper, or a bad solder "
                              "joint on those axes - more likely hardware than firmware."))
    return verdict, findings


# --------------------------------------------------------------------------
# Main scan
# --------------------------------------------------------------------------

def scan(port_info, label, reboot=False):
    port = port_info.device
    log_lines = []

    def log(msg=""):
        print(msg)
        log_lines.append(msg)

    log(f"Scanning {port} ({describe_port(port_info)})")
    data = {
        "usb_desc": describe_port(port_info),
        "boot": [], "m115": [], "m122": [], "m503": [], "fw": {},
    }
    ser, baud, boot, m115, saw_binary = connect(port, log)
    data.update(connected=ser is not None, saw_binary=saw_binary, boot=boot, m115=m115)

    if ser:
        log(f"  connected at {baud} baud")
        data["fw"] = parse_m115(m115)
        log("  asking drivers for status (M122)...")
        data["m122"] = send(ser, "M122", timeout=10.0)
        log("  reading saved settings (M503)...")
        data["m503"] = send(ser, "M503", timeout=8.0)
        if reboot:
            log("  rebooting printer to capture startup messages (M997)...")
            ser.write(b"M997\n")
            ser.close()
            time.sleep(1.0)
            try:
                ser = serial.Serial(port, baud, timeout=0.2)
                data["reboot"], _ = read_for(ser, 15.0, quiet=4.0)
            except serial.SerialException:
                data["reboot"] = ["(port disappeared during reboot - normal on some boards)"]
        ser.close()

    verdict, findings = diagnose(data)

    log()
    log("=" * 64)
    log(f" DIAGNOSIS for {label}:  {verdict}")
    log("=" * 64)
    for sev, msg in findings:
        log(f" [{sev}] {msg}")
    log()

    os.makedirs(REPORT_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_label = re.sub(r"[^A-Za-z0-9_-]+", "_", label)
    path = os.path.join(REPORT_DIR, f"{safe_label}_{stamp}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"Tim Cheese Scanner report\nLabel: {label}\nTime: {stamp}\n")
        f.write(f"Port: {port}\nUSB: {port_info.description} "
                f"VID:PID={port_info.vid}:{port_info.pid}\nBaud: {baud}\n\n")
        f.write("\n".join(log_lines) + "\n")
        for section in ("boot", "m115", "m122", "m503", "reboot"):
            if data.get(section):
                f.write(f"\n----- {section.upper()} -----\n")
                f.write("\n".join(data[section]) + "\n")
    log(f"Report saved to: {path}")
    return verdict


def main():
    ap = argparse.ArgumentParser(description="Diagnose an Ender 5 Pro over USB.")
    ap.add_argument("--port", help="COM port to use, e.g. COM3 (default: ask)")
    ap.add_argument("--label", help="name for this printer, e.g. ender1 (default: ask)")
    ap.add_argument("--reboot", action="store_true",
                    help="also reboot the printer to capture its startup log")
    args = ap.parse_args()

    print("+------------------------------------------+")
    print("|   TIM CHEESE SCANNER  -  Ender doctor    |")
    print("+------------------------------------------+")
    print("Close Cura / Pronterface / anything else using the printer first.\n")

    ports = find_ports()
    if not ports:
        print("No COM ports found.")
        print(" - Is the USB cable plugged in? Some cables are charge-only; try another.")
        print(" - Windows may need the CH340 driver (search 'CH340 driver WCH').")
        return 1

    if args.port:
        matches = [p for p in ports if p.device.upper() == args.port.upper()]
        if not matches:
            print(f"{args.port} not found. Available: {', '.join(p.device for p in ports)}")
            return 1
        chosen = matches[0]
    elif len(ports) == 1:
        chosen = ports[0]
    else:
        print("Found these ports:")
        for i, p in enumerate(ports, 1):
            print(f"  {i}. {p.device}  -  {describe_port(p)}")
        pick = input(f"Which one is the printer? [1-{len(ports)}, Enter=1]: ").strip() or "1"
        try:
            chosen = ports[int(pick) - 1]
        except (ValueError, IndexError):
            print("Invalid choice.")
            return 1

    label = args.label or input("Name this printer (e.g. ender1) [Enter=ender]: ").strip() or "ender"
    scan(chosen, label, reboot=args.reboot)
    return 0


if __name__ == "__main__":
    sys.exit(main())
