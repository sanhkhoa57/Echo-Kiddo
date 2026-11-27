"""Shared look for the OGK tray dialogs.

Mirrors the parent dashboard in dashboard/static/styles.css (cool grey ground, flat white card
with a hairline border, ink headings, one blue accent, pill buttons) so the child sees one product,
not two. Tone colour only marks the status dot, meters and notes, never a whole header band.
tkinter + Pillow (already required for the tray icon); Pillow draws the anti-aliased pills.
"""
import tkinter as tk
from tkinter import font as tkfont
from typing import Callable, Optional, Tuple

from PIL import Image, ImageDraw, ImageTk

# ---- tokens (same values as the CSS) ----
ACCENT = "#1d6ae5"
ACCENT_DEEP = "#1450b8"
ACCENT_MID = "#4a8af0"
ACCENT_SOFT = "#dbe7fd"
ACCENT_WASH = "#eef4ff"
# The GREEN_* names predate the blue redesign; tray_app.py still uses them for the accent family.
GREEN, GREEN_DEEP, GREEN_MID, GREEN_SOFT, GREEN_WASH = ACCENT, ACCENT_DEEP, ACCENT_MID, ACCENT_SOFT, ACCENT_WASH
GROUND = "#fafafb"
PAPER = "#ffffff"
INK = "#16181d"
INK_2 = "#464b55"
INK_3 = "#686e79"
RULE = "#e7e9ed"
RULE_STRONG = "#cdd2d9"
LOCKED = "#f0f1f4"
RED = "#d92d20"
RED_DEEP = "#b42318"
RED_SOFT = "#fdecea"
AMBER = "#b4690f"          # status dot / button tone for warnings (white text passes 4.5:1)
AMBER_BAR = "#d98a3d"
AMBER_SOFT = "#fbead6"
AMBER_INK = "#8f4f0c"
GOLD_SOFT = "#fdf1d0"

# tone -> (status colour, soft tint used for callouts)
TONES = {
    "ok": (GREEN, GREEN_WASH),
    "warn": (AMBER, AMBER_SOFT),
    "danger": (RED, RED_SOFT),
}

_FAMILY: Optional[str] = None


def font_family(root: tk.Misc) -> str:
    """Be Vietnam Pro when installed, otherwise Segoe UI (always present on Windows 10/11)."""
    global _FAMILY
    if _FAMILY is None:
        try:
            families = set(tkfont.families(root))
        except Exception:
            families = set()
        _FAMILY = "Be Vietnam Pro" if "Be Vietnam Pro" in families else "Segoe UI"
    return _FAMILY


def ui_font(root: tk.Misc, size: int, weight: str = "normal") -> Tuple[str, int, str]:
    return (font_family(root), size, weight)


def _pill_image(master: tk.Misc, w: int, h: int, fill: str, line: str, surface: str,
                inset: int = 0, ring: str = "") -> "ImageTk.PhotoImage":
    """Anti-aliased pill. Tk canvas shapes have jagged, gappy outlines, so draw at 4x and shrink."""
    k = 4
    img = Image.new("RGB", (w * k, h * k), surface)
    draw = ImageDraw.Draw(img)

    def _pill(pad: int, **kw) -> None:
        box = (pad * k, pad * k, (w - pad) * k - 1, (h - pad) * k - 1)
        draw.rounded_rectangle(box, radius=(box[3] - box[1]) // 2, **kw)

    _pill(inset, fill=fill, outline=line, width=k)
    if ring:
        _pill(inset + 3, outline=ring, width=k)
    return ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS), master=master)


def _round_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, r: float, **kw) -> int:
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


class PillButton(tk.Canvas):
    """Rounded button with hover, press and keyboard focus. Press scales down slightly."""

    STYLES = {
        "primary": dict(bg=GREEN, hover=GREEN_DEEP, fg="#ffffff", line=GREEN),
        "warn": dict(bg=AMBER, hover=AMBER_INK, fg="#ffffff", line=AMBER),
        "danger": dict(bg=RED, hover=RED_DEEP, fg="#ffffff", line=RED),
        "quiet": dict(bg=PAPER, hover=GREEN_WASH, fg=INK, line=RULE_STRONG),
    }

    def __init__(self, parent: tk.Misc, text: str, command: Callable[[], None],
                 style: str = "primary", size: int = 10, pad_x: int = 18, height: int = 38,
                 surface: str = PAPER):
        self._st = self.STYLES[style]
        self._surface = surface
        self._cmd = command
        self._text = text
        self._font = ui_font(parent, size, "bold")
        f = tkfont.Font(root=parent, font=self._font)
        width = f.measure(text) + pad_x * 2
        super().__init__(parent, width=width, height=height, bg=surface,
                         highlightthickness=0, bd=0, cursor="hand2", takefocus=1)
        self._bw, self._bh = width, height
        self._hover = False
        self._down = False
        self._focus = False
        self._draw()
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False, down=False))
        self.bind("<ButtonPress-1>", lambda e: self._set(down=True))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<FocusIn>", lambda e: self._set(focus=True))
        self.bind("<FocusOut>", lambda e: self._set(focus=False))
        self.bind("<Return>", lambda e: self._cmd())
        self.bind("<space>", lambda e: self._cmd())

    def _set(self, hover=None, down=None, focus=None) -> None:
        if hover is not None:
            self._hover = hover
        if down is not None:
            self._down = down
        if focus is not None:
            self._focus = focus
        self._draw()

    def _release(self, event) -> None:
        was_down = self._down
        self._set(down=False)
        if was_down and 0 <= event.x <= self._bw and 0 <= event.y <= self._bh:
            self._cmd()

    def _draw(self) -> None:
        self.delete("all")
        st = self._st
        fill = st["hover"] if self._hover else st["bg"]
        line = fill if st["bg"] != PAPER else st["line"]
        ring = ""
        if self._focus:
            ring = st["fg"] if st["bg"] != PAPER else GREEN
        inset = 1 if self._down else 0              # press: shrink a touch (scale 0.97 feel)
        self._img = _pill_image(self, self._bw, self._bh, fill, line, self._surface, inset, ring)
        self.create_image(0, 0, image=self._img, anchor="nw")
        self.create_text(self._bw / 2, self._bh / 2, text=self._text, fill=st["fg"], font=self._font)

class ProgressBar(tk.Canvas):
    """Thin rounded meter (same look as .meter on the dashboard)."""

    def __init__(self, parent: tk.Misc, width: int, color: str = GREEN, height: int = 10, surface: str = PAPER):
        super().__init__(parent, width=width, height=height, bg=surface, highlightthickness=0, bd=0)
        self._bw, self._bh, self._color = width, height, color
        self.set(0.0)

    def set(self, ratio: float, color: Optional[str] = None) -> None:
        ratio = max(0.0, min(1.0, ratio))
        self.delete("all")
        _round_rect(self, 0, 0, self._bw, self._bh, self._bh / 2, fill=LOCKED, outline="")
        if ratio > 0:
            w = max(self._bh, self._bw * ratio)
            _round_rect(self, 0, 0, w, self._bh, self._bh / 2, fill=color or self._color, outline="")


def make_window(title: str, heading: str, tone: str = "ok", parent: Optional[tk.Misc] = None,
                topmost: bool = True, width: int = 460, subtitle: str = "") -> Tuple[tk.Misc, tk.Frame]:
    """Create a themed window: one flat white card with a hairline border on the grey ground,
    like a dashboard card. The heading is ink; a small dot beside it carries the tone.
    Returns (window, body) - pack your content into `body`. Escape closes the window."""
    win = tk.Toplevel(parent) if parent is not None else tk.Tk()
    win.title(title)
    win.configure(bg=GROUND)
    win.resizable(False, False)
    if topmost:
        win.attributes("-topmost", True)
    tone_color, _ = TONES.get(tone, TONES["ok"])

    card = tk.Frame(win, bg=PAPER, highlightbackground=RULE, highlightthickness=1)
    card.pack(fill="both", expand=True, padx=14, pady=14)
    inner = tk.Frame(card, bg=PAPER, width=width - 28)
    inner.pack(fill="both", expand=True, padx=22, pady=20)

    header = tk.Frame(inner, bg=PAPER)
    header.pack(fill="x", pady=(0, 4 if subtitle else 14))
    dot = tk.Canvas(header, width=10, height=10, bg=PAPER, highlightthickness=0, bd=0)
    dot._img = _pill_image(win, 10, 10, tone_color, tone_color, PAPER)
    dot.create_image(0, 0, image=dot._img, anchor="nw")
    dot.pack(side="left", anchor="n", pady=(8, 0), padx=(0, 10))
    tk.Label(header, text=heading, font=ui_font(win, 14, "bold"), fg=INK, bg=PAPER,
             anchor="w", justify="left", wraplength=width - 92).pack(side="left", fill="x", expand=True)
    if subtitle:
        tk.Label(inner, text=subtitle, font=ui_font(win, 10), fg=INK_3, bg=PAPER,
                 anchor="w", justify="left", wraplength=width - 72).pack(fill="x", pady=(0, 14))

    # Content gets its own frame so callers can pack freely under the header
    body = tk.Frame(inner, bg=PAPER)
    body.pack(fill="both", expand=True)

    win.bind("<Escape>", lambda e: win.destroy())
    return win, body


def center(win: tk.Misc) -> None:
    """Center the window after its content has been laid out."""
    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    x = max(0, (win.winfo_screenwidth() - w) // 2)
    y = max(0, (win.winfo_screenheight() - h) // 3)
    win.geometry(f"+{x}+{y}")


def body_text(parent: tk.Misc, text: str, wraplength: int = 400, size: int = 10, color: str = INK,
              bold: bool = False, **pack) -> tk.Label:
    lbl = tk.Label(parent, text=text, font=ui_font(parent, size, "bold" if bold else "normal"),
                   fg=color, bg=parent.cget("bg"), justify="left", anchor="w", wraplength=wraplength)
    lbl.pack(fill="x", **pack)
    return lbl


def callout(parent: tk.Misc, text: str, tone: str = "ok", wraplength: int = 400) -> tk.Frame:
    """Soft tinted note (the .notice on the dashboard)."""
    _, tint = TONES.get(tone, TONES["ok"])
    frame = tk.Frame(parent, bg=tint)
    tk.Label(frame, text=text, font=ui_font(parent, 9), fg=INK_2, bg=tint, justify="left", anchor="w",
             wraplength=wraplength - 28).pack(fill="x", padx=14, pady=10)
    return frame
