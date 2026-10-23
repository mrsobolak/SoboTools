import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sobolak_repair import flasher  # noqa: E402
from sobolak_repair.flasher import Drive  # noqa: E402


def setup_firmware(tmp_path, monkeypatch):
    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "creality_v422.bin").write_bytes(os.urandom(4096))
    (fw / "manifest.json").write_text(json.dumps(
        {"images": {"creality_v422": {"file": "creality_v422.bin"},
                    "skr_mini_e3_v2": {"file": "creality_v422.bin"}}}))
    monkeypatch.setattr(flasher, "FIRMWARE_DIR", str(fw))
    card = tmp_path / "card"
    card.mkdir()
    return Drive(str(card), "CARD", "FAT32", 8 * 1024 ** 3)


def test_creality_gets_unique_83_name(tmp_path, monkeypatch):
    drive = setup_firmware(tmp_path, monkeypatch)
    names = {flasher.write_firmware(drive, "creality_v422", "creality_stm32") for _ in range(5)}
    assert len(names) == 5
    assert all(re.fullmatch(r"SR[0-9A-F]{6}\.bin", n) for n in names)
    # each write removes the previous .bin so the bootloader only ever sees one
    assert len(flasher.old_firmware_files(drive)) == 1


def test_btt_must_be_firmware_bin(tmp_path, monkeypatch):
    drive = setup_firmware(tmp_path, monkeypatch)
    (tmp_path / "card" / "FIRMWARE.CUR").write_text("old")
    assert flasher.write_firmware(drive, "skr_mini_e3_v2", "btt") == "firmware.bin"
    assert (tmp_path / "card" / "FIRMWARE.CUR").exists()  # non-.bin files are left alone


def test_card_warnings():
    assert flasher.card_warnings(Drive("E:\\", "", "FAT32", 8 * 1024 ** 3)) == []
    assert len(flasher.card_warnings(Drive("E:\\", "", "exFAT", 64 * 1024 ** 3))) == 2


def test_missing_image_raises(tmp_path, monkeypatch):
    drive = setup_firmware(tmp_path, monkeypatch)
    try:
        flasher.write_firmware(drive, "creality_v427", "creality_stm32")
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError")
