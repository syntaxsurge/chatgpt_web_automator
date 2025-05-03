"""
Robust error-handling helpers for browser session validation.

The logic detects ChatGPT UI error bubbles and classifies them so that the
automation layer can decide whether to retry or abort.
"""

from __future__ import annotations

from enum import Enum
from typing import List


class ErrorType(str, Enum):
    """Categorisation of assistant failures emitted by the ChatGPT UI."""
    NONE = "none"
    NETWORK = "network"
    LENGTH = "length"
    GENERIC = "generic"


# Canonical phrases that appear (often at the start of) ChatGPT error bubbles
_NETWORK_PATTERNS: set[str] = {
    "a network error occurred",
    "network error",
}
_LENGTH_PATTERNS: set[str] = {
    "the message you submitted was too long",
    "message too long",
    "the message you submitted was too long, please reload the conversation and submit something shorter",
}

# Genuine error bubbles are concise; longer replies are treated as normal
_MAX_ERROR_CHARS: int = 180


# ──────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────


def _canonical(text: str) -> str:
    """Lower-case *text* and strip surrounding whitespace / trailing punctuation."""
    return text.strip().lower().rstrip(".! ")


def _matches_exact(text: str, patterns: set[str]) -> bool:
    """Return ``True`` iff *text* exactly equals one of *patterns*."""
    return _canonical(text) in patterns


def _matches_prefix(text: str, patterns: set[str]) -> bool:
    """Return ``True`` if *text* starts with any *patterns* entry (canonicalised)."""
    canon = _canonical(text)
    return any(canon.startswith(p) for p in patterns)


# ──────────────────────────────────────────────────────────────
# Public detection API
# ──────────────────────────────────────────────────────────────


def detect_error(chunks: List[str]) -> ErrorType:
    """
    Inspect assistant *chunks* and return the detected :class:`ErrorType`.

    Only the **final** chunk is considered authoritative so that a correct
    answer following a transient error bubble is not mis-classified.
    """
    if not chunks:
        return ErrorType.GENERIC

    last: str = chunks[-1].strip()

    # Ignore long, meaningful replies – genuine error bubbles are brief.
    if len(last) > _MAX_ERROR_CHARS:
        return ErrorType.NONE

    if _matches_exact(last, _LENGTH_PATTERNS):
        return ErrorType.LENGTH
    if _matches_exact(last, _NETWORK_PATTERNS) or _matches_prefix(last, _NETWORK_PATTERNS):
        return ErrorType.NETWORK

    return ErrorType.NONE