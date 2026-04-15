"""
128x64 monochrome OLED via luma.oled — **I2C** (4 wires: SDA/SCL) or **SPI** (CLK/MOSI/CS + DC/RES).

Requires: pip install luma.oled
Pi I2C: raspi-config → enable I2C; SDA→GPIO2, SCL→GPIO3, VCC→3.3V, GND.
Pi SPI: raspi-config → enable SPI; see OLED_INTERFACE=spi and env GPIO defaults in _lazy_device.

Docs example: https://community.microcenter.com/kb/articles/795-inland-1-3-128x64-oled-graphic-display
"""

from __future__ import annotations

import os
from typing import Any

from PIL import ImageFont

_STATE: str = "uninit"  # uninit | ready | failed
_DEVICE: Any = None


def _oled_enabled() -> bool:
    return os.getenv("OLED_ENABLED", "0").strip() == "1"


def _lazy_device() -> Any:
    global _STATE, _DEVICE
    if not _oled_enabled():
        return None
    if _STATE == "failed":
        return None
    if _STATE == "ready":
        return _DEVICE
    try:
        from luma.core.interface.serial import i2c, spi
        from luma.oled.device import ssd1306, sh1106

        driver = os.getenv("OLED_DRIVER", "ssd1306").strip().lower()
        rotate = int(os.getenv("OLED_ROTATE", "0").strip())
        rotate = rotate % 4

        iface = os.getenv("OLED_INTERFACE", "i2c").strip().lower()
        if iface == "spi":
            spi_port = int(os.getenv("OLED_SPI_PORT", "0").strip())
            spi_dev = int(os.getenv("OLED_SPI_DEVICE", "0").strip())
            gpio_dc = int(os.getenv("OLED_GPIO_DC", "24").strip())
            gpio_rst = int(os.getenv("OLED_GPIO_RST", "25").strip())
            bus_hz = int(os.getenv("OLED_SPI_HZ", "8000000").strip())
            serial = spi(
                port=spi_port,
                device=spi_dev,
                gpio_DC=gpio_dc,
                gpio_RST=gpio_rst,
                bus_speed_hz=bus_hz,
            )
        else:
            i2c_port = int(os.getenv("OLED_I2C_PORT", "1").strip())
            addr = int(os.getenv("OLED_I2C_ADDRESS", "0x3C").strip(), 16)
            serial = i2c(port=i2c_port, address=addr)

        if driver == "sh1106":
            _DEVICE = sh1106(serial, width=128, height=64, rotate=rotate)
        else:
            _DEVICE = ssd1306(serial, width=128, height=64, rotate=rotate)
        _STATE = "ready"
        return _DEVICE
    except Exception as e:
        print(f"[OLED] init failed: {e}")
        low = str(e).lower()
        if "i2c" in low or "/dev/i2c" in low:
            print(
                "[OLED] hint: SPI panels need OLED_INTERFACE=spi (and SPI on in raspi-config). "
                "I2C panels need I2C enabled and /dev/i2c-* present."
            )
        _STATE = "failed"
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
    dev = _lazy_device()
    if dev is None:
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


def main() -> None:
    import sys

    if "--test" not in sys.argv:
        print(
            "Usage: OLED_ENABLED=1 [OLED_INTERFACE=spi] python3 oled.py --test",
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
