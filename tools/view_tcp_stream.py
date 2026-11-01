#!/usr/bin/env python3
"""
View JPEG frames sent by the ESP32S3 TCP camera client.

The firmware connects to HOST:PORT and sends frames as:
    uint32 little-endian frame_length + JPEG bytes
"""

from __future__ import annotations

import argparse
import queue
import socket
import struct
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 9090
MAX_FRAME_SIZE = 2 * 1024 * 1024
VIDEO_DIR = Path("captures")


def import_viewer_deps():
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        print("Missing Python dependency:", exc)
        print("Install with: python -m pip install opencv-python numpy")
        raise SystemExit(1) from exc

    return cv2, np


cv2, np = import_viewer_deps()


def local_ipv4_candidates() -> list[str]:
    candidates: list[str] = []

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        ip = probe.getsockname()[0]
        if ip and not ip.startswith("127."):
            candidates.append(ip)
    except OSError:
        pass
    finally:
        probe.close()

    try:
        hostname = socket.gethostname()
        for item in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = item[4][0]
            if ip and not ip.startswith("127.") and ip not in candidates:
                candidates.append(ip)
    except OSError:
        pass

    return candidates


def recv_exact(sock: socket.socket, size: int, stop_event: threading.Event | None = None) -> bytes:
    data = bytearray()
    while len(data) < size:
        if stop_event is not None and stop_event.is_set():
            raise ConnectionError("stopped")
        try:
            chunk = sock.recv(size - len(data))
        except socket.timeout:
            continue
        if not chunk:
            raise ConnectionError("connection closed")
        data.extend(chunk)
    return bytes(data)


def parse_frame_len(raw: bytes) -> int:
    little = struct.unpack("<I", raw)[0]
    if 0 < little <= MAX_FRAME_SIZE:
        return little

    big = struct.unpack(">I", raw)[0]
    if 0 < big <= MAX_FRAME_SIZE:
        return big

    raise ValueError(f"invalid frame size: little={little}, big={big}")


class TcpStreamWorker:
    def __init__(self, host: str, port: int, save_video: bool, output_dir: Path, events: queue.Queue):
        self.host = host
        self.port = port
        self.save_video = save_video
        self.output_dir = output_dir
        self.events = events
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.server: socket.socket | None = None
        self.client: socket.socket | None = None
        self.writer = None
        self.video_path: Path | None = None

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        for sock in (self.client, self.server):
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass

    def _emit(self, kind: str, **payload) -> None:
        self.events.put((kind, payload))

    def _open_writer(self, frame) -> None:
        if not self.save_video or self.writer is not None:
            return
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.video_path = self.output_dir / time.strftime("esp32_%Y%m%d_%H%M%S.avi")
        height, width = frame.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        self.writer = cv2.VideoWriter(str(self.video_path), fourcc, 15.0, (width, height))
        if not self.writer.isOpened():
            self.writer.release()
            self.writer = None
            self._emit("status", text=f"Could not open video file: {self.video_path}")
        else:
            self._emit("status", text=f"Saving video: {self.video_path}")

    def _close_writer(self) -> None:
        if self.writer is not None:
            self.writer.release()
            self.writer = None
            self._emit("status", text=f"Video saved: {self.video_path}")

    def _run(self) -> None:
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((self.host, self.port))
            self.server.listen(1)
            self.server.settimeout(0.5)
            self._emit("status", text=f"Listening on {self.host}:{self.port}")

            while not self.stop_event.is_set():
                try:
                    self.client, address = self.server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break

                self._emit("status", text=f"ESP32 connected from {address[0]}:{address[1]}")
                self.client.settimeout(0.5)
                self.client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

                frame_count = 0
                fps = 0.0
                fps_tick = time.time()

                try:
                    while not self.stop_event.is_set():
                        frame_len = parse_frame_len(recv_exact(self.client, 4, self.stop_event))
                        jpeg = recv_exact(self.client, frame_len, self.stop_event)
                        image_array = np.frombuffer(jpeg, dtype=np.uint8)
                        frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
                        if frame is None:
                            self._emit("status", text=f"Skipped undecodable frame: {frame_len} bytes")
                            continue

                        frame_count += 1
                        now = time.time()
                        elapsed = now - fps_tick
                        if elapsed >= 1.0:
                            fps = frame_count / elapsed
                            frame_count = 0
                            fps_tick = now

                        self._open_writer(frame)
                        if self.writer is not None:
                            self.writer.write(frame)

                        self._emit("frame", frame=frame, fps=fps, size=frame_len, address=address[0])
                except (ConnectionError, OSError, ValueError) as exc:
                    if not self.stop_event.is_set():
                        self._emit("status", text=f"ESP32 disconnected: {exc}")
                finally:
                    if self.client is not None:
                        try:
                            self.client.close()
                        except OSError:
                            pass
                        self.client = None

            self._emit("status", text="Stopped")
        except OSError as exc:
            self._emit("error", text=str(exc))
        finally:
            self._close_writer()
            if self.server is not None:
                try:
                    self.server.close()
                except OSError:
                    pass
            self._emit("stopped")


class StreamViewerApp:
    def __init__(self, root: tk.Tk, initial_host: str = "", initial_port: int = DEFAULT_PORT):
        self.root = root
        self.root.title("ESP32S3 TCP Camera")
        self.root.geometry("900x680")
        self.root.minsize(720, 520)

        ips = local_ipv4_candidates()
        default_host = initial_host if initial_host else (ips[0] if ips else DEFAULT_HOST)
        self.host_var = tk.StringVar(value=default_host)
        self.port_var = tk.StringVar(value=str(initial_port))
        self.save_video_var = tk.BooleanVar(value=False)
        self.output_dir_var = tk.StringVar(value=str(VIDEO_DIR))
        self.status_var = tk.StringVar(value="Ready")
        self.info_var = tk.StringVar(value="FPS: 0.0    Size: 0 bytes")
        self.local_ip_var = tk.StringVar(value="Local IPv4: " + (", ".join(ips) if ips else "not detected"))

        self.events: queue.Queue = queue.Queue()
        self.worker: TcpStreamWorker | None = None
        self.current_photo = None

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(30, self._process_events)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        controls = ttk.Frame(outer)
        controls.pack(fill=tk.X)

        ttk.Label(controls, text="Target IP").grid(row=0, column=0, sticky=tk.W, padx=(0, 6))
        self.host_entry = ttk.Entry(controls, textvariable=self.host_var, width=18)
        self.host_entry.grid(row=0, column=1, sticky=tk.W, padx=(0, 12))

        ttk.Label(controls, text="Port").grid(row=0, column=2, sticky=tk.W, padx=(0, 6))
        self.port_entry = ttk.Entry(controls, textvariable=self.port_var, width=8)
        self.port_entry.grid(row=0, column=3, sticky=tk.W, padx=(0, 12))

        self.save_check = ttk.Checkbutton(controls, text="Save video", variable=self.save_video_var)
        self.save_check.grid(row=0, column=4, sticky=tk.W, padx=(0, 10))

        self.dir_button = ttk.Button(controls, text="Folder", command=self._choose_output_dir)
        self.dir_button.grid(row=0, column=5, sticky=tk.W, padx=(0, 10))

        self.start_button = ttk.Button(controls, text="Start listening", command=self._start)
        self.start_button.grid(row=0, column=6, sticky=tk.W, padx=(0, 8))

        self.stop_button = ttk.Button(controls, text="Stop", command=self._stop, state=tk.DISABLED)
        self.stop_button.grid(row=0, column=7, sticky=tk.W)

        controls.columnconfigure(8, weight=1)

        ttk.Label(outer, textvariable=self.local_ip_var).pack(anchor=tk.W, pady=(8, 0))
        ttk.Label(outer, textvariable=self.status_var).pack(anchor=tk.W, pady=(2, 0))
        ttk.Label(outer, textvariable=self.info_var).pack(anchor=tk.W, pady=(2, 10))

        video_frame = ttk.Frame(outer, relief=tk.SUNKEN, padding=4)
        video_frame.pack(fill=tk.BOTH, expand=True)
        self.video_label = ttk.Label(video_frame, anchor=tk.CENTER, text="No video")
        self.video_label.pack(fill=tk.BOTH, expand=True)

    def _choose_output_dir(self) -> None:
        path = filedialog.askdirectory(initialdir=self.output_dir_var.get() or ".")
        if path:
            self.output_dir_var.set(path)

    def _set_running(self, running: bool) -> None:
        state = tk.DISABLED if running else tk.NORMAL
        self.host_entry.configure(state=state)
        self.port_entry.configure(state=state)
        self.save_check.configure(state=state)
        self.dir_button.configure(state=state)
        self.start_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.stop_button.configure(state=tk.NORMAL if running else tk.DISABLED)

    def _start(self) -> None:
        host = self.host_var.get().strip() or DEFAULT_HOST
        try:
            port = int(self.port_var.get().strip())
            if not 0 < port < 65536:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid port", "Port must be a number from 1 to 65535.")
            return

        self.events = queue.Queue()
        self.worker = TcpStreamWorker(
            host=host,
            port=port,
            save_video=self.save_video_var.get(),
            output_dir=Path(self.output_dir_var.get() or VIDEO_DIR),
            events=self.events,
        )
        self.worker.start()
        self.status_var.set("Starting...")
        self._set_running(True)

    def _stop(self) -> None:
        if self.worker is not None:
            self.status_var.set("Stopping...")
            self.worker.stop()

    def _process_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "frame":
                    self._show_frame(payload["frame"])
                    self.info_var.set(
                        f"FPS: {payload['fps']:.1f}    Size: {payload['size']} bytes    From: {payload['address']}"
                    )
                elif kind == "status":
                    self.status_var.set(payload["text"])
                elif kind == "error":
                    self.status_var.set("Error: " + payload["text"])
                    messagebox.showerror("Listen error", payload["text"])
                elif kind == "stopped":
                    self.worker = None
                    self._set_running(False)
        except queue.Empty:
            pass

        self.root.after(30, self._process_events)

    def _show_frame(self, frame) -> None:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        max_w = max(self.video_label.winfo_width() - 8, 1)
        max_h = max(self.video_label.winfo_height() - 8, 1)
        h, w = rgb.shape[:2]
        scale = min(max_w / w, max_h / h, 1.0)
        if scale < 1.0:
            rgb = cv2.resize(rgb, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
            h, w = rgb.shape[:2]

        header = f"P6 {w} {h} 255\n".encode("ascii")
        self.current_photo = tk.PhotoImage(data=header + rgb.tobytes(), format="PPM")
        self.video_label.configure(image=self.current_photo, text="")

    def _on_close(self) -> None:
        if self.worker is not None:
            self.worker.stop()
        self.root.destroy()


def run_gui(initial_host: str = "", initial_port: int = DEFAULT_PORT) -> None:
    root = tk.Tk()
    StreamViewerApp(root, initial_host=initial_host, initial_port=initial_port)
    root.mainloop()


def run_server_cli(host: str, port: int, save_dir: Path | None) -> None:
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)

    events: queue.Queue = queue.Queue()
    worker = TcpStreamWorker(host, port, save_dir is not None, save_dir or VIDEO_DIR, events)
    worker.start()

    print(f"Listening on {host}:{port}")
    ips = local_ipv4_candidates()
    if ips:
        print("PC IPv4 candidates:", ", ".join(ips))
    print("Press Ctrl+C to stop.")

    try:
        while True:
            try:
                kind, payload = events.get(timeout=0.2)
            except queue.Empty:
                continue
            if kind == "status":
                print(payload["text"])
            elif kind == "frame":
                print(f"FPS: {payload['fps']:.1f}  Size: {payload['size']} bytes", end="\r")
            elif kind == "error":
                print("Error:", payload["text"])
            elif kind == "stopped":
                break
    except KeyboardInterrupt:
        pass
    finally:
        worker.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="View ESP32S3 TCP JPEG video stream.")
    parser.add_argument("--cli", action="store_true", help="Run without the Tkinter UI.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Local host/IP to bind.")
    parser.add_argument("--port", default=DEFAULT_PORT, type=int, help="Local TCP port.")
    parser.add_argument(
        "--save-dir",
        type=Path,
        default=None,
        help="CLI mode video output directory. Omit to disable saving.",
    )
    args = parser.parse_args()

    if args.cli:
        run_server_cli(args.host, args.port, args.save_dir)
    else:
        run_gui(initial_host=args.host, initial_port=args.port)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
