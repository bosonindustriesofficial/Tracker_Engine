# Boson Plant Monitor — Engine API Guide

## 1. Purpose

This document explains how the frontend/UI should communicate with the
Boson Plant Monitor engine.

The goal is to keep the UI completely separate from the plant-monitoring
logic. The UI developer should use the public API described below and should
not directly modify or access the engine's internal data structures.

Recommended project layout:

    BosonPlantMonitor/
    ├── BosonPlantMonitor_ENGINE.py
    ├── BosonPlantMonitor_UI.py
    └── plant_data.csv

Run the application from the UI file:

    python BosonPlantMonitor_UI.py

The UI imports the engine:

    import BosonPlantMonitor_ENGINE as engine


## 2. Architecture

    Pico devices
       |
       | TCP / JSON
       v
    ENGINE
       |
       +--> Device Manager
       +--> Packet Queue
       +--> Statistics
       +--> CSV Logger
       +--> Online/Offline Monitor
       |
       | public API
       v
    UI / UX

The UI should consume engine information through the public API.

The UI should NOT directly manipulate:

    devices
    devices_lock
    packet_queue
    total_packets
    total_errors
    csv_writer
    server_running

These are engine-owned resources.


## 3. Public Engine API

The current engine exposes these functions for the frontend:

    engine.start_engine()
    engine.stop_engine()
    engine.get_devices_snapshot()
    engine.get_statistics()
    engine.get_server_config()


## 4. engine.start_engine()

Starts the engine's background services:

- TCP server
- packet processor
- device monitor

Call once when the application starts.

Example:

    import BosonPlantMonitor_ENGINE as engine

    engine.start_engine()


## 5. engine.stop_engine()

Stops the engine and closes the CSV logger.

Example:

    def shutdown():
        engine.stop_engine()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", shutdown)

The UI should not directly close the engine's CSV file or manipulate
server-running state.


## 6. engine.get_devices_snapshot()

Returns a safe snapshot of currently known device states.

This is the primary API for the live device dashboard.

Example:

    devices = engine.get_devices_snapshot()

    for device in devices:
        print(device["device_id"])
        print(device["online"])
        print(device["ip_address"])

Example device structure:

    {
        "device_id": "PICO_001",
        "ip_address": "192.168.1.12",
        "online": True,
        "last_seen": datetime(...),
        "last_sequence": 104,
        "packet_count": 104,
        "temperature": 25.42,
        "water_level": 81.20,
        "pressure": 101.32
    }

Field meanings:

device_id
    Application-level identity of the Pico.

ip_address
    IP address from the most recently received packet.

online
    True if the engine currently considers the device online.

last_seen
    Python datetime corresponding to the most recently received packet.

last_sequence
    Sequence number from the most recently processed packet.

packet_count
    Number of packets processed for that device.

temperature
    Most recently received temperature value.

water_level
    Most recently received water-level value.

pressure
    Most recently received pressure value.


## 7. Example: Building a Device Table

The UI can refresh a table periodically:

    def refresh_devices():
        devices = engine.get_devices_snapshot()

        for device in devices:
            device_id = device["device_id"]

            status = "ONLINE" if device["online"] else "OFFLINE"

            temperature = device["temperature"]
            level = device["water_level"]
            pressure = device["pressure"]

            # Update your UI widgets here.

        root.after(500, refresh_devices)

The engine remains completely unaware of how the table is displayed.


## 8. engine.get_statistics()

Returns global engine statistics.

Example:

    stats = engine.get_statistics()

    print("Packets:", stats["total_packets"])
    print("Errors:", stats["total_errors"])

Current structure:

    {
        "total_packets": 1234,
        "total_errors": 5
    }

Example dashboard cards:

    stats = engine.get_statistics()

    packet_count_label.config(
        text=f"PACKETS: {stats['total_packets']}"
    )

    error_count_label.config(
        text=f"ERRORS: {stats['total_errors']}"
    )


## 9. engine.get_server_config()

Returns server configuration needed by the UI.

Example:

    config = engine.get_server_config()

    print(config["host"])
    print(config["port"])
    print(config["max_devices"])
    print(config["offline_timeout"])

Current structure:

    {
        "host": "0.0.0.0",
        "port": 5000,
        "max_devices": 8,
        "offline_timeout": 10
    }

Example:

    config = engine.get_server_config()

    port_label.config(
        text=f"PORT: {config['port']}"
    )


## 10. Recommended UI Refresh Pattern

The UI should periodically ask the engine for snapshots:

    def update_dashboard():

        devices = engine.get_devices_snapshot()
        stats = engine.get_statistics()

        update_device_table(devices)
        update_statistics(stats)

        root.after(500, update_dashboard)

This keeps the Tkinter UI thread responsible for UI updates while the
engine handles networking in its own background threads.


## 11. Complete Minimal UI Skeleton

    import tkinter as tk
    import BosonPlantMonitor_ENGINE as engine

    root = tk.Tk()
    root.title("Boson Plant Monitor")

    def update_dashboard():

        devices = engine.get_devices_snapshot()
        stats = engine.get_statistics()

        print("Known devices:", len(devices))
        print("Packets:", stats["total_packets"])
        print("Errors:", stats["total_errors"])

        for device in devices:
            print(
                device["device_id"],
                device["online"],
                device["temperature"]
            )

        root.after(500, update_dashboard)

    def shutdown():

        engine.stop_engine()
        root.destroy()

    engine.start_engine()

    root.protocol("WM_DELETE_WINDOW", shutdown)

    update_dashboard()

    root.mainloop()


## 12. Formatting Data for the UI

The engine returns raw values. The UI owns presentation.

Example:

    temperature = device["temperature"]

    if temperature is None:
        text = "--"
    else:
        text = f"{temperature:.2f} °C"

Similarly:

    level = device["water_level"]

    if level is None:
        text = "--"
    else:
        text = f"{level:.2f} %"

The engine should not contain GUI-specific formatting such as labels,
colors, fonts, widget names, or layout decisions.


## 13. Online / Offline Display

Use the engine's `online` field.

Example:

    if device["online"]:
        status = "● ONLINE"
    else:
        status = "● OFFLINE"

The UI may choose any visual representation:

- text
- color
- icon
- badge
- card
- table row
- animation

Those decisions belong entirely to the frontend.


## 14. Important Threading Rule

The engine uses background threads for network handling and processing.

The UI should NOT attempt to update Tkinter widgets from engine threads.

Correct pattern:

    engine background threads
            |
            v
    engine state
            |
            v
    UI periodically reads snapshot
            |
            v
    Tkinter main thread updates widgets

Do not do this from an engine callback/thread:

    label.config(...)

Instead, let the UI's `after()` loop read the engine state.


## 15. Multiple Pico Devices

The engine is designed for multiple devices.

A UI should not assume that only PICO_001 exists.

Example:

    devices = engine.get_devices_snapshot()

    for device in devices:
        render_device(device)

The device ID is the application's identity for a Pico.

Do NOT use the IP address as the device identity.

    device["device_id"]     # identity
    device["ip_address"]    # network information

A device may receive a different DHCP IP address while retaining the same
device_id.


## 16. Handling Missing Sensor Values

Sensor values may be None if a packet does not contain that field.

Always handle this safely:

    value = device["temperature"]

    if value is None:
        display_value = "--"
    else:
        display_value = f"{value:.2f}"


## 17. What the UI Developer CAN Change

The frontend developer can freely modify:

- Tkinter widgets
- Window layout
- Fonts
- Colors
- Icons
- Tables
- Cards
- Status indicators
- Navigation
- Graphs
- Charts
- Dashboard arrangement
- Menus
- Buttons
- Themes
- UX behavior
- Screen transitions

As long as the UI continues to use the public engine API, the backend does
not need to be changed for visual redesigns.


## 18. What the UI Developer SHOULD NOT Change

Do not modify engine internals just to redesign the UI.

Avoid directly accessing:

    devices
    devices_lock
    packet_queue
    csv_file
    csv_writer
    csv_lock
    server_running
    total_packets
    total_errors
    statistics_lock

If a future UI feature needs information that is not currently exposed,
request a new public engine API rather than reaching into an internal
variable.


## 19. Example: Future API Expansion

If the UI eventually needs historical data, alarms, device details, or other
information, the preferred pattern is to add a public function such as:

    engine.get_device_history("PICO_001")

or:

    engine.get_alarms()

or:

    engine.get_latest_packets()

The exact APIs should be designed and implemented in the engine before the
UI starts depending on them.

This will become particularly useful when SQLite is introduced.


## 20. Current Data Flow

    Pico
      |
      | TCP JSON packet
      v
    Client handler thread
      |
      | validation + metadata
      v
    ACK sent
      |
      v
    Central packet queue
      |
      v
    Packet processor
      |
      +--> update device state
      |
      +--> update statistics
      |
      +--> write CSV
      |
      v
    UI reads snapshot
      |
      v
    Dashboard


## 21. ACK Note

The current engine sends the ACK immediately after basic packet validation
and before the packet is processed by the central queue.

Therefore, the current ACK means approximately:

    "The server received and accepted the packet format."

It does NOT currently mean:

    "The packet has definitely been persisted to permanent storage."

This distinction should be preserved when designing future UI status
indicators.

A future production architecture may change the ACK semantics when database
persistence is introduced.


## 22. CSV Note

The current engine writes telemetry to:

    plant_data.csv

The UI should treat the CSV as engine-owned data storage.

The UI should not open, modify, or lock the CSV file directly.

Future database integration should similarly remain inside the engine.


## 23. Recommended Development Rule

Frontend developers should think of the engine as a service/library:

    "Give me the current plant state."

rather than:

    "Let me inspect the engine's internal variables."

Good:

    devices = engine.get_devices_snapshot()

Avoid:

    devices = engine.devices

Good:

    stats = engine.get_statistics()

Avoid:

    packets = engine.total_packets


## 24. Quick API Cheat Sheet

    # Start backend
    engine.start_engine()

    # Stop backend
    engine.stop_engine()

    # Get current devices
    devices = engine.get_devices_snapshot()

    # Get global statistics
    stats = engine.get_statistics()

    # Get server settings
    config = engine.get_server_config()


## 25. Design Principle

    ENGINE = What the system DOES

    UI = How the system LOOKS

The engine owns plant communication, data processing, device state,
statistics, persistence, and system behavior.

The UI owns presentation, visualization, navigation, and user experience.

Keeping this boundary clean will allow the Boson Plant Monitor frontend to
evolve independently while the same engine continues to support real Pico
devices, multiple simultaneous devices, virtual devices, CSV storage, and
future SQLite/database functionality.
