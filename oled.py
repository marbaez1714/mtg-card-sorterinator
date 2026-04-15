"""
128x64 monochrome OLED via luma.oled — **SPI** (default: CLK/MOSI/CS/DC/RES) or **I2C** (SDA/SCL).

Requires: pip install luma.oled
Pi SPI: raspi-config → enable SPI; GPIO defaults in _lazy_device (override with OLED_GPIO_*).
  Typical SPI: GND, VCC (often **5V** per breakout docs — follow the silkscreen), CLK→GPIO11,
  MOSI→GPIO10, CS→GPIO8 (CE0), DC→GPIO24, RES→GPIO25. Do **not** set OLED_GPIO_CS when CS is on CE0.
Pi I2C: set OLED_INTERFACE=i2c, enable I2C; SDA→GPIO2, SCL→GPIO3, VCC→3.3V, GND.

Docs example: https://community.microcenter.com/kb/articles/795-inland-1-3-128x64-oled-graphic-display
"""

from __future__ import annotations

import glob
import os
from typing import Any

from PIL import Image, ImageDraw, ImageFont

_STATE: str = "uninit"  # uninit | ready | failed
_DEVICE: Any = None
_LAST_FAIL_FP: str | None = None
_STUCK_LOGGED: bool = False


def _oled_enabled() -> bool:
    return os.getenv("OLED_ENABLED", "0").strip() == "1"


def _oled_debug(msg: str) -> None:
    if os.getenv("OLED_DEBUG", "0").strip() == "1":
        print(f"[OLED] debug: {msg}")


def _oled_cfg_fingerprint() -> str:
    keys = (
        "OLED_INTERFACE",
        "OLED_I2C_PORT",
        "OLED_I2C_ADDRESS",
        "OLED_SPI_PORT",
        "OLED_SPI_DEVICE",
        "OLED_GPIO_DC",
        "OLED_GPIO_RST",
        "OLED_GPIO_CS",
        "OLED_SPI_HZ",
        "OLED_DRIVER",
        "OLED_ROTATE",
        "OLED_RESET_HOLD_S",
        "OLED_RESET_RELEASE_S",
    )
    return "|".join(f"{k}={os.getenv(k, '')}" for k in keys)


def _env_optional_int(key: str) -> int | None:
    raw = os.getenv(key)
    if raw is None or not str(raw).strip():
        return None
    return int(str(raw).strip(), 0)


def _env_rst_gpio() -> int | None:
    """BCM pin for RES, or None if the board ties reset high (no Pi wire)."""
    if "OLED_GPIO_RST" not in os.environ:
        return 25
    s = os.environ["OLED_GPIO_RST"].strip().lower()
    if s in ("none", "nc", "float"):
        return None
    return int(s, 0)


def _lazy_device() -> Any:
    global _STATE, _DEVICE, _LAST_FAIL_FP, _STUCK_LOGGED
    if not _oled_enabled():
        return None
    fp = _oled_cfg_fingerprint()
    if _STATE == "failed" and fp != _LAST_FAIL_FP:
        _STATE = "uninit"
        _DEVICE = None
        _STUCK_LOGGED = False
    if _STATE == "failed":
        return None
    if _STATE == "ready":
        return _DEVICE
    try:
        from luma.core.interface.serial import gpio_cs_spi, i2c, spi
        from luma.oled.device import ssd1306, sh1106

        driver = os.getenv("OLED_DRIVER", "ssd1306").strip().lower()
        rotate = int(os.getenv("OLED_ROTATE", "0").strip())
        rotate = rotate % 4

        iface = os.getenv("OLED_INTERFACE", "spi").strip().lower()
        if iface == "i2c":
            i2c_port = int(os.getenv("OLED_I2C_PORT", "1").strip())
            addr = int(os.getenv("OLED_I2C_ADDRESS", "0x3C").strip(), 16)
            _oled_debug(f"i2c port={i2c_port} addr=0x{addr:02X} driver={driver}")
            serial = i2c(port=i2c_port, address=addr)
        else:
            spi_port = int(os.getenv("OLED_SPI_PORT", "0").strip())
            spi_dev = int(os.getenv("OLED_SPI_DEVICE", "0").strip())
            gpio_dc = int(os.getenv("OLED_GPIO_DC", "24").strip())
            gpio_rst = _env_rst_gpio()
            gpio_cs = _env_optional_int("OLED_GPIO_CS")
            # Default 1 MHz — matches raw --probe default; raise (e.g. 4_000_000) if wiring is short/clean.
            bus_hz = int(os.getenv("OLED_SPI_HZ", "1000000").strip())
            rst_hold = float(os.getenv("OLED_RESET_HOLD_S", "0.002").strip())
            rst_release = float(os.getenv("OLED_RESET_RELEASE_S", "0.05").strip())
            spi_kw: dict[str, Any] = dict(
                port=spi_port,
                device=spi_dev,
                gpio_DC=gpio_dc,
                gpio_RST=gpio_rst,
                bus_speed_hz=bus_hz,
                reset_hold_time=rst_hold,
                reset_release_time=rst_release,
            )
            if gpio_cs is not None:
                _oled_debug(
                    f"spi spidev{spi_port}.{spi_dev} software-CS=GPIO{gpio_cs} "
                    f"DC=GPIO{gpio_dc} RST={gpio_rst} {bus_hz}Hz driver={driver} rotate={rotate}"
                )
                serial = gpio_cs_spi(gpio_CS=gpio_cs, **spi_kw)
            else:
                _oled_debug(
                    f"spi spidev{spi_port}.{spi_dev} CE{spi_dev} DC=GPIO{gpio_dc} RST={gpio_rst} "
                    f"{bus_hz}Hz driver={driver} rotate={rotate}"
                )
                serial = spi(**spi_kw)

        if driver == "sh1106":
            _DEVICE = sh1106(serial, width=128, height=64, rotate=rotate)
        else:
            _DEVICE = ssd1306(serial, width=128, height=64, rotate=rotate)
        _STATE = "ready"
        _LAST_FAIL_FP = None
        _STUCK_LOGGED = False
        _oled_debug("init OK")
        return _DEVICE
    except Exception as e:
        print(f"[OLED] init failed: {e}")
        low = str(e).lower()
        if "i2c" in low or "/dev/i2c" in low:
            print(
                "[OLED] hint: I2C bus missing or wrong port — enable I2C (raspi-config), "
                "check /dev/i2c-*, OLED_I2C_PORT, and OLED_I2C_ADDRESS."
            )
        if "spi" in low or "spidev" in low:
            print(
                "[OLED] hint: enable SPI (raspi-config), check /dev/spidev0.0 exists, "
                "and CS→CE0 (OLED_SPI_DEVICE=0) vs CE1 (=1). Try OLED_SPI_HZ=1000000. "
                "If CS is on a random GPIO (not pin 24/26), set OLED_GPIO_CS=<BCM>. "
                "Four-wire SDA/SCL boards need OLED_INTERFACE=i2c."
            )
        _STATE = "failed"
        _LAST_FAIL_FP = fp
        _DEVICE = None
        return None


def _fit_lines(text: str, width: int = 21, max_lines: int = 6) -> list[str]:
    t = " ".join((text or "?").split())
    out: list[str] = []
    while t and len(out) < max_lines:
        line = t[:width].rstrip()
        if not line:
            line = t[:width]
        out.append(line if line else "?")
        t = t[len(line) :].lstrip()
    return out if out else ["?"]


def _oled_font() -> Any:
    """Prefer a small TrueType font on the Pi; fallback to PIL default (very small)."""
    px = int(os.getenv("OLED_FONT_PX", "14").strip())
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ):
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, px)
            except OSError:
                continue
    return ImageFont.load_default()


def _draw(lines: list[str]) -> None:
    global _STUCK_LOGGED
    dev = _lazy_device()
    if dev is None:
        if _oled_enabled() and _STATE == "failed" and not _STUCK_LOGGED:
            print(
                "[OLED] draw skipped: init already failed for this config. Fix wiring/env, "
                "then restart the process or change any OLED_* variable to retry. "
                "Run: OLED_DEBUG=1 OLED_ENABLED=1 python3 oled.py --diag",
            )
            _STUCK_LOGGED = True
        return
    try:
        if hasattr(dev, "contrast"):
            dev.contrast(0xFF)

        # Leave "entire display ON" (0xA5) / test modes — shows all pixels lit regardless of RAM.
        const = getattr(dev, "_const", None)
        try:
            if const is not None:
                if hasattr(const, "DISPLAYALLON_RESUME"):
                    dev.command(const.DISPLAYALLON_RESUME)
                if hasattr(const, "NORMALDISPLAY"):
                    dev.command(const.NORMALDISPLAY)
        except Exception as e:
            _oled_debug(f"DISPLAYALLON_RESUME/NORMALDISPLAY: {e}")

        mode = dev.mode
        w, h = dev.size
        im = Image.new(mode, (w, h), 0)
        dr = ImageDraw.Draw(im)
        dr.rectangle((0, 0, w - 1, h - 1), outline=255, width=1)
        font = _oled_font()
        try:
            line_h = int(os.getenv("OLED_LINE_H", "0").strip())
        except ValueError:
            line_h = 0
        if line_h <= 0:
            try:
                bbox = dr.textbbox((0, 0), "Ay", font=font)
                line_h = max(12, bbox[3] - bbox[1] + 4)
            except Exception:
                line_h = 16
        y = 2
        for line in lines[:6]:
            if y + line_h > h:
                break
            s = line[:48]
            for ox, oy in ((0, 0), (1, 0), (0, 1), (1, 1)):
                dr.text((3 + ox, y + oy), s, font=font, fill=255)
            y += line_h

        dev.display(im)
        if hasattr(dev, "show"):
            dev.show()
    except Exception as e:
        print(f"[OLED] draw failed: {e}")


def oled_clear() -> None:
    dev = _lazy_device()
    if dev is None:
        return
    try:
        dev.clear()
        dev.show()
    except Exception as e:
        print(f"[OLED] clear failed: {e}")


def oled_show_lines(lines: list[str]) -> None:
    """Show up to ~6 lines of ASCII-ish text (128x64, default font). Never raises."""
    try:
        flat: list[str] = []
        for block in lines:
            flat.extend(_fit_lines(block, width=21, max_lines=6))
        _draw(flat[:6])
    except Exception as e:
        print(f"[OLED] show_lines failed: {e}")


def oled_show_idle() -> None:
    oled_show_lines(["MTG scanner", "Ready", "", "POST /scan"])


def oled_show_pending(vision: dict[str, Any], scryfall: dict[str, Any]) -> None:
    name = (scryfall.get("name") or vision.get("name") or "?") or "?"
    set_code = scryfall.get("set_code") or "--"
    price = scryfall.get("price_usd")
    if price is None:
        price_s = "$--"
    else:
        try:
            price_s = f"${float(price):.2f}"
        except (TypeError, ValueError):
            price_s = str(price)
    lines = ["Match:", name, f"set {set_code}", price_s, "", "Confirm=save"]
    oled_show_lines(lines)


def oled_show_saved(name: str) -> None:
    oled_show_lines(["Saved", name[:42], "", "Scan next card"])


def oled_show_error(message: str) -> None:
    oled_show_lines(["Error", message[:63]])


def oled_run_probe_raw() -> None:
    """
    Minimal SSD1306 SPI bring-up without luma (spidev + RPi.GPIO for DC/CS/RST).

    Use this when --diag shows no errors but the panel stays black: if --probe
    also shows nothing, the problem is almost certainly wiring, voltage, wrong
    controller (not SSD1306-class), or CS/DC/RST on the wrong pins — not Python logic.
    """
    import sys
    import time

    if os.getenv("OLED_INTERFACE", "spi").strip().lower() == "i2c":
        print("[OLED] probe: raw SPI probe is only for SPI panels.", file=sys.stderr)
        sys.exit(2)
    if not _oled_enabled():
        print("Set OLED_ENABLED=1", file=sys.stderr)
        sys.exit(2)

    try:
        import spidev  # type: ignore[import-untyped]
    except ImportError:
        print("[OLED] probe: pip install spidev  (usually pulled in with luma.oled)", file=sys.stderr)
        sys.exit(1)

    gpio_dc = int(os.getenv("OLED_GPIO_DC", "24").strip())
    gpio_rst = _env_rst_gpio()
    gpio_cs = _env_optional_int("OLED_GPIO_CS")
    spi_port = int(os.getenv("OLED_SPI_PORT", "0").strip())
    spi_dev = int(os.getenv("OLED_SPI_DEVICE", "0").strip())
    hz = int(os.getenv("OLED_SPI_HZ", "1000000").strip())

    try:
        import RPi.GPIO as GPIO  # type: ignore[import-untyped]
    except Exception as e:
        print(f"[OLED] probe: RPi.GPIO import failed: {e}", file=sys.stderr)
        print("  Try: pip install rpi-lgpio   (Pi 5 / Bookworm)", file=sys.stderr)
        sys.exit(1)

    # Same init bytes as luma ssd1306 128x64 (see luma.oled.device.ssd1306).
    _INIT12864: list[int] = [
        0xAE,
        0xD5,
        0x80,
        0xA8,
        0x3F,
        0xD3,
        0x00,
        0x40,
        0x8D,
        0x14,
        0x20,
        0x00,
        0xA1,
        0xC8,
        0xDA,
        0x12,
        0xD9,
        0xF1,
        0xDB,
        0x40,
        0xA4,
        0xA6,
    ]

    spi: Any = None
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(gpio_dc, GPIO.OUT)
        GPIO.output(gpio_dc, GPIO.LOW)
        if gpio_cs is not None:
            GPIO.setup(gpio_cs, GPIO.OUT)
            GPIO.output(gpio_cs, GPIO.HIGH)
        if gpio_rst is not None:
            GPIO.setup(gpio_rst, GPIO.OUT)
            GPIO.output(gpio_rst, GPIO.LOW)
            time.sleep(0.01)
            GPIO.output(gpio_rst, GPIO.HIGH)
            time.sleep(0.05)

        spi = spidev.SpiDev()
        spi.open(spi_port, spi_dev)
        if gpio_cs is not None:
            spi.no_cs = True
        spi.max_speed_hz = hz
        spi.mode = 0

        def xfer_cmd(bs: list[int]) -> None:
            GPIO.output(gpio_dc, GPIO.LOW)
            if gpio_cs is not None:
                GPIO.output(gpio_cs, GPIO.LOW)
            spi.xfer2(bs)
            if gpio_cs is not None:
                GPIO.output(gpio_cs, GPIO.HIGH)

        def xfer_data(bs: list[int]) -> None:
            GPIO.output(gpio_dc, GPIO.HIGH)
            if gpio_cs is not None:
                GPIO.output(gpio_cs, GPIO.LOW)
            spi.xfer2(bs)
            if gpio_cs is not None:
                GPIO.output(gpio_cs, GPIO.HIGH)

        xfer_cmd(_INIT12864)
        xfer_cmd([0x81, 0xFF])

        hold = float(os.getenv("OLED_PROBE_HOLD_S", "5").strip())

        if os.getenv("OLED_PROBE_INVERT", "0").strip() == "1":
            xfer_cmd([0xAF])
            xfer_cmd([0xA7])
            print(
                "[OLED] probe: sent DISPLAYON + INVERT (0xA7). "
                "The whole panel should look inverted / lit if this is an SSD1306 and DC/SPI/CS are correct."
            )
            if hold > 0:
                print(
                    f"[OLED] probe: holding {hold}s so you can see the pattern "
                    f"(then GPIO cleanup may dim the panel — set OLED_PROBE_HOLD_S=0 to skip wait)."
                )
                time.sleep(hold)
            return

        xfer_cmd([0x21, 0x00, 0x7F, 0x22, 0x00, 0x07])
        xfer_data([0xFF] * 1024)
        xfer_cmd([0xAF])
        print(
            "[OLED] probe: raw SSD1306 init + full white framebuffer + DISPLAYON (bypassed luma). "
            "If you only saw a flash: that was real pixels; cleanup releases SPI/GPIO and can blank the glass. "
            f"Default wait is {hold}s before cleanup (OLED_PROBE_HOLD_S)."
        )
        if hold > 0:
            print(
                f"[OLED] probe: holding {hold}s — you should see solid white; "
                "set OLED_PROBE_HOLD_S=0 to skip."
            )
            time.sleep(hold)
    finally:
        try:
            if spi is not None:
                spi.close()
        except Exception:
            pass
        try:
            GPIO.cleanup()
        except Exception:
            pass


def oled_run_diag() -> None:
    """High-contrast pattern to verify OLED wiring. Prints bus device paths."""
    import sys

    print("[OLED] diag — kernel devices:")
    print("  SPI:", sorted(glob.glob("/dev/spidev*")))
    print("  I2C:", sorted(glob.glob("/dev/i2c*")))
    print("[OLED] diag — GPIO library (DC/RST bit-bang):")
    try:
        __import__("RPi.GPIO")
        print("  RPi.GPIO import OK (BCM mode used by luma).")
    except Exception as e:
        print(f"  RPi.GPIO failed: {e}")
        print(
            "  On Pi 5 / newer OS, install: pip install rpi-lgpio  (RPi.GPIO-compatible shim)."
        )
    print("[OLED] diag — config:", _oled_cfg_fingerprint())
    if not _oled_enabled():
        print("Set OLED_ENABLED=1", file=sys.stderr)
        sys.exit(2)
    dev = _lazy_device()
    if dev is None:
        print("[OLED] diag: init failed.", file=sys.stderr)
        sys.exit(1)
    try:
        dev.contrast(0xFF)
        from luma.core.render import canvas

        font = ImageFont.load_default()
        if os.getenv("OLED_DIAG_FULL", "0").strip() == "1":
            with canvas(dev) as draw:
                draw.rectangle((0, 0, 127, 63), fill="white")
            print("[OLED] diag: full-screen white (OLED_DIAG_FULL=1).")
        else:
            with canvas(dev) as draw:
                draw.rectangle((0, 0, 127, 63), outline="white", width=2)
                draw.rectangle((24, 20, 103, 44), fill="white")
                draw.text((32, 28), "DIAG", font=font, fill="black")
        if hasattr(dev, "show"):
            dev.show()
    except Exception as e:
        print(f"[OLED] diag draw failed: {e}", file=sys.stderr)
        sys.exit(1)
    print(
        "[OLED] diag: expect a white rectangle and 'DIAG' in the middle (or full white if OLED_DIAG_FULL=1). "
        "If still black: 3.3V/GND; CS on CE0 pin 24 (else OLED_SPI_DEVICE=1 for CE1 pin 26, or "
        "OLED_GPIO_CS=<BCM> if CS is a GPIO); DC/RST must match OLED_GPIO_DC / OLED_GPIO_RST; "
        "try OLED_SPI_HZ=1000000, OLED_DRIVER=sh1106, or longer OLED_RESET_RELEASE_S=0.15.",
    )


def main() -> None:
    import sys

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    if "--diag" in sys.argv:
        oled_run_diag()
        return
    if "--probe" in sys.argv:
        oled_run_probe_raw()
        return
    if "--test" not in sys.argv:
        print(
            "Usage:\n"
            "  OLED_ENABLED=1 python3 oled.py --test\n"
            "  OLED_ENABLED=1 python3 oled.py --diag\n"
            "  OLED_ENABLED=1 python3 oled.py --probe   (raw spidev+GPIO, SSD1306 only)\n"
            "I2C boards: OLED_INTERFACE=i2c\n"
            "Optional: OLED_DEBUG=1  OLED_SPI_HZ=1000000  OLED_DRIVER=sh1106\n"
            "  OLED_GPIO_CS=<BCM> if CS is not on CE0/CE1  OLED_DIAG_FULL=1  OLED_RESET_RELEASE_S=0.15\n"
            "  OLED_PROBE_INVERT=1 python3 oled.py --probe  (display invert test)\n"
            "  OLED_PROBE_HOLD_S=5  (default; seconds to keep image before GPIO cleanup)\n"
            "  OLED_TEST_HOLD_S=5   (default for --test; seconds before exit)",
            file=sys.stderr,
        )
        sys.exit(2)
    if not _oled_enabled():
        print("Set OLED_ENABLED=1 for hardware test.", file=sys.stderr)
        sys.exit(2)

    import time

    dev = _lazy_device()
    if dev is None:
        print(
            "[OLED] --test: luma init failed (no device). See [OLED] init failed lines above, "
            "or run: OLED_DEBUG=1 OLED_ENABLED=1 python3 oled.py --diag",
            file=sys.stderr,
        )
        sys.exit(1)

    oled_show_lines(["Hello world"])
    hold = float(os.getenv("OLED_TEST_HOLD_S", "5").strip())
    if hold > 0:
        print(
            f"[OLED] --test: holding {hold}s so you can read the screen "
            f"(same idea as --probe; set OLED_TEST_HOLD_S=0 for instant exit).",
            flush=True,
        )
        time.sleep(hold)
    print("Wrote 'Hello world' to OLED (if wired correctly).", flush=True)


if __name__ == "__main__":
    main()
