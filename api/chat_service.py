"""
FastAPI proxy converting OpenAI-style chat completion and model requests into
browser automation jobs and returning compatible JSON responses.

Canonical endpoints are **/chat/completions** and **/models** – any version-
prefixed paths (e.g. /v1/chat/completions, /v3/models, /version42/…) are
transparently redirected via HTTP 307 so the original request method and body
are preserved.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from config import ENABLE_DEBUG, env  # Centralised helper loads .env at import time
from orchestrator.browser_pool import BrowserSessionPool
from utils.tokenization import num_tokens

# ──────────────────────────────────────────────────────────────
#  Logging setup
# ──────────────────────────────────────────────────────────────

_logger = logging.getLogger(__name__)
if ENABLE_DEBUG and not logging.getLogger().handlers:
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s | %(message)s")

# ──────────────────────────────────────────────────────────────
#  Constants & helpers
# ──────────────────────────────────────────────────────────────

ROOT_DIR: Path = Path(__file__).resolve().parent.parent
ASSETS_DIR: Path = ROOT_DIR / "assets"

with open(ASSETS_DIR / "fallback_models.json", encoding="utf-8") as fh:
    FALLBACK_MODELS: dict = json.load(fh)

SYSTEM_PROMPT_MODE_DEFAULT: str = env("SYSTEM_PROMPT_MODE", "delete").lower()

_UI_CLOSING_RE = re.compile(r"(</user_instructions>)", re.IGNORECASE)
_META_CLOSING_RE = re.compile(r"(</meta\s*prompt>)", re.IGNORECASE)

# ──────────────────────────────────────────────────────────────
#  Application bootstrap
# ──────────────────────────────────────────────────────────────

app = FastAPI()

# —— CORS middleware ——————————————————————————————————————————
# Allow configurable origins for browser-based clients; enables
# successful OPTIONS preflight requests to all endpoints.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in env("CORS_ALLOW_ORIGINS", "*").split(",")],
    allow_credentials=env("CORS_ALLOW_CREDENTIALS", True, cast=bool),
    allow_methods=["*"],
    allow_headers=["*"],
)

browser_pool = BrowserSessionPool()

# ──────────────────────────────────────────────────────────────
#  Core handler (unversioned chat completions)
# ──────────────────────────────────────────────────────────────


@app.post("/chat/completions", name="completions_no_version")
async def _handle_completions(request: Request):
    """
    Accept an OpenAI-compatible chat payload, forward it to ChatGPT via a
    headless browser session, then return a matching JSON response.
    """
    if ENABLE_DEBUG:
        _logger.debug(
            "Incoming request: %s %s from %s",
            request.method,
            request.url.path,
            request.client or "unknown",
        )

    try:
        payload: dict = await request.json()
    except ValueError:
        return JSONResponse(
            {"error": {"message": "Invalid JSON"}},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if ENABLE_DEBUG:
        _logger.debug("Payload received:\n%s", json.dumps(payload, indent=2, ensure_ascii=False))

    # ───── Strip unsupported parameters ─────
    payload.pop("temperature", None)

    # ───── Manipulate messages list ─────
    mode: str = SYSTEM_PROMPT_MODE_DEFAULT.replace("-", "_")
    messages: List[dict] = payload.get("messages", [])

    if mode == "delete":
        messages = [m for m in messages if m.get("role") != "system"]

    elif mode == "merge":
        system_texts = [m["content"] for m in messages if m.get("role") == "system"]
        messages = [m for m in messages if m.get("role") != "system"]
        if system_texts and messages:
            messages[-1]["content"] = (
                "\n".join(system_texts) + "\n" + messages[-1]["content"]
            )

    elif mode == "merge_post_user_instructions":
        system_texts = [m["content"] for m in messages if m.get("role") == "system"]
        messages = [m for m in messages if m.get("role") != "system"]
        if system_texts and messages:
            combined = "\n".join(system_texts)
            last_content = messages[-1]["content"]
            match = _UI_CLOSING_RE.search(last_content)
            if match:
                idx = match.end()
                messages[-1]["content"] = (
                    f"{last_content[:idx]}\n{combined}\n{last_content[idx:]}"
                )
            else:
                messages[-1]["content"] = f"{combined}\n{last_content}"

    elif mode == "merge_post_meta":
        system_texts = [m["content"] for m in messages if m.get("role") == "system"]
        messages = [m for m in messages if m.get("role") != "system"]
        if system_texts and messages:
            combined = "\n".join(system_texts)
            last_content = messages[-1]["content"]
            matches = list(_META_CLOSING_RE.finditer(last_content))
            if matches:
                idx = matches[-1].end()
                messages[-1]["content"] = (
                    f"{last_content[:idx]}\n{combined}\n{last_content[idx:]}"
                )
            else:
                messages[-1]["content"] = f"{last_content}\n{combined}"

    # else: "keep" – no modification

    # ───── Flatten messages into a single prompt string ─────
    prompt_string: str = "\n".join(m.get("content", "") for m in messages)

    model: Optional[str] = payload.get("model")
    if payload.get("stream", False):
        return JSONResponse(
            {"error": {"message": "stream=True not supported"}}, status_code=501
        )

    # ───── Forward prompt to browser worker pool ─────
    try:
        result = await browser_pool.ask_async(prompt_string, model)
        answer_chunks: List[str] = result["answer"]
    except Exception as exc:  # pragma: no cover – runtime error
        return JSONResponse(
            {"error": {"message": f"Browser worker error: {exc}"}},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    assistant_reply: str = "".join(answer_chunks).strip()

    # If browser layer signals an unrecoverable error, propagate structured error
    if assistant_reply.lower().startswith("error"):
        _, _, raw_msg = assistant_reply.partition(":")
        error_msg = raw_msg.strip() or "error"

        completion_id: str = f"chatcmpl-{uuid.uuid4().hex[:27]}"
        created_ts: int = int(time.time())
        prompt_tokens: int = num_tokens(prompt_string, model)
        response_body: dict = {
            "id": completion_id,
            "object": "chat.completion",
            "created": created_ts,
            "model": model or "browser",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": error_msg},
                    "logprobs": None,
                    "finish_reason": "error",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": 0,
                "total_tokens": prompt_tokens,
            },
        }
        return JSONResponse(response_body, status_code=500)

    # ───── Compute token usage ─────
    prompt_tokens: int = num_tokens(prompt_string, model)
    completion_tokens: int = num_tokens(assistant_reply, model)

    # ───── Assemble OpenAI-compatible payload ─────
    completion_id: str = f"chatcmpl-{uuid.uuid4().hex[:27]}"
    created_ts: int = int(time.time())

    response_body: dict = {
        "id": completion_id,
        "object": "chat.completion",
        "created": created_ts,
        "model": model or "browser",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": assistant_reply},
                "logprobs": None,
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }

    if ENABLE_DEBUG:
        _logger.debug("Response body:\n%s", json.dumps(response_body, indent=2, ensure_ascii=False))

    return JSONResponse(response_body, status_code=200)


# ──────────────────────────────────────────────────────────────
#  Redirects for version-prefixed chat completions paths
# ──────────────────────────────────────────────────────────────


@app.post("/v{version:int}/chat/completions", name="completions_redirect_v")
@app.post("/version{version:int}/chat/completions", name="completions_redirect_version")
async def _redirect_completions(version: int):
    """Redirect any version-prefixed completions path to /chat/completions."""
    return RedirectResponse(url="/chat/completions", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


# ──────────────────────────────────────────────────────────────
#  Model list endpoints and redirects
# ──────────────────────────────────────────────────────────────


@app.get("/models", name="models_no_version")
async def list_models(request: Request):
    """Return a static model list when upstream is unavailable."""
    if ENABLE_DEBUG:
        _logger.debug(
            "Incoming request: %s %s from %s",
            request.method,
            request.url.path,
            request.client or "unknown",
        )
    return JSONResponse(FALLBACK_MODELS, status_code=200)


@app.get("/v{version:int}/models", name="models_redirect_v")
@app.get("/version{version:int}/models", name="models_redirect_version")
async def _redirect_models(version: int):
    """Redirect any version-prefixed models path to /models."""
    return RedirectResponse(url="/models", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


# ──────────────────────────────────────────────────────────────
#  Main entry-point
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    host: str = env("CHAT_SERVICE_HOST", "0.0.0.0")
    port: int = env("CHAT_SERVICE_PORT", 8000, cast=int)
    reload: bool = env("CHAT_SERVICE_RELOAD", False, cast=bool)

    uvicorn.run(app, host=host, port=port, reload=reload)