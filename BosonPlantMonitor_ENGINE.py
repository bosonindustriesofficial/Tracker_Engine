import socket
import threading
import queue
import json
import csv
import os
import time
import re
from datetime import datetime, date


# ============================================================
# CONFIGURATION
# ============================================================

SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5000

MAX_DEVICES = 8
OFFLINE_TIMEOUT = 10          # seconds

LOG_ROOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "logs",
)

CSV_HEADER = [
    "timestamp",
    "device_id",
    "ip_address",
    "sequence",
    "barcode_id",
    "product_code",
    "batch",
    "barcode_sequence",
]


# ============================================================
# GLOBAL DATA STRUCTURES
# ============================================================

packet_queue = queue.Queue()
devices = {}
devices_lock = threading.Lock()

server_running = True

total_packets = 0
total_errors = 0
statistics_lock = threading.Lock()


# ============================================================
# GS1 BARCODE PARSER
# ============================================================

GS1_PATTERN = re.compile(
    r"^\(91\)(?P<product>\d{3})"
    r"\(10\)(?P<batch>.*)"
    r"\(21\)(?P<sequence>\d{4})$"
)


def parse_barcode_id(barcode_id):
    """Parse the exact textual GS1 format produced by the barcode generator.

    Expected form:
        (91)001(10)260915AX4(21)0001

    Returns product_code, batch, and barcode_sequence.
    Raises ValueError if the format is invalid.
    """

    if not isinstance(barcode_id, str) or not barcode_id:
        raise ValueError("barcode_id must be a non-empty string")

    match = GS1_PATTERN.match(barcode_id.strip())

    if not match:
        raise ValueError(
            "Invalid barcode format. Expected "
            "(91)PPP(10)BATCH(21)SSSS"
        )

    product_code = match.group("product")
    batch = match.group("batch")
    sequence_text = match.group("sequence")

    if not batch:
        raise ValueError("Barcode batch is empty")

    sequence = int(sequence_text)

    if not 1 <= sequence <= 5000:
        raise ValueError("Barcode sequence must be between 1 and 5000")

    return {
        "product_code": product_code,
        "batch": batch,
        "barcode_sequence": sequence,
    }


# ============================================================
# DEVICE STATE
# ============================================================


def create_device(device_id):
    return {
        "device_id": device_id,
        "ip_address": "",
        "online": False,
        "last_seen": None,
        "last_sequence": 0,
        "packet_count": 0,
        "last_barcode_id": None,
        "product_code": None,
        "batch": None,
        "barcode_sequence": None,
    }


# ============================================================
# CSV LOGGER (daily file: logs/Nov2026/13Nov2026.csv)
# ============================================================

csv_file = None
csv_writer = None
current_log_date = None
current_csv_path = None
csv_lock = threading.Lock()


def daily_csv_path(for_day):
    month_dir = for_day.strftime("%b%Y")
    file_name = for_day.strftime("%d%b%Y") + ".csv"
    return os.path.join(LOG_ROOT, month_dir, file_name)


def ensure_daily_csv():
    global csv_file
    global csv_writer
    global current_log_date
    global current_csv_path

    today = datetime.now().date()

    if (
        current_log_date == today
        and csv_file is not None
        and current_csv_path
        and os.path.isfile(current_csv_path)
    ):
        return

    if csv_file is not None:
        try:
            csv_file.close()
        except Exception:
            pass
        csv_file = None
        csv_writer = None

    csv_path = daily_csv_path(today)
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)

    file_exists = os.path.isfile(csv_path)

    csv_file = open(
        csv_path,
        "a",
        newline="",
        encoding="utf-8",
    )

    csv_writer = csv.writer(csv_file)

    if not file_exists:
        csv_writer.writerow(CSV_HEADER)
        csv_file.flush()

    current_log_date = today
    current_csv_path = csv_path


def get_active_csv_path():
    if current_csv_path:
        return current_csv_path
    return daily_csv_path(datetime.now().date())


def log_packet(packet):
    global total_errors

    timestamp = packet["_received_time"].strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    try:
        with csv_lock:
            ensure_daily_csv()

            csv_writer.writerow([
                timestamp,
                packet.get("device_id"),
                packet.get("_ip_address"),
                packet.get("sequence"),
                packet.get("barcode_id"),
                packet.get("product_code"),
                packet.get("batch"),
                packet.get("barcode_sequence")
            ])
            csv_file.flush()

    except OSError as error:
        with statistics_lock:
            total_errors += 1
        print(f"ERROR: CSV write failed: {error}")


# ============================================================
# TCP CLIENT HANDLER
# ============================================================


def handle_client(client, address):
    global total_errors

    ip_address = address[0]

    print(f"Connection received from {ip_address}")

    buffer = ""

    try:
        while server_running:
            data = client.recv(4096)

            if not data:
                break

            buffer += data.decode(
                "utf-8",
                errors="replace"
            )

            # Extract complete newline-delimited packets.
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()

                if not line:
                    continue

                # Parse JSON.
                try:
                    packet = json.loads(line)
                except json.JSONDecodeError:
                    with statistics_lock:
                        total_errors += 1
                    print("ERROR: Invalid JSON received")
                    continue

                # Validate device ID.
                device_id = packet.get("device_id")
                if not device_id:
                    with statistics_lock:
                        total_errors += 1
                    print("ERROR: Packet has no device_id")
                    continue

                # Presence heartbeat (keeps device online while powered on network).
                if packet.get("heartbeat") is True:
                    now = datetime.now()
                    with devices_lock:
                        if device_id not in devices:
                            if len(devices) >= MAX_DEVICES:
                                with statistics_lock:
                                    total_errors += 1
                                print("Maximum device count reached")
                                continue

                            devices[device_id] = create_device(device_id)
                            print(f"NEW DEVICE: {device_id}")

                        device = devices[device_id]
                        device["ip_address"] = ip_address
                        device["online"] = True
                        device["last_seen"] = now

                    try:
                        client.sendall(b"ACK:0\n")
                    except Exception:
                        with statistics_lock:
                            total_errors += 1
                        break
                    continue

                # Validate transport sequence.
                if "sequence" not in packet:
                    with statistics_lock:
                        total_errors += 1
                    print(
                        f"ERROR: {device_id} packet has no sequence"
                    )
                    continue

                # Validate barcode ID.
                barcode_id = packet.get("barcode_id")
                if not barcode_id:
                    with statistics_lock:
                        total_errors += 1
                    print(
                        f"ERROR: {device_id} packet has no barcode_id"
                    )
                    continue

                # Parse barcode contents from the exact generator format.
                try:
                    barcode_data = parse_barcode_id(barcode_id)
                except ValueError as error:
                    with statistics_lock:
                        total_errors += 1
                    print(
                        f"ERROR: Invalid barcode from {device_id}: {error}"
                    )
                    continue

                # Keep the Pico transport sequence and barcode sequence
                # explicitly aligned, but validate rather than blindly trust.
                try:
                    transport_sequence = int(packet["sequence"])
                except (TypeError, ValueError):
                    with statistics_lock:
                        total_errors += 1
                    print(
                        f"ERROR: Invalid packet sequence from {device_id}"
                    )
                    continue

                if transport_sequence != barcode_data["barcode_sequence"]:
                    with statistics_lock:
                        total_errors += 1
                    print(
                        f"ERROR: Sequence mismatch for {device_id}: "
                        f"packet={transport_sequence}, "
                        f"barcode={barcode_data['barcode_sequence']}"
                    )
                    continue

                # Attach server metadata + parsed barcode fields.
                packet["sequence"] = transport_sequence
                packet["product_code"] = barcode_data["product_code"]
                packet["batch"] = barcode_data["batch"]
                packet["barcode_sequence"] = barcode_data["barcode_sequence"]
                packet["_ip_address"] = ip_address
                packet["_received_time"] = datetime.now()

                # Current protocol: ACK after packet validation, before
                # central processing / CSV persistence.
                ack = f"ACK:{transport_sequence}\n"

                try:
                    client.sendall(ack.encode("utf-8"))
                except Exception:
                    with statistics_lock:
                        total_errors += 1
                    break

                # Send packet to central queue.
                packet_queue.put(packet)

    except ConnectionResetError:
        print(f"Connection reset by {ip_address}")

    except Exception as error:
        with statistics_lock:
            total_errors += 1
        print(f"Client error {ip_address}: {error}")

    finally:
        client.close()
        print(f"Disconnected: {ip_address}")


# ============================================================
# CENTRAL DATA ORCHESTRATOR
# ============================================================


def packet_processor():
    global total_packets
    global total_errors

    while server_running:
        try:
            packet = packet_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        try:
            device_id = packet["device_id"]
            sequence = packet["sequence"]

            with devices_lock:
                if device_id not in devices:
                    if len(devices) >= MAX_DEVICES:
                        with statistics_lock:
                            total_errors += 1
                        print("Maximum device count reached")
                        continue

                    devices[device_id] = create_device(device_id)
                    print(f"NEW DEVICE: {device_id}")

                device = devices[device_id]

                device["ip_address"] = packet["_ip_address"]
                device["online"] = True
                device["last_seen"] = packet["_received_time"]
                device["last_sequence"] = sequence
                device["packet_count"] += 1

                device["last_barcode_id"] = packet.get("barcode_id")
                device["product_code"] = packet.get("product_code")
                device["batch"] = packet.get("batch")
                device["barcode_sequence"] = packet.get("barcode_sequence")

            with statistics_lock:
                total_packets += 1

            log_packet(packet)

        except Exception as error:
            with statistics_lock:
                total_errors += 1
            print(f"Packet processing error: {error}")

        finally:
            packet_queue.task_done()


# ============================================================
# OFFLINE DEVICE MONITOR
# ============================================================


def device_monitor():
    while server_running:
        now = datetime.now()

        with devices_lock:
            for device in devices.values():
                if device["last_seen"] is None:
                    continue

                elapsed = (
                    now - device["last_seen"]
                ).total_seconds()

                if elapsed > OFFLINE_TIMEOUT:
                    device["online"] = False

        time.sleep(1)


# ============================================================
# TCP SERVER
# ============================================================


def start_server():
    server = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    server.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1
    )

    server.bind((SERVER_HOST, SERVER_PORT))
    server.listen(MAX_DEVICES)
    server.settimeout(1.0)

    print()
    print("================================================")
    print("        BOSON PLANT TELEMETRY SERVER")
    print("================================================")
    print()
    print(f"Listening on port {SERVER_PORT}")
    print(f"Maximum devices: {MAX_DEVICES}")
    print()

    threading.Thread(
        target=packet_processor,
        daemon=True
    ).start()

    threading.Thread(
        target=device_monitor,
        daemon=True
    ).start()

    while server_running:
        try:
            client, address = server.accept()
        except socket.timeout:
            continue
        except OSError:
            break

        threading.Thread(
            target=handle_client,
            args=(client, address),
            daemon=True
        ).start()

    server.close()


# ============================================================
# PUBLIC ENGINE API
# ============================================================


def start_engine():
    global server_running

    server_running = True

    threading.Thread(
        target=start_server,
        daemon=True
    ).start()


def stop_engine():
    global server_running
    global csv_file
    global csv_writer

    server_running = False

    with csv_lock:
        try:
            if csv_file is not None:
                csv_file.close()
        except Exception:
            pass
        csv_file = None
        csv_writer = None


def get_devices_snapshot():
    with devices_lock:
        snapshot = {}

        for device_id, device in devices.items():
            snapshot[device_id] = dict(device)

        return snapshot


def get_statistics():
    with statistics_lock:
        return {
            "total_packets": total_packets,
            "total_errors": total_errors,
            "queued_packets": packet_queue.qsize()
        }


def get_server_config():
    with csv_lock:
        csv_path = get_active_csv_path()

    return {
        "server_host": SERVER_HOST,
        "server_port": SERVER_PORT,
        "max_devices": MAX_DEVICES,
        "offline_timeout": OFFLINE_TIMEOUT,
        "log_root": LOG_ROOT,
        "csv_file": csv_path,
    }
