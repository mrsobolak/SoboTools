"""Sobolak Technologies design system for tkinter.

Immersive dark canvas, bento cards with frosted-glass edges, continuous-curve
("squircle") corners, gradient accents and animated hover states.

Tk can only draw jagged shapes, so every surface is rendered with Pillow at 3x
and downsampled for smooth anti-aliased edges. Results are cached by size/state.
"""

import math
import os
import sys
import tkinter as tk
from tkinter import font as tkfont

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageTk

# ---- palette -------------------------------------------------------------
BG = "#000000"          # canvas
CARD = "#1C1C1E"        # glass card
CARD_DEEP = "#121214"
RAISED = "#2C2C2E"      # controls on cards
RAISED_HOVER = "#3A3A3C"
BORDER = "#2C2C2E"
BORDER_HOVER = "#48484A"
TEXT = "#FFFFFF"
MUTED = "#8E8E93"
FAINT = "#5A5A60"
BLUE = "#0A84FF"
CYAN = "#64D2FF"
PINK = "#FF375F"
PURPLE = "#BF5AF2"
GREEN = "#30D158"
ORANGE = "#FF9F0A"
RED = "#FF453A"

GRAD_BLUE = (BLUE, CYAN)
GRAD_SUNSET = (PINK, PURPLE)
GRAD_GREEN = (GREEN, CYAN)
GRAD_RED = (RED, PINK)
GRAD_ORANGE = (ORANGE, PINK)

SEVERITY = {"ok": GREEN, "info": BLUE, "warn": ORANGE, "error": RED}
SEVERITY_GRAD = {"ok": GRAD_GREEN, "info": GRAD_BLUE, "warn": GRAD_ORANGE, "error": GRAD_RED}

SS = 3            # supersampling factor
SCALE = 1.0       # screen DPI / 96, set in init()
FONTS = {}
_cache = {}


def px(v):
    return int(round(v * SCALE))


def resource(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, *parts)


# ---- fonts ---------------------------------------------------------------
FONT_FILES = {
    "regular": ["Inter-Regular.otf"], "medium": ["Inter-Medium.otf"],
    "semibold": ["Inter-SemiBold.otf"], "bold": ["Inter-Bold.otf"],
    "display": ["InterDisplay-Bold.otf"], "display_semi": ["InterDisplay-SemiBold.otf"],
}


def _font_path(weight):
    for name in FONT_FILES[weight]:
        p = resource("assets", "fonts", name)
        if os.path.exists(p):
            return p
    return None


def _register_private_fonts():
    """Make the bundled Inter fonts visible to Tk on Windows without installing them."""
    if os.name != "nt":
        return
    import ctypes
    for files in FONT_FILES.values():
        p = resource("assets", "fonts", files[0])
        if os.path.exists(p):
            ctypes.windll.gdi32.AddFontResourceExW(p, 0x10, 0)  # FR_PRIVATE


def init(root):
    global SCALE
    SCALE = max(1.0, root.winfo_fpixels("1i") / 96.0)
    _register_private_fonts()
    families = set(tkfont.families(root))

    def pick(options, size, weight="normal"):
        for fam, w in options:
            if fam in families:
                return tkfont.Font(root, family=fam, size=size, weight=w)
        return tkfont.Font(root, family="TkDefaultFont", size=size, weight=weight)

    text = [("SF Pro Text", "normal"), ("Inter", "normal"), ("Segoe UI", "normal")]
    medium = [("SF Pro Text", "bold"), ("Inter Medium", "normal"), ("Inter", "normal"),
              ("Segoe UI Semibold", "normal")]
    semi = [("SF Pro Text", "bold"), ("Inter SemiBold", "normal"), ("Inter", "bold"),
            ("Segoe UI Semibold", "normal")]
    display = [("SF Pro Display", "bold"), ("Inter Display", "bold"), ("Inter", "bold"),
               ("Segoe UI", "bold")]
    FONTS.update(
        body=pick(text, 11), small=pick(text, 10), tiny=pick(medium, 9),
        label=pick(medium, 10), button=pick(semi, 11), h3=pick(semi, 13),
        h2=pick(display, 17), h1=pick(display, 30), brand=pick(semi, 13),
        mono=pick([("SF Mono", "normal"), ("Cascadia Mono", "normal"), ("Consolas", "normal"),
                   ("DejaVu Sans Mono", "normal")], 10),
    )


def dark_title_bar(root):
    """Windows 10 20H1+ / 11: dark window title bar to match the canvas."""
    if os.name != "nt":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        on = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE, then its pre-20H1 id
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), 4) == 0:
                break
        black = ctypes.c_int(0x000000)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(black), 4)  # caption colour (Win 11)
    except Exception:
        pass


# ---- colour + geometry helpers ------------------------------------------
def rgb(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def mix(a, b, t):
    pa, pb = rgb(a), rgb(b)
    return "#%02X%02X%02X" % tuple(round(x + (y - x) * t) for x, y in zip(pa, pb))


def squircle_points(x0, y0, x1, y1, r, n=5.0, steps=18):
    """Continuous-curvature rounded rectangle (superellipse corners), clockwise."""
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    e = 2.0 / n
    pts = []
    corners = [
        (x1 - r, y0 + r, lambda s, c: (s, -c)),   # top-right
        (x1 - r, y1 - r, lambda s, c: (c, s)),    # bottom-right
        (x0 + r, y1 - r, lambda s, c: (-s, c)),   # bottom-left
        (x0 + r, y0 + r, lambda s, c: (-c, -s)),  # top-left
    ]
    for cx, cy, f in corners:
        for i in range(steps + 1):
            t = i / steps * math.pi / 2
            s, c = abs(math.sin(t)) ** e, abs(math.cos(t)) ** e
            dx, dy = f(s, c)
            pts.append((cx + dx * r, cy + dy * r))
    return pts


def _mask(w, h, r, inset=0):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).polygon(squircle_points(inset, inset, w - inset, h - inset,
                                              max(0, r - inset)), fill=255)
    return m


def _gradient(w, h, colors, angle=0):
    """Two-colour linear gradient. angle 0 = left->right, 90 = top->bottom."""
    # Rotate an oversized ramp and take the middle, so no blank corners creep in.
    g = Image.linear_gradient("L").resize((512, 512)).rotate(90 - angle)
    g = g.crop((128, 128, 384, 384)).resize((w, h), Image.BILINEAR)
    return Image.composite(Image.new("RGB", (w, h), rgb(colors[1])),
                           Image.new("RGB", (w, h), rgb(colors[0])), g)


def surface(w, h, r, fill=CARD, border=BORDER, bg=BG, grad=None, border_grad=None, glow=None,
            sheen=True, border_w=1):
    """Render a rounded panel to a PhotoImage. Sizes are in screen pixels."""
    key = ("s", w, h, r, fill, border, bg, grad, border_grad, glow, sheen, border_w)
    if key in _cache:
        return _cache[key]
    W, H, R = w * SS, h * SS, r * SS
    out = Image.new("RGB", (W, H), rgb(bg))
    body = _gradient(W, H, grad, 35) if grad else Image.new("RGB", (W, H), rgb(fill))
    if glow:
        layer = Image.new("RGB", (W, H), (0, 0, 0))
        d = ImageDraw.Draw(layer)
        for gx, gy, gr, gc in glow:  # fractions of size, colour
            cx, cy, rr = gx * W, gy * H, gr * max(W, H)
            d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=rgb(gc))
        layer = layer.filter(ImageFilter.GaussianBlur(max(W, H) * .12))
        body = ImageChops.screen(body, layer)
    if sheen and not grad:
        # faint light falling on the top edge, like glass catching a highlight
        top = Image.new("RGB", (W, H), rgb(mix(fill, "#FFFFFF", .05)))
        fade = Image.linear_gradient("L").resize((W, H)).point(lambda v: 255 if v > 60 else
                                                                int(v * 255 / 60))
        body = Image.composite(body, top, fade)
    bw = max(1, round(border_w * SS * SCALE))
    if border or border_grad:
        edge = _gradient(W, H, border_grad, 0) if border_grad else Image.new("RGB", (W, H),
                                                                             rgb(border))
        out.paste(edge, (0, 0), _mask(W, H, R))
        out.paste(body, (0, 0), _mask(W, H, R, bw))
    else:
        out.paste(body, (0, 0), _mask(W, H, R))
    img = ImageTk.PhotoImage(out.resize((w, h), Image.LANCZOS))
    _cache[key] = img
    return img


def text_image(text, size_pt, colors, bg, weight="display"):
    """Gradient-filled text (Tk can't do it). Returns PhotoImage."""
    key = ("t", text, size_pt, colors, bg, weight, SCALE)
    if key in _cache:
        return _cache[key]
    size = int(size_pt * SCALE * 96 / 72 * SS)
    path = _font_path(weight)
    try:
        font = ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
    except (OSError, TypeError):
        font = ImageFont.load_default()
    x0, y0, x1, y1 = font.getbbox(text)
    W, H = x1 - x0 + 4 * SS, int((y1 + size * .28))
    W += (-W) % SS
    H += (-H) % SS
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).text((-x0 + 2 * SS, 0), text, font=font, fill=255)
    fill = _gradient(W, H, colors, 0) if isinstance(colors, tuple) else \
        Image.new("RGB", (W, H), rgb(colors))
    out = Image.new("RGB", (W, H), rgb(bg))
    out.paste(fill, (0, 0), mask)
    img = ImageTk.PhotoImage(out.resize((W // SS, H // SS), Image.LANCZOS))
    _cache[key] = img
    return img


def glyph_image(kind, d, color=None, bg=CARD, filled=False):
    """Round status glyph: ok, error, warn, info, question, radio, radio_on, dot, or a digit."""
    key = ("g", kind, d, color, bg, filled, SCALE)
    if key in _cache:
        return _cache[key]
    color = color or SEVERITY.get(kind, BLUE)
    D = d * SS
    im = Image.new("RGB", (D, D), rgb(bg))
    dr = ImageDraw.Draw(im)
    lw = max(SS, int(D * .085))
    if kind in ("radio", "radio_on"):
        dr.ellipse((lw, lw, D - lw, D - lw), outline=rgb(color if kind == "radio_on" else FAINT),
                   width=lw)
        if kind == "radio_on":
            c = D * .27
            dr.ellipse((D / 2 - c, D / 2 - c, D / 2 + c, D / 2 + c), fill=rgb(color))
    elif kind == "dot":
        dr.ellipse((D * .2, D * .2, D * .8, D * .8), fill=rgb(color))
    else:
        if filled:
            dr.ellipse((0, 0, D - 1, D - 1), fill=rgb(color))
            ink = rgb("#FFFFFF")
        else:
            dr.ellipse((0, 0, D - 1, D - 1), fill=rgb(mix(bg, color, .18)))
            ink = rgb(color)
        w = max(SS, int(D * .1))
        if kind == "ok":
            dr.line([(D * .29, D * .52), (D * .44, D * .67), (D * .72, D * .36)], fill=ink,
                    width=w, joint="curve")
        elif kind == "error":
            a, b = D * .34, D * .66
            dr.line([(a, a), (b, b)], fill=ink, width=w)
            dr.line([(a, b), (b, a)], fill=ink, width=w)
        elif kind == "empty":
            pass
        else:
            ch = {"warn": "!", "info": "i", "question": "?"}.get(kind, str(kind))
            path = _font_path("bold")
            f = ImageFont.truetype(path, int(D * .56)) if path else ImageFont.load_default()
            dr.text((D / 2, D / 2), ch, font=f, fill=ink, anchor="mm")
    img = ImageTk.PhotoImage(im.resize((d, d), Image.LANCZOS))
    _cache[key] = img
    return img


def logo_image(size, bg):
    key = ("logo", size, bg)
    if key in _cache:
        return _cache[key]
    S = size * SS
    tile = _gradient(S, S, (BLUE, PURPLE), 45)
    out = Image.new("RGB", (S, S), rgb(bg))
    out.paste(tile, (0, 0), _mask(S, S, int(S * .3)))
    path = _font_path("display")
    f = ImageFont.truetype(path, int(S * .58)) if path else ImageFont.load_default()
    ImageDraw.Draw(out).text((S / 2, S / 2 + S * .02), "S", font=f, fill=(255, 255, 255),
                             anchor="mm")
    img = ImageTk.PhotoImage(out.resize((size, size), Image.LANCZOS))
    _cache[key] = img
    return img


def wrap(text, font, width):
    lines = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            trial = (cur + " " + word).strip()
            if font.measure(trial) > width and cur:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        lines.append(cur)
    return lines


# ---- animation -----------------------------------------------------------
class Hover:
    """Eases a 0..1 hover value over ~120 ms and calls redraw() on each frame."""

    def __init__(self, widget, redraw):
        self.w, self.redraw = widget, redraw
        self.t, self.target, self.job = 0.0, 0.0, None
        widget.bind("<Enter>", lambda e: self.to(1.0), add="+")
        widget.bind("<Leave>", lambda e: self.to(0.0), add="+")

    def to(self, target):
        self.target = target
        if self.job is None:
            self._step()

    def _step(self):
        diff = self.target - self.t
        if abs(diff) < .01:
            self.t, self.job = self.target, None
            self.redraw()
            return
        self.t += diff * .45
        self.redraw()
        self.job = self.w.after(16, self._step)

    @property
    def level(self):
        return round(self.t * 4) / 4  # quantised so rendered images can be cached


# ---- widgets -------------------------------------------------------------
class Card(tk.Canvas):
    """Bento card: rounded glass surface hosting a normal frame (`.inner`)."""

    def __init__(self, master, pad=24, radius=18, fill=CARD, glow=None, grad=None, bg=None):
        bg = bg or master.cget("bg")
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, width=40, height=40)
        self.pad, self.radius, self.fill, self.glow, self.grad, self.bgc = \
            px(pad), px(radius), fill, glow, grad, bg
        self.inner = tk.Frame(self, bg=fill)
        self._win = self.create_window(self.pad, self.pad, window=self.inner, anchor="nw")
        self._img = None
        self.bind("<Configure>", self._resize)
        self.inner.bind("<Configure>", self._fit)

    def _fit(self, _=None):
        need_h = self.inner.winfo_reqheight() + 2 * self.pad
        need_w = self.inner.winfo_reqwidth() + 2 * self.pad
        if int(self.cget("height")) != need_h:
            self.config(height=need_h)
        if int(self.cget("width")) != need_w:
            self.config(width=need_w)

    def _resize(self, e):
        self.itemconfig(self._win, width=max(1, e.width - 2 * self.pad),
                        height=max(1, e.height - 2 * self.pad))
        self._img = surface(e.width, e.height, self.radius, self.fill, BORDER, self.bgc,
                            self.grad, glow=self.glow, sheen=False)
        self.delete("bgimg")
        self.create_image(0, 0, image=self._img, anchor="nw", tags="bgimg")
        self.tag_lower("bgimg")


class Button(tk.Canvas):
    """Capsule button. style: primary (gradient) | secondary | ghost | danger."""

    def __init__(self, master, text, command=None, style="primary", width=None, height=40,
                 bg=None):
        bg = bg or master.cget("bg")
        self.font = FONTS["button"]
        self.h = px(height)
        width = px(width) if width else self.font.measure(text) + px(44)
        super().__init__(master, width=width, height=self.h, bg=bg, highlightthickness=0,
                         cursor="hand2")
        self.text, self.command, self.style, self.bgc, self.w = text, command, style, bg, width
        self.enabled, self.pressed = True, False
        self.hover = Hover(self, self.draw)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.draw()

    def update_button(self, text=None, enabled=None, command=None, style=None):
        if text is not None and text != self.text:
            self.text = text
            self.w = self.font.measure(text) + px(44)
            self.config(width=self.w)
        if enabled is not None:
            self.enabled = enabled
            self.config(cursor="hand2" if enabled else "arrow")
        if command is not None:
            self.command = command
        if style is not None:
            self.style = style
        self.draw()

    def draw(self):
        self.delete("all")
        t = self.hover.level if self.enabled else 0
        r = self.h // 2
        fg = TEXT
        if not self.enabled:
            img = surface(self.w, self.h, r, RAISED, None, self.bgc, sheen=False)
            fg = FAINT
        elif self.style == "primary":
            a, b = GRAD_BLUE
            img = surface(self.w, self.h, r, None, None, self.bgc,
                          grad=(mix(a, "#FFFFFF", t * .14), mix(b, "#FFFFFF", t * .14)))
        elif self.style == "danger":
            img = surface(self.w, self.h, r, None, None, self.bgc,
                          grad=(mix(RED, "#FFFFFF", t * .12), mix(PINK, "#FFFFFF", t * .12)))
        elif self.style == "ghost":
            img = surface(self.w, self.h, r, mix(self.bgc, RAISED, t), None, self.bgc,
                          sheen=False)
            fg = mix(MUTED, TEXT, t)
        else:
            img = surface(self.w, self.h, r, mix(RAISED, RAISED_HOVER, t),
                          mix(BORDER, BORDER_HOVER, t), self.bgc, sheen=False)
        self._img = img
        dy = 1 if self.pressed else 0
        self.create_image(0, dy, image=img, anchor="nw")
        self.create_text(self.w / 2, self.h / 2 + dy, text=self.text, fill=fg, font=self.font)

    def _press(self, _):
        if self.enabled:
            self.pressed = True
            self.draw()

    def _release(self, e):
        was, self.pressed = self.pressed, False
        self.draw()
        if was and self.enabled and self.command and 0 <= e.x <= self.w and 0 <= e.y <= self.h:
            self.command()


class Progress(tk.Canvas):
    """Capsule progress bar with gradient fill; indeterminate mode sweeps a highlight."""

    def __init__(self, master, bg=None, height=6):
        bg = bg or master.cget("bg")
        self.h = px(height)
        super().__init__(master, height=self.h, width=200, bg=bg, highlightthickness=0)
        self.bgc, self.w, self.value, self.job, self.pos = bg, 200, 0.0, None, 0.0
        self.bind("<Configure>", self._resize)

    def _resize(self, e):
        self.w = e.width
        self.draw()

    def draw(self):
        self.delete("all")
        self._imgs = [surface(self.w, self.h, self.h // 2, RAISED, None, self.bgc, sheen=False)]
        self.create_image(0, 0, image=self._imgs[0], anchor="nw")
        if self.job is not None:
            seg = max(self.h * 2, int(self.w * .3))
            img = surface(seg, self.h, self.h // 2, None, None, RAISED, grad=GRAD_BLUE)
            self._imgs.append(img)
            self.create_image(int(self.pos) - seg, 0, image=img, anchor="nw")
        elif self.value > 0:
            fw = max(self.h * 2, int(self.w * self.value))
            img = surface(fw, self.h, self.h // 2, None, None, self.bgc, grad=GRAD_BLUE)
            self._imgs.append(img)
            self.create_image(0, 0, image=img, anchor="nw")

    def set(self, v):
        self.stop()
        self.value = max(0.0, min(1.0, v))
        self.draw()

    def start_indeterminate(self):
        if self.job is None:
            self.job = self.after(16, self._tick)

    def stop(self):
        if self.job is not None:
            self.after_cancel(self.job)
            self.job = None
            self.draw()

    @property
    def running(self):
        return self.job is not None

    def _tick(self):
        self.pos = (self.pos + max(5, self.w / 80)) % (self.w * 1.3)
        self.draw()
        self.job = self.after(16, self._tick)


class CheckRow(tk.Canvas):
    """iOS-style round checkbox with a label; whole row is clickable."""

    def __init__(self, master, text, variable, command=None, width=560, bg=None):
        bg = bg or master.cget("bg")
        self.var, self.command, self.text, self.bgc = variable, command, text, bg
        self.d = px(22)
        lines = wrap(text, FONTS["body"], width - self.d - px(16))
        self.lines = lines
        self.h = max(self.d, len(lines) * FONTS["body"].metrics("linespace")) + px(12)
        super().__init__(master, width=width, height=self.h, bg=bg, highlightthickness=0,
                         cursor="hand2")
        self.hover = Hover(self, self.draw)
        self.bind("<Button-1>", self._click)
        self.var.trace_add("write", lambda *a: self.draw())
        self.draw()

    def _click(self, _):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def draw(self):
        self.delete("all")
        on = bool(self.var.get())
        y = self.h / 2
        if on:
            img = glyph_image("ok", self.d, BLUE, self.bgc, filled=True)
        else:
            img = glyph_image("radio", self.d, mix(FAINT, MUTED, self.hover.level), self.bgc)
        self._img = img
        self.create_image(self.d / 2, y, image=img)
        self.create_text(self.d + px(14), y, text="\n".join(self.lines), anchor="w",
                         fill=MUTED if on else TEXT, font=FONTS["body"])


class OptionCard(tk.Canvas):
    """Selectable bento tile: radio, title, optional badge, description."""

    def __init__(self, master, title, desc, variable, value, badge=None, width=600,
                 command=None, bg=None):
        bg = bg or master.cget("bg")
        self.title, self.desc, self.var, self.value, self.badge = title, desc, variable, value, badge
        self.command, self.bgc, self.w = command, bg, width
        self.lines = wrap(desc, FONTS["small"], width - px(88)) if desc else []
        line_h = FONTS["small"].metrics("linespace")
        self.h = px(64) + len(self.lines) * line_h - (px(10) if not desc else 0)
        super().__init__(master, width=width, height=self.h, bg=bg, highlightthickness=0,
                         cursor="hand2")
        self.hover = Hover(self, self.draw)
        self.bind("<Button-1>", self._click)
        self.bind("<Configure>", self._resize)
        self.var.trace_add("write", lambda *a: self.draw())
        self.draw()

    def _resize(self, e):
        if e.width != self.w:
            self.w = e.width
            self.lines = wrap(self.desc, FONTS["small"], self.w - px(88)) if self.desc else []
            h = px(64) + len(self.lines) * FONTS["small"].metrics("linespace") - \
                (px(10) if not self.desc else 0)
            if h != self.h:
                self.h = h
                self.config(height=h)
            self.draw()

    def _click(self, _):
        self.var.set(self.value)
        if self.command:
            self.command()

    def draw(self):
        self.delete("all")
        on = self.var.get() == self.value
        t = self.hover.level
        fill = mix(CARD, "#1E2A3D", .9) if on else mix(CARD, "#232326", t)
        img = surface(self.w, self.h, px(16), fill, None if on else mix(BORDER, BORDER_HOVER, t),
                      self.bgc, border_grad=GRAD_BLUE if on else None,
                      border_w=1.5 if on else 1)
        self._imgs = [img]
        self.create_image(0, 0, image=img, anchor="nw")
        d = px(20)
        radio = glyph_image("radio_on" if on else "radio", d, BLUE if on else
                            mix(FAINT, MUTED, t), fill)
        self._imgs.append(radio)
        self.create_image(px(24) + d / 2, px(32), image=radio)
        tx = self.create_text(px(60), px(32), text=self.title, anchor="w", fill=TEXT,
                              font=FONTS["h3"])
        if self.badge:
            x = self.bbox(tx)[2] + px(12)
            bw, bh = FONTS["tiny"].measure(self.badge) + px(20), px(22)
            pill = surface(bw, bh, bh // 2, mix(fill, GREEN, .16), None, fill, sheen=False)
            self._imgs.append(pill)
            self.create_image(x, px(32) - bh / 2, image=pill, anchor="nw")
            self.create_text(x + bw / 2, px(32), text=self.badge, fill=GREEN, font=FONTS["tiny"])
        if self.lines:
            self.create_text(px(60), px(48), text="\n".join(self.lines), anchor="nw", fill=MUTED,
                             font=FONTS["small"])


class Field(tk.Canvas):
    """Rounded text entry with a glowing gradient edge when focused."""

    def __init__(self, master, variable, width=280, bg=None):
        bg = bg or master.cget("bg")
        self.w, self.h, self.bgc = px(width), px(44), bg
        super().__init__(master, width=self.w, height=self.h, bg=bg, highlightthickness=0)
        self.focused = False
        self.entry = tk.Entry(self, textvariable=variable, bg=RAISED, fg=TEXT, bd=0, relief="flat",
                              insertbackground=TEXT, font=FONTS["body"], highlightthickness=0)
        self.create_window(px(16), self.h / 2, window=self.entry, anchor="w",
                           width=self.w - px(32))
        self.entry.bind("<FocusIn>", lambda e: self._focus(True))
        self.entry.bind("<FocusOut>", lambda e: self._focus(False))
        self.hover = Hover(self, self.draw)
        self.draw()

    def _focus(self, v):
        self.focused = v
        self.draw()

    def draw(self):
        self.delete("bg")
        img = surface(self.w, self.h, px(12), RAISED,
                      None if self.focused else mix(BORDER, BORDER_HOVER, self.hover.level),
                      self.bgc, border_grad=GRAD_BLUE if self.focused else None,
                      border_w=1.5 if self.focused else 1, sheen=False)
        self._img = img
        self.create_image(0, 0, image=img, anchor="nw", tags="bg")
        self.tag_lower("bg")


class Pill(tk.Canvas):
    """Small status capsule with a coloured dot: e.g. driver 'X  OK'."""

    def __init__(self, master, text, color, bg=None):
        bg = bg or master.cget("bg")
        f = FONTS["label"]
        w, h = f.measure(text) + px(40), px(30)
        super().__init__(master, width=w, height=h, bg=bg, highlightthickness=0)
        self._imgs = [surface(w, h, h // 2, mix(bg, color, .14), None, bg, sheen=False),
                      glyph_image("dot", px(12), color, mix(bg, color, .14))]
        self.create_image(0, 0, image=self._imgs[0], anchor="nw")
        self.create_image(px(17), h / 2, image=self._imgs[1])
        self.create_text(px(28), h / 2, text=text, anchor="w", fill=TEXT, font=f)


class Glyph(tk.Label):
    def __init__(self, master, kind="info", size=28, bg=None, filled=False):
        self.bgc = bg or master.cget("bg")
        self.size, self.filled = px(size), filled
        super().__init__(master, bg=self.bgc, bd=0)
        self.set(kind)

    def set(self, kind, filled=None):
        if filled is not None:
            self.filled = filled
        self._img = glyph_image(kind, self.size, None, self.bgc, self.filled)
        self.config(image=self._img)


class GradientLabel(tk.Label):
    def __init__(self, master, text, size=30, colors=GRAD_BLUE, bg=None, weight="display"):
        self.bgc = bg or master.cget("bg")
        self.size, self.weight = size, weight
        super().__init__(master, bg=self.bgc, bd=0)
        self.set(text, colors)

    def set(self, text, colors=GRAD_BLUE):
        self._img = text_image(text, self.size, colors, self.bgc, self.weight)
        self.config(image=self._img)


class ScrollArea(tk.Frame):
    """Vertical scrolling region with a slim capsule scrollbar that appears only when needed."""

    def __init__(self, master, bg=BG):
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.bar = tk.Canvas(self, width=px(14), bg=bg, highlightthickness=0, bd=0)
        self.bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._update)
        self.canvas.bind("<Configure>", self._update)
        self.bind("<Enter>", self._bind_wheel)
        self.bind("<Leave>", self._unbind_wheel)

    def _bind_wheel(self, _):
        self.bind_all("<MouseWheel>", self._wheel)
        self.bind_all("<Button-4>", lambda e: self._scroll(-1))
        self.bind_all("<Button-5>", lambda e: self._scroll(1))

    def _unbind_wheel(self, _):
        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.unbind_all(ev)

    def _wheel(self, e):
        self._scroll(-1 if e.delta > 0 else 1)

    def _scroll(self, direction):
        if self.body.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(direction * 3, "units")
            self._draw_bar()

    def top(self):
        self.canvas.yview_moveto(0)
        self._draw_bar()

    def _update(self, _=None):
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        h = max(ch, self.body.winfo_reqheight())
        self.canvas.itemconfig(self._win, width=cw, height=h)
        self.canvas.config(scrollregion=(0, 0, cw, h), yscrollincrement=px(12))
        self._draw_bar()

    def _draw_bar(self):
        self.bar.delete("all")
        ch, total = self.canvas.winfo_height(), self.body.winfo_reqheight()
        if total <= ch or ch < 20:
            return
        first, last = self.canvas.yview()
        w = px(6)
        y0, y1 = int(first * ch), max(int(last * ch), int(first * ch) + px(30))
        self._thumb = surface(w, max(w, y1 - y0), w // 2, RAISED_HOVER, None, self.bar.cget("bg"),
                              sheen=False)
        self.bar.create_image(px(4), y0, image=self._thumb, anchor="nw")


def label(master, text="", kind="body", fg=TEXT, wrap=0, bg=None, **kw):
    return tk.Label(master, text=text, font=FONTS[kind], fg=fg, bg=bg or master.cget("bg"),
                    justify="left", anchor="w", wraplength=wrap, bd=0, **kw)


def text_box(master, height=10):
    """Monospace log inside a deep card."""
    card = Card(master, pad=18, fill=CARD_DEEP)
    t = tk.Text(card.inner, height=height, bg=CARD_DEEP, fg=MUTED, insertbackground=TEXT,
                relief="flat", bd=0, font=FONTS["mono"], wrap="word", highlightthickness=0,
                selectbackground="#1E3A66", spacing1=2)
    t.pack(fill="both", expand=True)
    return card, t


def ring_image(d, fraction, colors=GRAD_BLUE, bg=CARD, width=0.12):
    """Activity-style progress ring with a soft glow."""
    key = ("ring", d, round(fraction, 3), colors, bg, width)
    if key in _cache:
        return _cache[key]
    D = d * SS
    lw = int(D * width)
    pad = int(D * .16)
    box = (pad, pad, D - pad, D - pad)
    out = Image.new("RGB", (D, D), rgb(bg))
    ImageDraw.Draw(out).ellipse(box, outline=rgb(mix(bg, "#FFFFFF", .08)), width=lw)
    if fraction > 0:
        arc = Image.new("L", (D, D), 0)
        ad = ImageDraw.Draw(arc)
        end = -90 + 360 * min(fraction, 0.9999)
        ad.arc(box, -90, end, fill=255, width=lw)
        # round caps
        for ang in (-90, end):
            a = math.radians(ang)
            rr = (D - 2 * pad - lw) / 2
            cx, cy = D / 2 + rr * math.cos(a), D / 2 + rr * math.sin(a)
            ad.ellipse((cx - lw / 2, cy - lw / 2, cx + lw / 2, cy + lw / 2), fill=255)
        grad = _gradient(D, D, colors, 45)
        glow = Image.composite(grad, Image.new("RGB", (D, D), (0, 0, 0)),
                               arc.filter(ImageFilter.GaussianBlur(lw * .55)))
        out = ImageChops.screen(out, glow.point(lambda v: int(v * .45)))
        out.paste(grad, (0, 0), arc)
    img = ImageTk.PhotoImage(out.resize((d, d), Image.LANCZOS))
    _cache[key] = img
    return img
