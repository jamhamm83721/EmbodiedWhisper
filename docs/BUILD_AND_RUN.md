# Build and run

## Python SDK

Use Python 3.10 or later. From the repository root:

```sh
python -m pip install "./sdk[hardware]"
python examples/synthetic_pupil_stream.py
python examples/ring_events.py --device-name ESP32S3-Button
python examples/capture_scene_usb.py --camera 1 --output outputs/scene
python examples/record_eye.py --model models/pupil_detector.onnx --camera 0 --fps 20
```

Run each device example separately, checking local camera indexes and BLE discovery.
All device addresses are runtime options. Recordings remain in local `outputs/`.
The USB scene example is an alternative capture path; the custom glasses camera
uses `python tools/view_tcp_stream.py --host 0.0.0.0 --port 9090` instead.

The eye recorder expects a compatible single-frame YOLO-style ONNX detector using
the bundled bounding-box postprocessing. A temporal detector may require a different
input/output contract. Trained weights are not bundled or validated by this release.
The reflex monitor and RIPA trigger can consume externally obtained pupil samples.

## ESP32-S3 firmware

Install and activate ESP-IDF 5.4.3. For each board, run in its own directory:

```sh
cd firmware/ring
idf.py set-target esp32s3
idf.py build
idf.py -p YOUR_SERIAL_PORT flash monitor
```

For the glasses, use `firmware/glasses` instead and run `idf.py menuconfig` before
building. Set **EmbodiedWhisper network** to the local Wi-Fi settings and receiving
computer's IPv4 address. Start the TCP receiver before booting the glasses. The
camera dependency is fetched from its pinned upstream Git version on first build.

The ring button uses GPIO 36, active low, matching SW3 in the supplied schematic.
The glasses firmware uses the pin table in its README and external camera XCLK.
Flashing and operation on physical boards remain to be verified for this release.
