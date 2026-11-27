"""Shared look for the OGK tray dialogs.

Mirrors the dashboard tokens in dashboard/static/styles.css (mint ground, sage header,
rounded white card, pill buttons) so the child sees one product, not two.
Only tkinter + the standard library, so it works on a clean Windows machine.
"""
import tkinter as tk
from tkinter import font as tkfont
from typing import Callable, Optional, Tuple

# ---- tokens (same values as the CSS) ----
GREEN = "#2f7d63"
GREEN_DEEP = "#1d5a46"
GREEN_MID = "#3f9475"
GREEN_SOFT = "#d3ece2"
GREEN_WASH = "#eaf6f1"
GROUND = "#e3f1ee"
PAPER = "#ffffff"
INK = "#14211c"
INK_2 = "#3f514a"
INK_3 = "#587068"
RULE = "#d3e0db"
LOCKED = "#dde8e4"
RED = "#c8291a"
RED_DEEP = "#9c1d11"
RED_SOFT = "#fbe3df"
AMBER = "#b4690f"          # header tone for warnings (white text passes 4.5:1)
AMBER_BAR = "#d98a3d"
AMBER_SOFT = "#fbead6"
AMBER_INK = "#8f4f0c"
GOLD_SOFT = "#fdf1d0"

# tone -> (header colour, soft tint used for callouts)
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
        "quiet": dict(bg=PAPER, hover=GREEN_WASH, fg=INK, line="#9db3aa"),
    }

    def __init__(self, parent: tk.Misc, text: str, command: Callable[[], None],
                 style: str = "primary", size: int = 10, pad_x: int = 18, height: int = 38,
                 surface: str = PAPER):
        self._st = self.STYLES[style]
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
        inset = 1.5 if self._down else 0.5          # press: shrink a touch (scale 0.97 feel)
        r = (self._bh - inset * 2) / 2
        _round_rect(self, inset, inset, self._bw - inset, self._bh - inset, r, fill=fill, outline=st["line"])
        if self._focus:
            _round_rect(self, inset + 3, inset + 3, self._bw - inset - 3, self._bh - inset - 3,
                        r - 3, fill="", outline=st["fg"] if st["bg"] != PAPER else GREEN)
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
    """Create a themed window: sage/amber/red header band over a white card on the mint ground.
    Returns (window, body) - pack your content into `body`. Escape closes the window."""
    win = tk.Toplevel(parent) if parent is not None else tk.Tk()
    win.title(title)
    win.configure(bg=GROUND)
    win.resizable(False, False)
    if topmost:
        win.attributes("-topmost", True)
    head_color, _ = TONES.get(tone, TONES["ok"])

    header = tk.Frame(win, bg=head_color)
    header.pack(fill="x")
    tk.Label(header, text=heading, font=ui_font(win, 13, "bold"), fg="#ffffff", bg=head_color,
             anchor="w", justify="left", wraplength=width - 48).pack(fill="x", padx=24, pady=(16, 2 if subtitle else 16))
    if subtitle:
        tk.Label(header, text=subtitle, font=ui_font(win, 9), fg="#e3f3ec", bg=head_color,
                 anchor="w", justify="left", wraplength=width - 48).pack(fill="x", padx=24, pady=(0, 14))

    outer = tk.Frame(win, bg=GROUND)
    outer.pack(fill="both", expand=True, padx=16, pady=16)
    body = tk.Frame(outer, bg=PAPER, highlightbackground=RULE, highlightthickness=1)
    body.pack(fill="both", expand=True)
    inner = tk.Frame(body, bg=PAPER, width=width - 32)
    inner.pack(fill="both", expand=True, padx=20, pady=18)

    win.bind("<Escape>", lambda e: win.destroy())
    return win, inner


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
