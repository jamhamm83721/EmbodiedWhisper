# Release scope and validation

## Included

- Editable schematics and PCB layouts for the glasses and ring.
- Per-board Gerber and drill exports, component BOMs and reference previews.
- Ring button/BLE firmware and glasses Wi-Fi camera firmware.
- Python BLE and camera interfaces, pupil recording, reflex filtering and a RIPA trigger.
- A TCP scene-camera viewer and runnable examples.

## Validation

The release CAD archive is parsed as design records. Changes are confined to account
and editing-client metadata; non-metadata records retain their original bytes.
The included Gerber and drill member contents retain their original bytes.
Top/bottom silkscreen and document layers have been rendered and inspected.
Python syntax, synthetic pupil processing, BLE packet parsing and TCP JPEG framing
are checked without participant data or hardware.

The final source copy is prepared for anonymous sharing, without a further
functional or compilation verification pass. Instructions describe the intended
ESP-IDF environment and are not a claim of verified physical-device operation. No fabrication, flashing, RF qualification or end-to-end hardware test is
claimed for this release. The CAD archive has not been re-saved through an editor
as part of validation; open it and review design rules before fabrication.

## Not included

- Trained pupil-detector weights or a validated temporal-model inference wrapper.
- Participant media, experiment logs, API credentials or Wi-Fi credentials.
- A complete cloud-connected assistant application or hosted inference service.
- Mechanical enclosure or mounting CAD.

This package supports inspection and further development of the platform. Refer to
the build guide and board pin maps when adapting it to a different assembly.
