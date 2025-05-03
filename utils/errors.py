"""
Robust error-handling helpers for browser session validation.

The previous implementation could mis-classify normal assistant messages when
the last chunk was a short string; the new logic only flags *exact* matches of
the canonical ChatGPT error bubbles and exposes Enum values as strings to
ensure cross-module equality.
"""

from __future__ import annotations

from enum import Enum
from typing import List


class ErrorType(str, Enum):
    """
    Categorisation of assistant failures emitted by the ChatGPT UI.

    Using :class:`str` ensures that equality checks remain reliable across hot
    reloads and serialisation boundaries.
    """

    NONE = "none"
    NETWORK = "network"
    LENGTH = "length"
    GENERIC = "generic"


# Canonical phrases that appear verbatim in ChatGPT error bubbles.
_NETWORK_PATTERNS: set[str] = {
    "a network error occurred",
    "network error",
}

_LENGTH_PATTERNS: set[str] = {
    "the message you submitted was too long",
    "message too long",
}

# Genuine error bubbles are concise; anything longer than this is treated as a
# normal assistant reply.
_MAX_ERROR_CHARS: int = 180


# ──────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────


def _canonical(text: str) -> str:
    """
    Return *text* lower-cased with surrounding whitespace and trailing
    punctuation stripped so comparisons are reliable.
    """
    return text.strip().lower().rstrip(".! ")


def _matches_exact(text: str, patterns: set[str]) -> bool:
    """Return ``True`` iff *text* exactly equals one of *patterns*."""
    return _canonical(text) in patterns


# ──────────────────────────────────────────────────────────────
# Public detection API
# ──────────────────────────────────────────────────────────────


def detect_error(chunks: List[str]) -> ErrorType:
    """
    Inspect assistant *chunks* and return the detected :class:`ErrorType`.

    Only the **final** chunk is considered authoritative so that a correct
    answer following a transient error bubble is not mis-classified.

    Heuristics
    ----------
    * Empty *chunks* → :pydata:`ErrorType.GENERIC`
    * Replies longer than ``_MAX_ERROR_CHARS`` → :pydata:`ErrorType.NONE`
    * Otherwise, require an *exact* match against the curated phrase sets.
    """
    if not chunks:
        return ErrorType.GENERIC

    last: str = chunks[-1].strip()

    # Ignore long, meaningful replies – genuine error bubbles are brief.
    if len(last) > _MAX_ERROR_CHARS:
        return ErrorType.NONE

    if _matches_exact(last, _LENGTH_PATTERNS):
        return ErrorType.LENGTH
    if _matches_exact(last, _NETWORK_PATTERNS):
        return ErrorType.NETWORK

    return ErrorType.NONE