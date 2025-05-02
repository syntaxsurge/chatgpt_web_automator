from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load .env located at project root (if it exists)
ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env", override=False)


def _to_bool(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def env(key: str, default: Any = None, cast: type | None = str) -> Any:
    """
    Simple getenv helper with optional casting.
    """
    raw = os.getenv(key)
    if raw is None:
        return default

    if cast is bool:
        return _to_bool(raw)

    try:
        return cast(raw) if cast else raw
    except Exception:
        # Fallback to default on cast failure
        return default