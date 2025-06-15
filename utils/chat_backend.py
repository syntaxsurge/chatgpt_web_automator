from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

import requests

from config import ENABLE_DEBUG, env

_logger = logging.getLogger(__name__)
if ENABLE_DEBUG and not logging.getLogger().handlers:
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s | %(message)s")

# ──────────────────────────────────────────────────────────────
#  Environment & constants
# ──────────────────────────────────────────────────────────────

_AUTH_TOKEN: str = env("OPENAI_AUTH_TOKEN", "", cast=str)
if not _AUTH_TOKEN:
    raise RuntimeError("OPENAI_AUTH_TOKEN environment variable must be set")

_HEADERS_BASE: Dict[str, str] = {
    "accept": "*/*",
    "accept-encoding": "gzip, deflate",
    "accept-language": "en-US,en;q=0.6",
    "authorization": f"Bearer {_AUTH_TOKEN}",
    "oai-language": "en-US",
    "priority": "u=1, i",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "sec-gpc": "1",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
}

_WANTED_ROLE = "assistant"


# ──────────────────────────────────────────────────────────────
#  Internal helpers
# ──────────────────────────────────────────────────────────────


def _content_text(msg: Dict[str, Any]) -> str:
    content = msg.get("content", {})
    ctype = content.get("content_type")
    if ctype == "text":
        return "\n".join(content.get("parts", [])).strip()
    if ctype == "execution_output":
        return content.get("text", "").strip()
    if ctype == "thoughts":  # interim chain-of-thought message – ignore
        return ""
    return str(content).strip()


def _latest_assistant(mapping: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for node in reversed(list(mapping.values())):
        msg = node.get("message")
        if msg and msg.get("author", {}).get("role") == _WANTED_ROLE:
            return msg
    return None


# ──────────────────────────────────────────────────────────────
#  Public client
# ──────────────────────────────────────────────────────────────


class ChatBackendClient:
    """
    Wrapper around ChatGPT’s undocumented backend conversation API that
    gracefully handles in‑flight / non‑JSON responses and offers verbose
    debugging when *ENABLE_DEBUG* is true.
    """

    _BASE = "https://chatgpt.com/backend-api/conversation"

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(_HEADERS_BASE)

    # —— low-level ——————————————————————————————————————————

    def _url(self, conv_id: str) -> str:
        return f"{self._BASE}/{conv_id}"

    def fetch(self, conv_id: str) -> Dict[str, Any]:
        """
        Return the raw backend JSON for *conv_id*.

        If the response is empty or not valid JSON, a *ValueError* is raised so
        the caller can treat the conversation as "not ready yet".
        """
        url = self._url(conv_id)
        # Dynamic Referer is required for some Cloudflare checks
        headers = {"referer": f"https://chatgpt.com/c/{conv_id}"}

        resp = self._session.get(url, headers=headers, timeout=15)

        if ENABLE_DEBUG:
            _logger.debug(
                "Backend fetch %s – status %s – %.1f kB",
                conv_id,
                resp.status_code,
                len(resp.content) / 1024.0,
            )

        # 404 / 403 / 5xx → propagate to caller for retry logic
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError:
            if ENABLE_DEBUG:
                snippet = resp.text[:300].replace("\n", " ")
                _logger.debug("Backend non‑200 body for %s: %s", conv_id, snippet)
            raise

        # Empty body → treat as "not ready" rather than fatal
        if not resp.content or not resp.text.strip():
            raise ValueError("backend returned empty body")

        try:
            data = resp.json()
        except ValueError as exc:
            if ENABLE_DEBUG:
                snippet = resp.text[:300].replace("\n", " ")
                _logger.debug("Backend non‑JSON body for %s: %s", conv_id, snippet)
            raise ValueError("backend body not valid JSON") from exc

        if ENABLE_DEBUG:
            _logger.debug("Backend JSON for %s:\n%s", conv_id, json.dumps(data, indent=2)[:1_000])

        return data

    # —— high-level ——————————————————————————————————————————

    def wait_for_completion(
            self,
            conv_id: str,
            timeout_seconds: float = 7_200.0,
            poll_interval: float = 1.0,
    ) -> str:
        """
        Block until the *latest* node in the conversation mapping

           • has ``status == "finished_successfully"``,
           • its message author’s ``role`` is ``"assistant"``, **and**
           • it contains non-empty content.

        If debugging is enabled, the most recent node’s role and status are
        logged on every poll.  A :class:`TimeoutError` is raised after
        *timeout_seconds* elapsed.
        """
        deadline = time.monotonic() + timeout_seconds

        while time.monotonic() < deadline:
            try:
                data = self.fetch(conv_id)
            except Exception as exc:
                # Network / decoding issue ⇒ wait & retry
                _logger.warning("Backend fetch failed for %s: %s", conv_id, exc)
                time.sleep(poll_interval)
                continue

            # The mapping dict preserves insertion order ⇒ the newest node
            # is the last one.
            try:
                latest_node = next(reversed(data["mapping"].values()))
                msg = latest_node.get("message") or {}
            except (StopIteration, KeyError):
                # Mapping empty ⇒ keep polling
                time.sleep(poll_interval)
                continue

            role = msg.get("author", {}).get("role")
            status = msg.get("status")

            if ENABLE_DEBUG:
                _logger.debug("Latest node → role=%s, status=%s", role, status)

            if status != "finished_successfully":
                time.sleep(poll_interval)
                continue

            # We have a finished node.  Make sure it’s the assistant and has
            # something useful to say.
            content_text = _content_text(msg)
            if role == "assistant" and content_text:
                return content_text

            # Otherwise wait for the *next* node to appear.
            time.sleep(poll_interval)

        raise TimeoutError(
            f"No suitable assistant reply after {timeout_seconds}s for conversation {conv_id}"
        )