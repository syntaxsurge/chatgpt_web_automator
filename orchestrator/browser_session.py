from __future__ import annotations

import sys
import threading
import time
import traceback
import uuid
from typing import List

from automator.web_automator import ChatGPTWebAutomator
from config import env
from utils.errors import ErrorType, detect_error

# Maximum number of automatic retries for ChatGPT network-error bubbles
_MAX_NETWORK_ERROR_RETRIES: int = env("NETWORK_ERROR_RETRIES", 0, cast=int)


class BrowserSession:
    """
    Thin wrapper around a single ChatGPTWebAutomator instance.

    The internal lock guarantees that only *one* prompt is processed at a
    time; additional callers are automatically queued until the current
    interaction completes.
    """

    def __init__(self) -> None:
        self.session_id: str = str(uuid.uuid4())
        self._client: ChatGPTWebAutomator = ChatGPTWebAutomator()
        self._lock = threading.Lock()
        self.last_used_at: float = time.monotonic()

    # ──────────────────────────────────────────────────────────
    # public API
    # ──────────────────────────────────────────────────────────

    def ask(self, prompt: str, model: str | None = None) -> List[str]:
        """
        Send *prompt* to ChatGPT (using the specified *model*) and block until
        the full reply is streamed.

        All calls are serialised behind a lock so that exactly one browser
        interaction happens at a time.

        Any exception or recognised error type is **always** printed to
        ``stderr`` with a complete stack trace and context, regardless of the
        global debug flag.
        """
        attempts = 0
        with self._lock:
            while True:
                self.last_used_at = time.monotonic()

                try:
                    # Always start a brand-new conversation so replies don’t bleed.
                    self._client.open_new_chat(model)
                    chunks = self._client.send_message(prompt)
                except Exception:  # pragma: no cover – runtime failure
                    # Uncaught exception within Selenium or our wrapper
                    print("\n" + "=" * 80, file=sys.stderr)
                    print("Exception in BrowserSession.ask", file=sys.stderr)
                    traceback.print_exc(file=sys.stderr)
                    print("=" * 80 + "\n", file=sys.stderr)
                    last_chunk = chunks[-1] if chunks else "network error"
                    return [f"error: {last_chunk}"]

                error_type = detect_error(chunks)

                # —— unrecoverable errors ————————————————————————
                if error_type in {ErrorType.LENGTH, ErrorType.GENERIC}:
                    last_chunk = chunks[-1] if chunks else ""
                    print(f"Unrecoverable error detected: {error_type.name}. "
                          f"Last chunk: {last_chunk}", file=sys.stderr)
                    return [f"error: {last_chunk or error_type.name.lower()}"]

                # —— network errors (optional retry) —————————————————
                if error_type == ErrorType.NETWORK:
                    last_chunk = chunks[-1] if chunks else ""
                    print(
                        f"Network error detected "
                        f"(attempt {attempts + 1}/{_MAX_NETWORK_ERROR_RETRIES}). "
                        f"Last chunk: {last_chunk}",
                        file=sys.stderr,
                    )
                    if _MAX_NETWORK_ERROR_RETRIES and attempts < _MAX_NETWORK_ERROR_RETRIES:
                        attempts += 1
                        continue
                    return [f"error: {last_chunk or error_type.name.lower()}"]

                # —— success ————————————————————————————————
                return chunks

    def shutdown(self) -> None:
        """Close the underlying Chrome instance."""
        self._client.quit()