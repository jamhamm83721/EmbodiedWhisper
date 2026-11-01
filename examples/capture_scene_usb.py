"""Capture a local USB scene-camera snapshot sequence."""
import argparse
from platform_sdk.scene_camera import WorldCamera

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=int, required=True)
    parser.add_argument("--output", default="outputs/scene")
    parser.add_argument("--count", type=int, default=3)
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be positive")
    camera = WorldCamera(camera_id=args.camera, output_dir=args.output)
    try:
        for path in camera.capture_photos(count=args.count):
            print(path)
    finally:
        camera.close()

if __name__ == "__main__":
    main()
