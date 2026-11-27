"""OGK-Tray Application (FR-F1-04, FR-F2-02, FR-F3-03, FR-F3-07, FR-F5-09).
Provides the System Tray Icon (pystray) and Tkinter transparency / warning dialogs:
- Countdown timer for remaining screen time today
- 10m / 5m / 1m advance warning popups
- 60-second grace countdown dialog (ViolationCountdownWindow)
- 'What I used today' (Transparency Screen)
- 'Request more time' dialog
- 20-20-20 Eye break reminder cards
- Blocked app / website notification dialogs
"""
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Callable, List
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageDraw

if __package__ in (None, ""):
    # OGK-Service launches this file directly: make the `agent` package importable
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from branding import APP_NAME

from agent.ipc.pipe_protocol import IpcEnvelope, IpcClient
from agent.ui import theme as ui_theme

logger = logging.getLogger("OGK.TrayApp")

POLL_INTERVAL_SEC = 2.0
# Lock reasons for which the tray locks the Windows session (grace period is not a lock)
HARD_LOCK_REASONS = {"DAILY_LIMIT_REACHED", "OUTSIDE_ALLOWED_SCHEDULE", "MANUAL_LOCK"}


def get_user_idle_seconds() -> Optional[float]:
    """Seconds since the last keyboard/mouse input in this (the child's) session."""
    try:
        import ctypes
        from ctypes import wintypes

        class _LII(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        lii = _LII()
        lii.cbSize = ctypes.sizeof(_LII)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
            return ((now - lii.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:
        pass
    return None


def is_workstation_locked() -> Optional[bool]:
    """True while the Windows lock screen is up (the input desktop is not ours)."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        desk = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
        if not desk:
            return True
        try:
            return not bool(user32.SwitchDesktop(desk))
        finally:
            user32.CloseDesktop(desk)
    except Exception:
        return None


def lock_workstation() -> bool:
    """Locks the Windows session (same as Win+L). Unsaved work stays open behind it."""
    try:
        import ctypes
        return bool(ctypes.windll.user32.LockWorkStation())
    except Exception:
        return False
# warning code from the service -> minutes left
QUOTA_WARNING_MINUTES = {"warn_10m": 10, "warn_5m": 5, "warn_1m": 1}
GRACE_WARNING = "GRACE_PERIOD_60S"


def create_tray_icon_image(state: str = "active") -> Image.Image:
    """Show the app logo during normal operation and icons for special states."""
    if state == "active":
        with Image.open(Path(__file__).with_name("echo-kiddo-tray.png")) as logo:
            return logo.convert("RGBA")

    img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    colors = {
        "warning": (245, 124, 0, 255),   # Orange
        "locked": (198, 40, 40, 255),    # Red
        "paused": (21, 101, 192, 255),   # Blue
    }
    fill_color = colors.get(state, (46, 125, 50, 255))

    # Draw rounded shield / circle
    draw.ellipse([4, 4, 60, 60], fill=fill_color, outline=(255, 255, 255, 220), width=3)

    if state == "locked":
        # Draw white lock body
        draw.rectangle([22, 28, 42, 46], fill=(255, 255, 255, 255))
        draw.arc([24, 18, 40, 32], start=180, end=0, fill=(255, 255, 255, 255), width=3)
    elif state == "warning":
        # Draw exclamation mark
        draw.line([32, 20, 32, 36], fill=(255, 255, 255, 255), width=4)
        draw.ellipse([30, 41, 34, 45], fill=(255, 255, 255, 255))
    elif state == "paused":
        # Draw pause bars
        draw.rectangle([22, 22, 27, 42], fill=(255, 255, 255, 255))
        draw.rectangle([37, 22, 42, 42], fill=(255, 255, 255, 255))

    return img


class TrayApplication:
    """Manages the Tray Icon, Background IPC sync, and Tkinter UI Dialogs."""

    def __init__(self, ipc_client=None, headless: bool = False):
        self.ipc_client = ipc_client or IpcClient()
        self.headless = headless
        self.running = False
        self.tray_icon = None
        # True only once the tray icon is really on screen (No-Stealth-Mode)
        self.icon_visible: bool = False
        self.icon_state: str = "active"
        self.poll_interval: float = POLL_INTERVAL_SEC
        self.top_apps: List[Dict[str, Any]] = []
        self.top_domains: List[Dict[str, Any]] = []
        self.lock_reason: str = ""
        self.unprotected_halt: bool = False

        # State cache from service
        self.remaining_sec: int = 3600
        self.used_total_sec: int = 0
        self.is_locked: bool = False
        self.is_parent_paused: bool = False
        self.last_warning_shown: Optional[str] = None
        self.grace_window_open: bool = False

        # Eye rest tracking (20-20-20 rule)
        self.last_eye_break_time: float = time.time()

    def _send(self, envelope: IpcEnvelope):
        """Sends one envelope to OGK-Service; works with send_envelope() or send_request()."""
        client = self.ipc_client
        if client is None:
            return None
        sender = getattr(client, "send_envelope", None) or getattr(client, "send_request", None)
        if sender is None:
            return None
        return sender(envelope)

    def send_tray_ready(self) -> None:
        """Sends TRAY_READY envelope to service to confirm icon is visible."""
        try:
            self._send(IpcEnvelope(msg_type="TRAY_READY"))
            logger.info("Sent TRAY_READY to OGK-Service.")
        except Exception as e:
            logger.debug("Failed sending TRAY_READY: %s", e)

    def request_more_time(self, minutes: int = 15) -> None:
        """Sends REQUEST_MORE_TIME to parent via service."""
        try:
            self._send(IpcEnvelope(msg_type="REQUEST_MORE_TIME", payload={"minutes": minutes}))
        except Exception as e:
            logger.error("Failed requesting more time: %s", e)

    # ------------------------------------------------------------------ live status sync
    def poll_session_status(self) -> Optional[Dict[str, Any]]:
        """Asks OGK-Service for GET_SESSION_STATUS once and reacts to it."""
        resp = self._send(IpcEnvelope(msg_type="GET_SESSION_STATUS", payload=self._activity_report()))
        if resp is None:
            return None
        status = getattr(resp, "payload", resp)
        if not isinstance(status, dict):
            return None
        self.apply_session_status(status)
        return status

    def _activity_report(self) -> Dict[str, Any]:
        """Idle time / lock state of this session for the service's screen-time counter."""
        report: Dict[str, Any] = {}
        if self.headless:
            return report
        idle = get_user_idle_seconds()
        if idle is not None:
            report["idle_sec"] = round(idle, 1)
        locked = is_workstation_locked()
        if locked is not None:
            report["session_locked"] = locked
        return report

    def enforce_session_lock(self) -> None:
        """Out of quota / outside the schedule / LOCK_NOW: lock Windows, and keep it locked."""
        if self.headless or self.unprotected_halt:
            return
        if not self.is_locked or self.lock_reason not in HARD_LOCK_REASONS:
            return
        if is_workstation_locked():
            return
        logger.info("Locking the Windows session (%s).", self.lock_reason)
        lock_workstation()

    def apply_session_status(self, status: Dict[str, Any]) -> None:
        """Updates the cached state, tray tooltip / colour, and opens the warning, grace
        and block-explanation windows the service asks for."""
        self.remaining_sec = int(status.get("remaining_sec", self.remaining_sec) or 0)
        self.used_total_sec = int(status.get("used_total_sec", self.used_total_sec) or 0)
        self.is_locked = bool(status.get("is_locked", False))
        self.is_parent_paused = bool(status.get("is_parent_paused", False))
        self.lock_reason = str(status.get("lock_reason") or "")
        self.unprotected_halt = bool(status.get("unprotected_halt", False))
        if isinstance(status.get("top_apps"), list):
            self.top_apps = status["top_apps"]
        if isinstance(status.get("top_domains"), list):
            self.top_domains = status["top_domains"]

        # Service restarted and lost track of us: confirm again, but only with a real icon
        if status.get("tray_registered") is False and self.icon_visible:
            self.send_tray_ready()

        warning = status.get("warning")
        in_grace = warning == GRACE_WARNING or self.lock_reason == "GRACE_PERIOD"

        if in_grace:
            if self.last_warning_shown != GRACE_WARNING:
                self.last_warning_shown = GRACE_WARNING
                self.show_grace_countdown_dialog()
        elif warning in QUOTA_WARNING_MINUTES:
            if warning != self.last_warning_shown:
                self.last_warning_shown = warning
                minutes = QUOTA_WARNING_MINUTES[warning]
                self.show_warning_dialog(
                    f"{APP_NAME} - Sắp hết giờ",
                    f"Em còn khoảng {minutes} phút sử dụng máy tính hôm nay. "
                    "Hãy lưu lại bài đang làm nhé!",
                )
        elif self.last_warning_shown is not None and not self.is_locked and self.remaining_sec > 600:
            # Plenty of time again (new day / extra time granted): warnings may fire anew
            self.last_warning_shown = None

        # Never block silently: explain every newly blocked app / website
        blocks = status.get("recent_blocks")
        if isinstance(blocks, list):
            for item in blocks:
                if isinstance(item, dict) and item.get("subject"):
                    self.show_block_explanation(str(item["subject"]), str(item.get("reason") or ""))

        self._refresh_icon()
        self.enforce_session_lock()

    def compute_icon_state(self) -> str:
        if self.is_parent_paused or self.unprotected_halt:
            return "paused"
        if self.is_locked:
            return "locked"
        if self.last_warning_shown is not None or self.remaining_sec <= 600:
            return "warning"
        return "active"

    def build_tooltip(self) -> str:
        if self.unprotected_halt:
            return f"{APP_NAME} - Đang tạm dừng bảo vệ"
        if self.is_parent_paused:
            return f"{APP_NAME} - Bố mẹ đang cho tạm nghỉ"
        if self.is_locked:
            return f"{APP_NAME} - Đã hết giờ / ngoài khung giờ"
        return f"{APP_NAME} - Còn lại {max(0, self.remaining_sec) // 60} phút hôm nay"

    def _refresh_icon(self) -> None:
        """Reflects state on the tray icon (colour) and tooltip (time left)."""
        state = self.compute_icon_state()
        changed = state != self.icon_state
        self.icon_state = state
        icon = self.tray_icon
        if icon is None:
            return
        try:
            icon.title = self.build_tooltip()
            if changed:
                icon.icon = create_tray_icon_image(state)
        except Exception as e:
            logger.debug("Could not refresh tray icon: %s", e)

    def _verify_parent_pin(self, entered: str) -> bool:
        """Asks OGK-Service to check the parent PIN. No service connection -> never authorised."""
        if not entered or not self.ipc_client:
            return False
        try:
            resp_c = self._send(IpcEnvelope(msg_type="GET_CHALLENGE"))
            token = resp_c.payload.get("challenge_token") if resp_c else None
            resp_v = self._send(IpcEnvelope(
                msg_type="VERIFY_PARENT_PIN", challenge_token=token, payload={"pin": entered},
            ))
            return bool(resp_v and resp_v.payload.get("valid"))
        except Exception as e:
            logger.error("IPC PIN verification error: %s", e)
            return False

    def show_parent_pin_dialog(self, parent, on_authorized: Callable[[], None]) -> None:
        """Themed parent-PIN prompt. `parent` is an existing Tk window (a Toplevel is used) or
        None (the dialog then runs in its own thread). Calls on_authorized() after a correct PIN."""
        if self.headless:
            logger.info("[HEADLESS PIN DIALOG]")
            return

        def _build():
            pin_win, pin_body = ui_theme.make_window(
                "Xác thực phụ huynh", "Bố mẹ xác nhận", tone="ok", parent=parent, width=360,
            )
            ui_theme.body_text(pin_body, "Nhập mã PIN hoặc mật khẩu phụ huynh", wraplength=300, pady=(0, 8))
            pin_entry = tk.Entry(
                pin_body, show="*", font=ui_theme.ui_font(pin_win, 13), justify="center", width=18,
                relief="flat", bg=ui_theme.GREEN_WASH, fg=ui_theme.INK, insertbackground=ui_theme.GREEN,
                highlightthickness=2, highlightbackground=ui_theme.RULE, highlightcolor=ui_theme.GREEN,
            )
            pin_entry.pack(fill="x", ipady=8, pady=(0, 16))
            pin_entry.focus_set()

            def _verify():
                entered = pin_entry.get().strip()
                if not entered:
                    return
                if self._verify_parent_pin(entered):
                    messagebox.showinfo("Thành công", "Mã PIN chính xác.", parent=pin_win)
                    pin_win.destroy()
                    on_authorized()
                else:
                    messagebox.showerror("Sai mã PIN", "Mã PIN phụ huynh không đúng!", parent=pin_win)

            pin_entry.bind("<Return>", lambda e: _verify())
            row = tk.Frame(pin_body, bg=ui_theme.PAPER)
            row.pack(fill="x")
            ui_theme.PillButton(row, "Xác nhận", _verify).pack(side="right")
            ui_theme.center(pin_win)
            if parent is None:
                pin_win.mainloop()

        if parent is None:
            threading.Thread(target=_build, daemon=True).start()
        else:
            _build()

    def request_exit(self) -> None:
        """Tray menu 'Thoát'. A child must not be able to quit the companion: when OGK-Service
        is running it asks for the parent PIN. With no service reachable nothing is being
        enforced, so the tray simply closes."""
        try:
            service_up = self._send(IpcEnvelope(msg_type="GET_CHALLENGE")) is not None
        except Exception:
            service_up = False
        if not service_up:
            self.stop()
            return
        self.show_parent_pin_dialog(None, self.stop)

    def show_warning_dialog(self, title: str, message: str) -> None:
        """Displays friendly non-intrusive warning dialog."""
        if self.headless:
            logger.info("[HEADLESS WARNING] %s: %s", title, message)
            return

        def _popup():
            win, body = ui_theme.make_window(title, title.removeprefix(f"{APP_NAME} - "), tone="warn", width=440)
            ui_theme.body_text(body, message, wraplength=380, pady=(0, 18))
            row = tk.Frame(body, bg=ui_theme.PAPER)
            row.pack(fill="x")
            btn = ui_theme.PillButton(row, "Em đã hiểu", win.destroy)
            btn.pack(side="right")
            btn.focus_set()
            ui_theme.center(win)
            win.mainloop()

        threading.Thread(target=_popup, daemon=True).start()

    def show_grace_countdown_dialog(self) -> None:
        """Displays the 60-second ViolationCountdownWindow (FR-F1-04)."""
        if self.headless:
            logger.info("[HEADLESS GRACE WINDOW] 60s countdown started")
            return

        if self.grace_window_open:
            return
        self.grace_window_open = True

        def _countdown():
            win, body = ui_theme.make_window(
                f"{APP_NAME} - Hết giờ", "Đã hết thời gian dùng máy hôm nay", tone="warn", width=540,
            )
            root = win
            ui_theme.body_text(
                body,
                "Em có 60 giây để lưu bài tập, hoặc bấm 'Xin thêm 15 phút' trước khi máy khóa màn hình.",
                wraplength=480, pady=(0, 10),
            )

            countdown_var = tk.StringVar(value="60")
            tk.Label(body, textvariable=countdown_var, font=ui_theme.ui_font(win, 40, "bold"),
                     fg=ui_theme.AMBER_INK, bg=ui_theme.PAPER).pack(anchor="w")
            ui_theme.body_text(body, "giây trước khi máy khóa màn hình", size=9, color=ui_theme.INK_3, pady=(0, 6))
            bar = ui_theme.ProgressBar(body, width=480, color=ui_theme.AMBER_BAR)
            bar.set(1.0)
            bar.pack(anchor="w", pady=(0, 18))

            btn_frame = tk.Frame(body, bg=ui_theme.PAPER)
            btn_frame.pack(fill="x")

            def _close():
                self.grace_window_open = False
                try:
                    root.destroy()
                except tk.TclError:
                    pass

            def _on_req():
                self.request_more_time(15)
                messagebox.showinfo("Đã gửi yêu cầu", "Yêu cầu xin thêm 15 phút đã được gửi tới bố mẹ!", parent=root)
                _close()

            def _on_done():
                _close()

            def _on_parent_pin():
                self.show_parent_pin_dialog(root, _close)

            ui_theme.PillButton(btn_frame, "Xin thêm 15 phút", _on_req).pack(side="left")
            ui_theme.PillButton(btn_frame, "Đã lưu xong", _on_done, style="quiet").pack(side="left", padx=8)
            ui_theme.PillButton(btn_frame, "Bố mẹ mở khóa", _on_parent_pin, style="quiet").pack(side="left")

            win.protocol("WM_DELETE_WINDOW", _close)
            win.bind("<Escape>", lambda e: _close())

            # Countdown ticker
            remaining = [60]
            def _tick():
                if remaining[0] > 0:
                    remaining[0] -= 1
                    countdown_var.set(str(remaining[0]))
                    bar.set(remaining[0] / 60.0, ui_theme.RED if remaining[0] <= 10 else ui_theme.AMBER_BAR)
                    root.after(1000, _tick)
                else:
                    _close()

            root.after(1000, _tick)
            ui_theme.center(win)
            root.mainloop()

        threading.Thread(target=_countdown, daemon=True).start()

    def show_transparency_screen(self) -> None:
        """Displays 'Hôm nay em đã dùng gì' transparency screen (FR-F3-03)."""
        if self.headless:
            logger.info("[HEADLESS TRANSPARENCY SCREEN] Displaying child usage")
            return

        def _screen():
            win, body = ui_theme.make_window(
                f"{APP_NAME} - Hôm nay em đã dùng gì?", "Hôm nay em đã dùng gì?",
                tone="ok", parent=tk._default_root, topmost=False, width=640,
                subtitle="Bố mẹ và em cùng xem chung những con số này.",
            )

            used_min = self.used_total_sec // 60
            remain_min = max(0, self.remaining_sec) // 60
            total_min = used_min + remain_min

            ui_theme.body_text(body, f"Em còn {remain_min} phút hôm nay.", wraplength=570, size=22, bold=True)
            ui_theme.body_text(body, f"Em đã dùng {used_min} / {total_min} phút", size=10,
                               color=ui_theme.INK_3, pady=(2, 8))
            today_bar = ui_theme.ProgressBar(body, width=580, height=8)
            today_bar.set(used_min / total_min if total_min else 1.0, None if remain_min else ui_theme.RED)
            today_bar.pack(anchor="w", pady=(0, 14))
            tk.Frame(body, bg=ui_theme.RULE, height=1).pack(fill="x", pady=(0, 14))

            # Top apps / websites of today (exe names and site names only)
            def _fmt_duration(sec: int) -> str:
                return f"{sec // 60} phút" if sec >= 60 else f"{sec} giây"

            def _column(parent, title, rows, pad):
                col = tk.Frame(parent, bg=ui_theme.PAPER)
                col.pack(side="left", fill="both", expand=True, padx=pad)
                tk.Label(col, text=title, font=ui_theme.ui_font(win, 11, "bold"), fg=ui_theme.INK,
                         bg=ui_theme.PAPER, anchor="w").pack(fill="x", pady=(0, 8))
                if not rows:
                    tk.Label(col, text="Chưa có dữ liệu", font=ui_theme.ui_font(win, 9), fg=ui_theme.INK_3,
                             bg=ui_theme.PAPER, anchor="w").pack(fill="x")
                    return
                top = max((r[2] for r in rows), default=1) or 1
                for name, value_text, weight, blocked in rows:
                    line = tk.Frame(col, bg=ui_theme.PAPER)
                    line.pack(fill="x")
                    tk.Label(line, text=name, font=ui_theme.ui_font(win, 10, "bold"), fg=ui_theme.INK,
                             bg=ui_theme.PAPER, anchor="w").pack(side="left")
                    tk.Label(line, text=value_text, font=ui_theme.ui_font(win, 9), fg=ui_theme.INK_2,
                             bg=ui_theme.PAPER).pack(side="right")
                    meter = ui_theme.ProgressBar(col, width=276, height=6,
                                                 color=ui_theme.RED if blocked else ui_theme.ACCENT)
                    meter.set(weight / top)
                    meter.pack(anchor="w", pady=(2, 2 if not blocked else 0))
                    if blocked:
                        tk.Label(col, text="đã bị chặn", font=ui_theme.ui_font(win, 8), fg=ui_theme.RED_DEEP,
                                 bg=ui_theme.PAPER, anchor="w").pack(fill="x", pady=(0, 2))
                    tk.Frame(col, bg=ui_theme.PAPER, height=6).pack()

            app_rows = [
                (str(it.get("subject", "")), _fmt_duration(int(it.get("duration_sec") or 0)),
                 int(it.get("duration_sec") or 0), bool(int(it.get("blocked_count") or 0)))
                for it in (self.top_apps or [])[:5]
            ]
            dom_rows = [
                (str(it.get("subject", "")), f"{int(it.get('count') or 0)} lượt",
                 int(it.get("count") or 0), bool(int(it.get("blocked_count") or 0)))
                for it in (self.top_domains or [])[:5]
            ]
            lists = tk.Frame(body, bg=ui_theme.PAPER)
            lists.pack(fill="both", expand=True)
            _column(lists, "Ứng dụng hôm nay", app_rows, (0, 14))
            _column(lists, "Trang web hôm nay", dom_rows, (0, 0))

            # Transparency explanation
            note = ui_theme.callout(
                body,
                f"{APP_NAME} không chụp ảnh màn hình và không đọc tin nhắn của em.",
                tone="ok", wraplength=580,
            )
            note.pack(fill="x", pady=(8, 16))

            row = tk.Frame(body, bg=ui_theme.PAPER)
            row.pack(fill="x")
            btn = ui_theme.PillButton(row, "Đóng", win.destroy)
            btn.pack(side="right")
            btn.focus_set()
            ui_theme.center(win)
            win.mainloop()

        threading.Thread(target=_screen, daemon=True).start()

    def show_block_explanation(self, subject: str, reason: str) -> None:
        """Displays friendly explanation when an app or website is blocked (FR-F2-02)."""
        if self.headless:
            logger.info("[HEADLESS BLOCK NOTIFICATION] Blocked %s: %s", subject, reason)
            return

        def _popup():
            win, body = ui_theme.make_window(
                f"{APP_NAME} - Thông báo", "Ứng dụng hoặc trang web này đang bị hạn chế",
                tone="danger", width=460,
            )
            ui_theme.body_text(
                body, f"'{subject}' chưa phù hợp với khung giờ hoặc lứa tuổi của em.",
                wraplength=400, bold=True, pady=(0, 10),
            )
            ui_theme.callout(body, f"Lý do: {reason}", tone="danger", wraplength=400).pack(fill="x", pady=(0, 18))
            row = tk.Frame(body, bg=ui_theme.PAPER)
            row.pack(fill="x")
            btn = ui_theme.PillButton(row, "Em đã hiểu", win.destroy)
            btn.pack(side="right")
            btn.focus_set()
            ui_theme.center(win)
            win.mainloop()

        threading.Thread(target=_popup, daemon=True).start()

    def show_eye_break_reminder(self) -> None:
        """Displays 20-20-20 eye rest reminder card (FR-F3-07)."""
        if self.headless:
            logger.info("[HEADLESS EYE BREAK] 20-20-20 eye break reminder")
            return

        def _popup():
            win, body = ui_theme.make_window(
                f"{APP_NAME} - Nghỉ mắt", "Quy tắc 20-20-20: bảo vệ mắt của em", tone="ok", width=440,
            )
            ui_theme.body_text(
                body,
                "Em đã dùng máy tính 20 phút liên tục. Hãy nhìn xa khoảng 6 mét trong 20 giây "
                "để mắt được thư giãn nhé!",
                wraplength=380, pady=(0, 18),
            )
            row = tk.Frame(body, bg=ui_theme.PAPER)
            row.pack(fill="x")
            btn = ui_theme.PillButton(row, "Em đang nghỉ mắt nè", win.destroy)
            btn.pack(side="right")
            btn.focus_set()
            ui_theme.center(win)
            win.mainloop()

        threading.Thread(target=_popup, daemon=True).start()

    def start_background_loop(self, announce_ready: bool = True) -> None:
        """Background thread: confirms the tray to the service, then every 2 seconds polls
        GET_SESSION_STATUS (countdown, warnings, grace window, block notices) and checks
        the 20-20-20 eye break."""
        self.running = True
        if announce_ready:
            self.send_tray_ready()

        while self.running:
            try:
                # 1. Live status from OGK-Service
                try:
                    self.poll_session_status()
                except Exception as e:
                    logger.debug("Session status poll failed: %s", e)

                # 2. Check eye break (every 20 minutes / 1200s)
                now = time.time()
                if now - self.last_eye_break_time >= 1200:
                    self.last_eye_break_time = now
                    self.show_eye_break_reminder()

                time.sleep(self.poll_interval)
            except Exception as e:
                logger.error("Error in tray background loop: %s", e)
                time.sleep(self.poll_interval)

    def stop(self) -> None:
        self.running = False
        icon = self.tray_icon
        if icon is not None:
            try:
                icon.stop()
            except Exception as e:
                logger.debug("Could not stop tray icon: %s", e)


def main() -> int:
    app = TrayApplication(headless=False)

    # No-Stealth-Mode: TRAY_READY is only sent once the icon is really on screen. If the
    # icon cannot be shown we exit without confirming, and OGK-Service falls back to
    # UNPROTECTED_HALT after 3 unconfirmed attempts.
    try:
        import pystray
        icon_img = create_tray_icon_image("active")
        menu = pystray.Menu(
            pystray.MenuItem("Hôm nay em đã dùng gì?", lambda: app.show_transparency_screen()),
            pystray.MenuItem("Xin thêm giờ", lambda: app.request_more_time(15)),
            pystray.MenuItem("Nghỉ mắt 20-20-20", lambda: app.show_eye_break_reminder()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Thoát (cần bố mẹ)", lambda: app.request_exit()),
        )
        icon = pystray.Icon("OGK-Tray", icon_img, APP_NAME, menu)
        app.tray_icon = icon

        def _on_icon_ready(ic):
            ic.visible = True
            app.icon_visible = True
            threading.Thread(target=app.start_background_loop, daemon=True).start()

        icon.run(setup=_on_icon_ready)
        return 0
    except Exception as e:
        logger.error("Tray icon could not be displayed (%s). Not confirming TRAY_READY.", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
