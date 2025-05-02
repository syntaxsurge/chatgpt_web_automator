from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv, dotenv_values

# ──────────────────────────────────────────────────────────────
#  Project root & .env loading
# ──────────────────────────────────────────────────────────────

ROOT_DIR: Path = Path(__file__).resolve().parent

# Load the project-level .env file if present (values do **not** override
# already-exported environment variables).
load_dotenv(ROOT_DIR / ".env", override=False)

# ──────────────────────────────────────────────────────────────
#  Public helpers
# ──────────────────────────────────────────────────────────────


def _to_bool(value: str) -> bool:
    """Convert common truthy strings to ``True``."""
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env(key: str, default: Any = None, cast: type | None = str) -> Any:
    """
    Return environment variable *key* with optional *cast*.

    If *key* is missing or *cast* fails, *default* is returned instead.
    """
    raw = os.getenv(key)
    if raw is None:  # not set → fall back immediately
        return default

    if cast is bool:  # specialised fast-path for booleans
        return _to_bool(raw)

    try:
        return cast(raw) if cast else raw
    except Exception:
        return default


# ──────────────────────────────────────────────────────────────
#  Global debug flag
# ──────────────────────────────────────────────────────────────

ENABLE_DEBUG: bool = env("ENABLE_DEBUG", False, cast=bool)

# ──────────────────────────────────────────────────────────────
#  Optional debug dump of .env values
# ──────────────────────────────────────────────────────────────

if ENABLE_DEBUG:
    # Identify which file actually provided the values
    _env_file: Path = ROOT_DIR / ".env"
    if not _env_file.exists():
        _env_file = ROOT_DIR / ".env.example"

    _values = dotenv_values(_env_file)

    # Ensure at least one stream handler exists before emitting
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s | %(message)s")

    _logger = logging.getLogger("config")
    _dump = "\n".join(f"{k}={v}" for k, v in _values.items())
    _logger.debug("Loaded environment variables from %s:\n%s", _env_file.name, _dump)

__all__ = ["ROOT_DIR", "env", "ENABLE_DEBUG"]