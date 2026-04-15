"""Claude Vision: MTG card name + set from a JPEG."""

from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

_DEFAULT_MODEL = "claude-sonnet-4-20250514"
_MAX_TOKENS = 1024

_SYSTEM = (
    "You perform strict OCR on Magic: The Gathering trading cards shown in photographs. "
    "You read only ink that is printed on the card frame. You must not infer identity from artwork, "
    "flavor text, mana symbols, or prior knowledge of Magic cards. "
    "If the illustration resembles a well-known character but the printed title says something else, "
    "the printed title wins. "
    "Respond with exactly one JSON object and no other characters."
)

_PROMPT = """The image attached with this message shows one Magic: The Gathering card face (or should). Use upright reading order: the card name is the large title typography along the top inside the inner frame.

This is a transcription task, not "name the creature in the art."

1) "name" — title line only
The name is the prominent title line at the top of the face, inside the inner border. It is NOT the mana symbols/cost in the upper-right corner. It is NOT the type line (creature/artifact/etc.) immediately under the illustration. It is NOT flavor text in italics at the bottom.
Copy the printed spelling exactly (any language or script shown; punctuation and apostrophes as printed). If the title wraps to a second line on the cardboard, join with one ASCII space.
If any letters are unclear, transcribe the glyphs you see; do NOT replace with a different famous card name that matches the artwork.

2) "set_name"
Only if a set / expansion name is visibly printed on this face. Otherwise JSON null.

3) "set_code" and "collector_number"
Often on the TYPE line below the art: a short set code (e.g. neo, dmu, 10e) and collector number (e.g. 123 or 12a). Transcribe only if clearly legible; else JSON null each. Never invent from memory.

4) Output format
Return a single JSON object with these keys only:
{"name":"...","set_name":null,"set_code":null,"collector_number":null}
Use JSON null when absent or unreadable. No markdown fences, no commentary."""


def _temperature() -> float:
    raw = os.environ.get("ANTHROPIC_TEMPERATURE", "0").strip()
    try:
        t = float(raw)
    except ValueError:
        return 0.0
    return max(0.0, min(1.0, t))


def _prepare_jpeg_for_vision(jpeg_bytes: bytes) -> bytes:
    """
    Apply EXIF orientation (fixes sideways photos) and optional manual rotation.

    Set ``CLAUDE_AUTO_ORIENT=0`` to skip EXIF. Set ``CLAUDE_JPEG_ROTATE`` to ``90``,
    ``180``, or ``270`` to rotate the image clockwise that many degrees after EXIF fix
    (useful if the Pi camera is mounted sideways and JPEGs have no EXIF).
    """
    auto = os.getenv("CLAUDE_AUTO_ORIENT", "1").strip() != "0"
    rot_s = os.getenv("CLAUDE_JPEG_ROTATE", "0").strip()
    if not auto and rot_s not in ("90", "180", "270"):
        return jpeg_bytes
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return jpeg_bytes
    try:
        q = int(os.getenv("CLAUDE_JPEG_QUALITY", "92").strip())
    except ValueError:
        q = 92
    q = max(70, min(100, q))
    try:
        im = Image.open(io.BytesIO(jpeg_bytes))
        if auto:
            im = ImageOps.exif_transpose(im)
        if rot_s in ("90", "180", "270"):
            resample = getattr(Image, "Resampling", Image).BICUBIC
            im = im.rotate(-int(rot_s), expand=True, resample=resample, fillcolor=(255, 255, 255))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=q, optimize=True)
        return out.getvalue()
    except Exception:
        return jpeg_bytes


class CardIdentificationError(Exception):
    """Invalid API response, JSON, or identification payload."""


def _model() -> str:
    return os.environ.get("ANTHROPIC_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL


def _unwrap_json_text(raw: str) -> str:
    s = raw.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()
    if not lines:
        return s
    lines = lines[1:]
    while lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _message_text(response: Any) -> str:
    parts: list[str] = []
    for block in response.content:
        t = getattr(block, "text", None)
        if isinstance(t, str):
            parts.append(t)
    out = "".join(parts).strip()
    if not out:
        raise CardIdentificationError("Empty model response text")
    return out


def _parse_identification_json(raw: str) -> dict[str, Any]:
    """
    Parse the first JSON object from model text. Handles prose before/after the object
    and empty results after markdown fence stripping (common with stub/invalid images).
    """
    s = _unwrap_json_text(raw).strip()
    if not s:
        preview = (raw or "")[:400].replace("\n", "\\n")
        raise CardIdentificationError(
            "Model returned no usable text for JSON (empty after stripping). "
            f"Preview: {preview!r}"
        )
    start = s.find("{")
    if start == -1:
        raise CardIdentificationError(
            "Model output contained no JSON object starting with '{'. "
            f"Preview: {s[:400]!r}"
        )
    decoder = json.JSONDecoder()
    try:
        data, _end = decoder.raw_decode(s, start)
    except json.JSONDecodeError as e:
        snippet = s[start : start + 220]
        raise CardIdentificationError(
            f"Model did not return valid JSON: {e}. Snippet: {snippet!r}"
        ) from e
    if not isinstance(data, dict):
        raise CardIdentificationError("JSON root must be an object")

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise CardIdentificationError('Missing or invalid "name" string')

    set_name = data.get("set_name", None)
    if set_name is not None and not isinstance(set_name, str):
        raise CardIdentificationError('Invalid "set_name" (expected string or null)')
    sn = set_name.strip() if isinstance(set_name, str) else None
    if sn == "":
        sn = None

    set_code = data.get("set_code", None)
    if set_code is not None and not isinstance(set_code, str):
        raise CardIdentificationError('Invalid "set_code" (expected string or null)')
    sc = set_code.strip().lower() if isinstance(set_code, str) else None
    if sc == "":
        sc = None
    if sc is not None and not re.fullmatch(r"[a-z0-9]{2,8}", sc):
        sc = None

    coll = data.get("collector_number", None)
    if coll is not None and not isinstance(coll, str):
        raise CardIdentificationError('Invalid "collector_number" (expected string or null)')
    cn = coll.strip() if isinstance(coll, str) else None
    if cn == "":
        cn = None
    if cn is not None:
        if len(cn) > 14 or not re.fullmatch(r"[A-Za-z0-9*]+", cn):
            cn = None
        else:
            cn = cn.lower()

    return {"name": name.strip(), "set_name": sn, "set_code": sc, "collector_number": cn}


def identify_card_from_jpeg(jpeg_bytes: bytes) -> dict[str, str | None]:
    """
    Send JPEG bytes to Claude Vision.

    Returns ``name``, ``set_name``, and when readable on the frame ``set_code`` /
    ``collector_number`` for exact Scryfall lookup.

    Requires ANTHROPIC_API_KEY. Optional: ``ANTHROPIC_MODEL`` (default Sonnet per AGENT.md),
    ``ANTHROPIC_TEMPERATURE`` (default ``0`` for steadier OCR).
    JPEGs are passed through Pillow EXIF auto-orient by default; see ``CLAUDE_AUTO_ORIENT``,
    ``CLAUDE_JPEG_ROTATE``, and ``CLAUDE_JPEG_QUALITY`` in code docstrings if the camera
    is mounted sideways or titles still read wrong.
    """
    if not jpeg_bytes:
        raise CardIdentificationError("Empty JPEG buffer")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise CardIdentificationError("ANTHROPIC_API_KEY is not set")

    jpeg_for_api = _prepare_jpeg_for_vision(jpeg_bytes)
    b64 = base64.standard_b64encode(jpeg_for_api).decode("ascii")
    client = Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model=_model(),
            max_tokens=_MAX_TOKENS,
            temperature=_temperature(),
            system=_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": _PROMPT},
                    ],
                }
            ],
        )
    except Exception as e:
        raise CardIdentificationError(f"Anthropic API request failed: {e}") from e

    return _parse_identification_json(_message_text(response))


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python3 claude_id.py <path-to.jpeg>", file=sys.stderr)
        sys.exit(2)
    path = sys.argv[1]
    with open(path, "rb") as f:
        jpeg = f.read()
    try:
        result = identify_card_from_jpeg(jpeg)
    except CardIdentificationError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
