import tkinter as tk

# ---------------------------------------------------------
# Functions (Actions for Buttons)
# ---------------------------------------------------------
def start_work():
    # This runs when the "Start Work" button is clicked
    print("Work session started!")

def end_session():
    # This runs when the "End Session" button is clicked
    # It closes the application window
    root.destroy()

# ---------------------------------------------------------
# Main Window Setup
# ---------------------------------------------------------
root = tk.Tk()
root.title("Screen Break Reminder")
root.geometry("360x260")
root.configure(bg="#f4f6f9")
root.resizable(False, False)

# ---------------------------------------------------------
# Title Label (Optional description at the top)
# ---------------------------------------------------------
title_label = tk.Label(
    root,
    text="Screen Break Reminder",
    font=("Arial", 14, "bold"),
    fg="#333333",
    bg="#f4f6f9"
)
title_label.pack(pady=(25, 10))

# ---------------------------------------------------------
# Large Timer Display
# ---------------------------------------------------------
timer_label = tk.Label(
    root,
    text="00:00",
    font=("Arial", 46, "bold"),
    fg="#1e293b",
    bg="#f4f6f9"
)
timer_label.pack(pady=10)

# ---------------------------------------------------------
# Button Container (Frame to place buttons side by side)
# ---------------------------------------------------------
button_frame = tk.Frame(root, bg="#f4f6f9")
button_frame.pack(pady=(15, 20))

# "Start Work" Button
start_button = tk.Button(
    button_frame,
    text="Start Work",
    font=("Arial", 11, "bold"),
    bg="#2563eb",
    fg="white",
    activebackground="#1d4ed8",
    activeforeground="white",
    relief="flat",
    padx=16,
    pady=8,
    cursor="hand2",
    command=start_work
)
start_button.pack(side="left", padx=8)

# "End Session" Button
end_button = tk.Button(
    button_frame,
    text="End Session",
    font=("Arial", 11, "bold"),
    bg="#ef4444",
    fg="white",
    activebackground="#dc2626",
    activeforeground="white",
    relief="flat",
    padx=16,
    pady=8,
    cursor="hand2",
    command=end_session
)
end_button.pack(side="left", padx=8)

# ---------------------------------------------------------
# Start the Tkinter Event Loop
# ---------------------------------------------------------
root.mainloop()
