# ChatGPT Web Automator

**⚠️ Educational-purpose notice**  
This repository demonstrates browser-based scraping and an OpenAI-compatible proxy API **for learning only**.
Using it against the official ChatGPT site may violate future Terms of Service and could place your OpenAI/ChatGPT account at risk.
No warranty is provided; proceed at your own discretion.

---

1. [Key Features](#key-features)  
2. [High-level Architecture](#high-level-architecture)  
3. [Directory & File Overview](#directory--file-overview)
4. [Environment Variables](#environment-variables)  
5. [HTTP API Schema](#http-api-schema)  
   1. [POST /v1/chat/completions](#v1chatcompletions-post)  
      1. [Success Response (200)](#success-response-200)  
   2. [GET /v1/models](#v1models-get)  
6. [Payload & cURL Examples](#payload--curl-examples)
   1. [Basic chat completion](#basic-chat-completion)  
   2. [Retrieve model list](#retrieve-model-list)  
7. [Integrating into Your Codebase](#integrating-into-your-codebase)  
8. [Running & Deployment Guide](#running--deployment-guide)
9. [Queueing & Concurrency Model](#queueing--concurrency-model)
10. [Tokenisation Utility](#tokenisation-utility)  
11. [FAQ](#faq)  
12. [License](#license)

---

## Key Features

* **Browser automation** – controls a persistent or headless Chrome profile via Selenium & undetected-chromedriver.
* **OpenAI-style proxy** – exposes **/v1/chat/completions** & **/v1/models** so existing OpenAI SDK clients *just work*.
* **Prompt manipulation modes** – delete/keep/merge behaviour for `system` messages configured through `SYSTEM_PROMPT_MODE`.
* **Automatic network-error retry** – configurable via `NETWORK_ERROR_RETRIES`; backed by robust error-type detection.
* **Token accounting** – server-side usage stats via `tiktoken`.
* **Single-browser queue** – serialises concurrent FastAPI requests onto **one** shared Chrome instance for resource efficiency.
* **Human-like typing modes** – `normal`, `fast` or clipboard `paste`, with per-char delay ranges and chunked pasting.
* **CLI utility** – interactive shell in `main.py` for quick manual tests.

---

## High-level Architecture

1. **FastAPI server** receives OpenAI-compatible JSON.
2. Request is **flattened** to plain prompt text and forwarded to **BrowserSessionPool**.
3. `BrowserSessionPool` guarantees exactly one `BrowserSession` exists and dispatches work.
4. `BrowserSession` drives `ChatGPTWebAutomator` which chats with **chat.openai.com**.
5. Reply is streamed back, token usage is calculated, and a compatible response JSON is returned to the client.

---

## Directory & File Overview

| Path | Purpose |
| --- | --- |
| `main.py` | Interactive CLI harness around `ChatGPTWebAutomator`. |
| `config.py` | Environment helpers; loads `.env`, exposes `env()`, `ROOT_DIR`, and debug flag. |
| `api/chat_service.py` | FastAPI app exposing OpenAI-style routes; entry-point `python -m api.chat_service`. |
| `orchestrator/browser_pool.py` | Lazy singleton `BrowserSessionPool`; queues all conversations. |
| `orchestrator/browser_session.py` | Wraps one Chrome tab; locks per prompt, handles retries & error classification. |
| `automator/web_automator.py` | Selenium wrapper that performs typing, streaming detection, and Markdown extraction. |
| `automator/locators.py` | Centralised XPath/CSS selectors for ChatGPT UI. |
| `utils/tokenization.py` | Thin wrapper around `tiktoken` for counting prompt & completion tokens. |
| `utils/errors.py` | Detects ChatGPT error bubbles and classifies them (`network`, `length`, etc.). |
| `assets/fallback_models.json` | Static model list for `/v1/models` when upstream is unreachable. |
| `requirements.txt` | Runtime dependencies – Selenium, FastAPI, undetected-chromedriver, etc. |
| `.env.example` | Sample environment; copy to `.env` and tweak values. |

---

## Environment Variables

All settings are consumed via `config.env(...)`; see `.env.example` for defaults.

| Key | Description | Default |
| --- | --- | --- |
| `CHROME_PROFILE_DIR` | Path to Chrome user-data dir (persistent cookies, history). | `chromedata` |
| `HEADLESS_CHROME` | Run with `--headless=new`. | false |
| `AUTO_LOGIN` | Enable scripted login using credentials below. | false |
| `CHATGPT_EMAIL`, `CHATGPT_PASSWORD` | Only used when `AUTO_LOGIN=true`. | – |
| `EXPLICIT_WAIT_TIMEOUT` | Selenium explicit-wait seconds. | 15 |
| `TYPING_MODE` | `normal` \| `fast` \| `paste`; affects input speed. | normal |
| `HUMAN_KEY_DELAY_MIN` | Minimum per-char delay in `normal` mode (s). | 0.08 |
| `HUMAN_KEY_DELAY_MAX` | Maximum per-char delay in `normal` mode (s). | 0.30 |
| `STREAM_SETTLE_TIME` | Stable time window before a reply is considered complete (s). | 0.8 |
| `POLL_INTERVAL` | Polling interval while waiting for stream completion (s). | 0.20 |
| `PASTE_CHUNK_SIZE` | Clipboard chunk size when pasting long prompts. | 50000 |
| `SYSTEM_PROMPT_MODE` | How to treat `system` messages (`delete`\|`keep`\|`merge*`). | merge_post_meta |
| `NETWORK_ERROR_RETRIES` | Automatic retry count for ChatGPT *network error*. | 3 |
| `CHAT_SERVICE_HOST`, `CHAT_SERVICE_PORT` | Bind host / port for FastAPI. | 127.0.0.1 / 8000 |
| `CHAT_SERVICE_RELOAD` | Hot-reload server code for development. | false |
| `ENABLE_DEBUG` | Verbose logging for every request/response. | false |

---

## HTTP API Schema

### /v1/chat/completions POST <a id="v1chatcompletions-post"></a>

Accepts a subset of the OpenAI chat schema.

~~~json
{
  "model": "gpt-4o",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user",   "content": "Hello world!"}
  ],
  "stream": false
}
~~~

**Important deviations**

* `temperature`, `top_p`, etc. are silently ignored.
* `stream` must be **false** (streaming not supported).

#### Success Response (200) <a id="success-response-200"></a>

~~~json
{
  "id": "chatcmpl-abc123...",
  "object": "chat.completion",
  "created": 1714720000,
  "model": "gpt-4o",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "Hi there 👋"},
      "logprobs": null,
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 13,
    "completion_tokens": 4,
    "total_tokens": 17
  }
}
~~~

### /v1/models GET <a id="v1models-get"></a>

Returns the static contents of `assets/fallback_models.json`.

---

## Payload & cURL Examples

### Basic chat completion

~~~bash
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{
           "model": "gpt-4o",
           "messages": [
             {"role": "user", "content": "Write a haiku about sunrise"}
           ]
         }'
~~~

### Retrieve model list

~~~bash
curl http://127.0.0.1:8000/v1/models | jq
~~~

---

## Integrating into Your Codebase

Most OpenAI client libraries allow a base-URL override:

~~~python
import openai
openai.api_key = "FAKE"
openai.base_url = "http://127.0.0.1:8000/v1"

chat = openai.ChatCompletion.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Ping?"}]
)
print(chat.choices[0].message.content)
~~~

Because the proxy mirrors OpenAI’s schema, you can reuse existing retry/backoff logic, tool-calling, etc., as long as you respect the deviations noted above.

---

## Running & Deployment Guide

1. **Install dependencies** (Python ≥ 3.11 recommended):

   ~~~bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ~~~

2. **Create `.env`** – copy from `.env.example` and adjust as needed.
3. **Launch FastAPI server**:

   ~~~bash
   python -m api.chat_service            # production
   # or
   uvicorn api.chat_service:app --reload --host 0.0.0.0 --port 8000
   ~~~

4. **Optional CLI test**:

   ~~~bash
   python main.py
   ~~~

*Docker* support is intentionally omitted to keep the example lean; contributions welcome.

---

## Queueing & Concurrency Model

All incoming HTTP requests are serialised onto a **BrowserSessionPool**:

* `BrowserSessionPool` lazily instantiates **one** `BrowserSession`.
* Each `BrowserSession` contains a re-entrant `threading.Lock`.
* FastAPI requests run in worker threads via `anyio.to_thread.run_sync`; they block on the lock to ensure only one prompt is active in the UI at a time.
* This design minimises memory footprint (one Chrome) while guaranteeing reply accuracy (no cross-conversation bleed).
* `utils/errors.detect_error` classifies UI bubbles so browser-level errors propagate as structured JSON.

If you expect very high throughput, you could shard by `model` or spin up multiple processes behind a load-balancer.

---

## Tokenisation Utility

`utils/tokenization.py` wraps `tiktoken` to count tokens for arbitrary models:

~~~python
from utils.tokenization import num_tokens
print(num_tokens("Hello world", model="gpt-4o"))  # → 3
~~~

The helper falls back to `cl100k_base` when an unknown model is supplied.

---

## FAQ

**Why not use the official OpenAI API?**
This project is purely educational—use the official API for production workloads.

**Does this bypass rate limits or paid usage?**
No. You still need a ChatGPT account and are bound by OpenAI’s Terms of Service.

**Can I enable streaming?**
Not currently; the implementation would require response chunking and SSE support.

---

## License

MIT License. See `LICENSE` file for full text.