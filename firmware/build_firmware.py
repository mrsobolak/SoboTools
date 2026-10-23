"""
Build the Marlin firmware images that Sobolak Repair can flash.

Every image starts from an official Ender-5 Pro example config in
MarlinFirmware/Configurations, plus the small edits listed in TARGETS.
Nothing else is changed, so the output matches what Marlin publishes.

Usage:
    python firmware/build_firmware.py --marlin PATH --configs PATH [--only NAME ...]

PATH arguments are checkouts of:
    https://github.com/MarlinFirmware/Marlin          (tag MARLIN_TAG)
    https://github.com/MarlinFirmware/Configurations  (branch CONFIGS_BRANCH)

Output: sobolak_repair/firmware/<name>.bin|.hex + manifest.json
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

MARLIN_TAG = "2.1.2.9"
CONFIGS_BRANCH = "release-2.1.2.9"
E5P = "config/examples/Creality/Ender-5 Pro"

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "..", "sobolak_repair", "firmware")

# name -> how to build it.
#   config:  example folder to start from
#   env:     PlatformIO environment
#   set:     {OPTION: value} -> "#define OPTION value" (value None = bare #define)
#   unset:   [OPTION, ...]   -> commented out
TARGETS = {
    "creality_v422": {
        "title": "Creality 4.2.2 (stock, no probe)",
        "config": "CrealityV422", "env": "STM32F103RE_creality",
        "set": {}, "unset": [],
    },
    "creality_v422_bltouch": {
        "title": "Creality 4.2.2 + BLTouch/CR Touch",
        "config": "CrealityV422", "env": "STM32F103RE_creality",
        "set": {"ENDER5_USE_BLTOUCH": None}, "unset": [],
    },
    "creality_v427": {
        "title": "Creality 4.2.7 (stock, no probe)",
        "config": "CrealityV427", "env": "STM32F103RE_creality",
        "set": {}, "unset": [],
    },
    "creality_v1": {
        "title": "Creality 1.1.x (ATmega1284P) - needs bootloader",
        "config": "CrealityV1", "env": "melzi_optiboot_optimized",
        "set": {}, "unset": [],
    },
    "skr_mini_e3_v1_2": {
        "title": "BigTreeTech SKR Mini E3 V1.2",
        "config": "BigTreeTech SKR Mini E3 1.2", "env": "STM32F103RC_btt",
        "set": {}, "unset": [],
    },
    "skr_mini_e3_v2": {
        "title": "BigTreeTech SKR Mini E3 V2.0",
        "config": "BigTreeTech SKR Mini E3 1.2", "env": "STM32F103RC_btt",
        "set": {"MOTHERBOARD": "BOARD_BTT_SKR_MINI_E3_V2_0"}, "unset": [],
    },
    "skr_mini_e3_v3": {
        "title": "BigTreeTech SKR Mini E3 V3.0",
        "config": "BigTreeTech SKR Mini E3 1.2", "env": "STM32G0B1RE_btt",
        "set": {"MOTHERBOARD": "BOARD_BTT_SKR_MINI_E3_V3_0"}, "unset": [],
    },
}


def edit_config(path, set_opts, unset_opts):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    for opt, value in set_opts.items():
        line = f"#define {opt}" + ("" if value is None else f" {value}")
        pat = re.compile(rf"^(\s*)(//\s*)?#define\s+{opt}\b.*$", re.M)
        if pat.search(text):
            text = pat.sub(lambda m: m.group(1) + line, text, count=1)
        else:
            # Not present in the file: define it right after the header guard.
            text = text.replace("#pragma once", "#pragma once\n" + line, 1)
    for opt in unset_opts:
        text = re.sub(rf"^(\s*)#define\s+{opt}\b", r"\1//#define " + opt, text, flags=re.M)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def build(name, spec, marlin, configs, pio):
    print(f"\n=== {name}: {spec['title']} ===", flush=True)
    src = os.path.join(configs, E5P, spec["config"])
    dst = os.path.join(marlin, "Marlin")
    for fn in os.listdir(src):
        if fn.endswith(".h"):
            shutil.copy(os.path.join(src, fn), os.path.join(dst, fn))
    edit_config(os.path.join(dst, "Configuration.h"), spec["set"], spec["unset"])

    build_dir = os.path.join(marlin, ".pio", "build", spec["env"])
    shutil.rmtree(build_dir, ignore_errors=True)
    subprocess.run(pio + ["run", "-d", marlin, "-e", spec["env"]], check=True)

    images = [f for f in os.listdir(build_dir) if re.match(r"(firmware.*)\.(bin|hex)$", f)]
    if not images:
        raise RuntimeError(f"no firmware image produced in {build_dir}")
    image = sorted(images, key=lambda f: os.path.getmtime(os.path.join(build_dir, f)))[-1]
    ext = os.path.splitext(image)[1]
    out_name = name + ext
    os.makedirs(OUT_DIR, exist_ok=True)
    shutil.copy(os.path.join(build_dir, image), os.path.join(OUT_DIR, out_name))
    with open(os.path.join(OUT_DIR, out_name), "rb") as f:
        data = f.read()
    return {
        "file": out_name, "title": spec["title"], "env": spec["env"],
        "config": f"{E5P}/{spec['config']}", "set": spec["set"], "unset": spec["unset"],
        "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--marlin", required=True)
    ap.add_argument("--configs", required=True)
    ap.add_argument("--only", nargs="*", help="build only these targets")
    ap.add_argument("--pio", default=f"{sys.executable} -m platformio",
                    help="command used to run PlatformIO")
    args = ap.parse_args()

    names = args.only or list(TARGETS)
    manifest_path = os.path.join(OUT_DIR, "manifest.json")
    manifest = {"marlin": MARLIN_TAG, "configurations": CONFIGS_BRANCH, "images": {}}
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            manifest["images"] = json.load(f).get("images", {})

    failed = []
    for name in names:
        try:
            manifest["images"][name] = build(name, TARGETS[name], args.marlin,
                                             args.configs, args.pio.split())
        except Exception as e:  # keep going so one bad target doesn't block the rest
            print(f"!!! {name} failed: {e}", flush=True)
            failed.append(name)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nBuilt {len(names) - len(failed)}/{len(names)}." +
          (f" Failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
