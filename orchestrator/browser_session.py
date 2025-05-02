import uuid
import threading
import time

from main import ChatGPTWebAutomator


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

    def ask(self, prompt: str, model: str | None = None) -> list[str]:
        """
        Send *prompt* to ChatGPT (using the specified *model*) and block until
        the full reply is streamed.

        Calls are serialized; if another thread is already interacting with
        the browser, we wait our turn instead of spawning a new one.
        """
        with self._lock:
            self.last_used_at = time.monotonic()
            # Always start a brand-new conversation so replies don’t bleed over.
            self._client.open_new_chat(model)
            return self._client.send_message(prompt)

    def shutdown(self) -> None:
        """Close the underlying Chrome instance."""
        self._client.quit()