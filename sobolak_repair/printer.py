"""Talking to a printer over USB serial: find ports, connect, run the scan."""

import os
import time

import serial
from serial.tools import list_ports

BAUD_RATES = [115200, 250000]

# (VID, PID) -> (family, description)
KNOWN_USB = {
    (0x1A86, 0x7523): ("ch340", "CH340 USB chip (stock Creality board)"),
    (0x0483, 0x5740): ("stm32_native", "STM32 native USB (BigTreeTech SKR or similar)"),
    (0x1D50, 0x614E): ("klipper", "Klipper native USB"),
    (0x0403, 0x6001): ("ftdi", "FTDI USB chip (older or third-party board)"),
}


class Port:
    """A serial port, independent of pyserial's ListPortInfo (easy to fake in tests)."""

    def __init__(self, device, description="", vid=None, pid=None):
        self.device = device
        self.description = description or device
        self.vid, self.pid = vid, pid

    @property
    def usb_family(self):
        return KNOWN_USB.get((self.vid, self.pid), ("unknown", ""))[0]

    @property
    def friendly(self):
        known = KNOWN_USB.get((self.vid, self.pid))
        return known[1] if known else self.description

    @property
    def likely_printer(self):
        return (self.vid, self.pid) in KNOWN_USB


def find_ports():
    ports = [Port(p.device, p.description, p.vid, p.pid) for p in list_ports.comports()]
    # For testing without hardware: SOBOLAK_FAKE_PORT=/dev/pts/3 adds a fake CH340 printer.
    fake = os.environ.get("SOBOLAK_FAKE_PORT")
    if fake:
        ports.insert(0, Port(fake, "USB-SERIAL CH340 (simulated)", 0x1A86, 0x7523))
    ports.sort(key=lambda p: (not p.likely_printer, p.device))
    return ports


def _read_lines(ser, seconds, quiet=None):
    """Read lines for up to `seconds`, stopping early after `quiet` seconds of silence."""
    lines, raw, buf = [], b"", b""
    end = last = time.time()
    end += seconds
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
    return [l for l in lines if l], raw


def send(ser, cmd, timeout=8.0):
    """Send one G-code line and collect the reply up to the final 'ok'."""
    ser.reset_input_buffer()
    ser.write((cmd + "\n").encode("ascii"))
    ser.flush()
    lines, buf = [], b""
    end = time.time() + timeout
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
                end = time.time() + timeout  # still alive, keep waiting
    return lines


def looks_binary(raw):
    if len(raw) < 8:
        return False
    printable = sum(1 for b in raw if 32 <= b < 127 or b in (9, 10, 13))
    return printable / len(raw) < 0.7


class Printer:
    """An open connection to a printer that answers G-code."""

    def __init__(self, port, log=print):
        self.port = port
        self.log = log
        self.ser = None
        self.baud = None
        self.boot = []
        self.m115 = []
        self.saw_binary = False

    def connect(self):
        for baud in BAUD_RATES:
            self.log(f"Trying {self.port.device} at {baud} baud...")
            try:
                ser = serial.Serial(self.port.device, baud, timeout=0.2)
            except serial.SerialException as e:
                self.log(f"Could not open {self.port.device}: {e}")
                return False
            # Opening the port resets 8-bit boards (DTR). Whatever they print while
            # booting is a useful clue, so capture it.
            boot, raw = _read_lines(ser, 6.0, quiet=2.5)
            self.saw_binary |= looks_binary(raw)
            m115 = send(ser, "M115", timeout=4.0)
            if any("FIRMWARE_NAME" in l or l.startswith("ok") for l in m115):
                self.ser, self.baud, self.boot, self.m115 = ser, baud, boot, m115
                self.log(f"Connected at {baud} baud.")
                return True
            _, raw = _read_lines(ser, 0.5)
            self.saw_binary |= looks_binary(raw)
            ser.close()
        return False

    def send(self, cmd, timeout=8.0):
        return send(self.ser, cmd, timeout)

    def close(self):
        if self.ser:
            self.ser.close()
            self.ser = None


def scan(port, log=print, reboot=False):
    """Connect and collect everything the diagnosis needs. Returns a dict."""
    data = {
        "port": port.device, "usb_desc": port.friendly, "usb_family": port.usb_family,
        "vid": port.vid, "pid": port.pid,
        "connected": False, "saw_binary": False, "baud": None,
        "boot": [], "m115": [], "m122": [], "m503": [], "m21": [], "reboot": [],
    }
    p = Printer(port, log)
    try:
        if not p.connect():
            data["saw_binary"] = p.saw_binary
            return data
        data.update(connected=True, baud=p.baud, boot=p.boot, m115=p.m115)
        log("Asking the motor drivers how they are doing (M122)...")
        data["m122"] = p.send("M122", timeout=10.0)
        log("Reading saved settings (M503)...")
        data["m503"] = p.send("M503", timeout=8.0)
        log("Checking the printer's SD card slot (M21)...")
        data["m21"] = p.send("M21", timeout=8.0)
        if reboot:
            log("Restarting the printer to capture its startup messages...")
            p.ser.write(b"M997\n")
            p.close()
            time.sleep(1.0)
            try:
                ser = serial.Serial(port.device, p.baud, timeout=0.2)
                data["reboot"], _ = _read_lines(ser, 15.0, quiet=4.0)
                ser.close()
            except serial.SerialException:
                data["reboot"] = ["(port disappeared during restart - normal on some boards)"]
    finally:
        p.close()
    return data


def movement_test(port, baud, log=print):
    """Nudge X by +10 mm (relative move). Returns the printer's replies."""
    ser = serial.Serial(port.device, baud, timeout=0.2)
    try:
        _read_lines(ser, 2.0, quiet=1.0)
        out = []
        for cmd in ("M17", "G91", "G1 X10 F1200", "M400", "G90"):
            log(f"> {cmd}")
            out += send(ser, cmd, timeout=10.0)
        return out
    finally:
        ser.close()


def reset_settings(port, baud, log=print):
    """Load firmware defaults and save them (clears leftovers from old firmware)."""
    ser = serial.Serial(port.device, baud, timeout=0.2)
    try:
        _read_lines(ser, 2.0, quiet=1.0)
        out = []
        for cmd in ("M502", "M500"):
            log(f"> {cmd}")
            out += send(ser, cmd, timeout=10.0)
        return out
    finally:
        ser.close()
