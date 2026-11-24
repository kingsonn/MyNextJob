"""Free-tier and local models. Keys stay in the environment and are never logged."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from services.gateway.pool import ProviderError
from services.paths import repo_root

Transport = Callable[[str, dict[str, str], dict[str, Any]], tuple[int, dict[str, Any]]]


@dataclass(frozen=True)
class FreeProvider:
    name: str
    tier: str
    env: str
    url: str
    model: str


def load_providers() -> list[FreeProvider]:
    import yaml

    path = repo_root() / "services" / "gateway" / "free_tiers.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    rows = loaded["providers"]
    if not isinstance(rows, list):
        raise TypeError("providers must be a list")
    found: list[FreeProvider] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("provider row must be a mapping")
        found.append(
            FreeProvider(
                str(row["name"]),
                str(row["tier"]),
                str(row["env"]),
                str(row["url"]),
                str(row["model"]),
            )
        )
    return found


def configured() -> list[str]:
    if os.environ.get("CLAIMPILOT_LIVE_MODELS") != "1":
        return []
    return [item.name for item in load_providers() if os.environ.get(item.env, "").strip()]


def complete_chat(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tier: str,
    transport: Transport | None = None,
) -> tuple[str, dict[str, Any]]:
    """One tool-calling turn. A down provider is skipped. Scripted is last."""

    names = configured()
    if not names:
        return "scripted", {"role": "assistant", "content": ""}
    send = _http if transport is None else transport
    for item in _ordered(load_providers(), tier, names):
        secret = os.environ.get(item.env, "").strip()
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + secret}
        body: dict[str, Any] = {"model": item.model, "messages": messages}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        try:
            status, payload = send(item.url, headers, body)
        except ProviderError as exc:
            if exc.status in {400, 401, 403, 404, 408, 429, 500, 502, 503, 504}:
                continue
            raise
        if status in {400, 401, 403, 404, 408, 429, 500, 502, 503, 504}:
            continue
        message = _message(payload)
        if message:
            return item.name, message
    return "scripted", {"role": "assistant", "content": "Please say that once more."}


def explain(
    prompt: str,
    tier: str,
    transport: Transport | None = None,
) -> tuple[str, str]:
    """Return the provider name and one sentence. Scripted is the last resort."""

    names = configured()
    if not names:
        return "scripted", ""
    send = _http if transport is None else transport
    ordered = _ordered(load_providers(), tier, names)
    for item in ordered:
        secret = os.environ.get(item.env, "").strip()
        headers = {"Content-Type": "application/json"}
        if item.name != "ollama":
            headers["Authorization"] = "Bearer " + secret
        body = {
            "model": item.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            status, payload = send(item.url, headers, body)
        except ProviderError as exc:
            if exc.status in {400, 401, 403, 404, 408, 429, 500, 502, 503, 504}:
                continue
            raise
        if status in {400, 401, 403, 404, 408, 429, 500, 502, 503, 504}:
            continue
        text = _content(payload)
        if text:
            return item.name, text
    return "scripted", ""


def _ordered(providers: list[FreeProvider], tier: str, names: list[str]) -> list[FreeProvider]:
    chosen = [item for item in providers if item.name in names]
    return [item for item in chosen if item.tier == tier] + [
        item for item in chosen if item.tier != tier
    ]


def _message(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return {}
    first = choices[0]
    if not isinstance(first, dict):
        return {}
    message = first.get("message")
    if not isinstance(message, dict):
        return {}
    return message


def _content(payload: dict[str, Any]) -> str:
    content = _message(payload).get("content")
    return content if isinstance(content, str) else ""


def _http(url: str, headers: dict[str, str], body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={**headers, "User-Agent": "ClaimPilot/1.0"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=25) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise TypeError("provider response is not an object")
            return response.status, parsed
    except HTTPError as exc:
        raise ProviderError(exc.code) from exc
    except (URLError, TimeoutError) as exc:
        raise ProviderError(503) from exc
