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


# Variations seen in ChatGPT UI bubbles
_NETWORK_PATTERNS = {
    "a network error occurred",
    "network error",
    "something went wrong",  # guard for UI wording changes
}

_LENGTH_PATTERNS = {
    "the message you submitted was too long",
    "message too long",
}


def _matches(text: str, patterns: set[str]) -> bool:
    text = text.lower()
    return any(pat in text for pat in patterns)


def detect_error(chunks: List[str]) -> ErrorType:
    """
    Inspect *chunks* and return the detected :class:`ErrorType`.

    Only the **last** assistant chunk is considered so that a successful answer
    following an earlier transient error does **not** trigger a false retry.
    """
    if not chunks:
        return ErrorType.GENERIC

    last = chunks[-1].lower()

    if _matches(last, _LENGTH_PATTERNS):
        return ErrorType.LENGTH
    if _matches(last, _NETWORK_PATTERNS):
        return ErrorType.NETWORK
    return ErrorType.NONE