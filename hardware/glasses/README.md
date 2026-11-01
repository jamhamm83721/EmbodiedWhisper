# Glasses PCB

| File | Purpose |
| --- | --- |
| `gerbers.zip` | Four copper layers, masks, paste, silkscreen, outline, drill and test/placement data |
| `BOM.md` | Component-level BOM transcription |
| `layout.webp` | Layout reference preview |
| `../design/EmbodiedWhisper.epro2` | Editable schematic and board layout |

The Gerber archive retains the supplied manufacturing layer and drill contents.
A vendor ordering-instructions text file is omitted. Use the actual outline layer
for dimensions; the preview dimension annotations are reference information.

The scene-camera firmware is in `../../firmware/glasses`. Its DVP interface uses
GPIO 4/5 for SCCB and an external camera clock. Confirm the camera connector pin
order, 24 MHz clock source, power rails and sensor module before assembly.

The inward-facing USB eye-camera path is handled by the host SDK and is separate
from the DVP scene-camera firmware. Mechanical mounts and trained models are not
included in this package.
