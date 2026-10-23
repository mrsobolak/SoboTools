"""Where Sobolak Repair keeps reports and the list of printers it has seen."""

import datetime
import json
import os
import re

from . import APP_NAME, __version__


def data_dir():
    base = os.path.join(os.path.expanduser("~"), "Documents")
    if not os.path.isdir(base):
        base = os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def fleet_path():
    return os.path.join(data_dir(), "printers.json")


def load_fleet():
    try:
        with open(fleet_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def update_fleet(name, **fields):
    fleet = load_fleet()
    entry = fleet.setdefault(name, {"name": name})
    entry.update(fields, updated=datetime.datetime.now().isoformat(timespec="seconds"))
    with open(fleet_path(), "w", encoding="utf-8") as f:
        json.dump(fleet, f, indent=2)
    return entry


def format_report(name, data, diag, extra=None):
    out = [f"{APP_NAME} {__version__} - printer report",
           f"Printer: {name}",
           f"Time:    {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
           f"Port:    {data.get('port')}  USB {data.get('vid')}:{data.get('pid')}  "
           f"baud {data.get('baud')}",
           "",
           f"RESULT:  {diag.verdict} - {diag.title}",
           diag.summary, ""]
    out += [f"  [{sev}] {text}" for sev, text in diag.findings]
    if diag.candidates:
        out += ["", f"Board guess: {diag.board_text}",
                f"Firmware options: {', '.join(diag.candidates)}",
                f"Recommended: {diag.recommended or '(choose by board label)'}"]
    for line in extra or []:
        out.append(line)
    for section in ("boot", "m115", "m122", "m503", "reboot"):
        if data.get(section):
            out += ["", f"----- {section.upper()} -----"] + data[section]
    return "\n".join(out) + "\n"


def save_report(name, text):
    folder = os.path.join(data_dir(), "reports")
    os.makedirs(folder, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name) or "printer"
    path = os.path.join(folder, f"{safe}_{datetime.datetime.now():%Y%m%d-%H%M%S}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path
