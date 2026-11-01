# ESP32-S3 scene-camera firmware

The camera captures JPEG frames and opens a TCP connection to a receiving computer.
Each frame is a four-byte little-endian length followed by that many JPEG bytes.
The supplied source continuously streams while connected; event-triggered selection
or sampling belongs to the host application.

## Build

Use ESP-IDF 5.4.3 and a working ESP32-S3 toolchain:

```sh
idf.py set-target esp32s3
idf.py menuconfig
idf.py build
idf.py -p YOUR_SERIAL_PORT flash monitor
```

In **EmbodiedWhisper network**, set the Wi-Fi SSID/password, receiving computer's
IPv4 address and TCP port. The SSID/password defaults are blank. `192.0.2.1` is a
documentation placeholder, not a working destination. Both devices must be on a
network where the ESP32 can reach the receiver. Generated `sdkconfig` remains local.

Before booting the board, start the host viewer from the repository root:

```sh
python -m pip install "./sdk[hardware]"
python tools/view_tcp_stream.py --host 0.0.0.0 --port 9090
```

For a terminal receiver, append `--cli`. To save a local MJPEG AVI, also pass
`--save-dir outputs/scene`. The viewer's GUI can start/stop listening and save video.

## Camera wiring

| Signal | ESP32-S3 GPIO |
| --- | --- |
| PWDN / RESET | 14 / 15 |
| SCCB SDA / SCL | 4 / 5 |
| D0, D1, D2, D3 | 11, 9, 8, 10 |
| D4, D5, D6, D7 | 12, 18, 17, 16 |
| VSYNC / HREF / PCLK | 6 / 7 / 13 |
| XCLK | External oscillator; GPIO output disabled |

The camera configuration retains 24 MHz, JPEG, 240 x 240, quality 15, two PSRAM frame
buffers and latest-frame grabbing. The defaults enable octal 80 MHz PSRAM and 16 MiB
flash. These settings are specific to the supplied hardware; check other variants.

The external `esp32-camera` dependency references upstream v2.0.5, corresponding
to the supplied driver implementation. The supplied main and peripheral sources
are retained; an unused debug module containing personal initials is excluded.
Network values are supplied through local configuration. Wi-Fi credentials are not
printed by the release copy. No prebuilt firmware is distributed.

This distribution is prepared for anonymous sharing. Build instructions describe
the intended environment; the final privacy-only source copy has not undergone a
functional or hardware verification pass.
