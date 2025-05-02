from fastapi import FastAPI
from pydantic import BaseModel

from orchestrator.browser_pool import BrowserSessionPool
from anyio import to_thread

app = FastAPI()
browser_pool = BrowserSessionPool()


class ChatRequest(BaseModel):
    prompt: str
    model: str | None = None   # e.g. "o3"


class ChatResponse(BaseModel):
    browser_id: str
    answer: list[str]


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    POST /chat
    ----------
    JSON body:
        {
            "prompt": "Why is the sky blue?",
            "model" : "o3"          # optional – defaults to ChatGPT’s default
        }
    """
    result = await to_thread.run_sync(
        browser_pool.ask, request.prompt, request.model
    )
    return ChatResponse(**result)