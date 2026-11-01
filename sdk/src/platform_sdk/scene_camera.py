import time
from pathlib import Path
from typing import List

import cv2


class WorldCamera:
    """USB camera helper used by main.py to capture still images."""

    def __init__(
        self,
        camera_id: int = 2,
        output_dir: str = "./outputs/scene",
        frame_width: int = 640,
        frame_height: int = 480,
        warmup_frames: int = 5,
    ) -> None:
        self.camera_id = camera_id
        self.output_dir = Path(output_dir)
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.warmup_frames = warmup_frames
        self._cap = None

    def open(self) -> None:
        if self._cap is not None and self._cap.isOpened():
            return

        cap = cv2.VideoCapture(self.camera_id)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"Cannot open world camera: {self.camera_id}")

        for _ in range(self.warmup_frames):
            cap.read()

        self._cap = cap

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def capture_photos(self, count: int = 3, interval_seconds: float = 0.3) -> List[str]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.open()

        paths = []
        for idx in range(count):
            ok, frame = self._cap.read()
            if not ok:
                raise RuntimeError("Failed to read frame from world camera.")

            # Keep only the latest capture group by overwriting these files.
            path = self.output_dir / f"world_camera_latest_{idx + 1:02d}.jpg"
            cv2.imwrite(str(path), frame)
            paths.append(str(path))

            if idx < count - 1:
                time.sleep(interval_seconds)

        return paths
