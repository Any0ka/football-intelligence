"""Local server of the app: the static page plus the AI assistant.

python -m app.server            -> http://127.0.0.1:8200

The page itself is static and also works from GitHub Pages or `python -m http.server`; only the assistant needs
this server, because the API key must stay on the server (.env, never in the browser).
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import assistant as ai

WEB = ai.ROOT / "app" / "web"
app = FastAPI(title="Football Intelligence", docs_url=None, redoc_url=None)


@app.get("/api/ai")
def ai_status():
    return {"enabled": ai.enabled(), "model": ai.MODEL, "web_search": ai.WEB_SEARCH}


class ChatIn(BaseModel):
    chat_id: Optional[str] = None
    message: str = Field(..., min_length=1, max_length=ai.MAX_MESSAGE)
    state: Dict[str, Any] = Field(default_factory=dict)      # what the page shows: club, tab, slot, filters...


@app.post("/api/chat")
def chat_api(body: ChatIn, request: Request):
    who = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")
    why = ai.refusal(who)
    if why:
        raise HTTPException(429, why)
    s = ai.session(body.chat_id)

    def events():
        if not s.lock.acquire(blocking=False):
            yield _sse({"type": "error", "message": "Предыдущий ответ ещё пишется."})
            return
        try:
            for ev in ai.chat(s, body.state, body.message.strip()):
                yield _sse(ev)
        finally:
            s.lock.release()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(ev: dict) -> str:
    return "data: " + json.dumps(ev, ensure_ascii=False) + "\n\n"


app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")      # after the API routes


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("FI_HOST", "127.0.0.1"), port=int(os.getenv("FI_PORT", "8200")))
