import asyncio
import queue
import sys
import threading
import time
from dataclasses import dataclass
from typing import Optional, Tuple

if sys.platform == "win32":
    # Bleak on Windows console apps works more reliably when COM is initialized as MTA
    # before any dependency has a chance to switch the process to STA.
    sys.coinit_flags = 0

try:
    from bleak import BleakClient, BleakScanner
    from bleak.exc import BleakDeviceNotFoundError, BleakError
except ImportError:
    BleakClient = None
    BleakScanner = None
    BleakDeviceNotFoundError = Exception
    BleakError = Exception

try:
    from bleak.backends.winrt.util import uninitialize_sta
except ImportError:
    uninitialize_sta = None


RING_MODE_AUTO = "auto"
RING_MODE_MANUAL = "manual"

RING_ACTION_TOGGLE_MODE = "toggle_mode"
RING_ACTION_TOGGLE_AUTO_ACTIVE = "toggle_auto_active"
RING_ACTION_MANUAL_REQUEST = "manual_request"

BLE_EVENT_CLICKED = "clicked"
BLE_EVENT_LONG_PRESSED = "long_pressed"
BLE_EVENT_PRESSED = "pressed"
BLE_EVENT_RELEASED = "released"

RING_COMPANY_ID = 0xFFFF
RING_MFG_PREFIX = b"RNG"
RING_EVENT_NAMES = {
    1: BLE_EVENT_CLICKED,
    2: BLE_EVENT_LONG_PRESSED,
    3: BLE_EVENT_PRESSED,
}
BLE_BUTTON_CHAR_UUID = "12345678-1234-5678-1234-56789abcdef1"


@dataclass
class RingAction:
    kind: str
    mode: str
    auto_enabled: bool
    prompt_text: str
    timestamp: float


class RingController:
    """ESP32-S3 BLE ring controller with GATT notifications first, adv-scan fallback."""

    def __init__(
        self,
        mac_address: str = "",
        device_name: str = "ESP32S3-Button",
        long_press_seconds: float = 1.0,
        debounce_seconds: float = 0.20,
        initial_mode: str = RING_MODE_AUTO,
        initial_auto_enabled: bool = True,
        prefer_ble_gatt: bool = True,
        startup_ignore_seconds: float = 1.5,
        gatt_char_uuid: str = BLE_BUTTON_CHAR_UUID,
        fallback_gatt_address: Optional[str] = None,
        gatt_poll_interval_seconds: float = 0.15,
    ) -> None:
        self.mac_address = mac_address.upper()
        self.device_name = device_name
        self.long_press_seconds = long_press_seconds
        self.debounce_seconds = debounce_seconds
        self.mode = initial_mode
        self.auto_enabled = initial_auto_enabled
        self.prefer_ble_gatt = prefer_ble_gatt
        self.startup_ignore_seconds = startup_ignore_seconds
        self.gatt_char_uuid = gatt_char_uuid
        self.fallback_gatt_address = fallback_gatt_address.upper() if fallback_gatt_address else None
        self.gatt_poll_interval_seconds = max(0.05, float(gatt_poll_interval_seconds))

        self._actions: "queue.Queue[RingAction]" = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_action_time = 0.0
        self._last_adv_counter: Optional[int] = None
        self._listener_started_at = 0.0
        self._backend = "ble_gatt" if self.prefer_ble_gatt else "ble_adv"
        self._gatt_target: Optional[str] = None

    @property
    def is_auto_active(self) -> bool:
        return self.mode == RING_MODE_AUTO and self.auto_enabled

    def ensure_ready(self, timeout_seconds: float = 10.0) -> bool:
        if BleakScanner is None and BleakClient is None:
            print("[ERROR] bleak is not installed. Run: pip install bleak dbus-fast")
            return False

        self._prepare_windows_bleak_console_mode()

        if self.prefer_ble_gatt:
            try:
                resolved = asyncio.run(self._resolve_gatt_target(timeout_seconds))
            except Exception as exc:
                print(f"[WARN] ring GATT resolve failed: {exc}")
                resolved = None
            if resolved:
                self._gatt_target = resolved
                self._backend = "ble_gatt"
                print(f"[INFO] ring BLE GATT target resolved: {resolved}")
                return True
            print("[WARN] ring GATT path unavailable, trying advertisement fallback")

        try:
            found = bool(asyncio.run(self._wait_for_advertisement(timeout_seconds)))
        except Exception as exc:
            print(f"[ERROR] BLE advertising scan failed: {exc}")
            return False

        if not found:
            print(
                f"[ERROR] ring was not found: "
                f"name={self.device_name}, mac={self.mac_address}, fallback_gatt={self.fallback_gatt_address}"
            )
            print("[HINT] Make sure the ESP32-S3 is powered on and advertising.")
            return False

        self._backend = "ble_adv"
        print(f"[INFO] ring BLE advertising detected: {self.device_name} / {self.mac_address}")
        return True

    def _prepare_windows_bleak_console_mode(self) -> None:
        """Bleak on Windows console apps needs MTA instead of an accidental STA init."""
        if sys.platform != "win32":
            return
        if uninitialize_sta is None:
            return
        try:
            uninitialize_sta()
            print("[INFO] bleak Windows STA compatibility fix applied")
        except Exception as exc:
            print(f"[WARN] failed to apply bleak Windows STA fix: {exc}")

    async def _wait_for_advertisement(self, timeout_seconds: float) -> bool:
        if BleakScanner is None:
            return False
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                devices = await BleakScanner.discover(
                    timeout=min(2.0, max(0.5, deadline - time.time()))
                )
            except Exception as exc:
                if "InProgress" in str(exc) or "Operation already in progress" in str(exc):
                    print("[WARN] BLE scan already in progress, waiting and retrying...")
                    await asyncio.sleep(1.0)
                    continue
                raise

            for device in devices:
                name = (device.name or "").strip()
                if device.address.upper() == self.mac_address or name == self.device_name:
                    return True
        return False

    async def _resolve_gatt_target(self, timeout_seconds: float) -> Optional[str]:
        if BleakClient is None:
            return None

        candidates = []
        if self.fallback_gatt_address:
            candidates.append(self.fallback_gatt_address)
        if self.mac_address:
            candidates.append(self.mac_address)

        seen = set()
        deduped = []
        for item in candidates:
            upper = item.upper()
            if upper not in seen:
                deduped.append(upper)
                seen.add(upper)

        for address in deduped:
            if await self._probe_gatt_address(address, timeout_seconds=min(5.0, timeout_seconds)):
                return address

        if BleakScanner is None:
            return None

        device, devices = await self._find_device_by_name(timeout_seconds)
        if device is not None and await self._probe_gatt_address(device.address, timeout_seconds=min(5.0, timeout_seconds)):
            return device.address

        if devices:
            print("[INFO] nearby BLE devices:")
            for device in devices:
                if device.name:
                    print(f"  {device.address} | {device.name}")
        return None

    async def _find_device_by_name(self, timeout_seconds: float):
        devices = await BleakScanner.discover(timeout=timeout_seconds)
        for device in devices:
            if (device.name or "").strip() == self.device_name:
                return device, devices
        return None, devices

    async def _probe_gatt_address(self, address: str, timeout_seconds: float) -> bool:
        if BleakClient is None:
            return False
        try:
            async with BleakClient(address, timeout=timeout_seconds) as client:
                connected = bool(client.is_connected)
                print(f"[INFO] ring GATT probe: address={address}, connected={connected}")
                return connected
        except (BleakDeviceNotFoundError, BleakError, OSError) as exc:
            print(f"[WARN] ring GATT probe failed for {address}: {exc}")
            return False

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._last_adv_counter = None
        self._listener_started_at = time.time()
        self._thread = threading.Thread(target=self._listener_loop_thread, daemon=True)
        self._thread.start()
        print(
            "[INFO] ring listener started: "
            f"backend={self._backend}, mode={self.mode}, auto_enabled={self.auto_enabled}, mac={self.mac_address}"
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def get_action(self, timeout: float = 0.0) -> Optional[RingAction]:
        try:
            return self._actions.get(timeout=timeout)
        except queue.Empty:
            return None

    def _listener_loop_thread(self) -> None:
        try:
            if self._backend == "ble_gatt":
                asyncio.run(self._ble_gatt_loop())
            else:
                asyncio.run(self._ble_adv_loop())
        except Exception as exc:
            if not self._stop_event.is_set():
                print(f"[ERROR] ring listener failed: {exc}")

    async def _ble_gatt_loop(self) -> None:
        if BleakClient is None:
            return
        target = self._gatt_target or self.fallback_gatt_address or self.mac_address
        if not target:
            raise RuntimeError("No GATT target address is available.")

        while not self._stop_event.is_set():
            disconnected_event = asyncio.Event()

            def disconnect_callback(_client) -> None:
                disconnected_event.set()

            try:
                async with BleakClient(target, disconnected_callback=disconnect_callback) as client:
                    if not client.is_connected:
                        raise RuntimeError(f"Ring GATT client did not connect: {target}")
                    print(f"[INFO] ring GATT connected: {target}")
                    await client.start_notify(self.gatt_char_uuid, self._gatt_notification_handler)
                    print(f"[INFO] ring GATT subscribed: {self.gatt_char_uuid}")

                    while not self._stop_event.is_set() and client.is_connected:
                        await self._poll_gatt_characteristic(client)
                        try:
                            await asyncio.wait_for(
                                disconnected_event.wait(),
                                timeout=self.gatt_poll_interval_seconds,
                            )
                        except asyncio.TimeoutError:
                            continue
                        else:
                            break
            except (BleakDeviceNotFoundError, BleakError, OSError) as exc:
                if self._stop_event.is_set():
                    break
                print(f"[WARN] ring GATT loop error: {exc}")
            finally:
                if self._stop_event.is_set():
                    break
            await asyncio.sleep(1.0)

    def _gatt_notification_handler(self, sender, data) -> None:
        try:
            message = bytes(data).decode("utf-8", errors="replace").strip().lower()
        except Exception:
            return
        if message not in (
            BLE_EVENT_CLICKED,
            BLE_EVENT_LONG_PRESSED,
            BLE_EVENT_PRESSED,
            BLE_EVENT_RELEASED,
        ):
            return
        self._handle_ble_message(message, time.time())

    async def _poll_gatt_characteristic(self, client) -> None:
        try:
            raw = await client.read_gatt_char(self.gatt_char_uuid)
        except Exception:
            return

        try:
            message = bytes(raw).decode("utf-8", errors="replace").strip().lower()
        except Exception:
            return

        if message not in (BLE_EVENT_CLICKED, BLE_EVENT_LONG_PRESSED):
            return

        print(f"[INFO] ring GATT polled event: {message}")
        self._handle_ble_message(message, time.time())

    async def _ble_adv_loop(self) -> None:
        if BleakScanner is None:
            return

        def callback(device, advertisement_data) -> None:
            if device.address.upper() != self.mac_address:
                name = (device.name or "").strip()
                if name != self.device_name:
                    return

            parsed = self._parse_adv_event(advertisement_data)
            if parsed is None:
                return

            message, counter = parsed
            now = time.time()
            if counter == self._last_adv_counter:
                return

            # BLE advertisements can repeat the last button event after a process restart.
            # Treat the first/new-startup counters as baseline state, not as user input.
            if self._last_adv_counter is None:
                self._last_adv_counter = counter
                print(f"[INFO] ring BLE initial advertisement ignored: event={message}, counter={counter}")
                return

            if now - self._listener_started_at < self.startup_ignore_seconds:
                self._last_adv_counter = counter
                print(f"[INFO] ring BLE startup advertisement ignored: event={message}, counter={counter}")
                return

            self._last_adv_counter = counter
            self._handle_ble_message(message, now)

        async with BleakScanner(detection_callback=callback):
            while not self._stop_event.is_set():
                await asyncio.sleep(0.2)

    def _parse_adv_event(self, advertisement_data) -> Optional[Tuple[str, int]]:
        manufacturer_data = getattr(advertisement_data, "manufacturer_data", {}) or {}
        for company_id, payload in manufacturer_data.items():
            raw = bytes(payload)
            if company_id == RING_COMPANY_ID and raw.startswith(RING_MFG_PREFIX) and len(raw) >= 6:
                event_code = raw[3]
                counter = raw[4] | (raw[5] << 8)
                event_name = RING_EVENT_NAMES.get(event_code)
                return (event_name, counter) if event_name else None

            if raw.startswith(b"\xff\xff" + RING_MFG_PREFIX) and len(raw) >= 8:
                event_code = raw[5]
                counter = raw[6] | (raw[7] << 8)
                event_name = RING_EVENT_NAMES.get(event_code)
                return (event_name, counter) if event_name else None

        return None

    def _handle_ble_message(self, message: str, now: float) -> None:
        if message not in (BLE_EVENT_CLICKED, BLE_EVENT_LONG_PRESSED):
            return
        if now - self._last_action_time < self.debounce_seconds:
            return
        self._last_action_time = now

        if message == BLE_EVENT_LONG_PRESSED:
            self._toggle_mode(now)
        elif message == BLE_EVENT_CLICKED:
            self._handle_short_press(now)

    def _toggle_mode(self, now: float) -> None:
        if self.mode == RING_MODE_AUTO:
            self.mode = RING_MODE_MANUAL
            self.auto_enabled = False
            prompt = "已切换为手动请求模式"
        else:
            self.mode = RING_MODE_AUTO
            self.auto_enabled = True
            prompt = "已切换为自动辅助模式"

        self._actions.put(
            RingAction(
                kind=RING_ACTION_TOGGLE_MODE,
                mode=self.mode,
                auto_enabled=self.auto_enabled,
                prompt_text=prompt,
                timestamp=now,
            )
        )

    def _handle_short_press(self, now: float) -> None:
        if self.mode == RING_MODE_MANUAL:
            self._actions.put(
                RingAction(
                    kind=RING_ACTION_MANUAL_REQUEST,
                    mode=self.mode,
                    auto_enabled=self.auto_enabled,
                    prompt_text="",
                    timestamp=now,
                )
            )
            return

        self.auto_enabled = not self.auto_enabled
        prompt = "已进入自动辅助" if self.auto_enabled else "已退出自动辅助"
        self._actions.put(
            RingAction(
                kind=RING_ACTION_TOGGLE_AUTO_ACTIVE,
                mode=self.mode,
                auto_enabled=self.auto_enabled,
                prompt_text=prompt,
                timestamp=now,
            )
        )
