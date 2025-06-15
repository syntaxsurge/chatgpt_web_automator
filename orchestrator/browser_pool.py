import threading
from typing import Dict, List

from anyio import to_thread

from orchestrator.browser_session import BrowserSession


class BrowserSessionPool:
    """
    Serialises all incoming chatbot requests onto **one** BrowserSession.

    The first call creates the browser; every subsequent call re-uses it.
    Concurrent FastAPI requests are transparently queued by the session’s lock,
    so no additional browser instances are ever spawned.
    """

    def __init__(self) -> None:
        self._session: BrowserSession | None = None
        self._create_lock = threading.Lock()

    # ──────────────────────────────────────────────────────────
    # internal helpers
    # ──────────────────────────────────────────────────────────

    def _ensure_session(self) -> BrowserSession:
        """
        Lazily create the singleton BrowserSession, protecting against the
        race where multiple requests arrive before the first one finishes
        booting.
        """
        if self._session is None:
            with self._create_lock:
                if self._session is None:  # double-checked locking
                    self._session = BrowserSession()
        return self._session

    # ──────────────────────────────────────────────────────────
    # public API
    # ──────────────────────────────────────────────────────────

    def ask(self, prompt: str, model: str | None = None, timeout_seconds: float = 7_200.0) -> Dict[
        str, List[str] | str]:
        session = self._ensure_session()
        answer_chunks = session.ask(prompt, model, timeout_seconds)  # queued via session lock
        return {"browser_id": session.session_id, "answer": answer_chunks}

    async def ask_async(self, prompt: str, model: str | None = None, timeout_seconds: float = 7_200.0):
        return await to_thread.run_sync(
            self.ask, prompt, model, timeout_seconds, cancellable=True
        )
