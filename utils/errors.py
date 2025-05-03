"""
Shared error-handling helpers for browser session validation.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import List


class ErrorType(Enum):
    NONE = auto()
    NETWORK = auto()
    LENGTH = auto()
    GENERIC = auto()


# Explicit phrases that appear **verbatim** in ChatGPT error bubbles.
# Substring matches are intentionally avoided to reduce false positives when
# the assistant legitimately writes similar wording inside a normal reply.
_NETWORK_PATTERNS = {
    "a network error occurred",
    "network error",
}

_LENGTH_PATTERNS = {
    "the message you submitted was too long",
    "message too long",
}


def _matches_exact(text: str, patterns: set[str]) -> bool:
    """
    Return ``True`` if *text* exactly equals any entry in *patterns* once
    lower-cased and stripped of trailing punctuation.
    """
    simplified = text.lower().rstrip(".! ")
    return simplified in patterns


def detect_error(chunks: List[str]) -> ErrorType:
    """
    Inspect *chunks* and return the detected :class:`ErrorType`.

    The **last** assistant chunk is considered authoritative so that a
    successful answer following a transient error does not trigger a retry.

    Heuristics
    ----------
    * Only very short chunks (≤ 120 characters) are eligible for automatic
      error detection.  This prevents flagging normal, lengthy replies that
      merely *mention* phrases like "network error" inside the content.
    * A match must be an **exact** phrase equality against the curated sets
      above, after case-folding and punctuation trimming.
    """
    if not chunks:
        return ErrorType.GENERIC

    last = chunks[-1].strip()

    # Ignore long, meaningful replies – genuine error bubbles are concise.
    if len(last) > 120:
        return ErrorType.NONE

    if _matches_exact(last, _LENGTH_PATTERNS):
        return ErrorType.LENGTH
    if _matches_exact(last, _NETWORK_PATTERNS):
        return ErrorType.NETWORK
    return ErrorType.NONE