"""Deterministic demonstration; all samples below are generated, not experimental data."""
import json
import math
from platform_sdk.pupil_trigger import PupilRipaTrigger
from platform_sdk.reflex_filter import SlidingWindowNearReflexMonitor

def main():
    monitor = SlidingWindowNearReflexMonitor(window_seconds=4.0, step_seconds=2.0,
                                           nominal_fps=20, output_csv=None)
    trigger = PupilRipaTrigger(nominal_fs=20, ripa_window_seconds=2.0)
    samples = []
    for frame in range(161):
        t = frame / 20.0
        area = 1200.0 + 45.0 * math.sin(2.0 * math.pi * 0.6 * t)
        sample = {"frame": frame, "time_sec": t, "detected": 1,
                  "confidence": 0.95, "pupil_area": area, "pupil_area_norm_320": area / 4.0}
        samples.append(sample)
        monitor.push_sample(sample)
    print(json.dumps({"data_kind": "synthetic", "sample_count": len(samples),
                      "ripa": trigger.update(samples),
                      "reflex": monitor.get_latest_result()}, indent=2))

if __name__ == "__main__":
    main()
