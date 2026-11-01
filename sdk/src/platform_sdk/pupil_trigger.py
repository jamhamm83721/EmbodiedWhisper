import math
import statistics
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    from scipy.signal import savgol_filter as _savgol_filter
except Exception:  # pragma: no cover - fallback for environments without scipy
    _savgol_filter = None


def _safe_savgol(values: np.ndarray, window_length: int, polyorder: int, deriv: int = 0) -> np.ndarray:
    if values.size == 0:
        return values
    usable = min(window_length, int(values.size) if int(values.size) % 2 == 1 else int(values.size) - 1)
    if usable < polyorder + 2:
        if deriv == 0:
            return values.copy()
        return np.gradient(values)
    if usable % 2 == 0:
        usable -= 1
    if usable < 3:
        if deriv == 0:
            return values.copy()
        return np.gradient(values)
    if _savgol_filter is not None:
        return _savgol_filter(values, usable, min(polyorder, usable - 1), deriv=deriv)
    if deriv == 0:
        kernel = np.ones(usable, dtype=float) / float(usable)
        return np.convolve(values, kernel, mode="same")
    return np.gradient(values)


class RealtimeLhipaEngine:
    """Streaming RIPA/LHIPA score computed on a fixed-length recent buffer."""

    def __init__(self, fs: int = 20, buf_seconds: float = 2.0) -> None:
        self.fs = int(fs)
        self.buf_seconds = float(buf_seconds)
        self.n = max(3, int(round(self.fs * self.buf_seconds)))
        self.buf: Deque[float] = deque(maxlen=self.n)
        self.omega = (1.0 / 0.6745) ** 2

    def reset(self) -> None:
        self.buf.clear()

    def push(self, value: float) -> None:
        if value is None:
            return
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return
        if math.isnan(numeric):
            return
        self.buf.append(numeric)

    def compute(self) -> float:
        if len(self.buf) < self.n:
            return float("nan")

        x = np.asarray(self.buf, dtype=float)
        low = _safe_savgol(x, 13, 2, deriv=0)
        high = _safe_savgol(x, 13, 3, deriv=1)
        ratio = low / (np.abs(high) + 1e-9)
        extrema = np.zeros_like(ratio)
        for idx in range(1, len(ratio) - 1):
            left = abs(ratio[idx - 1])
            center = abs(ratio[idx])
            right = abs(ratio[idx + 1])
            if (center > left and center >= right) or (center >= left and center > right):
                extrema[idx] = np.sign(ratio[idx]) * center

        non_zero = extrema[extrema != 0]
        if non_zero.size < 3:
            return float("nan")

        lam = self.omega * float(np.std(non_zero))
        center = float(np.median(extrema))
        count = int(np.sum((ratio > center + lam) | (ratio < center - lam)))
        return 1.0 - count / float(self.n)


class PupilRipaTrigger:
    """Trigger wrapper that computes online RIPA scores from recent pupil windows."""

    def __init__(
        self,
        nominal_fs: float = 20.0,
        ripa_window_seconds: float = 2.0,
        min_confidence: float = 0.70,
        bad_span_seconds: float = 0.20,
        min_valid_samples: int = 40,
        trigger_threshold: float = 0.58,
        baseline_window_size: int = 60,
        min_baseline_scores: int = 12,
        z_score_threshold: float = 1.2,
        cooldown_seconds: float = 10.0,
        max_interp_gap_seconds: float = 0.40,
        hold_last_value_seconds: float = 0.75,
        use_zscore_trigger: bool = True,
    ) -> None:
        self.nominal_fs = float(nominal_fs)
        self.ripa_window_seconds = float(ripa_window_seconds)
        self.min_confidence = float(min_confidence)
        self.bad_span_seconds = float(bad_span_seconds)
        self.min_valid_samples = int(min_valid_samples)
        self.trigger_threshold = float(trigger_threshold)
        self.baseline_window_size = int(baseline_window_size)
        self.min_baseline_scores = int(min_baseline_scores)
        self.z_score_threshold = float(z_score_threshold)
        self.cooldown_seconds = float(cooldown_seconds)
        self.max_interp_gap_seconds = float(max_interp_gap_seconds)
        self.hold_last_value_seconds = float(hold_last_value_seconds)
        self.use_zscore_trigger = bool(use_zscore_trigger)

        self.last_trigger_time = 0.0
        self.last_metrics: Dict[str, object] = {}
        self.baseline_scores: Deque[float] = deque(maxlen=self.baseline_window_size)
        self.last_window_signature: Optional[Tuple[object, ...]] = None
        self.last_ready_metrics: Optional[Dict[str, object]] = None
        self.last_ready_time_sec: Optional[float] = None

    def update(self, window: List[Dict[str, float]]) -> Dict[str, object]:
        metrics = self._compute_metrics(window)
        self.last_metrics = metrics
        if bool(metrics.get("ready", False)):
            latest_score = float(metrics["ripa_score"])
            baseline_median = float(metrics["baseline_median"])
            baseline_std = max(float(metrics["baseline_std"]), 1e-6)
            metrics["z_score"] = (latest_score - baseline_median) / baseline_std
            if metrics.get("reason") == "ready":
                metrics["reason"] = "monitoring"
            self._update_baseline(latest_score)
            self.last_ready_metrics = dict(metrics)
            self.last_ready_time_sec = self._latest_time_sec(window)
            return dict(metrics)

        latest_time_sec = self._latest_time_sec(window)
        if (
            metrics.get("reason") == "insufficient_clean_signal"
            and self.last_ready_metrics is not None
            and self.last_ready_time_sec is not None
            and latest_time_sec is not None
            and latest_time_sec - self.last_ready_time_sec <= self.hold_last_value_seconds
        ):
            held = dict(self.last_ready_metrics)
            held["reason"] = "holding_last_ripa"
            held["held_since_sec"] = latest_time_sec - self.last_ready_time_sec
            self.last_metrics = held
            return held
        return dict(metrics)

    def should_trigger(self, window: List[Dict[str, float]]) -> bool:
        now = time.time()
        metrics = self.update(window)
        self.last_metrics = metrics

        if not bool(metrics.get("ready", False)):
            return False

        if now - self.last_trigger_time < self.cooldown_seconds:
            metrics["reason"] = "cooldown"
            metrics["cooldown_remaining"] = self.cooldown_seconds - (now - self.last_trigger_time)
            return False

        latest_score = float(metrics["ripa_score"])
        baseline_median = float(metrics["baseline_median"])
        baseline_std = max(float(metrics["baseline_std"]), 1e-6)
        z_score = (latest_score - baseline_median) / baseline_std
        metrics["z_score"] = z_score

        threshold_hit = latest_score <= self.trigger_threshold
        baseline_shift_hit = self.use_zscore_trigger and z_score <= -abs(self.z_score_threshold)
        if threshold_hit or baseline_shift_hit:
            metrics["reason"] = "triggered"
            metrics["threshold_hit"] = threshold_hit
            metrics["baseline_shift_hit"] = baseline_shift_hit
            self.last_trigger_time = now
            return True

        metrics["reason"] = "below_evidence"
        return False

    def get_last_metrics(self) -> Dict[str, object]:
        return dict(self.last_metrics)

    def _compute_metrics(self, window: List[Dict[str, float]]) -> Dict[str, object]:
        if not window:
            return {"reason": "empty_window", "ready": False}

        signature = self._window_signature(window)
        if signature == self.last_window_signature and self.last_metrics:
            return dict(self.last_metrics)
        self.last_window_signature = signature

        session = self._prepare_session(window)
        if session is None:
            return {"reason": "insufficient_clean_signal", "ready": False}

        times, diameters = session
        if len(times) < self.min_valid_samples:
            return {
                "reason": "too_few_resampled_points",
                "ready": False,
                "resampled_points": len(times),
            }

        engine = RealtimeLhipaEngine(
            fs=max(2, int(round(self.nominal_fs))),
            buf_seconds=self.ripa_window_seconds,
        )
        series: List[float] = []
        for value in diameters:
            engine.push(value)
            series.append(engine.compute())

        valid_scores = [float(v) for v in series if not math.isnan(v)]
        if not valid_scores:
            return {"reason": "no_valid_ripa_scores", "ready": False}

        latest_score = valid_scores[-1]
        temp_baseline = list(self.baseline_scores)
        if len(temp_baseline) < self.min_baseline_scores:
            temp_baseline.extend(valid_scores[:-1])

        if self.min_baseline_scores <= 0:
            baseline_source = temp_baseline or valid_scores[:-1] or [latest_score]
            baseline_median = statistics.median(baseline_source)
            baseline_std = statistics.pstdev(baseline_source) if len(baseline_source) > 1 else 0.01
            valid_ratio = len(valid_scores) / max(len(series), 1)
            recent_mean = statistics.mean(valid_scores[-min(10, len(valid_scores)):])
            return {
                "reason": "ready",
                "ready": True,
                "ripa_score": latest_score,
                "ripa_recent_mean": recent_mean,
                "ripa_min": min(valid_scores),
                "ripa_max": max(valid_scores),
                "ripa_valid_ratio": valid_ratio,
                "baseline_median": baseline_median,
                "baseline_std": max(baseline_std, 0.01),
                "baseline_count": len(baseline_source),
                "resampled_points": len(times),
                "window_duration": float(times[-1] - times[0]) if len(times) > 1 else 0.0,
            }

        if len(temp_baseline) < self.min_baseline_scores:
            return {
                "reason": "collecting_ripa_baseline",
                "ready": False,
                "ripa_score": latest_score,
                "baseline_count": len(temp_baseline),
                "min_baseline_scores": self.min_baseline_scores,
            }

        baseline_median = statistics.median(temp_baseline)
        baseline_std = statistics.pstdev(temp_baseline) if len(temp_baseline) > 1 else 0.01
        valid_ratio = len(valid_scores) / max(len(series), 1)
        recent_mean = statistics.mean(valid_scores[-min(10, len(valid_scores)):])

        return {
            "reason": "ready",
            "ready": True,
            "ripa_score": latest_score,
            "ripa_recent_mean": recent_mean,
            "ripa_min": min(valid_scores),
            "ripa_max": max(valid_scores),
            "ripa_valid_ratio": valid_ratio,
            "baseline_median": baseline_median,
            "baseline_std": max(baseline_std, 0.01),
            "baseline_count": len(temp_baseline),
            "resampled_points": len(times),
            "window_duration": float(times[-1] - times[0]) if len(times) > 1 else 0.0,
        }

    def _prepare_session(self, window: List[Dict[str, float]]) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        samples: List[Tuple[float, float, int, float]] = []
        for sample in window:
            try:
                time_sec = float(sample.get("time_sec", 0.0))
                area = float(sample.get("pupil_area_norm_320", sample.get("pupil_area", -1.0)))
                detected = int(sample.get("detected", 0))
                confidence = float(sample.get("confidence", 0.0))
            except (TypeError, ValueError):
                continue
            samples.append((time_sec, area, detected, confidence))

        if len(samples) < self.min_valid_samples:
            return None

        samples.sort(key=lambda item: item[0])
        cleaned_times: List[float] = []
        cleaned_diameters: List[float] = []
        last_valid_time: Optional[float] = None
        last_valid_diameter: Optional[float] = None

        for time_sec, area, detected, confidence in samples:
            is_valid = detected == 1 and confidence >= self.min_confidence and area > 0
            if is_valid:
                diameter = 2.0 * math.sqrt(area / math.pi)
                cleaned_times.append(time_sec)
                cleaned_diameters.append(diameter)
                last_valid_time = time_sec
                last_valid_diameter = diameter
                continue

            if (
                last_valid_time is not None
                and last_valid_diameter is not None
                and time_sec - last_valid_time <= self.max_interp_gap_seconds
            ):
                cleaned_times.append(time_sec)
                cleaned_diameters.append(last_valid_diameter)

        if len(cleaned_times) < self.min_valid_samples:
            return None

        unique_times, unique_indices = np.unique(np.asarray(cleaned_times, dtype=float), return_index=True)
        unique_diams = np.asarray(cleaned_diameters, dtype=float)[unique_indices]
        if unique_times.size < self.min_valid_samples:
            return None

        t0 = float(unique_times[0])
        t1 = float(unique_times[-1])
        if t1 - t0 < self.ripa_window_seconds:
            return None

        t_new = np.arange(t0, t1, 1.0 / self.nominal_fs, dtype=float)
        if t_new.size < self.min_valid_samples:
            return None
        x_new = np.interp(t_new, unique_times, unique_diams)
        return t_new, x_new

    def _update_baseline(self, latest_score: float) -> None:
        if not math.isnan(latest_score):
            self.baseline_scores.append(float(latest_score))

    def _window_signature(self, window: Sequence[Dict[str, float]]) -> Tuple[object, ...]:
        latest = window[-1]
        return (
            len(window),
            latest.get("frame"),
            latest.get("time_sec"),
            latest.get("pupil_area_norm_320", latest.get("pupil_area")),
            latest.get("confidence"),
        )

    @staticmethod
    def _latest_time_sec(window: Sequence[Dict[str, float]]) -> Optional[float]:
        if not window:
            return None
        latest = window[-1].get("time_sec")
        try:
            return float(latest)
        except (TypeError, ValueError):
            return None
