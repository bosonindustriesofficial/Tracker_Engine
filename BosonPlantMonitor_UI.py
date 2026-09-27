import tkinter as tk
from tkinter import ttk
from datetime import datetime

import BosonPlantMonitor_ENGINE as engine


# ============================================================
# GUI
# ============================================================

class BosonGUI:

    def __init__(self, root):
        self.root = root

        self.root.title("Boson Plant Monitor")
        self.root.geometry("1250x600")
        self.root.minsize(1050, 500)

        # ----------------------------------------------------
        # Main title
        # ----------------------------------------------------

        title = tk.Label(
            root,
            text="BOSON PLANT MONITOR",
            font=("Segoe UI", 22, "bold")
        )
        title.pack(pady=(15, 2))

        subtitle = tk.Label(
            root,
            text="Live Production Barcode Tracking System",
            font=("Segoe UI", 11)
        )
        subtitle.pack(pady=(0, 15))

        # ----------------------------------------------------
        # Status frame
        # ----------------------------------------------------

        status_frame = tk.Frame(root)
        status_frame.pack(fill="x", padx=20)

        self.server_status = tk.Label(
            status_frame,
            text="● SERVER RUNNING",
            font=("Segoe UI", 11, "bold")
        )
        self.server_status.pack(side="left")

        config = engine.get_server_config()

        self.port_label = tk.Label(
            status_frame,
            text=f"PORT: {config['server_port']}",
            font=("Segoe UI", 11)
        )
        self.port_label.pack(side="left", padx=30)

        self.device_count_label = tk.Label(
            status_frame,
            text=f"DEVICES: 0 / {config['max_devices']}",
            font=("Segoe UI", 11)
        )
        self.device_count_label.pack(side="left")

        self.last_update_label = tk.Label(
            status_frame,
            text="LAST UPDATE: --",
            font=("Segoe UI", 11)
        )
        self.last_update_label.pack(side="right")

        # ----------------------------------------------------
        # Separator
        # ----------------------------------------------------

        ttk.Separator(
            root,
            orient="horizontal"
        ).pack(fill="x", padx=20, pady=15)

        # ----------------------------------------------------
        # Device table
        # ----------------------------------------------------

        table_frame = tk.Frame(root)
        table_frame.pack(fill="both", expand=True, padx=20)

        columns = (
            "device",
            "status",
            "ip",
            "barcode",
            "product",
            "batch",
            "sequence",
            "count",
            "last_seen"
        )

        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            height=8
        )

        headings = {
            "device": "DEVICE ID",
            "status": "STATUS",
            "ip": "IP ADDRESS",
            "barcode": "BARCODE ID",
            "product": "PRODUCT",
            "batch": "BATCH",
            "sequence": "SEQUENCE",
            "count": "PACKETS",
            "last_seen": "LAST RX"
        }

        widths = {
            "device": 110,
            "status": 100,
            "ip": 125,
            "barcode": 285,
            "product": 80,
            "batch": 150,
            "sequence": 80,
            "count": 80,
            "last_seen": 110
        }

        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(
                column,
                width=widths[column],
                anchor="center"
            )

        self.tree.pack(fill="both", expand=True)

        # ----------------------------------------------------
        # Bottom statistics
        # ----------------------------------------------------

        ttk.Separator(
            root,
            orient="horizontal"
        ).pack(fill="x", padx=20, pady=15)

        bottom_frame = tk.Frame(root)
        bottom_frame.pack(
            fill="x",
            padx=20,
            pady=(0, 15)
        )

        self.packet_label = tk.Label(
            bottom_frame,
            text="TOTAL BARCODES: 0",
            font=("Segoe UI", 10, "bold")
        )
        self.packet_label.pack(side="left")

        self.error_label = tk.Label(
            bottom_frame,
            text="ERRORS: 0",
            font=("Segoe UI", 10, "bold")
        )
        self.error_label.pack(side="left", padx=30)

        self.queue_label = tk.Label(
            bottom_frame,
            text="QUEUE: 0",
            font=("Segoe UI", 10, "bold")
        )
        self.queue_label.pack(side="left")

        self.csv_label = tk.Label(
            bottom_frame,
            text=f"LOG: {config['csv_file']}",
            font=("Segoe UI", 10)
        )
        self.csv_label.pack(side="right")

        self.update_gui()

    # ========================================================
    # UPDATE GUI
    # ========================================================

    def update_gui(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        current_devices = engine.get_devices_snapshot()

        for device_id in sorted(current_devices.keys()):
            device = current_devices[device_id]

            status = "● ONLINE" if device["online"] else "● OFFLINE"

            barcode = device["last_barcode_id"] or "--"
            product = device["product_code"] or "--"
            batch = device["batch"] or "--"

            sequence = device["barcode_sequence"]
            sequence_text = "--" if sequence is None else str(sequence)

            packet_count = device["packet_count"]

            if device["last_seen"]:
                last_seen = device["last_seen"].strftime("%H:%M:%S")
            else:
                last_seen = "--"

            self.tree.insert(
                "",
                "end",
                values=(
                    device_id,
                    status,
                    device["ip_address"],
                    barcode,
                    product,
                    batch,
                    sequence_text,
                    packet_count,
                    last_seen
                )
            )

        stats = engine.get_statistics()
        config = engine.get_server_config()

        online_count = sum(
            1 for device in current_devices.values()
            if device["online"]
        )

        self.device_count_label.config(
            text=f"DEVICES: {online_count} / {config['max_devices']}"
        )

        self.packet_label.config(
            text=f"TOTAL BARCODES: {stats['total_packets']}"
        )

        self.error_label.config(
            text=f"ERRORS: {stats['total_errors']}"
        )

        self.queue_label.config(
            text=f"QUEUE: {stats['queued_packets']}"
        )

        self.last_update_label.config(
            text=(
                "LAST UPDATE: "
                + datetime.now().strftime("%H:%M:%S")
            )
        )

        self.root.after(500, self.update_gui)


# ============================================================
# SHUTDOWN
# ============================================================


def shutdown():
    engine.stop_engine()
    root.destroy()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    engine.start_engine()

    root = tk.Tk()
    app = BosonGUI(root)

    root.protocol(
        "WM_DELETE_WINDOW",
        shutdown
    )

    root.mainloop()
