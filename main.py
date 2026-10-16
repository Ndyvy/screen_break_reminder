import tkinter as tk
import ctypes
from datetime import datetime
import socket
from supabase import create_client

# ---------------------------------------------------------
# Supabase Configuration
# ---------------------------------------------------------
SUPABASE_URL = "https://bmtiwolfusrtqnyhpsbr.supabase.co"
SUPABASE_KEY = "sb_publishable_oscxtHoJELmPC3EsaK6qdg_SSPys9k-"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------------
# Settings and Constants
# ---------------------------------------------------------
DEMO_MODE = True            # Set to True for testing, False for normal use

if DEMO_MODE:
    WORK_TARGET = 10        # 10 seconds of active work for demo
    IDLE_LIMIT = 5          # 5 seconds of inactivity considered idle for demo
    BREAK_SECONDS = 10      # 10 seconds break duration for demo
else:
    WORK_TARGET = 3600      # 3600 seconds (1 hour) of active work
    IDLE_LIMIT = 300        # 300 seconds (5 minutes) of inactivity
    BREAK_SECONDS = 60      # 60 seconds break duration

# ---------------------------------------------------------
# Tracking Variables
# ---------------------------------------------------------
session_start = datetime.now()   # Records when this session began
active_work_seconds = 0          # Active work seconds for current interval (resets after break)
total_active_seconds = 0         # Cumulative active seconds across the entire session
break_count = 0                  # Number of breaks completed
idle_count = 0                   # Number of times user became idle
is_idle = False                  # True when user has been inactive for >= IDLE_LIMIT
monitor_running = False          # True when monitoring loop is active

break_remaining = BREAK_SECONDS
break_timer_running = False
break_window = None

# ---------------------------------------------------------
# Windows Activity Detection (Keyboard & Mouse)
# ---------------------------------------------------------
def get_idle_seconds():
    # In Windows, GetLastInputInfo gives the timestamp (tick count) of the last
    # physical keyboard or mouse input across the entire computer.
    buffer = (ctypes.c_uint * 2)(8, 0)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(buffer))

    ctypes.windll.kernel32.GetTickCount.restype = ctypes.c_uint
    current_tick = ctypes.windll.kernel32.GetTickCount()

    idle_milliseconds = (current_tick - buffer[1]) & 0xFFFFFFFF
    return idle_milliseconds / 1000.0

# ---------------------------------------------------------
# Automatic Activity Monitoring Loop
# ---------------------------------------------------------
def start_monitoring():
    global monitor_running
    if not monitor_running and not break_timer_running:
        monitor_running = True
        root.after(1000, monitor_activity)

def monitor_activity():
    global active_work_seconds, total_active_seconds, is_idle, idle_count, monitor_running

    if not monitor_running:
        return

    # Measure how many seconds since the last keyboard or mouse input
    idle_seconds = get_idle_seconds()

    # If the user has been inactive for >= IDLE_LIMIT
    if idle_seconds >= IDLE_LIMIT:
        if not is_idle:
            # User just became idle: increment idle count and deduct the waiting threshold
            is_idle = True
            idle_count += 1
            active_work_seconds = max(0, active_work_seconds - IDLE_LIMIT)
            total_active_seconds = max(0, total_active_seconds - IDLE_LIMIT)
            status_label.config(text="Status: Inactive (Away)", fg="#f59e0b")
    else:
        if is_idle:
            # User returned and pressed a key or moved the mouse
            is_idle = False
            status_label.config(text="Status: Active", fg="#10b981")

        # User is actively working, count this second
        active_work_seconds += 1
        total_active_seconds += 1

    # Format and update the MM:SS display
    minutes = active_work_seconds // 60
    seconds = active_work_seconds % 60
    timer_label.config(text=f"{minutes:02d}:{seconds:02d}")

    # Check if accumulated active work time has reached the target
    if active_work_seconds >= WORK_TARGET:
        monitor_running = False
        open_break_window()
    else:
        root.after(1000, monitor_activity)

# ---------------------------------------------------------
# Break Time Window & Circular Countdown
# ---------------------------------------------------------
def open_break_window():
    global break_window, break_remaining, break_timer_running
    global break_canvas, break_ring, break_text

    break_remaining = BREAK_SECONDS
    break_timer_running = True

    # Create the popup window
    break_window = tk.Toplevel(root)
    break_window.title("Break Time")
    break_window.geometry("380x380")
    break_window.configure(bg="#ffffff")
    break_window.resizable(False, False)

    # Prevent user from closing with 'X' button
    def ignore_close():
        pass

    break_window.protocol("WM_DELETE_WINDOW", ignore_close)

    # Title label inside break window
    title = tk.Label(
        break_window,
        text="Time for a Break!",
        font=("Segoe UI", 16, "bold"),
        fg="#1e293b",
        bg="#ffffff"
    )
    title.pack(pady=(28, 10))

    # Canvas for circular countdown
    break_canvas = tk.Canvas(
        break_window,
        width=220,
        height=220,
        bg="#ffffff",
        highlightthickness=0
    )
    break_canvas.pack(pady=10)

    # Background ring track
    break_canvas.create_oval(
        30, 30, 190, 190,
        outline="#edf2f7",
        width=6
    )

    # Countdown progress arc
    break_ring = break_canvas.create_arc(
        30, 30, 190, 190,
        start=90,
        extent=-359.9,
        outline="#4a80e8",
        width=6,
        style="arc"
    )

    # Center countdown number
    break_text = break_canvas.create_text(
        110, 102,
        text=str(BREAK_SECONDS),
        font=("Segoe UI", 34, "bold"),
        fill="#1e293b"
    )

    # "seconds" label
    break_canvas.create_text(
        110, 128,
        text="seconds",
        font=("Segoe UI", 10),
        fill="#94a3b8"
    )

    # Start break countdown
    root.after(1000, update_break_timer)

def update_break_timer():
    global break_remaining, break_timer_running, break_window, active_work_seconds, break_count

    if not break_timer_running or break_window is None:
        return

    if break_remaining > 0:
        break_remaining -= 1

        # Update number and progress ring
        break_canvas.itemconfig(break_text, text=str(break_remaining))
        fraction = break_remaining / BREAK_SECONDS
        angle = -359.9 * fraction if fraction > 0 else 0
        break_canvas.itemconfig(break_ring, extent=angle)

        if break_remaining > 0:
            root.after(1000, update_break_timer)
        else:
            # Break finished: increment breaks completed, close window, resume
            break_count += 1
            break_timer_running = False
            break_window.destroy()
            break_window = None

            active_work_seconds = 0
            timer_label.config(text="00:00")
            start_monitoring()

# ---------------------------------------------------------
# Helper to format seconds as MM:SS or HH:MM:SS
# ---------------------------------------------------------
def format_duration(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

# ---------------------------------------------------------
# End Session & Report Window
# ---------------------------------------------------------
def end_session():
    global monitor_running, break_timer_running, break_window

    # 1. Stop monitoring and close any active break window
    monitor_running = False
    break_timer_running = False
    if break_window is not None:
        try:
            break_window.destroy()
        except Exception:
            pass

    # 2. Record session_end
    session_end = datetime.now()

    # 3. Calculate session metrics
    session_seconds = max(1, int((session_end - session_start).total_seconds()))
    active_seconds = total_active_seconds
    idle_seconds = max(0, session_seconds - active_seconds)
    active_rate = round((active_seconds / session_seconds) * 100, 1)

    date_str = session_start.strftime("%Y-%m-%d")
    start_time_str = session_start.strftime("%H:%M:%S")
    end_time_str = session_end.strftime("%H:%M:%S")

    try:
        device_name = socket.gethostname()
    except Exception:
        device_name = "Desktop"

    # 4. Insert report row into Supabase (Columns requested)
    report_data = {
        "date": date_str,
        "start_time": start_time_str,
        "end_time": end_time_str,
        "session_seconds": session_seconds,
        "active_seconds": active_seconds,
        "idle_seconds": idle_seconds,
        "break_count": break_count,
        "idle_count": idle_count,
        "active_rate": active_rate,
        "device_name": device_name
    }

    # 5. Use try/except so the app does not crash if Supabase fails
    saved_to_cloud = False
    try:
        supabase.table("screen_break_reports").insert(report_data).execute()
        saved_to_cloud = True
    except Exception as e:
        print("Note: Could not save to Supabase cloud:", e)

    # Hide the main window and display the Session Report window
    root.withdraw()
    show_report_window(
        session_seconds=session_seconds,
        active_seconds=active_seconds,
        idle_seconds=idle_seconds,
        break_count=break_count,
        idle_count=idle_count,
        active_rate=active_rate,
        saved_to_cloud=saved_to_cloud
    )

# ---------------------------------------------------------
# Session Report Window (Requirement 6 & 7)
# ---------------------------------------------------------
def show_report_window(session_seconds, active_seconds, idle_seconds, break_count, idle_count, active_rate, saved_to_cloud):
    report_window = tk.Toplevel(root)
    report_window.title("Session Report")
    report_window.geometry("380x460")
    report_window.configure(bg="#ffffff")
    report_window.resizable(False, False)

    # Make closing the report window cleanly close the whole app
    report_window.protocol("WM_DELETE_WINDOW", root.destroy)

    # Title
    title = tk.Label(
        report_window,
        text="Session Report",
        font=("Segoe UI", 16, "bold"),
        fg="#1e293b",
        bg="#ffffff"
    )
    title.pack(pady=(25, 4))

    # Cloud Save Status Note
    status_text = "Data saved to Supabase successfully" if saved_to_cloud else "Report generated (Offline mode)"
    status_color = "#10b981" if saved_to_cloud else "#f59e0b"
    save_badge = tk.Label(
        report_window,
        text=status_text,
        font=("Segoe UI", 9),
        fg=status_color,
        bg="#ffffff"
    )
    save_badge.pack(pady=(0, 15))

    # Metrics Card Container
    card = tk.Frame(
        report_window,
        bg="#f8fafc",
        padx=20,
        pady=15,
        highlightbackground="#e2e8f0",
        highlightthickness=1
    )
    card.pack(fill="x", padx=25, pady=5)

    # The 6 metrics required
    metrics = [
        ("Session Duration", format_duration(session_seconds)),
        ("Active Work Time", format_duration(active_seconds)),
        ("Idle Time", format_duration(idle_seconds)),
        ("Breaks Completed", str(break_count)),
        ("Idle Events", str(idle_count)),
        ("Active Rate", f"{active_rate}%")
    ]

    for label_text, val_text in metrics:
        row = tk.Frame(card, bg="#f8fafc")
        row.pack(fill="x", pady=5)

        lbl = tk.Label(
            row,
            text=label_text,
            font=("Segoe UI", 10),
            fg="#64748b",
            bg="#f8fafc"
        )
        lbl.pack(side="left")

        val = tk.Label(
            row,
            text=val_text,
            font=("Segoe UI", 10, "bold"),
            fg="#1e293b",
            bg="#f8fafc"
        )
        val.pack(side="right")

    # Requirement 7: Close button to close application
    close_button = tk.Button(
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
    )
    close_button.pack(pady=(25, 20))

# ---------------------------------------------------------
# Main Window Setup
# ---------------------------------------------------------
root = tk.Tk()
root.title("Screen Break Reminder")
root.geometry("380x300")
root.configure(bg="#ffffff")
root.resizable(False, False)

# Main Title Label
title_label = tk.Label(
    root,
    text="Screen Break Reminder",
    font=("Segoe UI", 16, "bold"),
    fg="#1e293b",
    bg="#ffffff"
)
title_label.pack(pady=(25, 4))

# Status Label (Shows if user is Active or Away)
status_label = tk.Label(
    root,
    text="Status: Active",
    font=("Segoe UI", 10),
    fg="#10b981",
    bg="#ffffff"
)
status_label.pack(pady=(0, 6))

# Active Work Timer Display (MM:SS)
timer_label = tk.Label(
    root,
    text="00:00",
    font=("Segoe UI", 46, "bold"),
    fg="#1e293b",
    bg="#ffffff"
)
timer_label.pack(pady=(5, 15))

# Button Container (Only End Session button)
button_frame = tk.Frame(root, bg="#ffffff")
button_frame.pack(pady=(5, 20))

# "End Session" Button
end_button = tk.Button(
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
)
end_button.pack()

# ---------------------------------------------------------
# Start Automatic Monitoring & Main Loop
# ---------------------------------------------------------
start_monitoring()
root.mainloop()
