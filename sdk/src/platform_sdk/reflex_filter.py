import csv
import os
import statistics
from collections import deque
from dataclasses import asdict, dataclass
from typing import Deque, Dict, List, Optional, Sequence

import numpy as np


@dataclass
class NearReflexWindowResult:
    frame: int
    timestamp_sec: float
    window_start_sec: float
    window_end_sec: float
    sample_count: int
    valid_ratio: float
    area_clean: float
    p_vel: float
    p_step: float
    p_amp: float
    event_prob: float
    is_near_reflex: int
    event_ratio: float
    sigma_v: float


class CumulativeNearReflexRealtime:
    """Causal near-reflex detector evaluated inside one independent window."""

    def __init__(
        self,
        fs: float,
        short_win_s: float = 0.4,
        long_win_s: float = 3.0,
        smooth_win_s: float = 0.1,
        vel_k: float = 4.0,
        step_k: float = 0.15,
        amp_k: float = 0.12,
        prob_th: float = 0.5,
        blink_pad_s: float = 0.2,
    ) -> None:
        self.fs = max(float(fs), 1.0)
        self.vel_k = vel_k
        self.step_k = step_k
        self.amp_k = amp_k
        self.prob_th = prob_th
        self.n_short = max(3, int(round(short_win_s * self.fs)))
        self.n_long = max(self.n_short * 3, int(round(long_win_s * self.fs)))
        self.n_smooth = max(3, int(round(smooth_win_s * self.fs)))
        self.blink_pad_n = max(1, int(round(blink_pad_s * self.fs)))
        self.raw_area: List[float] = []
        self.detected: List[int] = []
        self.area_clean: List[float] = []
        self.valid: List[bool] = []
        self.abs_velocity: List[float] = []
        self.event_prob: List[float] = []
        self.is_event: List[bool] = []
        self.sigma_v: List[float] = []
        self._hampel_buf: Deque[float] = deque(maxlen=9)
        self._prev_area: Optional[float] = None
        self._blink_cooldown = 0

    def push(self, raw_area: float, detected_flag: int) -> Dict[str, float]:
        raw = float(raw_area) if np.isfinite(raw_area) else np.nan
        det = int(detected_flag)
        self.raw_area.append(raw)
        self.detected.append(det)

        if det == 0:
            self._blink_cooldown = self.blink_pad_n
        elif self._blink_cooldown > 0:
            self._blink_cooldown -= 1
        is_valid = det == 1 and self._blink_cooldown == 0
        self.valid.append(is_valid)

        if not np.isfinite(raw):
            history = np.asarray(self.area_clean, dtype=float)
            raw = float(history[np.isfinite(history)][-1]) if history.size and np.isfinite(history).any() else 0.0

        self._hampel_buf.append(raw if is_valid else np.nan)
        area_c = self._online_hampel(raw) if is_valid else raw
        self.area_clean.append(float(area_c))

        vel = 0.0 if self._prev_area is None else abs(area_c - self._prev_area) * self.fs
        self._prev_area = area_c
        self.abs_velocity.append(float(vel))

        vel_arr = np.asarray(self.abs_velocity, dtype=float)
        valid_arr = np.asarray(self.valid, dtype=bool)
        sigma_source = vel_arr[valid_arr] if valid_arr.any() else vel_arr
        sigma_v = float(np.percentile(sigma_source, 60)) + 1e-9
        self.sigma_v.append(sigma_v)

        mu_long = self._causal_mean(self.area_clean, self.n_long)
        mu_short = self._causal_mean(self.area_clean, self.n_short)
        rel_amp = abs(area_c - mu_long) / (abs(mu_long) + 1e-9)
        step_ratio = abs(mu_short - mu_long) / (abs(mu_long) + 1e-9)
        p_vel = float(np.clip(vel / (self.vel_k * sigma_v), 0.0, 1.0))
        p_step = float(np.clip(step_ratio / self.step_k, 0.0, 1.0))
        p_amp = float(np.clip(rel_amp / self.amp_k, 0.0, 1.0))

        prob_raw = float(p_vel * max(p_step, p_amp))
        if not is_valid:
            prob_raw = 0.0
        prob = self._causal_mean(self.event_prob + [prob_raw], self.n_smooth)
        is_nr = bool(prob > self.prob_th)
        self.event_prob.append(float(prob))
        self.is_event.append(is_nr)

        return {
            "area_clean": float(area_c),
            "p_vel": p_vel,
            "p_step": p_step,
            "p_amp": p_amp,
            "event_prob": float(prob),
            "is_near_reflex": float(is_nr),
            "sigma_v": float(sigma_v),
        }

    def _online_hampel(self, x: float, n_sigma: float = 3.0) -> float:
        arr = np.array([v for v in self._hampel_buf if np.isfinite(v)], dtype=float)
        if arr.size < 3:
            return float(x)
        med = float(np.median(arr))
        mad = float(np.median(np.abs(arr - med))) + 1e-9
        return med if abs(x - med) > n_sigma * 1.4826 * mad else float(x)

    @staticmethod
    def _causal_mean(seq: Sequence[float], n: int) -> float:
        if not seq:
            return float("nan")
        tail = np.asarray(seq[-n:], dtype=float)
        return float(np.mean(tail))


class SlidingWindowNearReflexMonitor:
    """Run the 90s/45s near-reflex detector on realtime pupil samples."""

    def __init__(
        self,
        window_seconds: float = 90.0,
        step_seconds: float = 45.0,
        nominal_fps: float = 30.0,
        min_valid_ratio: float = 0.65,
        abnormal_prob_threshold: float = 0.70,
        abnormal_event_ratio_threshold: float = 0.12,
        output_csv: Optional[str] = "./outputs/eye/near_reflex_latest.csv",
    ) -> None:
        self.window_seconds = float(window_seconds)
        self.step_seconds = float(step_seconds)
        self.nominal_fps = float(nominal_fps)
        self.min_valid_ratio = float(min_valid_ratio)
        self.abnormal_prob_threshold = float(abnormal_prob_threshold)
        self.abnormal_event_ratio_threshold = float(abnormal_event_ratio_threshold)
        self.output_csv = output_csv
        self.samples: Deque[Dict[str, float]] = deque()
        self.last_eval_time: Optional[float] = None
        self.latest_result: Optional[NearReflexWindowResult] = None

    def push_sample(self, sample: Dict[str, float]) -> Optional[NearReflexWindowResult]:
        timestamp = float(sample.get("time_sec", 0.0))
        self.samples.append(dict(sample))
        self._trim(timestamp)

        if self.last_eval_time is None:
            self.last_eval_time = timestamp
            return None
        if timestamp < self.window_seconds:
            return None
        if timestamp - self.last_eval_time < self.step_seconds:
            return None

        result = self.evaluate_current_window(timestamp)
        self.last_eval_time = timestamp
        if result is not None:
            self.latest_result = result
            self._write_latest_csv(result)
        return result

    def evaluate_current_window(self, timestamp: Optional[float] = None) -> Optional[NearReflexWindowResult]:
        if not self.samples:
            return None
        end_t = float(timestamp if timestamp is not None else self.samples[-1].get("time_sec", 0.0))
        start_t = end_t - self.window_seconds
        window = [row for row in self.samples if float(row.get("time_sec", 0.0)) >= start_t]
        if len(window) < 8:
            return None

        fs = self._estimate_fps(window)
        detector = CumulativeNearReflexRealtime(fs=fs)
        last = None
        valid_count = 0
        event_count = 0

        for row in window:
            area = float(row.get("pupil_area", -1.0))
            detected = int(row.get("detected", 0) == 1 and area > 0)
            valid_count += detected
            last = detector.push(area if area > 0 else np.nan, detected)
            event_count += int(bool(last["is_near_reflex"]))

        valid_ratio = valid_count / max(len(window), 1)
        if valid_ratio < self.min_valid_ratio or last is None:
            return None

        return NearReflexWindowResult(
            frame=int(window[-1].get("frame", -1)),
            timestamp_sec=end_t,
            window_start_sec=float(window[0].get("time_sec", start_t)),
            window_end_sec=end_t,
            sample_count=len(window),
            valid_ratio=valid_ratio,
            area_clean=float(last["area_clean"]),
            p_vel=float(last["p_vel"]),
            p_step=float(last["p_step"]),
            p_amp=float(last["p_amp"]),
            event_prob=float(last["event_prob"]),
            is_near_reflex=int(bool(last["is_near_reflex"])),
            event_ratio=event_count / max(len(window), 1),
            sigma_v=float(last["sigma_v"]),
        )

    def get_latest_result(self) -> Optional[Dict[str, float]]:
        return asdict(self.latest_result) if self.latest_result else None

    def check_current_abnormal(
        self,
        timestamp: Optional[float] = None,
    ) -> tuple[bool, Optional[NearReflexWindowResult]]:
        """Evaluate the current 90s window and return whether it should block LLM calls."""
        result = self.evaluate_current_window(timestamp)
        if result is None:
            result = self.latest_result
        else:
            self.latest_result = result
            self._write_latest_csv(result)

        if result is None:
            return False, None

        prob_high = result.event_prob >= self.abnormal_prob_threshold
        ratio_high = result.event_ratio >= self.abnormal_event_ratio_threshold
        instant_high = bool(result.is_near_reflex) and result.event_prob >= self.abnormal_prob_threshold
        # Avoid blocking on one noisy near-reflex cue; require probability plus persistence.
        abnormal = (prob_high and ratio_high) or instant_high
        return abnormal, result

    def _estimate_fps(self, window: Sequence[Dict[str, float]]) -> float:
        times = [float(row.get("time_sec", 0.0)) for row in window]
        diffs = [b - a for a, b in zip(times, times[1:]) if b > a]
        if not diffs:
            return self.nominal_fps
        return 1.0 / max(statistics.median(diffs), 1e-6)

    def _trim(self, current_time: float) -> None:
        keep_seconds = self.window_seconds + max(self.step_seconds, 5.0)
        while self.samples and current_time - float(self.samples[0].get("time_sec", 0.0)) > keep_seconds:
            self.samples.popleft()

    def _write_latest_csv(self, result: NearReflexWindowResult) -> None:
        if not self.output_csv:
            return
        os.makedirs(os.path.dirname(self.output_csv), exist_ok=True)
        with open(self.output_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(asdict(result).keys()))
            writer.writeheader()
            writer.writerow(asdict(result))
