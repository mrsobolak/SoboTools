"""Find SD cards and put firmware on them the way each board's bootloader expects."""

import hashlib
import json
import os
import secrets
import shutil
import sys
from dataclasses import dataclass

from .diagnose import FLASH_METHOD

FIRMWARE_DIR = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))),
                            *(["sobolak_repair"] if hasattr(sys, "_MEIPASS") else []), "firmware")

MAX_CARD_BYTES = 16 * 1024 ** 3  # bootloaders only read FAT32; big cards are unreliable


@dataclass
class Drive:
    root: str
    label: str
    filesystem: str
    total: int

    @property
    def display(self):
        gb = self.total / 1024 ** 3 if self.total else 0
        return f"{self.root}  {self.label or 'Removable Disk'}  ({self.filesystem or '?'}, {gb:.1f} GB)"


def load_manifest():
    path = os.path.join(FIRMWARE_DIR, "manifest.json")
    if not os.path.exists(path):
        return {"images": {}}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def firmware_path(target):
    info = load_manifest()["images"].get(target)
    return os.path.join(FIRMWARE_DIR, info["file"]) if info else None


def list_drives():
    """Removable drives. On Windows uses the Win32 API; elsewhere SOBOLAK_FAKE_SD
    (a folder path) can stand in for a card when testing."""
    fake = os.environ.get("SOBOLAK_FAKE_SD")
    if fake:
        return [Drive(fake, "TESTCARD", "FAT32", 8 * 1024 ** 3)]
    if os.name != "nt":
        return []
    import ctypes
    k32 = ctypes.windll.kernel32
    drives = []
    mask = k32.GetLogicalDrives()
    for i in range(26):
        if not mask & (1 << i):
            continue
        root = f"{chr(65 + i)}:\\"
        if k32.GetDriveTypeW(root) != 2:  # DRIVE_REMOVABLE
            continue
        label = ctypes.create_unicode_buffer(261)
        fs = ctypes.create_unicode_buffer(261)
        if not k32.GetVolumeInformationW(root, label, 261, None, None, None, fs, 261):
            continue  # empty card reader slot
        total = ctypes.c_ulonglong(0)
        k32.GetDiskFreeSpaceExW(root, None, ctypes.byref(total), None)
        drives.append(Drive(root, label.value, fs.value, total.value))
    return drives


def card_warnings(drive):
    warnings = []
    if drive.filesystem and drive.filesystem.upper() not in ("FAT32", "FAT"):
        warnings.append(f"The card is formatted as {drive.filesystem}. Printer bootloaders "
                        "only read FAT32. Reformat it as FAT32 first.")
    if drive.total > MAX_CARD_BYTES:
        warnings.append("Cards larger than 16 GB often don't work with printer bootloaders. An 8 GB card is safest.")
    return warnings


def old_firmware_files(drive):
    """Firmware files in the card's top folder that would confuse the bootloader."""
    try:
        return sorted(f for f in os.listdir(drive.root)
                      if f.lower().endswith(".bin") and os.path.isfile(os.path.join(drive.root, f)))
    except OSError:
        return []


def target_filename(board_family):
    if FLASH_METHOD.get(board_family) == "sd_firmware_bin":
        return "firmware.bin"
    # Creality's bootloader silently skips a file whose name matches the last one it
    # flashed (and never renames it), so every flash gets a fresh 8.3-safe name.
    return f"SR{secrets.token_hex(3).upper()}.bin"


def write_firmware(drive, target, board_family, remove_old=True):
    """Copy the firmware image to the card and read it back. Returns the file name."""
    src = firmware_path(target)
    if not src or not os.path.exists(src):
        raise FileNotFoundError(f"Firmware image for '{target}' is not bundled with this build.")
    if remove_old:
        for name in old_firmware_files(drive):
            os.remove(os.path.join(drive.root, name))
    name = target_filename(board_family)
    dst = os.path.join(drive.root, name)
    shutil.copyfile(src, dst)
    with open(dst, "rb+") as f:
        os.fsync(f.fileno())
    with open(src, "rb") as a, open(dst, "rb") as b:
        if hashlib.sha256(a.read()).digest() != hashlib.sha256(b.read()).digest():
            raise IOError("The file on the card doesn't match. The card may be failing.")
    return name
