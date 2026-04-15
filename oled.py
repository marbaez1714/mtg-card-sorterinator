"""
128x64 monochrome OLED via luma.oled — **SPI** (default: CLK/MOSI/CS/DC/RES) or **I2C** (SDA/SCL).

Requires: pip install luma.oled
Pi SPI: raspi-config → enable SPI; GPIO defaults in _lazy_device (override with OLED_GPIO_*).
Pi I2C: set OLED_INTERFACE=i2c, enable I2C; SDA→GPIO2, SCL→GPIO3, VCC→3.3V, GND.

Docs example: https://community.microcenter.com/kb/articles/795-inland-1-3-128x64-oled-graphic-display
"""

from __future__ import annotations

import glob
import os
from typing import Any

from PIL import ImageFont

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
            # 4 MHz default — dupont wires often glitch at 8 MHz on some modules.
            bus_hz = int(os.getenv("OLED_SPI_HZ", "4000000").strip())
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
        from luma.core.render import canvas

        font = ImageFont.load_default()
        with canvas(dev) as draw:
            y = 0
            for line in lines[:6]:
                draw.text((0, y), line[:32], font=font, fill="white")
                y += 11
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

    if "--diag" in sys.argv:
        oled_run_diag()
        return
    if "--test" not in sys.argv:
        print(
            "Usage:\n"
            "  OLED_ENABLED=1 python3 oled.py --test\n"
            "  OLED_ENABLED=1 python3 oled.py --diag\n"
            "I2C boards: OLED_INTERFACE=i2c\n"
            "Optional: OLED_DEBUG=1  OLED_SPI_HZ=1000000  OLED_DRIVER=sh1106\n"
            "  OLED_GPIO_CS=<BCM> if CS is not on CE0/CE1  OLED_DIAG_FULL=1  OLED_RESET_RELEASE_S=0.15",
            file=sys.stderr,
        )
        sys.exit(2)
    if not _oled_enabled():
        print("Set OLED_ENABLED=1 for hardware test.", file=sys.stderr)
        sys.exit(2)
    oled_show_lines(["Hello world"])
    print("Wrote 'Hello world' to OLED (if wired correctly).")


if __name__ == "__main__":
    main()
