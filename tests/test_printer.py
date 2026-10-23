"""Connection logic against a printer that stays silent while it boots."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sobolak_repair import printer  # noqa: E402


class SlowBootSerial:
    """Answers G-code only after `boot_s` seconds, like a Creality board restarting on DTR."""

    def __init__(self, device, baud, timeout=0.2, boot_s=7.0):
        self.start, self.boot_s, self.out = time.time(), boot_s, b""

    @property
    def in_waiting(self):
        return len(self.out)

    def read(self, n=1):
        if not self.out:
            time.sleep(0.01)
        data, self.out = self.out[:n], self.out[n:]
        return data

    def write(self, data):
        if time.time() - self.start < self.boot_s:
            return  # still in the bootloader: input is lost
        for line in data.decode().splitlines():
            if line.strip() == "M115":
                self.out += b"FIRMWARE_NAME:Marlin 2.0.8.2 MACHINE_TYPE:Ender-5 Pro\nok\n"
            elif line.strip():
                self.out += b"ok\n"

    def reset_input_buffer(self):
        self.out = b""

    def flush(self):
        pass

    def close(self):
        pass


def test_waits_for_a_slow_booting_board(monkeypatch):
    monkeypatch.setattr(printer.serial, "Serial", SlowBootSerial)
    p = printer.Printer(printer.Port("COM3", "CH340", 0x1A86, 0x7523), log=lambda m: None)
    assert p.connect()
    assert p.baud == 115200  # found at the first speed, didn't give up and switch
    assert any("FIRMWARE_NAME" in l for l in p.m115)


def test_port_in_use_is_reported(monkeypatch):
    def busy(*a, **k):
        raise printer.serial.SerialException("could not open port 'COM3': PermissionError(13)")
    monkeypatch.setattr(printer.serial, "Serial", busy)
    data = printer.scan(printer.Port("COM3", "CH340", 0x1A86, 0x7523), log=lambda m: None)
    from sobolak_repair.diagnose import diagnose
    assert diagnose(data).verdict == "PORT_BUSY"
    assert data["log"]  # the report keeps the steps
