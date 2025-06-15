from __future__ import annotations

import sys
import threading
import time
import traceback
import uuid
from typing import List

from automator.web_automator import ChatGPTWebAutomator
from config import env
from utils.audio import play_ringtone
from utils.chat_backend import ChatBackendClient
from utils.errors import ErrorType, detect_error

_MAX_NETWORK_ERROR_RETRIES: int = env("NETWORK_ERROR_RETRIES", 0, cast=int)
_ENABLE_RINGTONES: bool = env("ENABLE_RINGTONES", True, cast=bool)
_RINGTONE_DURATION: float = env("RINGTONE_DURATION", 1.0, cast=float)


class BrowserSession:
    """
    Handles one Chrome instance; submits prompts sequentially but releases the
    browser lock immediately after obtaining the conversation ID so that
    backend polling can proceed in parallel with new prompts.
    """

    def __init__(self) -> None:
        self.session_id: str = str(uuid.uuid4())
        self._client = ChatGPTWebAutomator()
        self._backend = ChatBackendClient()
        self._lock = threading.Lock()
        self.last_used_at: float = time.monotonic()

    # ──────────────────────────────────────────────────────────
    # public API
    # ──────────────────────────────────────────────────────────

    def ask(self, prompt: str, model: str | None = None, timeout_seconds: float = 7_200.0) -> List[str]:
        """
        Submit *prompt* and return the assistant reply once the backend API
        reports ``finished_successfully`` within *timeout_seconds*.
        """
        attempts = 0
        while True:
            uid = str(uuid.uuid4())
            tagged_prompt = f"{prompt}\n<chatName=\"Request\" uChatId=\"{uid}\"/>"

            try:
                # —— browser interaction (serialised) ————————————
                with self._lock:
                    self.last_used_at = time.monotonic()
                    self._client.open_new_chat(model)
                    chat_id = self._client.send_prompt(tagged_prompt)

                # Print mapping for log/debug purposes
                print(f"{uid}={chat_id}")

                # —— backend polling (runs without browser lock) ———
                assistant_text = self._backend.wait_for_completion(chat_id, timeout_seconds=timeout_seconds)
                chunks = [assistant_text]

            except TimeoutError as exc:
                print(f"Timeout waiting for backend reply: {exc}", file=sys.stderr)
                return [f"error: {exc}"]

            except Exception:  # pragma: no cover – unexpected failure
                print("\n" + "=" * 80, file=sys.stderr)
                print("Exception in BrowserSession.ask", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                print("=" * 80 + "\n", file=sys.stderr)
                if attempts < _MAX_NETWORK_ERROR_RETRIES:
                    attempts += 1
                    continue
                return ["error: unexpected failure"]

            # —— error classification ——————————————————————
            error_type = detect_error(chunks)
            if error_type != ErrorType.NONE:
                return [f"error: {chunks[-1]}"]

            # —— success ————————————————————————————————
            if _ENABLE_RINGTONES:
                play_ringtone(duration=_RINGTONE_DURATION)
            return chunks

    def shutdown(self) -> None:
        """Terminate the underlying Chrome session."""
        self._client.quit()
