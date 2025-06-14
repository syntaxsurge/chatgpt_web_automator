# ChatGPT Web Automator – UID‑driven Async Edition

**⚠️ Educational‑purpose notice**
This repository showcases a headless‑browser bridge that turns the public ChatGPT UI into a drop‑in, OpenAI‑compatible API.
It is for learning and experimentation only and may violate future Terms of Service; use at your own risk.

---

1. [Key Features](#key-features)  
2. [How It Works](#how-it-works)
3. [Project Layout](#project-layout)
4. [Environment Variables](#environment-variables)  
5. [HTTP API](#http-api)
6. [End‑to‑End Example](#end-to-end-example)
7. [Concurrency Model](#concurrency-model)
8. [FAQ](#faq)
9. [License](#license)

---

## Key Features

* **Zero‑wait browser submits** – Chrome types the prompt, hits send, **immediately extracts the conversation ID** and frees the page for the next job.
* **Deterministic UID mapping** – every request is tagged with a freshly generated `uChatId` that the assistant echoes back, giving an unbreakable mapping between your queue IDs and ChatGPT IDs.
* **Asynchronous backend polling** – a standalone client checks `/backend-api/conversation/<chat_id>` every second (up to two hours) until the newest node reports `finished_successfully`.
* **Single‑browser queue** – unlimited HTTP clients share one Chrome instance via a lock; the lock is held **only** while acquiring the chat ID.
* **OpenAI‑compatible JSON** – `/v1/chat/completions` and `/v1/models` mirror the official schema so existing SDKs work out of the box.
* **Robust error detection & retry** – network and length errors are classified and optionally retried without human intervention.
* **Token accounting** – prompt and completion tokens are counted with `tiktoken` for budget tracking.
* **Human‑like typing modes** – `normal`, `fast`, or clipboard `paste` with adjustable delays.

---

## How It Works

### Request life‑cycle

1. **Client POSTs** to `/v1/chat/completions` with a standard OpenAI chat payload.
2. The FastAPI handler:
   * Flattens `messages` to plain text.
   * Generates a UUID **U** and appends
     `<chatName="Request" uChatId="U"/>`
     to the prompt.
3. The prompt is dispatched to the **BrowserSessionPool**.
4. The pool’s **BrowserSession** acquires the lock, opens *https://chatgpt.com/?model=…*, types the prompt, presses **Send**, waits (≤ 10 s) for the URL to redirect to `/c/<chat_id>`, then **releases the lock**.
5. The mapping `U=<chat_id>` is printed to stdout (or your preferred log sink).
6. In parallel, the session’s **ChatBackendClient** starts polling
   *https://chatgpt.com/backend-api/conversation/<chat_id>*
   every second until the latest node satisfies:
   * `status == finished_successfully`
   * `author.role == assistant`
   * non‑empty text
7. When ready, the assistant text is wrapped in an OpenAI‑style JSON body and returned to the original HTTP caller.

Because steps 4 → 7 happen off‑browser, new API requests can start while earlier ones are still being polled.

---

## Project Layout

| Path | Purpose |
| --- | --- |
| `api/chat_service.py` | FastAPI entry‑point implementing OpenAI routes. |
| `orchestrator/browser_pool.py` | Singleton pool that guarantees **one** Chrome instance. |
| `orchestrator/browser_session.py` | Owns the browser tab and the asynchronous backend poller. |
| `automator/web_automator.py` | Selenium helper: open page, type, hit send, grab chat ID. |
| `utils/chat_backend.py` | Thin client for the undocumented `/backend-api/conversation` endpoint. |
| `utils/errors.py` | Classifies ChatGPT UI error bubbles. |
| `utils/tokenization.py` | Counts tokens via `tiktoken`. |
| `assets/fallback_models.json` | Static model list for `/v1/models`. |
| `tests/backend_api.py` | Smoke test for direct backend polling. |

---

## Environment Variables

| Key | Description | Default |
| --- | --- | --- |
| `CHROME_PROFILE_DIR` | User‑data dir for Chrome. | `chromedata` |
| `HEADLESS_CHROME` | Launch Chrome with `--headless=new`. | `false` |
| `AUTO_LOGIN` | Scripted login using `CHATGPT_EMAIL/PASSWORD`. | `false` |
| `TYPING_MODE` | `normal` \| `fast` \| `paste`. | `normal` |
| `HUMAN_KEY_DELAY_MIN/MAX` | Per‑character delay range (s) in `normal` mode. | `0.08 / 0.30` |
| `POLL_INTERVAL` | Seconds between backend polls. | `0.20` |
| `NETWORK_ERROR_RETRIES` | Automatic retries for ChatGPT network errors. | `3` |
| `OPENAI_AUTH_TOKEN` | **Required.** Bearer token for backend API calls. | – |
| `ENABLE_DEBUG` | Verbose logging of every step. | `false` |
| `CHAT_SERVICE_HOST/PORT` | Bind host & port for FastAPI. | `0.0.0.0 / 8000` |

Copy `.env.example` to `.env` and adjust as needed.

---

## HTTP API

### POST `/v1/chat/completions`

Minimal viable payload:

~~~json
{
  "model": "o3-pro",
  "messages": [
    {"role": "user", "content": "Hello, world!"}
  ]
}
~~~

**Rules**

* `stream` must be `false` (streaming not supported).
* `temperature`, `top_p`, etc. are ignored.
* Replies arrive once the backend reports success; typical latency equals ChatGPT typing time + polling interval.

### GET `/v1/models`

Returns the JSON in `assets/fallback_models.json`.

---

## End‑to‑End Example

~~~bash
# Launch server (assumes virtualenv activated and .env configured)
python -m api.chat_service
~~~

In another shell:

~~~bash
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"o3","messages":[{"role":"user","content":"Write a haiku about sunrise"}]}' | jq
~~~

Log output will include a line like:

~~~text
3f4c2c2b-7d87-4f56-b471-1d8fcd746b6d=684d025a-04ac-8003-8141-ea8646a18850
~~~

showing the UUID ⇒ ChatGPT conversation ID mapping.

---

## Concurrency Model

* **Browser lock scope**: *only* from page load → conversation ID detection.
* **Backend polling**: fully parallel across requests via `asyncio.to_thread`.
* **Failure handling**:
  * network errors → configurable retry
  * length errors → propagate as JSON error
  * two‑hour absolute timeout per request
* **Scalability tips**: run multiple API instances behind a reverse proxy to shard load; each instance maintains one Chrome.

---

## FAQ

**Is this free?**
No. You still pay with your ChatGPT account; this merely automates the UI.

**Does the assistant really echo my `uChatId`?**
Yes – the tag is injected in the prompt you send, and models reliably reproduce it verbatim.

**Can I enable streaming?**
Not yet; the project waits for `finished_successfully` to ensure consistency.

---

## License

MIT – see `LICENSE` for full text.