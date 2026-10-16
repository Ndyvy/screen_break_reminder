import tkinter as tk
import ctypes
from ctypes import wintypes
import math
import os
import socket
import threading
import time
from datetime import datetime
from supabase import create_client

# ---------------------------------------------------------
# Supabase Configuration
# ---------------------------------------------------------
# Publishable (anon) key: safe to ship in the client only if the table has
# RLS enabled with an INSERT-only policy for the anon role.
SUPABASE_URL = "https://bmtiwolfusrtqnyhpsbr.supabase.co"
SUPABASE_KEY = "sb_publishable_oscxtHoJELmPC3EsaK6qdg_SSPys9k-"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------------
# Settings and Constants
# ---------------------------------------------------------
DEMO_MODE = True           # Set to False for normal use

if DEMO_MODE:
    WORK_TARGET = 10        # 10 seconds of active work for demo
    IDLE_LIMIT = 5          # 5 seconds of inactivity considered idle for demo
    BREAK_SECONDS = 10      # 10 seconds break duration for demo
else:
    WORK_TARGET = 3600      # 1 hour of active work
    IDLE_LIMIT = 300        # 5 minutes of inactivity
    BREAK_SECONDS = 60      # 60 seconds break duration

MONITOR_TICK_MS = 1000      # How often activity is checked
BREAK_TICK_MS = 200         # How often the break countdown refreshes

# ---------------------------------------------------------
# Break Overlay Settings (countdown box + cat)
# ---------------------------------------------------------
# Put cat.gif in the same folder as this script. Needs: pip install pillow
CAT_GIF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cat.gif")
CAT_HEIGHT = 220            # Height of the cat on screen (pixels)
CAT_SPEED = 6               # Pixels moved per step when walking in / out
CAT_BOTTOM_MARGIN = 60      # Distance from the bottom of the screen (above the taskbar)

# Every pixel of this exact color becomes see-through (Windows only).
# Pick a color that does not appear in the GIF.
KEY_COLOR = "#ff00fe"

# If the GIF has no transparent background, remove the background color
# automatically (taken from the top-left pixel).
CHROMA_KEY = True
CHROMA_TOLERANCE = 40       # Higher = removes more colors close to the background

# Countdown box
TIMER_BG = "#111111"
TIMER_FG = "#ffffff"
TIMER_ALPHA = 0.88          # 1.0 = solid, lower = more see-through

# Screen lock during breaks
LOCK_SCREEN = True          # True = mouse and keyboard are blocked while on break
DIM_ALPHA = 0.45            # How dark the screen gets during a break (0 = clear, 1 = black)
# Emergency skip: Ctrl + Shift + Q ends the break early.
# Ctrl + Alt + Del always works too (Windows never lets apps block it).

# ---------------------------------------------------------
# Tracking Variables
# ---------------------------------------------------------
# Wall-clock timestamps are only used for reporting; all durations are
# measured with time.monotonic() so they don't drift.
session_start = datetime.now().astimezone()
session_start_mono = time.monotonic()

active_work_seconds = 0.0        # Active seconds in current interval (resets after break)
total_active_seconds = 0.0       # Active seconds across the whole session
total_break_seconds = 0.0        # Time spent in breaks
break_count = 0                  # Breaks completed fully
idle_count = 0                   # Times the user became idle
is_idle = False
monitor_running = False
session_ended = False
last_tick = None                 # monotonic time of the previous monitor tick

break_timer_running = False
break_started_at = None          # monotonic time when the current break began
timer_window = None              # Countdown box shown during a break
timer_canvas = None
timer_text = None
cat_overlay = None               # The cat currently on screen (if any)
cat_frames = None                # Prepared GIF frames (loaded once)
cat_durations = None
dim_window = None                # Full-screen dark layer that swallows mouse clicks
skip_requested = False           # Set by the emergency key combo


# ---------------------------------------------------------
# Keyboard Lock (Windows low-level keyboard hook)
# ---------------------------------------------------------
# While the hook is installed, every key press on the computer is swallowed
# (Win key, Alt+Tab, Alt+F4, typing...). Ctrl+Alt+Del still works because
# Windows handles it before any app can see it - that is the safety exit.
WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0100, 0x0101, 0x0104, 0x0105
VK_Q = 0x51
CTRL_KEYS = {0x11, 0xA2, 0xA3}
SHIFT_KEYS = {0x10, 0xA0, 0xA1}

LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


try:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
    _user32.SetWindowsHookExW.restype = wintypes.HHOOK
    _user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    _user32.CallNextHookEx.restype = LRESULT
    _user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
    _user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    _kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
    _kernel32.GetModuleHandleW.restype = wintypes.HMODULE
except (AttributeError, OSError):
    _user32 = None              # Not on Windows - the lock is simply skipped

_kb_hook = None
_held_keys = set()


def _keyboard_proc(n_code, w_param, l_param):
    global skip_requested
    try:
        if n_code == 0:
            vk = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents.vkCode
            if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                _held_keys.add(vk)
                # Emergency skip: Ctrl + Shift + Q. Only a flag is set here;
                # the break timer picks it up (no Tk calls inside the hook).
                if vk == VK_Q and _held_keys & CTRL_KEYS and _held_keys & SHIFT_KEYS:
                    skip_requested = True
            elif w_param in (WM_KEYUP, WM_SYSKEYUP):
                _held_keys.discard(vk)
            return 1            # Swallow the key: no other app receives it
    except Exception:
        pass
    return _user32.CallNextHookEx(None, n_code, w_param, l_param)


_keyboard_proc_ref = HOOKPROC(_keyboard_proc)   # keep a reference so it isn't garbage-collected


def lock_keyboard():
    global _kb_hook
    if _user32 is None or _kb_hook:
        return
    _held_keys.clear()
    _kb_hook = _user32.SetWindowsHookExW(
        WH_KEYBOARD_LL, _keyboard_proc_ref, _kernel32.GetModuleHandleW(None), 0
    )
    if not _kb_hook:
        print("Note: could not lock the keyboard, error", ctypes.get_last_error())


def unlock_keyboard():
    global _kb_hook
    if _kb_hook:
        _user32.UnhookWindowsHookEx(_kb_hook)
        _kb_hook = None
    _held_keys.clear()


# ---------------------------------------------------------
# Dark layer over every monitor (blocks mouse clicks)
# ---------------------------------------------------------
def virtual_screen_rect():
    """Position and size of the area covering ALL monitors."""
    try:
        gsm = ctypes.windll.user32.GetSystemMetrics
        return gsm(76), gsm(77), gsm(78), gsm(79)   # x, y, width, height
    except AttributeError:
        return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def open_dim_layer():
    global dim_window
    x, y, w, h = virtual_screen_rect()
    dim_window = tk.Toplevel(root)
    dim_window.overrideredirect(True)
    dim_window.attributes("-topmost", True)
    dim_window.attributes("-alpha", DIM_ALPHA)
    dim_window.configure(bg="black")
    try:
        dim_window.configure(cursor="none")   # hide the mouse pointer
    except tk.TclError:
        pass
    dim_window.geometry(f"{w}x{h}{x:+d}{y:+d}")
    dim_window.protocol("WM_DELETE_WINDOW", lambda: None)
    dim_window.focus_force()


def close_dim_layer():
    global dim_window
    if dim_window is not None:
        try:
            dim_window.destroy()
        except tk.TclError:
            pass
        dim_window = None


# ---------------------------------------------------------
# Windows Activity Detection (Keyboard & Mouse)
# ---------------------------------------------------------
def get_idle_seconds():
    # GetLastInputInfo returns the tick count of the last keyboard/mouse
    # input across the whole computer. LASTINPUTINFO = {UINT cbSize; DWORD dwTime}
    buffer = (ctypes.c_uint * 2)(8, 0)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(buffer))

    ctypes.windll.kernel32.GetTickCount.restype = ctypes.c_uint
    current_tick = ctypes.windll.kernel32.GetTickCount()

    # Mask handles the 32-bit tick counter wrapping (~49.7 days)
    idle_milliseconds = (current_tick - buffer[1]) & 0xFFFFFFFF
    return idle_milliseconds / 1000.0


# ---------------------------------------------------------
# Automatic Activity Monitoring Loop
# ---------------------------------------------------------
def start_monitoring():
    global monitor_running, last_tick, is_idle
    if session_ended or monitor_running or break_timer_running:
        return
    monitor_running = True
    is_idle = False
    last_tick = time.monotonic()
    status_label.config(text="Status: Active", fg="#10b981")
    root.after(MONITOR_TICK_MS, monitor_activity)


def monitor_activity():
    global active_work_seconds, total_active_seconds, is_idle, idle_count
    global monitor_running, last_tick

    if not monitor_running:
        return

    # Real elapsed time since the previous tick (after() is never exactly 1s)
    now = time.monotonic()
    elapsed = now - last_tick
    last_tick = now

    idle_seconds = get_idle_seconds()

    if idle_seconds >= IDLE_LIMIT:
        if not is_idle:
            # User just became idle. The seconds between their last input and
            # this tick were wrongly counted as active on earlier ticks, so
            # remove them (excluding this tick, which isn't counted).
            is_idle = True
            idle_count += 1
            overcount = max(0.0, idle_seconds - elapsed)
            active_work_seconds = max(0.0, active_work_seconds - overcount)
            total_active_seconds = max(0.0, total_active_seconds - overcount)
            status_label.config(text="Status: Inactive (Away)", fg="#f59e0b")
    else:
        if is_idle:
            is_idle = False
            status_label.config(text="Status: Active", fg="#10b981")
        active_work_seconds += elapsed
        total_active_seconds += elapsed

    shown = int(active_work_seconds)
    timer_label.config(text=f"{shown // 60:02d}:{shown % 60:02d}")

    if active_work_seconds >= WORK_TARGET:
        monitor_running = False
        open_break_window()
    else:
        root.after(MONITOR_TICK_MS, monitor_activity)


# ---------------------------------------------------------
# Cat GIF Loading
# ---------------------------------------------------------
def load_cat_frames():
    """Read cat.gif and turn every frame into a PhotoImage whose background
    is KEY_COLOR, so Windows can make it see-through.
    Returns ([], []) if Pillow or the GIF is missing - the app still works."""
    try:
        from PIL import Image, ImageChops, ImageSequence, ImageTk
    except ImportError:
        print("Note: run 'pip install pillow' to show the cat during breaks")
        return [], []

    if not os.path.exists(CAT_GIF):
        print(f"Note: {CAT_GIF} not found - breaks will show without the cat")
        return [], []

    try:
        gif = Image.open(CAT_GIF)
        raw_frames, durations = [], []
        for frame in ImageSequence.Iterator(gif):
            raw_frames.append(frame.convert("RGBA"))
            durations.append(max(20, frame.info.get("duration", 100) or 100))

        # Does the GIF already have a transparent background?
        has_alpha = any(f.getextrema()[3][0] < 255 for f in raw_frames)

        # If not, remove the background color (taken from the top-left pixel)
        if not has_alpha and CHROMA_KEY:
            bg = raw_frames[0].getpixel((0, 0))[:3]
            for f in raw_frames:
                rgb = f.convert("RGB")
                diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, bg)).convert("L")
                f.putalpha(diff.point(lambda v: 255 if v > CHROMA_TOLERANCE else 0))

        # Resize to CAT_HEIGHT. Pixel art stays sharp with NEAREST.
        src_w, src_h = raw_frames[0].size
        scale = CAT_HEIGHT / src_h
        size = (max(1, round(src_w * scale)), CAT_HEIGHT)
        resample = Image.NEAREST if scale >= 2 else Image.LANCZOS

        key_rgb = tuple(int(KEY_COLOR[i:i + 2], 16) for i in (1, 3, 5))
        photos = []
        for f in raw_frames:
            f = f.resize(size, resample)
            # Hard edge: a pixel is either fully shown or fully hidden
            mask = f.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
            canvas = Image.new("RGB", size, key_rgb)
            canvas.paste(f.convert("RGB"), mask=mask)
            photos.append(ImageTk.PhotoImage(canvas))
        return photos, durations
    except Exception as e:
        print("Note: could not load cat.gif:", e)
        return [], []


def preload_cat():
    """Load the GIF once at startup so the first break opens instantly."""
    global cat_frames, cat_durations
    if cat_frames is None:
        cat_frames, cat_durations = load_cat_frames()


# ---------------------------------------------------------
# Cat Overlay: walks in, stays animated during the break, walks out
# ---------------------------------------------------------
class CatOverlay:
    def __init__(self, frames, durations):
        self.frames = frames
        self.durations = durations
        self.index = 0
        self.alive = True
        self.phase = "enter"

        self.w = frames[0].width()
        self.h = frames[0].height()
        self.screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        self.x = -self.w                                  # start off-screen on the left
        self.y = screen_h - self.h - CAT_BOTTOM_MARGIN
        self.target_x = (self.screen_w - self.w) // 2     # stop in the middle

        # Borderless window whose KEY_COLOR pixels are see-through
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=KEY_COLOR)
        self.win.attributes("-transparentcolor", KEY_COLOR)

        self.label = tk.Label(self.win, image=frames[0], bg=KEY_COLOR, bd=0, highlightthickness=0)
        self.label.pack()
        self.win.geometry(f"{self.w}x{self.h}+{self.x}+{self.y}")

        self.animate()
        self.move()

    def animate(self):
        """Play the GIF frames in a loop."""
        if not self.alive:
            return
        self.index = (self.index + 1) % len(self.frames)
        self.label.config(image=self.frames[self.index])
        self.win.after(self.durations[self.index], self.animate)

    def move(self):
        """Walk in from the left, stay in the middle, walk out to the right."""
        if not self.alive:
            return
        if self.phase == "enter":
            self.x = min(self.target_x, self.x + CAT_SPEED)
            if self.x >= self.target_x:
                self.phase = "stay"
        elif self.phase == "leave":
            self.x += CAT_SPEED
            if self.x > self.screen_w:
                self.destroy()
                return
        self.win.geometry(f"+{self.x}+{self.y}")
        self.win.after(16, self.move)    # ~60 fps

    def leave(self):
        self.phase = "leave"

    def destroy(self):
        self.alive = False
        try:
            self.win.destroy()
        except tk.TclError:
            pass


# ---------------------------------------------------------
# Break Countdown Box (top-left corner, like "0:52")
# ---------------------------------------------------------
def rounded_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
              x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
              x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def format_countdown(seconds):
    seconds = max(0, math.ceil(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def set_main_window_enabled(enabled):
    # Windows-only: block clicks on the main window during a break
    try:
        root.attributes("-disabled", not enabled)
    except tk.TclError:
        pass


def open_break_window():
    global break_timer_running, break_started_at
    global timer_window, timer_canvas, timer_text, cat_overlay

    global skip_requested
    break_timer_running = True
    break_started_at = time.monotonic()
    skip_requested = False
    set_main_window_enabled(False)

    # Lock the screen first, so the countdown and the cat appear ON TOP of it
    if LOCK_SCREEN:
        open_dim_layer()
        lock_keyboard()

    # Borderless, always-on-top, slightly see-through box with rounded corners
    W, H = 230, 110
    timer_window = tk.Toplevel(root)
    timer_window.overrideredirect(True)
    timer_window.attributes("-topmost", True)
    timer_window.attributes("-alpha", TIMER_ALPHA)
    timer_window.configure(bg=KEY_COLOR)
    timer_window.attributes("-transparentcolor", KEY_COLOR)
    timer_window.geometry(f"{W}x{H}+28+28")

    timer_canvas = tk.Canvas(timer_window, width=W, height=H, bg=KEY_COLOR, highlightthickness=0)
    timer_canvas.pack()
    rounded_rect(timer_canvas, 0, 0, W, H, 26, fill=TIMER_BG)
    timer_text = timer_canvas.create_text(
        W // 2, H // 2,
        text=format_countdown(BREAK_SECONDS),
        font=("Segoe UI", 54, "bold"),
        fill=TIMER_FG
    )

    # The cat walks in (skipped if Pillow or cat.gif is missing)
    preload_cat()
    if cat_frames:
        cat_overlay = CatOverlay(cat_frames, cat_durations)

    root.after(BREAK_TICK_MS, update_break_timer)


def update_break_timer():
    global active_work_seconds

    if not break_timer_running or timer_window is None:
        return

    remaining = max(0.0, BREAK_SECONDS - (time.monotonic() - break_started_at))
    timer_canvas.itemconfig(timer_text, text=format_countdown(remaining))

    if skip_requested:
        # Emergency skip (Ctrl + Shift + Q): end the break early, not counted
        finish_break(completed=False)
        active_work_seconds = 0.0
        timer_label.config(text="00:00")
        start_monitoring()
    elif remaining > 0:
        root.after(BREAK_TICK_MS, update_break_timer)
    else:
        finish_break(completed=True)
        active_work_seconds = 0.0
        timer_label.config(text="00:00")
        start_monitoring()


def finish_break(completed):
    """Close the countdown, send the cat away and record the break time."""
    global break_timer_running, break_started_at, timer_window
    global total_break_seconds, break_count, cat_overlay

    if break_started_at is not None:
        total_break_seconds += time.monotonic() - break_started_at
        break_started_at = None

    break_timer_running = False
    if completed:
        break_count += 1

    # Unlock first, so the user gets control back even if anything below fails
    unlock_keyboard()
    close_dim_layer()

    if timer_window is not None:
        try:
            timer_window.destroy()
        except tk.TclError:
            pass
        timer_window = None

    if cat_overlay is not None:
        if completed:
            cat_overlay.leave()      # walks off the screen, then closes itself
        else:
            cat_overlay.destroy()
            cat_overlay = None

    set_main_window_enabled(True)


# ---------------------------------------------------------
# Helper to format seconds as MM:SS or HH:MM:SS
# ---------------------------------------------------------
def format_duration(seconds):
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ---------------------------------------------------------
# End Session & Report
# ---------------------------------------------------------
def end_session():
    global monitor_running, session_ended, cat_overlay

    # Can be triggered by the button or the window's X - only run once
    if session_ended:
        return
    session_ended = True

    # 1. Stop monitoring, close any unfinished break and remove the cat
    monitor_running = False
    if break_timer_running:
        finish_break(completed=False)
    if cat_overlay is not None:
        cat_overlay.destroy()
        cat_overlay = None

    # 2. Session end time and duration
    session_end = datetime.now().astimezone()
    session_seconds = max(1, round(time.monotonic() - session_start_mono))

    # 3. Metrics: session = active + break + idle
    active_seconds = min(round(total_active_seconds), session_seconds)
    break_seconds = min(round(total_break_seconds), session_seconds - active_seconds)
    idle_seconds = max(0, session_seconds - active_seconds - break_seconds)
    active_rate = round(active_seconds / session_seconds * 100, 1)

    try:
        device_name = socket.gethostname()
    except Exception:
        device_name = "Desktop"

    # Matches the existing screen_break_reports columns exactly
    # (id and created_at are filled in by Supabase).
    # break_seconds is shown in the report window but not stored.
    report_data = {
        "date": session_start.strftime("%Y-%m-%d"),
        "start_time": session_start.strftime("%H:%M:%S"),
        "end_time": session_end.strftime("%H:%M:%S"),
        "session_seconds": session_seconds,
        "active_seconds": active_seconds,
        "idle_seconds": idle_seconds,
        "break_count": break_count,
        "idle_count": idle_count,
        "active_rate": active_rate,
        "device_name": device_name,
    }

    # 4. Save to Supabase in a background thread so the UI never freezes.
    #    Non-daemon thread: if the user closes the app while saving, Python
    #    waits for the insert to finish instead of dropping it.
    save_result = {"status": "pending"}

    def save_worker():
        try:
            # returning="minimal": no SELECT permission needed under RLS
            supabase.table("screen_break_reports").insert(
                report_data, returning="minimal"
            ).execute()
            save_result["status"] = "ok"
        except Exception as e:
            print("Note: Could not save to Supabase cloud:", e)
            save_result["status"] = "error"

    threading.Thread(target=save_worker, daemon=False).start()

    root.withdraw()
    show_report_window(
        session_seconds=session_seconds,
        active_seconds=active_seconds,
        idle_seconds=idle_seconds,
        break_seconds=break_seconds,
        break_count=break_count,
        idle_count=idle_count,
        active_rate=active_rate,
        save_result=save_result,
    )


def show_report_window(session_seconds, active_seconds, idle_seconds, break_seconds,
                       break_count, idle_count, active_rate, save_result):
    report_window = tk.Toplevel(root)
    report_window.title("Session Report")
    report_window.geometry("380x500")
    report_window.configure(bg="#ffffff")
    report_window.resizable(False, False)
    report_window.protocol("WM_DELETE_WINDOW", root.destroy)

    tk.Label(
        report_window,
        text="Session Report",
        font=("Segoe UI", 16, "bold"),
        fg="#1e293b",
        bg="#ffffff"
    ).pack(pady=(25, 4))

    # Save status badge - starts as "Saving..." and updates when the thread finishes
    save_badge = tk.Label(
        report_window,
        text="Saving to Supabase...",
        font=("Segoe UI", 9),
        fg="#94a3b8",
        bg="#ffffff"
    )
    save_badge.pack(pady=(0, 15))

    def poll_save_status():
        # Tkinter isn't thread-safe, so the UI is updated from the main
        # thread by polling the result the worker wrote.
        status = save_result["status"]
        if status == "pending":
            report_window.after(200, poll_save_status)
        elif status == "ok":
            save_badge.config(text="Data saved to Supabase successfully", fg="#10b981")
        else:
            save_badge.config(text="Report generated (Offline mode)", fg="#f59e0b")

    poll_save_status()

    card = tk.Frame(
        report_window,
        bg="#f8fafc",
        padx=20,
        pady=15,
        highlightbackground="#e2e8f0",
        highlightthickness=1
    )
    card.pack(fill="x", padx=25, pady=5)

    metrics = [
        ("Session Duration", format_duration(session_seconds)),
        ("Active Work Time", format_duration(active_seconds)),
        ("Break Time", format_duration(break_seconds)),
        ("Idle Time", format_duration(idle_seconds)),
        ("Breaks Completed", str(break_count)),
        ("Idle Events", str(idle_count)),
        ("Active Rate", f"{active_rate}%"),
    ]

    for label_text, val_text in metrics:
        row = tk.Frame(card, bg="#f8fafc")
        row.pack(fill="x", pady=5)
        tk.Label(row, text=label_text, font=("Segoe UI", 10),
                 fg="#64748b", bg="#f8fafc").pack(side="left")
        tk.Label(row, text=val_text, font=("Segoe UI", 10, "bold"),
                 fg="#1e293b", bg="#f8fafc").pack(side="right")

    tk.Button(
        report_window,
        text="Close",
        font=("Segoe UI", 10, "bold"),
        bg="#4a80e8",
        fg="#ffffff",
        activebackground="#3b6fc9",
        activeforeground="#ffffff",
        relief="flat",
        padx=30,
        pady=9,
        cursor="hand2",
        command=root.destroy
    ).pack(pady=(25, 20))


# ---------------------------------------------------------
# Main Window Setup
# ---------------------------------------------------------
root = tk.Tk()
root.title("Screen Break Reminder")
root.geometry("380x300")
root.configure(bg="#ffffff")
root.resizable(False, False)

# Closing the main window with X ends the session properly (report + save)
root.protocol("WM_DELETE_WINDOW", end_session)

tk.Label(
    root,
    text="Screen Break Reminder",
    font=("Segoe UI", 16, "bold"),
    fg="#1e293b",
    bg="#ffffff"
).pack(pady=(25, 4))

status_label = tk.Label(
    root,
    text="Status: Active",
    font=("Segoe UI", 10),
    fg="#10b981",
    bg="#ffffff"
)
status_label.pack(pady=(0, 6))

timer_label = tk.Label(
    root,
    text="00:00",
    font=("Segoe UI", 46, "bold"),
    fg="#1e293b",
    bg="#ffffff"
)
timer_label.pack(pady=(5, 15))

button_frame = tk.Frame(root, bg="#ffffff")
button_frame.pack(pady=(5, 20))

tk.Button(
    button_frame,
    text="End Session",
    font=("Segoe UI", 10, "bold"),
    bg="#e57373",
    fg="#ffffff",
    activebackground="#d66060",
    activeforeground="#ffffff",
    relief="flat",
    padx=22,
    pady=9,
    cursor="hand2",
    command=end_session
).pack()

# ---------------------------------------------------------
# Start Automatic Monitoring & Main Loop
# ---------------------------------------------------------
root.after(300, preload_cat)
start_monitoring()
try:
    root.mainloop()
finally:
    unlock_keyboard()       # Never leave the keyboard locked, even after a crash
