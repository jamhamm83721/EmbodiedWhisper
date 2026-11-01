# Ring PCB

| File | Purpose |
| --- | --- |
| `gerbers.zip` | Four copper layers, masks, paste, silkscreen, outline, drill and test/placement data |
| `BOM.md` | Component-level BOM transcription |
| `layout.webp` | Layout reference preview |
| `schematic.webp` | Schematic reference preview |
| `../design/EmbodiedWhisper.epro2` | Editable schematic and board layout |

The Gerber archive retains the supplied manufacturing layer and drill contents.
A vendor ordering-instructions text file is omitted. The schematic connects SW3
to GPIO 36 and ground, matching the firmware's active-low button configuration.

The BLE firmware is in `../../firmware/ring`; the host interface is
`platform_sdk.ring.RingController`. Check antenna clearance, power and boot/program
connections in the editable design before manufacturing or flashing.
