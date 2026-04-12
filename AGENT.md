# MTG Card Scanner — Claude Code Context

## Project Overview
A Raspberry Pi-based Magic: The Gathering card scanner that identifies cards using the Claude Vision API, fetches card data from Scryfall, and saves results to a local SQLite inventory database. Displayed via pygame on a small DSI screen — no browser, no desktop.

## Hardware
- **Pi:** Raspberry Pi 4 (2GB)
- **Camera:** Raspberry Pi Camera Module 3 (standard, not wide-angle), accessed via Picamera2
- **Display:** Waveshare 4" DSI display, pygame renders direct to framebuffer
- **Input:** Physical momentary buttons wired to GPIO pins (no touchscreen)

## Project Structure
```
mtg-scanner/
├── app.py           # Flask server — coordinates all modules
├── camera.py        # Picamera2 wrapper — captures JPEG on demand
├── claude_id.py     # Claude Vision API call — returns card name + set
├── scryfall.py      # Scryfall API wrapper — fetches card data and pricing
├── db.py            # SQLite CRUD — inventory read/write
├── display.py       # Pygame framebuffer renderer — draws UI to DSI screen
├── gpio.py          # GPIO button input handler
├── inventory.db     # Auto-created SQLite file (gitignore this)
├── .env             # API keys (gitignore this)
└── requirements.txt
```

## Key APIs

### Claude Vision API
- Model: `claude-sonnet-4-20250514`
- Purpose: Identify card name and set from a JPEG image
- Prompt must instruct the model to return **JSON only**, no preamble:
  ```
  You are an MTG card identifier. Given an image of a Magic: The Gathering card,
  return ONLY a JSON object: {"name": "exact card name", "set_name": "set name or null"}.
  No other text.
  ```
- API key stored in `.env` as `ANTHROPIC_API_KEY`

### Scryfall API
- Base URL: `https://api.scryfall.com`
- No authentication required
- Fuzzy card lookup: `GET /cards/named?fuzzy={card_name}`
- Returns: price (USD/foil), image URI, set code, legality, collector number
- Respect Scryfall's request that clients wait 50–100ms between requests

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

## User Flow
1. User presses physical **scan button** (GPIO)
2. `camera.py` captures a JPEG
3. `claude_id.py` sends image to Claude API → returns `{"name": ..., "set_name": ...}`
4. `scryfall.py` does a fuzzy lookup → returns price, art URL, legality
5. `display.py` renders card name, set, price, and art on the pygame screen
6. User presses **confirm button** → saved to SQLite via `db.py`
7. User presses **rescan button** → discard and restart flow

## Display
- Pygame renders directly to `/dev/fb0` (framebuffer), no X11/Wayland/Chromium
- Target resolution: 800×480 (Waveshare 4" DSI)
- Keep UI minimal: card art thumbnail, name, set, price, and button prompts
- Use `pygame.display.init()` with the framebuffer driver:
  ```python
  import os
  os.environ["SDL_VIDEODRIVER"] = "fbcon"
  os.environ["SDL_FBDEV"] = "/dev/fb0"
  ```

## GPIO Button Mapping
- Define pin numbers in `.env` or a `config.py` — do not hardcode
- Debounce all button inputs in `gpio.py`
- Use `RPi.GPIO` or `gpiozero` — prefer `gpiozero` for cleaner code

## Development Notes
- **Dev machine:** All development happens on a separate computer. The Pi is the deploy target only.
- **No desktop on Pi:** Do not assume X11, Wayland, or a browser is available.
- **Testing display locally:** When running on a non-Pi machine, fall back to a standard pygame window (`SDL_VIDEODRIVER=` unset) so UI can be developed without hardware.
- **Testing camera locally:** Mock `camera.py` with a static test JPEG when not on Pi hardware.
- **Deployment:** rsync or `scp` to Pi, run via a systemd service on boot.

## Environment Variables (.env)
```
ANTHROPIC_API_KEY=your_key_here
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
pygame
python-dotenv
```

## What To Avoid
- Do not use Chromium, a browser, or any web-based display
- Do not use SPI displays or I2C displays for the main screen
- Do not hardcode GPIO pin numbers or API keys
- Do not assume the Pi has internet access during dev/test — mock API calls where needed