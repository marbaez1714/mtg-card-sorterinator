# MTG Card Scanner — Claude Code Context

## Project Overview
A Raspberry Pi-based Magic: The Gathering card scanner that identifies cards using the Claude Vision API, fetches card data from Scryfall, and saves results to a local SQLite inventory database. **Headless for now** (no attached screen): feedback via logs, Flask, or the serial/SSH session — no browser, no desktop assumed on the Pi.

## Hardware
- **Pi:** Raspberry Pi 4 (2GB)
- **Camera:** **Raspberry Pi Camera Module 3** (the “Module 3” / IMX708 sensor; standard, not wide-angle). Software is still **`picamera2`** (libcamera) on Raspberry Pi OS — there is no separate `picamera3` Python package; `sudo apt install python3-picamera2` is correct.
- **Input:** Physical momentary buttons wired to GPIO pins (no touchscreen)

**Scan quality (accuracy):** Move the camera so the **card fills most of the frame** (if the saved JPEG shows a tiny card on a big desk, OCR will struggle). Use diffuse light (avoid glare on the title) and keep the name line in focus. Optional Picamera2 env vars (see [`camera.py`](camera.py)): **`MTG_STILL_SIZE`** / **`CAMERA_STILL_SIZE`** as `WxH` (default still is **`3280x2464`**; lower to e.g. `2304x1296` if the Pi runs out of memory), **`CAMERA_SETTLE_S`**, **`CAMERA_AF_RANGE`**. For Claude only, **`MTG_CENTER_CROP_RATIO`** (e.g. `0.55`) in [`claude_id.py`](claude_id.py) crops to the center of the image so a **centered** card appears larger before vision (does not help if the card is off-center).

## Project Structure
```
mtg-scanner/
├── app.py           # Flask server — coordinates all modules
├── camera.py        # Picamera2 wrapper — captures JPEG on demand
├── claude_id.py     # Claude Vision API call — returns card name + set
├── scryfall.py      # Scryfall API wrapper — fetches card data and pricing
├── db.py            # SQLite CRUD — inventory read/write
├── gpio.py          # GPIO button input handler
├── inventory.db     # Auto-created SQLite file (gitignore this)
├── .env             # API keys (gitignore this)
├── scripts/
│   └── api.sh       # Short commands to hit the Flask API (see Running the Flask app)
└── requirements.txt
```

*(Deferred: optional `display.py` + DSI framebuffer UI — not in scope until re-enabled.)*

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
- **Camera:** [`camera.py`](camera.py) targets **Camera Module 3** via **`picamera2`** on the Pi. Use ``python3 test_camera.py`` on the device to verify capture; for Claude tests off the Pi, run ``claude_id.py`` on a JPEG saved from the camera.
- **Deployment:** rsync or `scp` to Pi, run via a systemd service on boot.

### Running the Flask app (headless API)

- **v1 has no authentication**; only run on a network you trust (e.g. home LAN). Listens on `0.0.0.0` so other devices can reach the Pi.
- Activate venv, set **`ANTHROPIC_API_KEY`**. Optional: **`FLASK_PORT`** (default `5000`), **`FLASK_DEBUG=1`** for Flask debug mode (not for production). Camera routes require **picamera2** on the Pi.

  `python3 app.py`

- **Endpoints:** `GET /api/health` — liveness. `POST /api/identify` — capture → Claude only; returns `{ "vision": { "name", "set_name", "set_code", "collector_number" } }` and does **not** call Scryfall or change **pending**. `POST /api/scan` — capture → Claude → Scryfall; returns `{ "vision", "scryfall" }` and stores a single **pending** match for confirm. `POST /api/confirm` — optional JSON body `{"foil": false, "quantity": 1}`; writes one inventory row; clears pending. `POST /api/rescan` — clears pending without saving. `GET /api/inventory?limit=50` — recent rows (limit capped at 200).

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
```

## Requirements (requirements.txt)
```
flask
picamera2
anthropic
requests
gpiozero
python-dotenv
```

## What To Avoid
- Do not use Chromium, a browser, or any web-based display
- Do not hardcode GPIO pin numbers or API keys
- Do not assume the Pi has internet access during dev/test — mock API calls where needed
