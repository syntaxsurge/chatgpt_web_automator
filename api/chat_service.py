"""
FastAPI proxy converting OpenAI-style ``/v1/chat/completions`` requests into browser
automation jobs and returning a compatible JSON response.

Running this file directly (``python -m api.chat_service`` or ``python api/chat_service.py``)
now boots a production-ready Uvicorn server hosting the ``FastAPI`` app.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from orchestrator.browser_pool import BrowserSessionPool
from utils.tokenization import num_tokens

# ──────────────────────────────────────────────────────────────
#  Bootstrap
# ──────────────────────────────────────────────────────────────

load_dotenv()

app = FastAPI()
browser_pool = BrowserSessionPool()

# ──────────────────────────────────────────────────────────────
#  Constants & helpers
# ──────────────────────────────────────────────────────────────

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
with open(ASSETS_DIR / "fallback_models.json", encoding="utf-8") as fh:
    FALLBACK_MODELS: dict = json.load(fh)

SYSTEM_PROMPT_MODE_DEFAULT: str = os.getenv("SYSTEM_PROMPT_MODE", "delete").lower()

_UI_CLOSING_RE = re.compile(r"(</user_instructions>)", re.IGNORECASE)
_META_CLOSING_RE = re.compile(r"(</meta\s*prompt>)", re.IGNORECASE)


# ──────────────────────────────────────────────────────────────
#  POST /v1/chat/completions
# ──────────────────────────────────────────────────────────────


@app.post("/v1/chat/completions")
async def completions(request: Request):
    """
    Accept an OpenAI chat payload, forward the flattened prompt to ChatGPT via a
    headless browser, then return an OpenAI-style completion response.
    """
    try:
        payload: dict = await request.json()
    except ValueError:
        return JSONResponse(
            {"error": {"message": "Invalid JSON"}},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

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

    # else: "keep" - no modification

    # ───── Flatten messages into single prompt ─────
    prompt_string: str = "\n".join(m.get("content", "") for m in messages)

    model: Optional[str] = payload.get("model")
    stream_requested: bool = bool(payload.get("stream", False))
    if stream_requested:
        return JSONResponse(
            {"error": {"message": "stream=True not supported"}}, status_code=501
        )

    # ───── Forward prompt to browser worker ─────
    try:
        result = await browser_pool.ask_async(prompt_string, model)
        answer_chunks: List[str] = result["answer"]
    except Exception as exc:  # pragma: no cover – runtime error
        return JSONResponse(
            {"error": {"message": f"Browser worker error: {exc}"}},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    assistant_reply: str = "".join(answer_chunks).strip()

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

    return JSONResponse(response_body, status_code=200)


# ──────────────────────────────────────────────────────────────
#  GET /v1/models  (and legacy /models)
# ──────────────────────────────────────────────────────────────


@app.get("/v1/models")
@app.get("/models")
async def list_models():
    """Return model list from assets when upstream is unavailable."""
    return JSONResponse(FALLBACK_MODELS, status_code=200)


# ──────────────────────────────────────────────────────────────
#  Main entrypoint
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    from config import env

    # Allow basic runtime configuration via environment variables
    host: str = env("CHAT_SERVICE_HOST", "0.0.0.0")
    port: int = env("CHAT_SERVICE_PORT", 8000, cast=int)
    reload: bool = env("CHAT_SERVICE_RELOAD", False, cast=bool)

    uvicorn.run(app, host=host, port=port, reload=reload)
