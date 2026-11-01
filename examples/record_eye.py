"""Record pupil samples using a compatible local detector model and USB camera."""
import argparse
from pathlib import Path
from platform_sdk.eye_camera import PupilAreaRecorder

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--camera", type=int, required=True)
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument("--output", default="outputs/eye/pupil_samples.csv")
    args = parser.parse_args()
    if not Path(args.model).is_file():
        parser.error("--model must point to an existing compatible ONNX file")
    recorder = PupilAreaRecorder(model_path=args.model, camera_id=args.camera,
                                camera_fps=args.fps, output_csv=args.output)
    try:
        recorder.open()
        recorder.run_forever()
    finally:
        recorder.close()

if __name__ == "__main__":
    main()
