# Interfaces

## Cameras

The inward-facing camera uses the host USB video interface. The eye recorder requests
640 x 480 frames and accepts a camera index, frame-rate request and model path. The
host may deliver a different frame rate. Recorded area is image-coordinate area,
not physical pupil diameter in millimetres.

The outward-facing path uses a DVP camera connected to an ESP32-S3. The supplied
firmware sends continuous JPEG frames over TCP/Wi-Fi. The computer listens on a
configurable port (default 9090). Frames use `uint32 little-endian length + JPEG`.
The receiver reconnects across client sessions and rejects invalid frame sizes.
Trigger-based scene selection is implemented by a consuming application.
`scene_camera.WorldCamera` is a separate USB capture alternative.

## Ring

The ring advertises `ESP32S3-Button` and exposes service
`12345678-1234-5678-1234-56789abcdef0` with readable/notifiable characteristic
`12345678-1234-5678-1234-56789abcdef1`. Values include `pressed`, `released`,
`clicked` and `long_pressed`. Advertising carries company field `0xffff`, marker
`RNG`, one event-code byte and a two-byte little-endian counter. The company field
is a development value, not a production allocation.

The source uses GPIO 36, an active-low button, 30 ms debounce, a 10 ms scan period
and a 1500 ms long-press threshold. The SDK's legacy `long_press_seconds` argument
does not change the firmware threshold.

In automatic mode, a short click toggles automatic assistance. A long press changes
between automatic and manual modes. In manual mode, a short click creates a request.
Applications consume `RingAction` records from `RingController.get_action()`.
The SDK defaults to device-name discovery and has no preset device MAC address.
