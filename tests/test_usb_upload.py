"""The USB uploader against a simulated Marlin binary-transfer receiver."""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sobolak_repair.usb_upload import (BinaryUploader, UploadError, build_packet,  # noqa: E402
                                       fletcher16)


def marlin_checksum(cs, value):  # Marlin's own formulation, to cross-check ours
    lo = ((cs & 0xFF) + value) % 255
    return ((((cs >> 8) + lo) % 255) << 8) | lo


class FakeMarlin:
    """Minimal pyserial stand-in that behaves like Marlin with BINARY_FILE_TRANSFER."""

    def __init__(self, buffer_size=256, corrupt_packets=(), drop_acks=(), binary=True):
        self.out = b""
        self.binary_supported = binary
        self.binary = False
        self.sync = 0
        self.buffer_size = buffer_size
        self.files = {}
        self.open_name = None
        self.corrupt = set(corrupt_packets)
        self.drop = set(drop_acks)
        self.count = 0
        self.ascii = b""
        self.pending = b""

    # pyserial surface
    @property
    def in_waiting(self):
        return len(self.out)

    def read(self, n=1):
        data, self.out = self.out[:n], self.out[n:]
        return data

    def reset_input_buffer(self):
        self.out = b""

    def say(self, line):
        self.out += line.encode() + b"\n"

    def write(self, data):
        if not self.binary:
            self.ascii += data
            while b"\n" in self.ascii:
                line, self.ascii = self.ascii.split(b"\n", 1)
                if line.strip() == b"M28 B1" and self.binary_supported:
                    self.say("echo:Switching to Binary Protocol")
                    self.binary = True
                else:
                    self.say("ok")
            return
        self.pending += data
        while self._packet():
            pass

    # Marlin's receive state machine, condensed
    def _packet(self):
        buf = self.pending
        start = buf.find(b"\xad\xb5")
        if start < 0 or len(buf) < start + 8:
            return False
        sync, meta, size, hcs = struct.unpack("<BBHH", buf[start + 2:start + 8])
        total = 8 + size + (2 if size else 0)
        if len(buf) < start + total:
            return False
        pkt = bytearray(buf[start:start + total])
        self.pending = buf[start + total:]
        self.count += 1
        if self.count in self.corrupt:
            pkt[-1] ^= 0xFF if size else 0
            if not size:
                pkt[6] ^= 0xFF
        cs = 0
        for b in pkt[2:6]:
            cs = marlin_checksum(cs, b)
        if cs != struct.unpack("<H", bytes(pkt[6:8]))[0]:
            self.say(f"rs{self.sync}")
            return True
        protocol, ptype = meta >> 4, meta & 0xF
        if protocol == 0 and ptype == 1:
            self.say(f"ss{self.sync},{self.buffer_size},0.1.0")
            return True
        if sync == (self.sync - 1) & 0xFF:
            self.say(f"ok{sync}")
            return True
        if sync != self.sync:
            self.say(f"rs{self.sync}")
            return True
        payload = bytes(pkt[8:8 + size])
        if size:
            for b in pkt[6:8 + size]:
                cs = marlin_checksum(cs, b)
            if cs != struct.unpack("<H", bytes(pkt[8 + size:]))[0]:
                self.say(f"rs{self.sync}")
                return True
            assert size <= self.buffer_size, "payload overran the printer's buffer"
        self.sync = (self.sync + 1) & 0xFF
        if self.count not in self.drop:
            self.say(f"ok{sync}")
        self._dispatch(protocol, ptype, payload)
        return True

    def _dispatch(self, protocol, ptype, payload):
        if protocol == 0 and ptype == 2:
            self.binary = False
        elif protocol == 1:
            if ptype == 0:
                self.say("PFT:version:0.1.0:compression:none")
            elif ptype == 1:
                self.open_name = payload[2:-1].decode()
                self.files[self.open_name] = b""
                self.say("PFT:success")
            elif ptype == 3:
                self.files[self.open_name] += payload
            elif ptype == 2:
                self.open_name = None
                self.say("PFT:success")
            elif ptype == 4:
                self.files.pop(self.open_name, None)
                self.say("PFT:success")


def run(fake, data, name="SRABCDEF.BIN"):
    up = BinaryUploader(fake, log=lambda m: None, timeout=0.3)
    up.start()
    up.upload(data, name)
    up.finish()
    return fake


def test_checksum_matches_marlin():
    data = bytes(range(256)) * 3
    cs = 0
    for b in data:
        cs = marlin_checksum(cs, b)
    assert fletcher16(data) == cs


def test_packet_layout():
    p = build_packet(5, 1, 3, b"hi")
    assert p[:2] == b"\xad\xb5" and p[2] == 5 and p[3] == 0x13
    assert struct.unpack("<H", p[4:6])[0] == 2 and len(p) == 8 + 2 + 2


def test_clean_upload_is_byte_exact():
    data = os.urandom(70_000)
    fake = run(FakeMarlin(), data)
    assert fake.files["SRABCDEF.BIN"] == data
    assert not fake.binary  # back in G-code mode


def test_recovers_from_corruption_and_lost_acks():
    data = os.urandom(20_000)
    fake = run(FakeMarlin(buffer_size=96, corrupt_packets={7, 30, 31}, drop_acks={12, 50}), data)
    assert fake.files["SRABCDEF.BIN"] == data


def test_firmware_without_binary_transfer_is_refused():
    up = BinaryUploader(FakeMarlin(binary=False), log=lambda m: None, timeout=0.2)
    try:
        up.start()
    except UploadError as e:
        assert "can't receive files" in str(e)
        return
    raise AssertionError("expected UploadError")
