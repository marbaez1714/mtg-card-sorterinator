import io
import os
import time

try:
    from picamera2 import Picamera2
except ImportError:
    Picamera2 = None  # type: ignore[misc, assignment]


def _still_size() -> tuple[int, int]:
    """Optional MTG_STILL_SIZE or CAMERA_STILL_SIZE as WxH (e.g. 3280x2464 for max detail)."""
    raw = (os.getenv("MTG_STILL_SIZE") or os.getenv("CAMERA_STILL_SIZE") or "").strip().lower()
    if raw and "x" in raw:
        try:
            a, b = raw.split("x", 1)
            w, h = int(a.strip()), int(b.strip())
            if w > 0 and h > 0:
                return (w, h)
        except ValueError:
            pass
    # Default 1080p — faster capture/encode than full sensor; raise MTG_STILL_SIZE if OCR needs more pixels.
    return (1920, 1080)


def _af_range() -> int:
    """0=Normal, 1=Macro (default, close desk), 2=Full — see Picamera2/libcamera docs."""
    try:
        v = int(os.getenv("CAMERA_AF_RANGE", "1").strip())
    except ValueError:
        return 1
    return v if v in (0, 1, 2) else 1


def _settle_s() -> float:
    try:
        return max(0.0, float(os.getenv("CAMERA_SETTLE_S", "2.0").strip()))
    except ValueError:
        return 2.0


_CAMERA_CONTROLS_BASE = {
    "AfMode": 1,       # Single-shot AF (not continuous)
    "AfSpeed": 1,      # Fast AF
    "AwbEnable": True,
    "AwbMode": 0,      # Auto — adapts to varied indoor lighting
    "Sharpness": 1.5,  # Modest boost for card text; default is 1.0
    "AeEnable": True,
}


def _camera_controls() -> dict:
    c = dict(_CAMERA_CONTROLS_BASE)
    c["AfRange"] = _af_range()
    return c


class _RealCardCamera:
    def __init__(self, jpeg_quality: int = 90) -> None:
        self._jpeg_quality = jpeg_quality
        self._cam = None

    def start(self) -> None:
        assert Picamera2 is not None
        self._cam = Picamera2()
        # JPEG quality is not a libcamera pipeline control on all stacks; use
        # Picamera2's encoder options (see picamera2#431).
        self._cam.options["quality"] = self._jpeg_quality
        w, h = _still_size()
        config = self._cam.create_still_configuration(
            main={"size": (w, h), "format": "RGB888"},
            buffer_count=1,  # conserve RAM on RPi4 2GB
        )
        self._cam.configure(config)
        self._cam.set_controls(_camera_controls())
        self._cam.start()
        time.sleep(_settle_s())  # AEC/AWB converge; override with CAMERA_SETTLE_S

    def capture_jpeg(self) -> bytes:
        if self._cam is None:
            raise RuntimeError("Camera not started — call start() first")
        success = self._cam.autofocus_cycle(wait=True)
        if not success:
            print("Warning: autofocus did not converge — proceeding with capture anyway")
        buf = io.BytesIO()
        self._cam.capture_file(buf, format="jpeg")
        return buf.getvalue()

    def stop(self) -> None:
        if self._cam is not None:
            self._cam.stop()
            self._cam.close()
            self._cam = None

    def __enter__(self) -> "_RealCardCamera":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()


def CardCamera(jpeg_quality: int = 90):
    """
    Return a Picamera2-backed camera controller for **Raspberry Pi Camera Module 3**
    (IMX708). The supported Python API is still the ``picamera2`` package on Raspberry Pi OS
    (``sudo apt install -y python3-picamera2``) — not a separate ``picamera3`` library name.
    """
    if Picamera2 is None:
        raise RuntimeError(
            "picamera2 is not installed or not importable.\n"
            "  • On Raspberry Pi OS: sudo apt update && "
            "sudo apt install -y python3-picamera2 python3-libcamera\n"
            "  • If you use a venv, it hides apt packages unless the venv was created with "
            "--system-site-packages, e.g.:\n"
            "      python3 -m venv .venv --system-site-packages\n"
            "      source .venv/bin/activate && pip install -r requirements.txt\n"
            "    Or run camera scripts with system Python: /usr/bin/python3 test_camera.py\n"
            "  • picamera2 only exists on Raspberry Pi OS (not macOS/Windows).\n"
            "  • Quick check: python3 -c \"from picamera2 import Picamera2\""
        )
    return _RealCardCamera(jpeg_quality)
