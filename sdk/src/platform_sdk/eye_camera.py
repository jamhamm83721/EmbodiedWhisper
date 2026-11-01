import csv
import math
import os
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Deque, Dict, List, Optional, Tuple

import cv2
import numpy as np
import onnxruntime as ort


MODEL_PATH = "./models/pupil_detector.onnx"
OUTPUT_DIR = "./outputs/eye"
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "pupil_area_latest_10s.csv")

CAMERA_ID = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
CAMERA_FPS = 30
# The exported YOLO model takes a square 320x320 tensor. A 4:3 camera frame is
# letterboxed into that tensor, so the effective image area is 320x240.
INPUT_SIZE = 320
AREA_NORM_WIDTH = 320.0
AREA_NORM_HEIGHT = 240.0
# Area output switch. Keep the camera opened at FRAME_WIDTH x FRAME_HEIGHT, run
# YOLO at INPUT_SIZE, then decide which area value is exposed as sample.pupil_area.
# True:  sample.pupil_area uses the 320x240-normalized area.
# False: sample.pupil_area uses the captured-frame coordinate area, e.g. 640x480.
USE_320X240_AREA = False
PUPIL_AREA_MODE = "norm_320" if USE_320X240_AREA else "raw"
CONF_THRES = 0.25
IOU_THRES = 0.45
WINDOW_SECONDS = 10.0
CSV_FLUSH_EVERY_FRAMES = 10


@dataclass
class PupilSample:
    frame: int
    time_sec: float
    detected: int
    center_x: int
    center_y: int
    bbox_w: float
    bbox_h: float
    pupil_area: float
    pupil_area_raw: float
    pupil_area_norm_320: float
    confidence: float
    fps: float


def compute_iou(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])

    inter = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    area1 = (box[2] - box[0]) * (box[3] - box[1])
    area2 = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    union = area1 + area2 - inter + 1e-6
    return inter / union


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thres: float) -> List[int]:
    order = scores.argsort()[::-1]
    keep = []

    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break

        ious = compute_iou(boxes[i], boxes[order[1:]])
        order = order[np.where(ious < iou_thres)[0] + 1]

    return keep


def letterbox(
    img: np.ndarray,
    new_shape: int = 320,
    color: Tuple[int, int, int] = (114, 114, 114),
) -> Tuple[np.ndarray, float, Tuple[float, float]]:
    shape = img.shape[:2]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)

    ratio = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
    new_unpad = (int(round(shape[1] * ratio)), int(round(shape[0] * ratio)))
    dw = new_shape[1] - new_unpad[0]
    dh = new_shape[0] - new_unpad[1]
    dw /= 2
    dh /= 2

    resized = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
    top = int(round(dh - 0.1))
    bottom = int(round(dh + 0.1))
    left = int(round(dw - 0.1))
    right = int(round(dw + 0.1))

    out = cv2.copyMakeBorder(
        resized,
        top,
        bottom,
        left,
        right,
        cv2.BORDER_CONSTANT,
        value=color,
    )
    return out, ratio, (dw, dh)


def preprocess(frame: np.ndarray, input_size: int) -> Tuple[np.ndarray, float, float, float]:
    img, ratio, (dw, dh) = letterbox(frame, input_size)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = img.astype(np.float32) / 255.0
    img = np.transpose(img, (2, 0, 1))
    img = np.expand_dims(img, axis=0)
    return img, ratio, dw, dh


def postprocess(
    pred: np.ndarray,
    orig_shape: Tuple[int, int],
    ratio: float,
    dw: float,
    dh: float,
    conf_thres: float,
    iou_thres: float,
) -> Tuple[np.ndarray, np.ndarray]:
    pred = np.squeeze(pred)

    if pred.ndim == 2 and pred.shape[0] < pred.shape[1]:
        pred = pred.T

    boxes = []
    scores = []

    for row in pred:
        if len(row) < 5:
            continue

        x, y, w, h = row[:4]
        score = float(np.max(row[4:]) if len(row) > 5 else row[4])
        if score < conf_thres:
            continue

        x1 = x - w / 2
        y1 = y - h / 2
        x2 = x + w / 2
        y2 = y + h / 2

        x1 = (x1 - dw) / ratio
        y1 = (y1 - dh) / ratio
        x2 = (x2 - dw) / ratio
        y2 = (y2 - dh) / ratio

        x1 = np.clip(x1, 0, orig_shape[1] - 1)
        y1 = np.clip(y1, 0, orig_shape[0] - 1)
        x2 = np.clip(x2, 0, orig_shape[1] - 1)
        y2 = np.clip(y2, 0, orig_shape[0] - 1)

        if x2 <= x1 or y2 <= y1:
            continue

        boxes.append([x1, y1, x2, y2])
        scores.append(score)

    if not boxes:
        return np.empty((0, 4), dtype=np.float32), np.empty((0,), dtype=np.float32)

    boxes_np = np.array(boxes, dtype=np.float32)
    scores_np = np.array(scores, dtype=np.float32)
    keep = nms(boxes_np, scores_np, iou_thres)
    return boxes_np[keep], scores_np[keep]


def select_pupil_area(pupil_area_raw: float, pupil_area_norm_320: float) -> float:
    if PUPIL_AREA_MODE == "raw":
        return pupil_area_raw
    if PUPIL_AREA_MODE == "norm_320":
        return pupil_area_norm_320
    raise ValueError(
        "Invalid PUPIL_AREA_MODE. Use 'norm_320' for 320x240-normalized area "
        "or 'raw' for captured-frame area."
    )


class PupilAreaRecorder:
    """Realtime pupil detector with a rolling 10-second area window."""

    def __init__(
        self,
        model_path: str = MODEL_PATH,
        camera_id: int = CAMERA_ID,
        output_csv: Optional[str] = OUTPUT_CSV,
        window_seconds: float = WINDOW_SECONDS,
        input_size: int = INPUT_SIZE,
        conf_thres: float = CONF_THRES,
        iou_thres: float = IOU_THRES,
        frame_width: int = FRAME_WIDTH,
        frame_height: int = FRAME_HEIGHT,
        camera_fps: int = CAMERA_FPS,
        use_v4l2: bool = False,
        camera_fourcc: Optional[str] = None,
        max_impute_gap_frames: int = 5,
    ) -> None:
        self.model_path = model_path
        self.camera_id = camera_id
        self.output_csv = output_csv
        self.window_seconds = window_seconds
        self.input_size = input_size
        self.conf_thres = conf_thres
        self.iou_thres = iou_thres
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.camera_fps = camera_fps
        self.use_v4l2 = use_v4l2
        self.camera_fourcc = camera_fourcc
        self.max_impute_gap_frames = max_impute_gap_frames

        self.session: Optional[ort.InferenceSession] = None
        self.input_name: Optional[str] = None
        self.cap: Optional[cv2.VideoCapture] = None
        self.window: Deque[PupilSample] = deque()
        self.frame_count = 0
        self.avg_fps = 0.0
        self.start_time = 0.0
        self.last_sample_wall_time = 0.0
        self.last_valid_sample: Optional[PupilSample] = None
        self.last_frame: Optional[np.ndarray] = None
        self.impute_gap_frames = 0

    def open(self) -> None:
        if self.output_csv:
            os.makedirs(os.path.dirname(self.output_csv), exist_ok=True)

        self.session = ort.InferenceSession(
            self.model_path,
            providers=["CPUExecutionProvider"],
        )
        self.input_name = self.session.get_inputs()[0].name

        if self.use_v4l2:
            self.cap = cv2.VideoCapture(self.camera_id, cv2.CAP_V4L2)
        else:
            self.cap = cv2.VideoCapture(self.camera_id)

        if self.camera_fourcc:
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.camera_fourcc))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
        self.cap.set(cv2.CAP_PROP_FPS, self.camera_fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open camera: {self.camera_id}")

        self.frame_count = 0
        self.avg_fps = 0.0
        self.start_time = time.time()
        self.last_sample_wall_time = 0.0
        self.last_valid_sample = None
        self.last_frame = None
        self.impute_gap_frames = 0
        self.window.clear()

        actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
        print(f"[INFO] model: {self.model_path}")
        print(f"[INFO] camera actual size: {actual_w}x{actual_h}, fps={actual_fps}")
        print(f"[INFO] pupil area mode: {PUPIL_AREA_MODE}")
        print(f"[INFO] normalized area reference: {AREA_NORM_WIDTH:.0f}x{AREA_NORM_HEIGHT:.0f}")
        print(f"[INFO] rolling window: {self.window_seconds:.1f}s")
        if self.output_csv:
            print(f"[INFO] output csv: {self.output_csv}")

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        if self.output_csv:
            self.flush_csv()

    def read_once(self) -> PupilSample:
        if self.cap is None or self.session is None or self.input_name is None:
            raise RuntimeError("Recorder is not opened. Call open() first.")

        ok, frame = self.cap.read()
        if not ok:
            raise RuntimeError("Failed to read frame from camera.")
        self.last_frame = frame.copy()

        t0 = time.time()
        elapsed = t0 - self.start_time

        inp, ratio, dw, dh = preprocess(frame, self.input_size)
        pred = self.session.run(None, {self.input_name: inp})[0]
        boxes, scores = postprocess(
            pred,
            frame.shape[:2],
            ratio,
            dw,
            dh,
            self.conf_thres,
            self.iou_thres,
        )

        detected = 0
        center_x = center_y = -1
        bbox_w = bbox_h = -1.0
        pupil_area = -1.0
        pupil_area_raw = -1.0
        pupil_area_norm_320 = -1.0
        confidence = -1.0

        if len(boxes) > 0:
            idx = int(np.argmax(scores))
            x1, y1, x2, y2 = boxes[idx]
            confidence = float(scores[idx])
            bbox_w = float(max(0.0, x2 - x1))
            bbox_h = float(max(0.0, y2 - y1))
            center_x = int((x1 + x2) / 2)
            center_y = int((y1 + y2) / 2)
            pupil_area_raw = math.pi * (bbox_w / 2.0) * (bbox_h / 2.0)
            scale_x = AREA_NORM_WIDTH / max(float(frame.shape[1]), 1.0)
            scale_y = AREA_NORM_HEIGHT / max(float(frame.shape[0]), 1.0)
            pupil_area_norm_320 = pupil_area_raw * scale_x * scale_y
            pupil_area = select_pupil_area(pupil_area_raw, pupil_area_norm_320)
            detected = 1
        elif self.last_valid_sample is not None and self.impute_gap_frames < self.max_impute_gap_frames:
            # Smooth over brief detector dropouts so one -1 frame does not break trend logic.
            self.impute_gap_frames += 1
            detected = 1
            center_x = self.last_valid_sample.center_x
            center_y = self.last_valid_sample.center_y
            bbox_w = self.last_valid_sample.bbox_w
            bbox_h = self.last_valid_sample.bbox_h
            pupil_area = self.last_valid_sample.pupil_area
            pupil_area_raw = self.last_valid_sample.pupil_area_raw
            pupil_area_norm_320 = self.last_valid_sample.pupil_area_norm_320
            confidence = self.last_valid_sample.confidence

        t1 = time.time()
        total_frames = self.frame_count + 1
        self.avg_fps = total_frames / max(t1 - self.start_time, 1e-6)
        self.last_sample_wall_time = t1

        sample = PupilSample(
            frame=self.frame_count,
            time_sec=elapsed,
            detected=detected,
            center_x=center_x,
            center_y=center_y,
            bbox_w=bbox_w,
            bbox_h=bbox_h,
            pupil_area=pupil_area,
            pupil_area_raw=pupil_area_raw,
            pupil_area_norm_320=pupil_area_norm_320,
            confidence=confidence,
            fps=self.avg_fps,
        )

        if len(boxes) > 0:
            self.last_valid_sample = sample
            self.impute_gap_frames = 0

        self.frame_count += 1
        self.window.append(sample)
        self._trim_window(elapsed)
        return sample

    def get_latest_sample(self) -> Optional[Dict[str, float]]:
        if not self.window:
            return None
        return asdict(self.window[-1])

    def get_recent_window(self) -> List[Dict[str, float]]:
        return [asdict(sample) for sample in self.window]

    def get_last_frame(self) -> Optional[np.ndarray]:
        if self.last_frame is None:
            return None
        return self.last_frame.copy()

    def flush_csv(self) -> None:
        if not self.output_csv:
            return

        os.makedirs(os.path.dirname(self.output_csv), exist_ok=True)
        with open(self.output_csv, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "frame",
                    "time_sec",
                    "detected",
                    "center_x",
                    "center_y",
                    "bbox_w",
                    "bbox_h",
                    "pupil_area",
                    "pupil_area_raw",
                    "pupil_area_norm_320",
                    "confidence",
                    "fps",
                ],
            )
            writer.writeheader()
            for sample in self.window:
                row = asdict(sample)
                row["time_sec"] = f"{row['time_sec']:.4f}"
                row["bbox_w"] = f"{row['bbox_w']:.2f}"
                row["bbox_h"] = f"{row['bbox_h']:.2f}"
                row["pupil_area"] = f"{row['pupil_area']:.2f}"
                row["pupil_area_raw"] = f"{row['pupil_area_raw']:.2f}"
                row["pupil_area_norm_320"] = f"{row['pupil_area_norm_320']:.2f}"
                row["confidence"] = f"{row['confidence']:.4f}"
                row["fps"] = f"{row['fps']:.2f}"
                writer.writerow(row)

    def _trim_window(self, current_time: float) -> None:
        while self.window and current_time - self.window[0].time_sec > self.window_seconds:
            self.window.popleft()

    def run_forever(
        self,
        print_every: int = 30,
        flush_every: int = CSV_FLUSH_EVERY_FRAMES,
    ) -> None:
        try:
            while True:
                try:
                    sample = self.read_once()
                except RuntimeError as exc:
                    print(f"[WARN] {exc}")
                    continue

                if self.frame_count % flush_every == 0:
                    self.flush_csv()

                if self.frame_count % print_every == 0:
                    print(
                        f"[INFO] frame={sample.frame}, "
                        f"time={sample.time_sec:.2f}s, "
                        f"window={len(self.window)} samples, "
                        f"area={sample.pupil_area:.1f}, "
                        f"center=({sample.center_x},{sample.center_y}), "
                        f"conf={sample.confidence:.3f}, "
                        f"fps={sample.fps:.2f}"
                    )
        except KeyboardInterrupt:
            print("\n[INFO] stopped by user")
        finally:
            self.close()
            if self.output_csv:
                print(f"[INFO] saved rolling csv: {self.output_csv}")


def main() -> None:
    recorder = PupilAreaRecorder()
    recorder.open()
    recorder.run_forever()


if __name__ == "__main__":
    main()
