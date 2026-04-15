# MTG Card Scanner — Claude Code Context

## Project Overview
A Raspberry Pi-based Magic: The Gathering card scanner that identifies cards using the Claude Vision API, fetches card data from Scryfall, and saves results to a local SQLite inventory database. **Headless by default** (no browser or desktop): feedback via logs, Flask JSON, SSH, and optionally a small **128×64 OLED** over **I2C or SPI** (see [`oled.py`](oled.py)).

## Hardware
- **Pi:** Raspberry Pi 4 (2GB)
- **Camera:** **Raspberry Pi Camera Module 3** (the “Module 3” / IMX708 sensor; standard, not wide-angle). Software is still **`picamera2`** (libcamera) on Raspberry Pi OS — there is no separate `picamera3` Python package; `sudo apt install python3-picamera2` is correct.
- **Input:** Physical momentary buttons wired to GPIO pins (no touchscreen)
- **Display (optional):** **128×64 monochrome OLED** (common **SSD1306** or **SH1106**; e.g. [Inland 1.3" 128×64 article](https://community.microcenter.com/kb/articles/795-inland-1-3-128x64-oled-graphic-display)). **I2C** boards use **SDA/SCL**; **SPI** boards use **CLK, MOSI, CS, DC, RES** plus power. Software: [`oled.py`](oled.py) + **`luma.oled`**. Set **`OLED_ENABLED=1`**; **SPI is the default** (`OLED_INTERFACE` unset or **`spi`**). **I2C-only** boards need **`OLED_INTERFACE=i2c`**. Use **`OLED_DRIVER=ssd1306`** vs **`sh1106`** if the image is wrong. **DSI / HDMI framebuffer UI** remains deferred.

**Scan quality (accuracy):** Move the camera so the **card fills most of the frame** (if the saved JPEG shows a tiny card on a big desk, OCR will struggle). Use diffuse light (avoid glare on the title) and keep the name line in focus. Picamera2 tuning (see [`camera.py`](camera.py)): **`MTG_STILL_SIZE`** / **`CAMERA_STILL_SIZE`** (`WxH`; default **`1920x1080`**), **`CAMERA_SETTLE_S`** (seconds after start before capture; default **`0.75`**, raise if color/exposure drifts), **`CAMERA_JPEG_QUALITY`** (default **`82`**, lower = smaller/faster JPEG), **`CAMERA_SKIP_AF=1`** to skip **autofocus** each shot (faster; only if distance is fixed and sharp), **`CAMERA_AF_RANGE`**. For Claude only, **`MTG_CENTER_CROP_RATIO`** in [`claude_id.py`](claude_id.py) for a centered crop before vision.

## Project Structure
```
mtg-scanner/
├── app.py           # Flask server — coordinates all modules
├── camera.py        # Picamera2 wrapper — captures JPEG on demand
├── claude_id.py     # Claude Vision API call — returns card name + set
├── scryfall.py      # Scryfall API wrapper — fetches card data and pricing
├── db.py            # SQLite CRUD — inventory read/write
├── gpio.py          # GPIO button input handler (planned)
├── oled.py          # 128x64 OLED status — I2C or SPI (luma.oled; optional)
├── inventory.db     # Auto-created SQLite file (gitignore this)
├── .env             # API keys (gitignore this)
├── scripts/
│   └── api.sh       # Short commands to hit the Flask API (see Running the Flask app)
└── requirements.txt
```

*(Deferred: optional `display.py` + DSI framebuffer UI — not in scope until re-enabled; use `oled.py` for compact on-device text.)*

## Key APIs

### Claude Vision API
- Model: `claude-sonnet-4-20250514`
- Purpose: Read a JPEG and return **`name`**, **`set_name`**, **`set_code`**, **`collector_number`** as **printed OCR** on the frame — the prompts frame this as strict transcription (title strip, type line), not “guess the famous card from the art.” Instructions are sent **before** the image in the API call; **`ANTHROPIC_TEMPERATURE`** defaults to **`0`** for steadier reads (override in `.env` if needed).
- When the **type-line set code** and **collector number** are legible, Scryfall can use an exact card URL instead of fuzzy name search.
- See [`claude_id.py`](claude_id.py) for full prompt text and keys.
- **If the model is consistently wrong but stable:** the JPEG may be **sideways** (common with a fixed Pi camera). JPEGs are **EXIF-corrected** with Pillow before sending to Claude. If there is still no correct orientation in EXIF, set **`CLAUDE_JPEG_ROTATE`** to **`90`**, **`180`**, or **`270`** (clockwise degrees) in the environment running `app.py` / `claude_id.py`. Disable EXIF correction with **`CLAUDE_AUTO_ORIENT=0`** if it ever makes things worse. Optional **`CLAUDE_JPEG_QUALITY`** (default `92`) when re-encoding after rotation.
- API key stored in `.env` as `ANTHROPIC_API_KEY`

### Testing Claude ID

- Activate your project venv first if you use one (see **Python venv** under Development Notes).
- Set `ANTHROPIC_API_KEY` in `.env` (or export it in the shell). Optional: `ANTHROPIC_MODEL` overrides the default Sonnet model id.
- With any JPEG of a card (for example from the Pi: `python3 test_camera.py --save` then copy `/tmp/card_test.jpg`):

  `python3 claude_id.py /path/to/card.jpg`

- Prints JSON with `name` and `set_name` to stdout, or a clear error message on stderr.

### Scryfall API
- Base URL: `https://api.scryfall.com`
- No authentication required
- Fuzzy card lookup: `GET /cards/named?fuzzy={card_name}`
- When [`claude_id.py`](claude_id.py) returns readable **`set_code`** and **`collector_number`** from the type line, [`scryfall.lookup_card_from_vision`](scryfall.py) uses **`GET /cards/{set}/{collector}`** first (exact print), then falls back to fuzzy name if that fails—this greatly reduces wrong reprints.
- Returns: price (USD/foil), image URI, set code, legality, collector number
- Respect Scryfall's request that clients wait 50–100ms between requests

### Testing Scryfall lookup

- Activate your project venv if you use one (see **Python venv** under Development Notes). No API key is required.
- Fuzzy lookup uses only the **card name** for now. `set_name` from [`claude_id.py`](claude_id.py) is not passed to Scryfall until we resolve display set names to set codes (e.g. a separate sets endpoint).
- Optional: `SCRYFALL_MIN_INTERVAL_MS` (default `75`) sets the minimum gap between outbound Scryfall requests in milliseconds.

  `python3 scryfall.py "Lightning Bolt"`

- Prints normalized JSON (`id`, `name`, `set_code`, `collector_number`, `price_usd`, `price_usd_foil`, `image_uri`, `legalities`) or an error on stderr.

## Database Schema
```sql
CREATE TABLE IF NOT EXISTS inventory (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scryfall_id TEXT,
  name TEXT NOT NULL,
  set_code TEXT,
  quantity INTEGER DEFAULT 1,
  foil BOOLEAN DEFAULT 0,
  price_usd REAL,
  added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Testing inventory DB

- No API keys required. A venv is optional (stdlib `sqlite3` only).
- Default file is **`inventory.db`** in the process working directory (gitignored). Override with **`INVENTORY_DB`** or **`INVENTORY_DB_PATH`** (same meaning) for a fixed path on the Pi (e.g. under `/var/lib/...`).
- **v1:** each confirm is a new `INSERT`; duplicate `scryfall_id` rows are allowed (no unique constraint). Upsert/increment can be added later.

  `python3 db.py --init` — creates the file and `inventory` table if needed; prints the resolved path.

  `python3 db.py --list` — prints a JSON array of recent rows (newest first, default limit 50).

## User Flow
1. User presses physical **scan button** (GPIO)
2. `camera.py` captures a JPEG
3. `claude_id.py` sends image to Claude API → returns `{"name": ..., "set_name": ...}`
4. `scryfall.py` does a fuzzy lookup → returns price, art URL, legality
5. **Headless:** app surfaces the match (e.g. logging, Flask JSON, or stdout) so the operator can decide
6. User presses **confirm button** → saved to SQLite via `db.py`
7. User presses **rescan button** → discard and restart flow

## GPIO Button Mapping
- Define pin numbers in `.env` or a `config.py` — do not hardcode
- Debounce all button inputs in `gpio.py`
- Use `RPi.GPIO` or `gpiozero` — prefer `gpiozero` for cleaner code

## Development Notes
- **Python venv (required if `pip` says “externally managed”):** macOS Homebrew / Xcode Python and current Raspberry Pi OS use PEP 668, so you must not install into the system interpreter. From the project root:
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  ```
  Use `python3` / `pip` only while the venv is activated (or run tools as `.venv/bin/python`). On Windows: `.venv\Scripts\activate`.
- **Dev machine:** All development happens on a separate computer. The Pi is the deploy target only.
- **No desktop on Pi:** Do not assume X11, Wayland, or a browser is available.
- **Camera:** [`camera.py`](camera.py) targets **Camera Module 3** via **`picamera2`** on the Pi. Install with ``sudo apt install -y python3-picamera2 python3-libcamera``. **Venv note:** a normal venv cannot import apt-only packages. Either create the venv with ``python3 -m venv .venv --system-site-packages`` (then ``pip install -r requirements.txt`` again), or run camera code with **system** Python: ``/usr/bin/python3 test_camera.py``. Verify: ``python3 -c 'from picamera2 import Picamera2'``. For Claude-only work off the Pi, use ``claude_id.py`` on a JPEG saved from the camera.
- **Deployment:** rsync or `scp` to Pi, run via a systemd service on boot.

### Running the Flask app (headless API)

- **v1 has no authentication**; only run on a network you trust (e.g. home LAN). Listens on `0.0.0.0` so other devices can reach the Pi.
- Activate venv, set **`ANTHROPIC_API_KEY`**. Optional: **`FLASK_PORT`** (default `5000`), **`FLASK_DEBUG=1`** for Flask debug mode (not for production). Camera routes require **picamera2** on the Pi.

  `python3 app.py`

- **Endpoints:** `GET /api/health` — liveness. `POST /api/identify` — capture → Claude only; returns `{ "vision": { "name", "set_name", "set_code", "collector_number" } }` and does **not** call Scryfall or change **pending**. `POST /api/scan` — capture → Claude → Scryfall; returns `{ "vision", "scryfall" }` and stores a single **pending** match for confirm. `POST /api/confirm` — optional JSON body `{"foil": false, "quantity": 1}`; writes one inventory row; clears pending. `POST /api/rescan` — clears pending without saving. `GET /api/inventory?limit=50` — recent rows (limit capped at 200).
- **OLED:** With **`OLED_ENABLED=1`**, successful **`/api/scan`** shows the pending match on the display; **`/api/confirm`** shows “Saved”; **`/api/rescan`** shows the idle banner; failed **`/api/identify`**, **`/api/scan`**, or confirm paths show a short error line. Hardware smoke test: **`OLED_ENABLED=1 python3 oled.py --test`** (**SPI** default — enable SPI in raspi-config); **I2C** boards set **`OLED_INTERFACE=i2c`**. If the panel stays black, run **`OLED_ENABLED=1 python3 oled.py --diag`**. Use **`OLED_DEBUG=1`** for init logging; try **`OLED_SPI_HZ=1000000`** or **`OLED_DRIVER=sh1106`** if wiring is correct but the image is wrong.

- **Quick terminal testing** (no long `curl` lines): run [`scripts/api.sh`](scripts/api.sh) from the repo root, e.g. `./scripts/api.sh health`, `./scripts/api.sh identify`, `./scripts/api.sh scan`, `./scripts/api.sh confirm`, `./scripts/api.sh inventory 10`. Set **`MTG_API_BASE`** for a remote Pi (e.g. `MTG_API_BASE=http://raspberrypi.local:5000 ./scripts/api.sh scan`). Optional **`MTG_CONFIRM_JSON`** for confirm. Output is passed through **`jq`** if installed, else **`python3 -m json.tool`**.

- **Example curl** (from another machine, replace host):

  ```bash
  curl -sS http://raspberrypi.local:5000/api/health
  curl -sS -X POST http://raspberrypi.local:5000/api/identify
  curl -sS -X POST http://raspberrypi.local:5000/api/scan
  curl -sS -X POST http://raspberrypi.local:5000/api/confirm -H 'Content-Type: application/json' -d '{"foil":false,"quantity":1}'
  ```

## Environment Variables (.env)
```
ANTHROPIC_API_KEY=your_key_here
ANTHROPIC_TEMPERATURE=0
# If titles read sideways in saved JPEGs: CLAUDE_JPEG_ROTATE=90
SCAN_BUTTON_PIN=17
CONFIRM_BUTTON_PIN=27
RESCAN_BUTTON_PIN=22

# Optional OLED (see oled.py)
# OLED_ENABLED=1
# OLED_INTERFACE=spi
# OLED_INTERFACE=i2c
# OLED_I2C_PORT=1
# OLED_I2C_ADDRESS=0x3C
# OLED_SPI_PORT=0
# OLED_SPI_DEVICE=0
# OLED_GPIO_DC=24
# OLED_GPIO_RST=25
# OLED_SPI_HZ=4000000
# OLED_GPIO_CS=5
# OLED_RESET_HOLD_S=0.002
# OLED_RESET_RELEASE_S=0.05
# OLED_DRIVER=ssd1306
# OLED_DRIVER=sh1106
# OLED_ROTATE=0
# OLED_GPIO_RST=none
# OLED_DIAG_FULL=1
```

**SPI OLED → Pi (SPI0, matches `oled.py` defaults):** **GND** → GND (e.g. pin 6); **VCC** → **5V (pin 2 or 4)** or **3.3V (pin 1 or 17)** per your module’s silkscreen/docs (many 128×64 SPI breakouts use **5V** on **VCC** with level shifting for logic); **CLK** → **GPIO11** / SCLK (pin 23); **MOSI** → **GPIO10** / MOSI (pin 19); **CS** → **GPIO8** / **CE0** (pin 24) — leave **`OLED_GPIO_CS` unset** (hardware CE); **DC** → **GPIO24** (pin 18); **RES** → **GPIO25** (pin 22). If **CS** goes to **CE1** (GPIO7, pin 26) instead, set **`OLED_SPI_DEVICE=1`**. Only set **`OLED_GPIO_CS=<BCM>`** when **CS** is on a **GPIO other than CE0/CE1** (never set **`OLED_GPIO_CS=8`** while using SPI0 CE0 — that fights the kernel driver). **`OLED_GPIO_RST=none`** only if the PCB ties reset high. Default SPI clock is **4 MHz** (`OLED_SPI_HZ`); try **`1000000`** on long jumpers. **`OLED_RESET_RELEASE_S`** (default **0.05**) can be raised (e.g. **0.15**) for fussy modules.

**Still a black screen (init succeeds, no errors):** Run **`OLED_ENABLED=1 python3 oled.py --diag`** and read the **RPi.GPIO** line — on **Pi 5** / newer Bookworm, install **`rpi-lgpio`** (`pip install rpi-lgpio`) so **DC/RST** can toggle. Try **`OLED_DIAG_FULL=1`** with **`--diag`** (entire panel white). Try **`OLED_DRIVER=sh1106`**, **`OLED_SPI_HZ=1000000`**, **`OLED_RESET_RELEASE_S=0.15`**, and re-check **CS** (CE0 vs CE1 vs **`OLED_GPIO_CS`**). Last resort: **`OLED_ENABLED=1 python3 oled.py --probe`** bypasses luma and drives an **SSD1306** over **spidev** + **RPi.GPIO**; **`OLED_PROBE_INVERT=1`** with **`--probe`** only sends **DISPLAYON + invert** (very obvious if the controller is SSD1306-class). If you only see a **quick flash**, the panel **did** update — **`GPIO.cleanup()`** at the end releases pins and can blank it; use **`OLED_PROBE_HOLD_S`** (default **5** seconds) to **hold the image** before cleanup so you can confirm steady white or invert.

## Requirements (requirements.txt)
```
flask
anthropic
python-dotenv
requests
Pillow
luma.oled
```
`picamera2` is **apt-only** on the Pi (see `requirements-pi.txt`). GPIO stack (e.g. `gpiozero`) is not wired in `requirements.txt` until `gpio.py` lands.

## What To Avoid
- Do not use Chromium, a browser, or any web-based display
- Do not hardcode GPIO pin numbers or API keys
- Do not assume the Pi has internet access during dev/test — mock API calls where needed
