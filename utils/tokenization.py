"""
Tokenisation utilities.

Provides :func:`num_tokens` which returns the number of tokens for a given
piece of text, using the model-specific encoding when available and falling
back to ``cl100k_base`` otherwise.
"""

from __future__ import annotations

from typing import Optional

import tiktoken

# Re-use the same fallback encoder to avoid repeated look-ups
_FALLBACK_ENCODER = tiktoken.get_encoding("cl100k_base")


def _encoder_for(model: Optional[str] = None) -> tiktoken.Encoding:
    """
    Return a *tiktoken* encoder appropriate for *model*.

    Falls back to ``cl100k_base`` if the model is unknown or *None*.
    """
    if not model:
        return _FALLBACK_ENCODER

    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        # Unknown model name → default
        return _FALLBACK_ENCODER


def num_tokens(text: str, model: Optional[str] = None) -> int:
    """
    Count the number of tokens used by *text* for the specified *model*.

    Parameters
    ----------
    text:
        The input string whose tokens we wish to count.
    model:
        Optional model name (e.g. ``"gpt-4o"``). If omitted or unrecognised,
        the ``cl100k_base`` encoding is used.

    Returns
    -------
    int
        The number of tokens.
    """
    encoder = _encoder_for(model)
    # Exclude special tokens from normal text
    return len(encoder.encode(text, disallowed_special=()))
