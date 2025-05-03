from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path

from config import ROOT_DIR, env


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────


def _resolve_profile_dir() -> Path:
    """
    Return an absolute path for the Chrome user-data directory.

    If *CHROME_PROFILE_DIR* is relative, it is made relative to *ROOT_DIR* so
    the profile can be located regardless of the current working directory.
    """
    raw = env("CHROME_PROFILE_DIR", "chromedata")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path.resolve()


# ──────────────────────────────────────────────────────────────
# Typed configuration containers
# ──────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Credentials:
    """Simple container for ChatGPT login credentials (used when AUTO_LOGIN=true)."""

    email: str = env("CHATGPT_EMAIL", "your_email@example.com")
    password: str = env("CHATGPT_PASSWORD", "your_password_here")


@dataclass(slots=True)
class ClientConfig:
    """
    Aggregates all runtime settings for the web automator.

    Defaults are pulled from environment variables so they remain centrally
    configurable via *config.py*.
    """

    profile_dir: Path = _resolve_profile_dir()
    headless: bool = env("HEADLESS_CHROME", False, cast=bool)
    auto_login: bool = env("AUTO_LOGIN", False, cast=bool)
    explicit_timeout: int = env("EXPLICIT_WAIT_TIMEOUT", 15, cast=int)
    key_delay_range: tuple[float, float] = (
        env("HUMAN_KEY_DELAY_MIN", 0.08, cast=float),
        env("HUMAN_KEY_DELAY_MAX", 0.30, cast=float),
    )
    stream_settle: float = env("STREAM_SETTLE_TIME", 0.8, cast=float)
    poll_interval: float = env("POLL_INTERVAL", 0.20, cast=float)
    typing_mode: str = env("TYPING_MODE", "normal").lower()  # normal | fast | paste
    paste_chunk_size: int = env("PASTE_CHUNK_SIZE", 50000, cast=int)

    def ctrl_or_cmd(self) -> str:
        """Return the correct clipboard modifier key for the current platform."""
        from selenium.webdriver.common.keys import Keys

        return Keys.COMMAND if platform.system() == "Darwin" else Keys.CONTROL