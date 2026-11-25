"""Turn a call recording into text. Tests pass a fake and never open a socket."""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_WHISPER_MODEL = "whisper-large-v3-turbo"


def transcript_from_turn(
    body: dict[str, Any],
    transcribe: Callable[[bytes], str] | None,
) -> str:
    text = body.get("transcript")
    if isinstance(text, str) and text.strip():
        return text.strip()
    raw = body.get("audio_wav_base64")
    if not isinstance(raw, str) or not raw.strip():
        return ""
    try:
        wav = base64.b64decode(raw)
    except ValueError:
        return ""
    if transcribe is not None:
        return transcribe(wav).strip()
    return _groq_whisper(wav).strip()


def _groq_whisper(wav: bytes) -> str:
    if os.environ.get("CLAIMPILOT_LIVE_MODELS") != "1":
        return ""
    secret = os.environ.get("GROQ_API_KEY", "").strip()
    if not secret:
        return ""
    boundary = "----claimpilot"
    payload = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="turn.wav"\r\n'
            "Content-Type: audio/wav\r\n\r\n"
        ).encode()
        + wav
        + (
            f"\r\n--{boundary}\r\n"
            'Content-Disposition: form-data; name="model"\r\n\r\n'
            f"{_WHISPER_MODEL}\r\n"
            f"--{boundary}--\r\n"
        ).encode()
    )
    request = Request(
        _WHISPER_URL,
        data=payload,
        headers={
            "Authorization": "Bearer " + secret,
            "Content-Type": "multipart/form-data; boundary=" + boundary,
            "User-Agent": "ClaimPilot/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=25) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(parsed, dict):
        return ""
    heard = parsed.get("text")
    return heard if isinstance(heard, str) else ""
