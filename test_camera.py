#!/usr/bin/env python3
"""
Manual verification for Raspberry Pi **Camera Module 3** via ``picamera2`` (libcamera).

Usage:
    python3 test_camera.py              # capture twice
    python3 test_camera.py --save       # save JPEG to /tmp/card_test.jpg
                                        # then: scp pi@raspberrypi.local:/tmp/card_test.jpg .
                                        # Prints JPEG width x height (needs Pillow).
"""
import io
import sys
import time

from camera import CardCamera


def _print_jpeg_size(label: str, data: bytes) -> None:
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(data))
        print(f"  {label} JPEG size: {im.size[0]} x {im.size[1]} px")
    except Exception:
        print(f"  {label} (could not read JPEG dimensions — pip install Pillow)")


def main():
    save = "--save" in sys.argv

    print("Initialising camera...")
    cam = CardCamera()

    try:
        cam.start()
        print("Camera started.")

        print("Triggering autofocus + capture (first capture)...")
        t0 = time.monotonic()
        data = cam.capture_jpeg()
        elapsed = time.monotonic() - t0
        print(f"  {len(data):,} bytes in {elapsed:.2f}s")
        _print_jpeg_size("First", data)

        if len(data) < 500:
            print("WARN: suspiciously small JPEG — AF or capture may have failed")

        if save:
            path = "/tmp/card_test.jpg"
            with open(path, "wb") as f:
                f.write(data)
            print(f"  Saved to {path}")
            print("  Inspect with: scp pi@raspberrypi.local:/tmp/card_test.jpg .")

        print("Second capture (no AWB re-settle)...")
        t0 = time.monotonic()
        data2 = cam.capture_jpeg()
        elapsed2 = time.monotonic() - t0
        print(f"  {len(data2):,} bytes in {elapsed2:.2f}s")
        _print_jpeg_size("Second", data2)

        print("PASS")

    except Exception as e:
        print(f"FAIL: {e}")
        raise
    finally:
        cam.stop()
        print("Camera stopped.")


if __name__ == "__main__":
    main()
