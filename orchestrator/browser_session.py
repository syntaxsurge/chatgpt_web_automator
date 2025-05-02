import threading
import time
import uuid
from typing import List

from main import ChatGPTWebAutomator
from config import env


# Maximum number of automatic retries for ChatGPT "network error” bubbles
_MAX_NETWORK_ERROR_RETRIES: int = env("NETWORK_ERROR_RETRIES", 0, cast=int)


class BrowserSession:
    """
    Thin wrapper around a single ChatGPTWebAutomator instance.

    The internal lock guarantees that only *one* prompt is processed at a
    time; additional callers are automatically queued until the current
    interaction completes.
    """

    def __init__(self) -> None:
        self.session_id = str(uuid.uuid4())
        self._client = ChatGPTWebAutomator()
        self._lock = threading.Lock()
        self.last_used_at = time.monotonic()

    # ──────────────────────────────────────────────────────────
    # public API
    # ──────────────────────────────────────────────────────────

    def ask(self, prompt: str, model: str | None = None) -> List[str]:
        """
        Send *prompt* to ChatGPT (using the specified *model*) and block until
        the full reply is streamed.

        Calls are serialized; if another thread is already interacting with
        the browser, we wait our turn instead of spawning a new one.

        If the ChatGPT UI returns a "network error” bubble, we automatically
        retry the entire interaction up to *_MAX_NETWORK_ERROR_RETRIES* times.
        After all retries are exhausted (or retries are disabled), a single
        element list containing the literal string ``"ERROR"`` is returned so
        the API layer can propagate a well-formed error payload.
        """
        attempts = 0
        with self._lock:
            while True:
                self.last_used_at = time.monotonic()
                # Always start a brand-new conversation so replies don’t bleed over.
                self._client.open_new_chat(model)
                chunks = self._client.send_message(prompt)

                # Detect the standard ChatGPT network-error text.
                joined = " ".join(chunks).lower()
                if "a network error occurred" in joined:
                    if _MAX_NETWORK_ERROR_RETRIES and attempts < _MAX_NETWORK_ERROR_RETRIES:
                        attempts += 1
                        continue
                    return ["ERROR"]

                return chunks

    def shutdown(self) -> None:
        """Close the underlying Chrome instance."""
        self._client.quit()