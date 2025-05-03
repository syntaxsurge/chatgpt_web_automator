import threading
import time
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

        Error handling is delegated to :func:`utils.errors.detect_error`.
        """
        attempts = 0
        with self._lock:
            while True:
                self.last_used_at = time.monotonic()
                # Always start a brand-new conversation so replies don’t bleed over.
                self._client.open_new_chat(model)
                chunks = self._client.send_message(prompt)

                error_type = detect_error(chunks)

                # Length errors are unrecoverable → propagate immediately
                if error_type in {ErrorType.LENGTH, ErrorType.GENERIC}:
                    return ["ERROR"]

                # Network errors may be transient → retry if allowed
                if error_type == ErrorType.NETWORK:
                    if _MAX_NETWORK_ERROR_RETRIES and attempts < _MAX_NETWORK_ERROR_RETRIES:
                        attempts += 1
                        continue
                    return ["ERROR"]

                # No error detected → success
                return chunks

    def shutdown(self) -> None:
        """Close the underlying Chrome instance."""
        self._client.quit()