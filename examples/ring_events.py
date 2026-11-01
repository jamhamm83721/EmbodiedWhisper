"""Print ring actions from a user-selected BLE device."""
import argparse
from dataclasses import asdict
import json
from platform_sdk.ring import RingController

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-name", default="ESP32S3-Button")
    parser.add_argument("--address", default="", help="Optional address from your own device")
    parser.add_argument("--advertising", action="store_true")
    args = parser.parse_args()
    ring = RingController(mac_address=args.address, device_name=args.device_name,
                          prefer_ble_gatt=not args.advertising)
    if not ring.ensure_ready():
        raise SystemExit("Ring not found. Check the configured device and Bluetooth adapter.")
    ring.start()
    try:
        while True:
            action = ring.get_action(timeout=0.5)
            if action is not None:
                print(json.dumps(asdict(action), ensure_ascii=False))
    except KeyboardInterrupt:
        pass
    finally:
        ring.stop()

if __name__ == "__main__":
    main()
