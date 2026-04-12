import io
import os
import time

_MOCK = os.getenv("MOCK_CAMERA", "0") == "1"

if not _MOCK:
    try:
        from picamera2 import Picamera2
    except ImportError:
        _MOCK = True

# Minimal valid 1x1 white JPEG — used by the mock, zero runtime deps
_MINIMAL_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000"
    "ffdb004300080606070605080707070909080a0c"
    "140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20"
    "242e2720222c231c1c2837292c30313434341f27"
    "393d38323c2e333432ffc0000b080001000101011"
    "100ffc4001f0000010501010101010100000000000"
    "00000010203040506070809000affc40000"
)

# Use a known-good minimal JPEG (1x1 white pixel, ~631 bytes)
_STUB_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff"
    b"\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f"
    b"\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5"
    b"\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01"
    b"}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07\"q\x142\x81\x91"
    b"\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16\x17\x18\x19\x1a%"
    b"&'()*456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x83\x84\x85\x86\x87"
    b"\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5"
    b"\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3"
    b"\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda"
    b"\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6"
    b"\xf7\xf8\xf9\xfa\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd4P\x00"
    b"\x00\x00\x00\x1f\xff\xd9"
)

def _still_size() -> tuple[int, int]:
    """Optional MTG_STILL_SIZE or CAMERA_STILL_SIZE as WxH (e.g. 3280x2464)."""
    raw = (os.getenv("MTG_STILL_SIZE") or os.getenv("CAMERA_STILL_SIZE") or "").strip().lower()
    if raw and "x" in raw:
        try:
            a, b = raw.split("x", 1)
            w, h = int(a.strip()), int(b.strip())
            if w > 0 and h > 0:
                return (w, h)
        except ValueError:
            pass
    return (2304, 1296)


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


class _MockCardCamera:
    """Stub used when MOCK_CAMERA=1 or picamera2 is not installed."""

    def __init__(self, jpeg_quality: int = 90) -> None:
        self._jpeg_quality = jpeg_quality
        self._started = False

    def start(self) -> None:
        self._started = True
        print("[MockCamera] started")

    def capture_jpeg(self) -> bytes:
        if not self._started:
            raise RuntimeError("Camera not started — call start() first")
        print("[MockCamera] returning stub JPEG")
        return _STUB_JPEG

    def stop(self) -> None:
        self._started = False
        print("[MockCamera] stopped")

    def __enter__(self) -> "_MockCardCamera":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()


def CardCamera(jpeg_quality: int = 90):
    """
    Factory that returns the appropriate camera implementation.

    On Raspberry Pi with picamera2 available (and MOCK_CAMERA != 1):
        returns _RealCardCamera

    On dev machine or when MOCK_CAMERA=1:
        returns _MockCardCamera
    """
    if _MOCK:
        return _MockCardCamera(jpeg_quality)
    return _RealCardCamera(jpeg_quality)
