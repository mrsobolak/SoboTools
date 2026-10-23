"""Sobolak Repair - main window."""

import os
import queue
import threading
import tkinter as tk
import traceback

from . import APP_NAME, __version__, diagnose as dx, flasher, printer, storage
from . import theme as T

COMPANY = "Sobolak Technologies"
STEPS = ["Connect", "Diagnose", "Firmware", "SD card", "Install", "Verify"]
GAP = 16

TARGET_INFO = {
    "creality_v422": ("Creality 4.2.2", "The most common Ender 5 Pro board from 2020 on. "
                      "Stock setup with the Z limit switch."),
    "creality_v427": ("Creality 4.2.7", "Later Creality board. Looks the same as 4.2.2, but "
                      "the motor pins differ, so match the label on the board."),
    "creality_v422_bltouch": ("Creality 4.2.2 + BLTouch", "Only if a bed-levelling probe "
                              "(BLTouch or CR Touch) is mounted next to the nozzle."),
    "creality_v1": ("Creality 1.1.x", "Early 2019 8-bit board. Flashed over USB rather than "
                    "SD card. Not supported in this version yet."),
    "skr_mini_e3_v1_2": ("SKR Mini E3 V1.2", "BigTreeTech upgrade board. 'V1.2' is printed "
                         "near the motor drivers."),
    "skr_mini_e3_v2": ("SKR Mini E3 V2.0", "BigTreeTech upgrade board. 'V2.0' is printed on "
                       "the board."),
    "skr_mini_e3_v3": ("SKR Mini E3 V3.0", "BigTreeTech upgrade board with the newer STM32G0 "
                       "chip. 'V3.0' is printed on the board."),
}


def target_family(target):
    if target.startswith("skr"):
        return "btt"
    if target == "creality_v1":
        return "creality_avr"
    return "creality_stm32"


class Session:
    """Everything known about the printer currently being repaired."""

    def __init__(self, name):
        self.name = name
        self.port = None
        self.data = None
        self.diag = None
        self.before = None
        self.target = None
        self.written = None
        self.report_path = None


# ==========================================================================
# Layout helpers
# ==========================================================================

def bento(parent, cols, rows=0):
    """A grid frame with equal-width columns."""
    g = tk.Frame(parent, bg=T.BG)
    for c in range(cols):
        g.columnconfigure(c, weight=1, uniform="col")
    for r in range(rows):
        g.rowconfigure(r, weight=1)
    return g


def place(card, row, col, colspan=1, rowspan=1):
    card.grid(row=row, column=col, columnspan=colspan, rowspan=rowspan, sticky="nsew",
              padx=(0 if col == 0 else T.px(GAP) // 2, T.px(GAP) // 2),
              pady=(0, T.px(GAP)))
    return card


def eyebrow(parent, text, color=T.MUTED):
    return T.label(parent, text.upper(), "tiny", fg=color)


def findings_list(parent, findings, wrap):
    for sev, text in findings:
        row = tk.Frame(parent, bg=parent.cget("bg"))
        row.pack(fill="x", pady=T.px(3))
        T.Glyph(row, sev, 18).pack(side="left", anchor="n", pady=T.px(1))
        T.label(row, text, "small", fg=T.TEXT if sev in ("error", "warn") else T.MUTED,
                wrap=wrap).pack(side="left", padx=T.px(10))


# ==========================================================================
# Pages
# ==========================================================================

class Page(tk.Frame):
    step = None
    title = ""
    subtitle = ""

    def __init__(self, app):
        super().__init__(app.scroll.body, bg=T.BG)
        self.app = app
        self.build()

    def build(self):
        pass

    def on_show(self):
        pass

    def back(self):          # (label, enabled) or None to hide
        return None

    def next(self):
        return None

    def go_back(self):
        pass

    def go_next(self):
        pass


class HomePage(Page):
    title = "Bring every printer back."
    subtitle = "Find and fix TMC connection errors on Creality Ender 5 Pro printers."

    def build(self):
        self.grid_ = bento(self, 3)
        self.grid_.pack(fill="both", expand=True)

        hero = place(T.Card(self.grid_, pad=32), 0, 0, colspan=2)
        h = hero.inner
        eyebrow(h, "How it works", T.CYAN).pack(anchor="w")
        T.label(h, "Plug in. Diagnose. Repaired.", "h2").pack(anchor="w", pady=(T.px(8), 0))
        T.label(h, "Sobolak Repair asks the printer what is wrong, writes the right firmware to "
                   "an SD card, and confirms the fix once it's installed.", "body", fg=T.MUTED,
                wrap=T.px(520)).pack(anchor="w", pady=(T.px(8), T.px(22)))
        steps = tk.Frame(h, bg=T.CARD)
        steps.pack(anchor="w")
        for i, s in enumerate(("Connect USB", "Scan", "Write SD card", "Verify")):
            T.Pill(steps, f"{i + 1}  {s}", T.BLUE if i == 0 else T.FAINT).pack(
                side="left", padx=(0, T.px(8)))

        ring = place(T.Card(self.grid_, pad=28), 0, 2)
        r = ring.inner
        eyebrow(r, "Fleet health").pack(anchor="w")
        self.ring = tk.Label(r, bg=T.CARD, bd=0)
        self.ring.pack(pady=(T.px(12), T.px(4)))
        self.ring_text = T.label(r, "", "small", fg=T.MUTED)
        self.ring_text.pack()

        self.metrics = {}
        for col, (key, name, colors) in enumerate((
                ("seen", "Printers scanned", T.GRAD_BLUE),
                ("needs", "Need repair", T.GRAD_ORANGE),
                ("fixed", "Repaired or healthy", T.GRAD_GREEN))):
            card = place(T.Card(self.grid_, pad=26), 1, col)
            eyebrow(card.inner, name).pack(anchor="w")
            big = T.GradientLabel(card.inner, "0", 34, colors, bg=T.CARD)
            big.pack(anchor="w", pady=(T.px(6), 0))
            self.metrics[key] = (big, colors)

        fleet = place(T.Card(self.grid_, pad=26), 2, 0, colspan=3)
        top = tk.Frame(fleet.inner, bg=T.CARD)
        top.pack(fill="x")
        T.label(top, "Your printers", "h3").pack(side="left")
        self.list = tk.Frame(fleet.inner, bg=T.CARD)
        self.list.pack(fill="x", pady=(T.px(10), 0))

    def on_show(self):
        fleet = storage.load_fleet()
        fixed = sum(1 for e in fleet.values() if e.get("status") in ("repaired", "healthy"))
        needs = len(fleet) - fixed
        for key, val in (("seen", len(fleet)), ("needs", needs), ("fixed", fixed)):
            big, colors = self.metrics[key]
            big.set(str(val), colors)
        frac = fixed / len(fleet) if fleet else 0
        self._ring = T.ring_image(T.px(132), frac, (T.GREEN, T.CYAN), T.CARD)
        self.ring.config(image=self._ring)
        self.ring_text.config(text=f"{fixed} of {len(fleet)} working" if fleet else
                              "No printers yet")

        for w in self.list.winfo_children():
            w.destroy()
        if not fleet:
            T.label(self.list, "Nothing here yet. Click Start repair to scan your first "
                               "printer.", "body", fg=T.MUTED).pack(anchor="w", pady=T.px(6))
            return
        rows = sorted(fleet.values(), key=lambda e: e.get("updated", ""), reverse=True)[:4]
        for e in rows:
            status = e.get("status", "scanned")
            kind = {"repaired": "ok", "healthy": "ok", "waiting": "warn"}.get(status, "error")
            row = tk.Frame(self.list, bg=T.CARD)
            row.pack(fill="x", pady=T.px(5))
            T.Glyph(row, kind, 26).pack(side="left")
            box = tk.Frame(row, bg=T.CARD)
            box.pack(side="left", padx=T.px(14))
            T.label(box, e["name"], "label").pack(anchor="w")
            T.label(box, e.get("detail", ""), "small", fg=T.MUTED).pack(anchor="w")
            T.Pill(row, status.capitalize(), T.SEVERITY[kind]).pack(side="right")

    def next(self):
        return ("Start repair", True)

    def go_next(self):
        self.app.session = Session(f"Printer {len(storage.load_fleet()) + 1}")
        self.app.show("connect")


class ConnectPage(Page):
    step = 0
    title = "Connect the printer."
    subtitle = "Plug it into this PC with USB and switch it on."

    def build(self):
        g = bento(self, 3)
        g.pack(fill="both", expand=True)
        checks = place(T.Card(g), 0, 0, colspan=2)
        eyebrow(checks.inner, "Before you scan").pack(anchor="w", pady=(0, T.px(8)))
        self.power = tk.BooleanVar(value=False)
        for text, var in (("Printer is plugged into the wall and the power switch is on",
                           self.power),
                          ("A USB cable connects the printer to this PC", tk.BooleanVar()),
                          ("Cura, OctoPrint and other printer apps are closed", tk.BooleanVar())):
            T.CheckRow(checks.inner, text, var, self.app.refresh_actions,
                       width=T.px(600)).pack(anchor="w")

        name = place(T.Card(g), 0, 2)
        eyebrow(name.inner, "Printer name").pack(anchor="w", pady=(0, T.px(10)))
        self.name = tk.StringVar()
        T.Field(name.inner, self.name, 240).pack(anchor="w")
        T.label(name.inner, "Put the same name on a sticker on the printer.", "small",
                fg=T.MUTED, wrap=T.px(250)).pack(anchor="w", pady=(T.px(10), 0))

        ports = place(T.Card(g), 1, 0, colspan=3)
        top = tk.Frame(ports.inner, bg=T.CARD)
        top.pack(fill="x", pady=(0, T.px(12)))
        T.label(top, "Choose the printer", "h3").pack(side="left")
        T.Button(top, "Refresh", self.refresh, style="secondary", height=34).pack(side="right")
        self.ports_box = tk.Frame(ports.inner, bg=T.CARD)
        self.ports_box.pack(fill="x")
        self.port_var = tk.StringVar()

    def on_show(self):
        self.name.set(self.app.session.name)
        self.refresh()

    def refresh(self):
        for w in self.ports_box.winfo_children():
            w.destroy()
        self.ports = {p.device: p for p in printer.find_ports()}
        if not self.ports:
            self.port_var.set("")
            T.label(self.ports_box, "No printer found. Try another USB cable (many only charge), "
                    "then click Refresh. Windows may need the CH340 driver.", "body",
                    fg=T.ORANGE, wrap=T.px(800)).pack(anchor="w")
        else:
            if self.port_var.get() not in self.ports:
                self.port_var.set(next(iter(self.ports)))
            for dev, p in self.ports.items():
                T.OptionCard(self.ports_box, dev, p.friendly, self.port_var, dev,
                             badge="Printer" if p.likely_printer else None, width=T.px(900),
                             command=self.app.refresh_actions).pack(fill="x", pady=T.px(5))
        self.app.refresh_actions()

    def back(self):
        return ("Back", True)

    def go_back(self):
        self.app.show("home")

    def next(self):
        return ("Scan printer", bool(self.port_var.get()) and self.power.get())

    def go_next(self):
        s = self.app.session
        s.name = self.name.get().strip() or s.name
        s.port = self.ports[self.port_var.get()]
        self.app.show("scan")


class ScanPage(Page):
    step = 1
    title = "Scanning."
    subtitle = "Asking the printer about its firmware and motor drivers. About 20 seconds."

    CHECKS = [("Connecting", "Connected"), ("Firmware identity", "M122"),
              ("Motor driver test", "M503"), ("Saved settings", "\x00")]

    def build(self):
        g = bento(self, 3)
        g.pack(fill="both", expand=True)
        g.rowconfigure(0, weight=1)
        log_card, self.log = T.text_box(g, 18)
        place(log_card, 0, 0, colspan=2)
        side = place(T.Card(g), 0, 2)
        eyebrow(side.inner, "Checking").pack(anchor="w")
        self.status = T.label(side.inner, "", "h3", wrap=T.px(260))
        self.status.pack(anchor="w", pady=(T.px(6), T.px(14)))
        self.bar = T.Progress(side.inner)
        self.bar.pack(fill="x", pady=(0, T.px(18)))
        self.rows = []
        for name, _ in self.CHECKS:
            row = tk.Frame(side.inner, bg=T.CARD)
            row.pack(fill="x", pady=T.px(5))
            g_ = T.Glyph(row, "empty", 22)
            g_.pack(side="left")
            T.label(row, name, "body").pack(side="left", padx=T.px(12))
            self.rows.append(g_)

    def on_show(self):
        s = self.app.session
        self.log.delete("1.0", "end")
        self.stage = 0
        for g_ in self.rows:
            g_.set("empty")
        self.rows[0].set("info")
        self.status.config(text=f"{s.name} on {s.port.device}", fg=T.TEXT)
        self.bar.start_indeterminate()
        self.app.run_bg(lambda log: printer.scan(s.port, log=log), self.done, log=self.write)

    def write(self, line):
        self.log.insert("end", line + "\n")
        self.log.see("end")
        # Tick off stages as the scan reports progress.
        for i, (_, trigger) in enumerate(self.CHECKS):
            if i == self.stage and trigger in line:
                self.rows[i].set("ok")
                self.stage = i + 1
                if self.stage < len(self.rows):
                    self.rows[self.stage].set("info")

    def done(self, data, error):
        self.bar.stop()
        s = self.app.session
        if error:
            self.write("Error: " + error)
            self.status.config(text="The scan failed.", fg=T.RED)
            return
        for g_ in self.rows:
            g_.set("ok" if data.get("connected") else "error")
        s.data = data
        s.diag = dx.diagnose(data)
        if s.before is None:
            s.before = s.diag
        s.report_path = storage.save_report(s.name, storage.format_report(s.name, data, s.diag))
        status = {"HEALTHY": "healthy", "DRIVERS_OK_NOW": "healthy",
                  "SOME_DRIVERS_FAIL": "hardware"}.get(s.diag.verdict, "needs repair")
        storage.update_fleet(s.name, status=status, detail=s.diag.title,
                             board=s.diag.board_text, report=s.report_path)
        self.app.show("result")

    def back(self):
        return ("Back", not self.bar.running)

    def go_back(self):
        self.app.show("connect")


class ResultPage(Page):
    step = 1
    title = "Diagnosis."

    def build(self):
        self.g = bento(self, 3)
        self.g.pack(fill="both", expand=True)

    def on_show(self):
        for w in self.g.winfo_children():
            w.destroy()
        s, d = self.app.session, self.app.session.diag
        self.app.sub.config(text=f"{s.name}  ·  {s.port.device}")

        verdict = place(T.Card(self.g, pad=30), 0, 0, colspan=2)
        v = verdict.inner
        row = tk.Frame(v, bg=T.CARD)
        row.pack(fill="x")
        T.Glyph(row, d.severity, 44, filled=True).pack(side="left", anchor="n")
        box = tk.Frame(row, bg=T.CARD)
        box.pack(side="left", padx=T.px(18), fill="x")
        T.GradientLabel(box, d.title, 20, T.SEVERITY_GRAD[d.severity], bg=T.CARD).pack(anchor="w")
        T.label(box, d.summary, "body", fg=T.MUTED, wrap=T.px(520)).pack(anchor="w",
                                                                       pady=(T.px(6), 0))

        board = place(T.Card(self.g), 0, 2)
        eyebrow(board.inner, "Board").pack(anchor="w")
        T.label(board.inner, d.board_text, "h3", wrap=T.px(250)).pack(anchor="w",
                                                                    pady=(T.px(6), T.px(4)))
        T.label(board.inner, s.data.get("usb_desc", ""), "small", fg=T.MUTED,
                wrap=T.px(250)).pack(anchor="w")

        drivers = place(T.Card(self.g), 1, 0)
        eyebrow(drivers.inner, "Motor drivers").pack(anchor="w", pady=(0, T.px(10)))
        tests = dx.parse_tmc_tests(s.data["boot"] + s.data["m122"] + s.data.get("reboot", []))
        pills = tk.Frame(drivers.inner, bg=T.CARD)
        pills.pack(anchor="w")
        if tests:
            for i, (axis, st) in enumerate(tests.items()):
                good = st.upper() == "OK"
                T.Pill(pills, f"{axis}  {'OK' if good else st}", T.GREEN if good else T.RED).grid(
                    row=i // 2, column=i % 2, sticky="w", padx=(0, T.px(8)), pady=T.px(3))
        else:
            T.Pill(pills, "Standalone mode" if d.verdict == "HEALTHY" else "No report",
                   T.GREEN if d.verdict == "HEALTHY" else T.FAINT).pack(anchor="w")

        fw = place(T.Card(self.g), 1, 1)
        eyebrow(fw.inner, "Firmware").pack(anchor="w")
        T.label(fw.inner, d.firmware.get("FIRMWARE_NAME", "Unknown"), "h3",
                wrap=T.px(250)).pack(anchor="w", pady=(T.px(6), T.px(4)))
        T.label(fw.inner, d.firmware.get("MACHINE_TYPE", ""), "small", fg=T.MUTED).pack(anchor="w")

        nxt = place(T.Card(self.g), 1, 2)
        eyebrow(nxt.inner, "Next step", T.CYAN).pack(anchor="w")
        if d.flash_helps:
            title = TARGET_INFO.get(d.recommended, ("Choose your board",))[0]
            T.label(nxt.inner, f"Install {title} firmware" if d.recommended else
                    "Install firmware for your board", "h3", wrap=T.px(250)).pack(
                anchor="w", pady=(T.px(6), T.px(4)))
            T.label(nxt.inner, "You'll need a microSD card and a card reader.", "small",
                    fg=T.MUTED, wrap=T.px(250)).pack(anchor="w")
        else:
            T.label(nxt.inner, "Nothing to install", "h3").pack(anchor="w", pady=(T.px(6), 0))

        det = place(T.Card(self.g), 2, 0, colspan=3)
        top = tk.Frame(det.inner, bg=T.CARD)
        top.pack(fill="x", pady=(0, T.px(8)))
        T.label(top, "Details", "h3").pack(side="left")
        T.Button(top, "Open reports", self.open_reports, style="secondary",
                 height=32).pack(side="right")
        T.Button(top, "Scan again", lambda: self.app.show("scan"), style="secondary",
                 height=32).pack(side="right", padx=T.px(8))
        findings_list(det.inner, [f for f in d.findings if not f[1].startswith("Driver ")][:6],
                      T.px(880))

    def open_reports(self):
        path = os.path.join(storage.data_dir(), "reports")
        if os.name == "nt":
            os.startfile(path)  # opens Explorer on our own folder

    def back(self):
        return ("Back", True)

    def go_back(self):
        self.app.show("connect")

    def next(self):
        return ("Repair this printer", True) if self.app.session.diag.flash_helps else ("Done", True)

    def go_next(self):
        self.app.show("board" if self.app.session.diag.flash_helps else "home")


class BoardPage(Page):
    step = 2
    title = "Choose the firmware."
    subtitle = "Pick the board inside this printer. The best match is already selected."

    def build(self):
        g = bento(self, 3)
        g.pack(fill="both", expand=True)
        self.options = place(T.Card(g), 0, 0, colspan=2)
        help_ = place(T.Card(g), 0, 2)
        eyebrow(help_.inner, "How to check", T.CYAN).pack(anchor="w")
        self.detected = T.label(help_.inner, "", "h3", wrap=T.px(260))
        self.detected.pack(anchor="w", pady=(T.px(6), T.px(10)))
        T.label(help_.inner, "Switch the printer off and unplug it. The main board sits in the "
                             "base, and its version (for example V4.2.2) is printed on it.\n\n"
                             "Not sure? Keep the suggestion. The last step tests the motors and "
                             "tells you if the other version is needed.", "small", fg=T.MUTED,
                wrap=T.px(260)).pack(anchor="w")
        self.choice = tk.StringVar()

    def on_show(self):
        s, d = self.app.session, self.app.session.diag
        for w in self.options.inner.winfo_children():
            w.destroy()
        self.detected.config(text=f"Detected: {d.board_text}")
        self.choice.set(s.target or d.recommended or (d.candidates[0] if d.candidates else ""))
        available = flasher.load_manifest().get("images", {})
        for t in d.candidates:
            title, desc = TARGET_INFO[t]
            if available and t not in available:
                desc += " (Not included in this build.)"
            T.OptionCard(self.options.inner, title, desc, self.choice, t,
                         badge="Recommended" if t == d.recommended else None, width=T.px(600),
                         command=self.app.refresh_actions).pack(fill="x", pady=T.px(5))

    def back(self):
        return ("Back", True)

    def go_back(self):
        self.app.show("result")

    def next(self):
        return ("Continue", bool(self.choice.get()))

    def go_next(self):
        self.app.session.target = self.choice.get()
        self.app.show("card")


class CardPage(Page):
    step = 3
    title = "Prepare the SD card."
    subtitle = "Put a microSD card into this PC's card reader."

    def build(self):
        g = bento(self, 3)
        g.pack(fill="both", expand=True)
        main = place(T.Card(g), 0, 0, colspan=2)
        top = tk.Frame(main.inner, bg=T.CARD)
        top.pack(fill="x", pady=(0, T.px(12)))
        T.label(top, "Choose the card", "h3").pack(side="left")
        T.Button(top, "Refresh", self.refresh, style="secondary", height=34).pack(side="right")
        self.drives_box = tk.Frame(main.inner, bg=T.CARD)
        self.drives_box.pack(fill="x")
        self.notes = tk.Frame(main.inner, bg=T.CARD)
        self.notes.pack(fill="x", pady=(T.px(10), 0))
        act = tk.Frame(main.inner, bg=T.CARD)
        act.pack(fill="x", pady=(T.px(16), 0))
        self.write_btn = T.Button(act, "Write firmware", self.write)
        self.write_btn.pack(side="left")
        self.result = T.label(act, "", "body", wrap=T.px(400))
        self.result.pack(side="left", padx=T.px(16))
        self.drive_var = tk.StringVar()
        self.drives = {}

        req = place(T.Card(g), 0, 2)
        eyebrow(req.inner, "Card requirements").pack(anchor="w", pady=(0, T.px(10)))
        for kind, text in (("ok", "microSD, 8 to 16 GB"), ("ok", "Formatted as FAT32"),
                           ("ok", "Old firmware files are removed for you"),
                           ("info", "The file gets a new name every time, because Creality "
                                    "boards skip names they've already installed")):
            row = tk.Frame(req.inner, bg=T.CARD)
            row.pack(fill="x", pady=T.px(4))
            T.Glyph(row, kind, 20).pack(side="left", anchor="n")
            T.label(row, text, "small", fg=T.MUTED, wrap=T.px(230)).pack(side="left",
                                                                         padx=T.px(10))

    def on_show(self):
        self.app.session.written = None
        self.result.config(text="")
        self.refresh()

    def refresh(self):
        for w in self.drives_box.winfo_children():
            w.destroy()
        s = self.app.session
        if target_family(s.target) == "creality_avr":
            self.drives = {}
            T.label(self.drives_box, "1.1.x boards can't be flashed from an SD card. They need a "
                    "USB upload, which this version doesn't do yet.", "body", fg=T.ORANGE,
                    wrap=T.px(560)).pack(anchor="w")
            self.refresh_notes()
            return
        self.drives = {d.root: d for d in flasher.list_drives()}
        if not self.drives:
            self.drive_var.set("")
            T.label(self.drives_box, "No SD card found. Insert one and click Refresh.", "body",
                    fg=T.ORANGE).pack(anchor="w")
        else:
            if self.drive_var.get() not in self.drives:
                self.drive_var.set(next(iter(self.drives)))
            for root, d in self.drives.items():
                T.OptionCard(self.drives_box, d.label or "Removable disk", d.display,
                             self.drive_var, root, width=T.px(600),
                             command=self.refresh_notes).pack(fill="x", pady=T.px(5))
        self.refresh_notes()

    def refresh_notes(self):
        for w in self.notes.winfo_children():
            w.destroy()
        s = self.app.session
        d = self.drives.get(self.drive_var.get())
        notes = []
        if d:
            notes += [("warn", w) for w in flasher.card_warnings(d)]
            old = flasher.old_firmware_files(d)
            if old:
                notes.append(("info", "Will delete old firmware: " + ", ".join(old)))
        has_fw = bool(flasher.firmware_path(s.target))
        if not has_fw and target_family(s.target) != "creality_avr":
            notes.append(("error", "This copy of Sobolak Repair doesn't include that firmware. "
                                   "Download the full release."))
        findings_list(self.notes, notes, T.px(540))
        self.write_btn.update_button(enabled=bool(d) and has_fw)
        self.app.refresh_actions()

    def write(self):
        s = self.app.session
        drive = self.drives[self.drive_var.get()]
        self.write_btn.update_button(enabled=False)
        self.result.config(text="Writing...", fg=T.MUTED)

        def done(name, error):
            if error:
                self.result.config(text=f"Couldn't write the card: {error}", fg=T.RED)
                self.write_btn.update_button(enabled=True)
                return
            s.written = name
            self.result.config(text=f"Wrote {name} and verified it. Eject the card.", fg=T.GREEN)
            storage.update_fleet(s.name, status="waiting",
                                 detail=f"{TARGET_INFO[s.target][0]} firmware on SD card")
            self.app.refresh_actions()

        self.app.run_bg(lambda log: flasher.write_firmware(drive, s.target,
                                                           target_family(s.target)), done)

    def back(self):
        return ("Back", True)

    def go_back(self):
        self.app.show("board")

    def next(self):
        return ("Continue", bool(self.app.session.written))

    def go_next(self):
        self.app.show("install")


class InstallPage(Page):
    step = 4
    title = "Install on the printer."
    subtitle = "Tick each step as you go."

    def build(self):
        g = bento(self, 3)
        g.pack(fill="both", expand=True)
        self.steps = place(T.Card(g, pad=30), 0, 0, colspan=2)
        info = place(T.Card(g), 0, 2)
        eyebrow(info.inner, "Good to know", T.CYAN).pack(anchor="w")
        self.note = T.label(info.inner, "", "small", fg=T.MUTED, wrap=T.px(260))
        self.note.pack(anchor="w", pady=(T.px(8), 0))

    def on_show(self):
        for w in self.steps.inner.winfo_children():
            w.destroy()
        s = self.app.session
        steps = ["Eject the SD card from this PC",
                 "Switch the printer off",
                 "Put the card in the printer's slot, on the base next to the USB port",
                 "Switch the printer on and wait one minute. The screen can stay blank while "
                 "it updates",
                 "The screen shows its normal status page again"]
        self.vars = [tk.BooleanVar(value=False) for _ in steps]
        for i, (text, var) in enumerate(zip(steps, self.vars)):
            T.CheckRow(self.steps.inner, text, var, self.app.refresh_actions,
                       width=T.px(600)).pack(anchor="w", pady=T.px(3))
        btt = target_family(s.target) == "btt"
        self.note.config(text=(
            "The printer gives no 'done' signal, so the next step scans it to make sure.\n\n"
            + ("This board renames firmware.bin to FIRMWARE.CUR once it's installed." if btt else
               f"Leave {s.written} on the card. It's harmless; Creality boards skip a name "
               "they've already installed.")))
        self.app.refresh_actions()

    def back(self):
        return ("Back", True)

    def go_back(self):
        self.app.show("card")

    def next(self):
        return ("Check the printer", all(v.get() for v in getattr(self, "vars", [])))

    def go_next(self):
        self.app.show("verify")


class VerifyPage(Page):
    step = 5
    title = "Checking the repair."
    subtitle = "Scanning again to confirm the new firmware is running."

    def build(self):
        self.g = bento(self, 3)
        self.g.pack(fill="both", expand=True)
        self.head = place(T.Card(self.g, pad=30), 0, 0, colspan=2)
        h = self.head.inner
        row = tk.Frame(h, bg=T.CARD)
        row.pack(fill="x")
        self.glyph = T.Glyph(row, "info", 44, filled=True)
        self.glyph.pack(side="left", anchor="n")
        box = tk.Frame(row, bg=T.CARD)
        box.pack(side="left", padx=T.px(18), fill="x")
        self.verdict = T.GradientLabel(box, "Scanning", 20, T.GRAD_BLUE, bg=T.CARD)
        self.verdict.pack(anchor="w")
        self.summary = T.label(box, "", "body", fg=T.MUTED, wrap=T.px(500))
        self.summary.pack(anchor="w", pady=(T.px(6), 0))
        self.bar = T.Progress(h)
        self.bar.pack(fill="x", pady=(T.px(20), 0))

        ring = place(T.Card(self.g), 0, 2)
        eyebrow(ring.inner, "Printer").pack(anchor="w")
        self.name_lbl = T.label(ring.inner, "", "h3")
        self.name_lbl.pack(anchor="w", pady=(T.px(6), T.px(4)))
        self.fw_lbl = T.label(ring.inner, "", "small", fg=T.MUTED, wrap=T.px(250))
        self.fw_lbl.pack(anchor="w")

        self.tools = tk.Frame(self.g, bg=T.BG)
        self.tools.grid(row=1, column=0, columnspan=3, sticky="nsew")
        for c in range(3):
            self.tools.columnconfigure(c, weight=1, uniform="col")
        self.success = False

    def on_show(self):
        s = self.app.session
        self.name_lbl.config(text=s.name)
        self.fw_lbl.config(text=f"Installed: {TARGET_INFO[s.target][0]} ({s.written})")
        self.rescan()

    def rescan(self):
        s = self.app.session
        for w in self.tools.winfo_children():
            w.destroy()
        self.verdict.set("Scanning", T.GRAD_BLUE)
        self.summary.config(text="")
        self.glyph.set("info")
        self.bar.pack(fill="x", pady=(T.px(20), 0))
        self.bar.start_indeterminate()
        ports = printer.find_ports()
        # The COM number usually stays the same; otherwise take the first likely printer.
        s.port = next((p for p in ports if p.device == s.port.device), None) or \
            next((p for p in ports if p.likely_printer), s.port)
        port = s.port
        self.app.run_bg(lambda log: printer.scan(port, log=lambda m: None), self.done)
        self.app.refresh_actions()

    def done(self, data, error):
        self.bar.stop()
        self.bar.pack_forget()
        s = self.app.session
        if error:
            self.verdict.set("Scan failed", T.GRAD_RED)
            self.summary.config(text=error)
            self.glyph.set("error")
            self._retry_tools()
            return
        after = dx.diagnose(data)
        ok, msg = dx.verify(s.before, after)
        self.success = ok
        s.data, s.diag = data, after
        s.report_path = storage.save_report(s.name, storage.format_report(
            s.name, data, after, [f"Installed: {s.target} as {s.written}"]))
        self.glyph.set("ok" if ok else "error")
        self.verdict.set("Repaired" if ok else "Not fixed yet", T.GRAD_GREEN if ok else T.GRAD_RED)
        self.summary.config(text=msg)
        storage.update_fleet(s.name, status="repaired" if ok else "needs repair",
                             detail=(f"{TARGET_INFO[s.target][0]} firmware installed" if ok
                                     else after.title), report=s.report_path)
        if ok:
            self._finish_tools()
        else:
            self._retry_tools()

    def _retry_tools(self):
        card = place(T.Card(self.tools), 0, 0, colspan=3)
        T.label(card.inner, "What to try", "h3").pack(anchor="w", pady=(0, T.px(10)))
        row = tk.Frame(card.inner, bg=T.CARD)
        row.pack(anchor="w")
        T.Button(row, "Scan again", self.rescan, style="secondary").pack(side="left")
        T.Button(row, "Redo SD card", lambda: self.app.show("card"),
                 style="secondary").pack(side="left", padx=T.px(10))
        self.app.refresh_actions()

    def _finish_tools(self):
        reset = place(T.Card(self.tools), 0, 0)
        eyebrow(reset.inner, "Recommended").pack(anchor="w")
        T.label(reset.inner, "Reset settings", "h3").pack(anchor="w", pady=(T.px(6), T.px(4)))
        T.label(reset.inner, "Clears values saved by the old firmware.", "small", fg=T.MUTED,
                wrap=T.px(250)).pack(anchor="w", pady=(0, T.px(14)))
        self.reset_msg = T.label(reset.inner, "", "small", fg=T.MUTED, wrap=T.px(250))
        T.Button(reset.inner, "Reset", self.reset, style="secondary", height=36).pack(anchor="w")
        self.reset_msg.pack(anchor="w", pady=(T.px(10), 0))

        motor = place(T.Card(self.tools), 0, 1, colspan=2)
        eyebrow(motor.inner, "Motor test").pack(anchor="w")
        T.label(motor.inner, "Check the motors move", "h3").pack(anchor="w",
                                                                 pady=(T.px(6), T.px(4)))
        T.label(motor.inner, "Push the print head to the middle by hand, then click Test. It "
                             "should glide about 1 cm.", "small", fg=T.MUTED,
                wrap=T.px(520)).pack(anchor="w", pady=(0, T.px(14)))
        self.motor_row = tk.Frame(motor.inner, bg=T.CARD)
        self.motor_row.pack(anchor="w")
        T.Button(self.motor_row, "Test", self.motor, style="secondary", height=36).pack(side="left")
        self.motor_msg = T.label(motor.inner, "", "small", fg=T.MUTED, wrap=T.px(520))
        self.motor_msg.pack(anchor="w", pady=(T.px(10), 0))
        self.app.refresh_actions()

    def reset(self):
        s = self.app.session
        self.reset_msg.config(text="Resetting...", fg=T.MUTED)
        self.app.run_bg(lambda log: printer.reset_settings(s.port, s.data["baud"]),
                        lambda r, e: self.reset_msg.config(
                            text=f"Couldn't reset: {e}" if e else "Defaults loaded and saved.",
                            fg=T.RED if e else T.GREEN))

    def motor(self):
        s = self.app.session
        self.motor_msg.config(text="Moving the X axis 10 mm...", fg=T.MUTED)

        def done(r, e):
            if e:
                self.motor_msg.config(text=f"Couldn't run the test: {e}", fg=T.RED)
                return
            for w in self.motor_row.winfo_children():
                w.destroy()
            self.motor_msg.config(text="Did the print head glide about 1 cm?", fg=T.TEXT)
            T.Button(self.motor_row, "Yes", self.motor_ok, height=36).pack(side="left")
            T.Button(self.motor_row, "No, it buzzed or stayed put", self.motor_bad,
                     style="secondary", height=36).pack(side="left", padx=T.px(10))

        self.app.run_bg(lambda log: printer.movement_test(s.port, s.data["baud"]), done)

    def motor_ok(self):
        for w in self.motor_row.winfo_children():
            w.destroy()
        self.motor_msg.config(text="All good. This printer is ready to print.", fg=T.GREEN)

    def motor_bad(self):
        s = self.app.session
        for w in self.motor_row.winfo_children():
            w.destroy()
        other = {"creality_v422": "creality_v427", "creality_v422_bltouch": "creality_v427",
                 "creality_v427": "creality_v422"}.get(s.target)
        if not other:
            self.motor_msg.config(text="Check that axis's motor cable. If it still won't move, "
                                       "save the report and contact Sobolak Technologies.",
                                  fg=T.ORANGE)
            return
        name = TARGET_INFO[other][0]
        self.motor_msg.config(text=f"The board is probably a {name}. Install that firmware "
                                   "instead; it only takes another minute.", fg=T.ORANGE)

        def switch():
            s.target = other
            self.app.show("card")

        T.Button(self.motor_row, f"Install {name}", switch, height=36).pack(side="left")

    def back(self):
        return ("Back", not self.bar.running)

    def go_back(self):
        self.app.show("install")

    def next(self):
        return ("Finish", not self.bar.running)

    def go_next(self):
        self.app.show("home")


# ==========================================================================
# Main window
# ==========================================================================

class App:
    def __init__(self, root):
        self.root = root
        T.init(root)
        root.title(APP_NAME)
        root.configure(bg=T.BG)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h = min(T.px(1180), sw - 40), min(T.px(840), sh - 90)
        root.minsize(min(T.px(980), sw - 40), min(T.px(600), sh - 90))
        root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
        ico = T.resource("assets", "sobolak.ico")
        if os.name == "nt" and os.path.exists(ico):
            root.iconbitmap(default=ico)
        root.update_idletasks()
        T.dark_title_bar(root)

        self.session = Session("Printer 1")
        self.jobs = queue.Queue()

        # Top bar: brand on the left, step tracker on the right.
        top = tk.Frame(root, bg=T.BG, padx=T.px(40), pady=T.px(22))
        top.pack(fill="x")
        self._logo = T.logo_image(T.px(34), T.BG)
        tk.Label(top, image=self._logo, bg=T.BG, bd=0).pack(side="left")
        T.label(top, "Sobolak Repair", "brand").pack(side="left", padx=(T.px(12), 0))
        self.tracker = tk.Canvas(top, width=T.px(420), height=T.px(34), bg=T.BG,
                                 highlightthickness=0)
        self.tracker.pack(side="right")

        main = tk.Frame(root, bg=T.BG, padx=T.px(40))
        main.pack(fill="both", expand=True)
        self.eyebrow = T.label(main, "", "tiny", fg=T.CYAN)
        self.eyebrow.pack(anchor="w", pady=(T.px(6), 0))
        self.h1 = T.label(main, "", "h1")
        self.h1.pack(anchor="w", pady=(T.px(2), 0))
        self.sub = T.label(main, "", "body", fg=T.MUTED, wrap=T.px(900))
        self.sub.pack(anchor="w", pady=(T.px(6), T.px(26)))

        bar = tk.Frame(main, bg=T.BG)
        bar.pack(side="bottom", fill="x", pady=(T.px(6), T.px(26)))
        self.next_btn = T.Button(bar, "Next", lambda: self.page.go_next())
        self.next_btn.pack(side="right")
        self.back_btn = T.Button(bar, "Back", lambda: self.page.go_back(), style="ghost")
        self.back_btn.pack(side="right", padx=T.px(10))
        self.footer = T.label(bar, f"{COMPANY}  ·  Version {__version__}", "small", fg=T.FAINT)
        self.footer.pack(side="left")

        self.scroll = T.ScrollArea(main)
        self.scroll.pack(fill="both", expand=True)
        self.pages = {name: cls(self) for name, cls in (
            ("home", HomePage), ("connect", ConnectPage), ("scan", ScanPage),
            ("result", ResultPage), ("board", BoardPage), ("card", CardPage),
            ("install", InstallPage), ("verify", VerifyPage))}
        self.page = None
        root.after(50, self._poll)
        self.show("home")

    def show(self, name):
        if self.page:
            self.page.pack_forget()
        self.page = self.pages[name]
        step = self.page.step
        self.eyebrow.config(text=f"STEP {step + 1} OF {len(STEPS)}  ·  {STEPS[step].upper()}"
                            if step is not None else "SOBOLAK TECHNOLOGIES")
        self.h1.config(text=self.page.title)
        self.sub.config(text=self.page.subtitle)
        self.page.pack(fill="both", expand=True, padx=(0, T.px(6)))
        self.page.on_show()
        self.scroll.top()
        self.draw_tracker()
        self.refresh_actions()

    def refresh_actions(self):
        if not self.page:
            return
        # Re-pack in a fixed order so the primary button always sits on the far right.
        self.next_btn.pack_forget()
        self.back_btn.pack_forget()
        for btn, spec in ((self.next_btn, self.page.next()), (self.back_btn, self.page.back())):
            if spec is not None:
                btn.update_button(text=spec[0], enabled=spec[1])
                btn.pack(side="right", padx=(0, T.px(10) if btn is self.back_btn else 0))
        if self.page.step is not None:
            self.footer.config(text=f"Repairing {self.session.name}")
        else:
            self.footer.config(text=f"{COMPANY}  ·  Version {__version__}")

    def draw_tracker(self):
        c = self.tracker
        c.delete("all")
        step = self.page.step if self.page else None
        if step is None:
            return
        w, seg_h, gap = T.px(420), T.px(6), T.px(6)
        seg_w = (w - gap * (len(STEPS) - 1)) // len(STEPS)
        self._track = []
        for i, name in enumerate(STEPS):
            x = i * (seg_w + gap)
            if i <= step:
                img = T.surface(seg_w, seg_h, seg_h // 2, None, None, T.BG,
                                grad=T.GRAD_BLUE if i < step else (T.BLUE, T.PURPLE))
            else:
                img = T.surface(seg_w, seg_h, seg_h // 2, T.RAISED, None, T.BG, sheen=False)
            self._track.append(img)
            c.create_image(x, T.px(4), image=img, anchor="nw")
            c.create_text(x, T.px(24), text=name, anchor="w", font=T.FONTS["tiny"],
                          fill=T.TEXT if i == step else (T.MUTED if i < step else T.FAINT))

    # ---- background work -------------------------------------------------
    def run_bg(self, fn, on_done, log=None):
        """Run fn(log) on a worker thread; on_done(result, error) runs on the UI thread."""
        def post_log(msg):
            if log:
                self.jobs.put((log, (msg,)))

        def worker():
            try:
                result, error = fn(post_log), None
            except Exception as e:  # show any failure in the UI instead of crashing
                traceback.print_exc()
                result, error = None, str(e) or e.__class__.__name__
            self.jobs.put((self._finish, (on_done, result, error)))

        threading.Thread(target=worker, daemon=True).start()

    def _finish(self, on_done, result, error):
        on_done(result, error)
        self.refresh_actions()

    def _poll(self):
        try:
            while True:
                fn, args = self.jobs.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.root.after(30, self._poll)


def main():
    if os.name == "nt":
        try:  # crisp text on high-DPI screens; the theme scales its images to match
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "SobolakTechnologies.SobolakRepair")
        except Exception:
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
