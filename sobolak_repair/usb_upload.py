"""Send a file to the printer's own SD card over USB.

Uses Marlin's binary file transfer protocol (M28 B1), available when the
firmware was built with BINARY_FILE_TRANSFER. Written from the protocol as
implemented in Marlin/src/feature/binary_stream.h:

  packet = AD B5 | sync u8 | protocol<<4|type u8 | size u16 | header fletcher16 u16
           | payload | packet fletcher16 u16 (only when size > 0)

The printer answers each packet with "ok<sync>", asks for a resend with
"rs<sync>", reports a fatal error with "fe<sync>" and answers a SYNC control
packet with "ss<sync>,<max payload>,<version>". File-transfer results arrive
as "PFT:success" / "PFT:fail" / "PFT:ioerror" / "PFT:busy".
"""

import re
import struct
import time

TOKEN = b"\xad\xb5"
CONTROL, FILE_TRANSFER = 0, 1
SYNC, CLOSE_STREAM = 1, 2
QUERY, OPEN, CLOSE, WRITE, ABORT = range(5)


class UploadError(Exception):
    pass


def fletcher16(data, cs=0):
    lo, hi = cs & 0xFF, cs >> 8
    for b in data:
        lo = (lo + b) % 255
        hi = (hi + lo) % 255
    return (hi << 8) | lo


def build_packet(sync, protocol, ptype, payload=b""):
    head = struct.pack("<BBH", sync & 0xFF, (protocol << 4) | ptype, len(payload))
    head += struct.pack("<H", fletcher16(head))
    footer = struct.pack("<H", fletcher16(head + payload)) if payload else b""
    return TOKEN + head + payload + footer


class BinaryUploader:
    """Drives one upload on an already-open pyserial connection in ASCII mode."""

    def __init__(self, ser, log=print, timeout=3.0, retries=8):
        self.ser, self.log, self.timeout, self.retries = ser, log, timeout, retries
        self.sync = 0
        self.max_payload = 0
        self._buf = b""

    # ---- line reading --------------------------------------------------
    def _readline(self, deadline):
        while time.time() < deadline:
            if b"\n" in self._buf:
                line, self._buf = self._buf.split(b"\n", 1)
                return line.decode("ascii", "replace").strip()
            chunk = self.ser.read(self.ser.in_waiting or 1)
            if chunk:
                self._buf += chunk
        return None

    def _wait(self, pattern, timeout=None):
        """Return the first line matching `pattern` (regex), or None on timeout."""
        deadline = time.time() + (timeout or self.timeout)
        while True:
            line = self._readline(deadline)
            if line is None:
                return None
            m = re.match(pattern, line)
            if m:
                return m
            if line.startswith("fe"):
                raise UploadError("The printer reported a transfer error.")

    # ---- packets -------------------------------------------------------
    def _send(self, protocol, ptype, payload=b""):
        """Send one packet and wait for its 'ok'. Handles resends."""
        for _ in range(self.retries):
            self.ser.write(build_packet(self.sync, protocol, ptype, payload))
            m = self._wait(r"^(ok|rs)(\d+)")
            if m is None:
                continue  # lost packet or lost reply: send again (printer dedupes)
            kind, n = m.group(1), int(m.group(2))
            if kind == "ok" and n == self.sync:
                self.sync = (self.sync + 1) & 0xFF
                return
            if kind == "rs":
                self.sync = n
        raise UploadError("The printer stopped acknowledging data.")

    def _pft(self, timeout=None):
        m = self._wait(r"^P[FT]T:(\w+)", timeout)
        return m.group(1) if m else None

    # ---- protocol steps ------------------------------------------------
    def start(self):
        self.ser.reset_input_buffer()
        self.ser.write(b"M28 B1\n")
        if not self._wait(r".*Switching to Binary Protocol", 5.0):
            raise UploadError("This firmware can't receive files over USB.")
        time.sleep(0.1)
        self.ser.write(build_packet(0, CONTROL, SYNC))
        m = self._wait(r"^ss(\d+),(\d+),")
        if not m:
            raise UploadError("The printer didn't answer the transfer handshake.")
        self.sync, self.max_payload = int(m.group(1)), int(m.group(2))
        self.log(f"Binary transfer ready (block size {self.max_payload} bytes).")

    def finish(self):
        """Return the printer to normal G-code mode."""
        try:
            self._send(CONTROL, CLOSE_STREAM)
        except UploadError:
            pass
        time.sleep(0.2)

    def upload(self, data, remote_name, progress=None):
        self._send(FILE_TRANSFER, QUERY)
        self._pft()  # version/compression line; we always send uncompressed
        self._send(FILE_TRANSFER, OPEN, b"\x00\x00" + remote_name.encode("ascii") + b"\x00")
        result = self._pft(5.0)
        if result != "success":
            raise UploadError(f"The printer couldn't create {remote_name} on its SD card "
                              f"({result or 'no answer'}). Is a card inserted?")
        try:
            # The printer's receive buffer (reported in the handshake) caps each payload.
            block = max(16, min(self.max_payload, 512))
            sent = 0
            while sent < len(data):
                chunk = data[sent:sent + block]
                self._send(FILE_TRANSFER, WRITE, chunk)
                sent += len(chunk)
                if progress:
                    progress(sent / len(data))
            self._send(FILE_TRANSFER, CLOSE)
            result = self._pft(10.0)
            if result != "success":
                raise UploadError(f"The SD card reported an error while saving ({result}).")
        except Exception:
            try:
                self._send(FILE_TRANSFER, ABORT)
            except UploadError:
                pass
            raise


def list_root_bins(ser, send):
    """Firmware files already in the top folder of the printer's card (via M20)."""
    lines = send(ser, "M20", timeout=10.0)
    names = []
    inside = False
    for l in lines:
        if l.startswith("Begin file list"):
            inside = True
        elif l.startswith("End file list"):
            inside = False
        elif inside:
            name = l.split()[0] if l.split() else ""
            if "/" not in name and name.upper().endswith(".BIN"):
                names.append(name)
    return names


def upload_firmware(port, baud, data, remote_name, log=print, progress=None):
    """Delete old firmware files from the printer's card, then upload `data`."""
    import serial
    from .printer import _read_lines, send

    ser = serial.Serial(port.device, baud, timeout=0.05)
    try:
        _read_lines(ser, 2.0, quiet=1.0)
        mounted = send(ser, "M21", timeout=8.0)
        if not any("SD card ok" in l for l in mounted):
            raise UploadError("The printer doesn't see an SD card. Insert one into the printer "
                              "and try again.")
        for old in list_root_bins(ser, send):
            log(f"Removing old firmware file {old} from the printer's card")
            send(ser, f"M30 {old}", timeout=5.0)
        up = BinaryUploader(ser, log)
        up.start()
        try:
            log(f"Sending {len(data) // 1024} KB as {remote_name}...")
            start = time.time()
            up.upload(data, remote_name, progress)
            log(f"Sent in {time.time() - start:.0f} s.")
        finally:
            up.finish()
    finally:
        ser.close()
