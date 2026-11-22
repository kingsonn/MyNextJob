"""Deterministic hashing embedding used by offline retrieval."""

from __future__ import annotations

import hashlib
import math
import re

WIDTH = 64
_TOKEN = re.compile(r"[a-z0-9]+")


def tokens(value: str) -> list[str]:
    return _TOKEN.findall(value.lower())


def embed(text: str) -> tuple[float, ...]:
    """Hash tokens into a unit vector. This is not a neural embedding model."""

    vector = [0.0] * WIDTH
    for token in tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:2], "big") % WIDTH
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0:
        return tuple(vector)
    return tuple(component / norm for component in vector)
