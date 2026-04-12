"""Claude Vision: MTG card name + set from a JPEG."""

from __future__ import annotations

import base64
import json
import os
import sys
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

_DEFAULT_MODEL = "claude-sonnet-4-20250514"
_MAX_TOKENS = 1024

_SYSTEM = (
    "You identify Magic: The Gathering cards from photos. "
    "Be literal: copy the printed English title from the card frame, not a similar card from memory. "
    "Output must be a single JSON object only."
)

_PROMPT = """Look at the Magic: The Gathering card in the image.

Rules for "name":
- Read the main card title printed along the top of the card face (the name line). Use that exact English text, including punctuation (e.g. commas, apostrophes) as printed.
- If only one face is visible on a double-faced card, use that face's printed name.
- Do not substitute a different card that "looks similar". If glare, sleeves, blur, or angle make the title ambiguous, transcribe the letters you can see literally; do not invent a clean guess of a different card.

Rules for "set_name":
- Only fill this if you can read an actual printed set name or expansion line on this card (not from artwork alone). Otherwise use null.
- If unsure, use null.

Return ONLY a JSON object (no markdown, no commentary):
{"name": "exact printed card name", "set_name": "printed set name or null"}"""


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

    return {"name": name.strip(), "set_name": sn}


def identify_card_from_jpeg(jpeg_bytes: bytes) -> dict[str, str | None]:
    """
    Send JPEG bytes to Claude Vision; return {"name": str, "set_name": str | None}.

    Requires ANTHROPIC_API_KEY. Optional ANTHROPIC_MODEL (default Sonnet per AGENT.md).
    """
    if not jpeg_bytes:
        raise CardIdentificationError("Empty JPEG buffer")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise CardIdentificationError("ANTHROPIC_API_KEY is not set")

    b64 = base64.standard_b64encode(jpeg_bytes).decode("ascii")
    client = Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model=_model(),
            max_tokens=_MAX_TOKENS,
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
