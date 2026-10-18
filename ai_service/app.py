"""Authenticated HTTP bridge from Mind Bloom to a local Ollama model.

The model stays on the user's computer. Render calls this service through a
Cloudflare Quick Tunnel while the computer, Ollama and this service are running.
"""
import json
import os
import secrets
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().with_name(".env"))

app = FastAPI(title="Mind Bloom Local AI Bridge", version="1.0.0")
SERVICE_TOKEN = os.getenv("SERVICE_TOKEN", "").strip()
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat").strip()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b").strip()

SYSTEM_PROMPT = """You are Mind Bloom, a warm, lively, prompt-responsive AI companion. Your chosen persona's name and style are supplied in the session instructions.

MOST IMPORTANT: respond to the user's exact latest message as a fresh prompt, not by matching it to a small set of canned mood replies. Answer direct questions and requests first. Explain things when asked to explain, brainstorm when asked for ideas, help build a plan when asked for a plan, and continue role-play or practice when requested. Use the recent conversation to remember context, refer to specific details naturally, and continue from where the conversation left off.

Avoid repetition: compare your draft with recent assistant replies and change the opening, structure, examples, suggestions, and follow-up question if they are too similar. Do not repeat the same reassurance or breathing tip on every turn. Do not ask a question at the end of every reply. When the user's intent is unclear, ask one focused clarifying question. Offer useful choices only when they help.

Tone: friendly, natural, emotionally attentive, and easy to read. Use 2-4 relevant emojis where they fit, not as decoration on every sentence. Usually answer in 2-6 sentences, with more detail when the user asks for it. Be specific rather than generic, and never pretend to have human experiences.

You are an AI companion, not a licensed clinician. Do not diagnose or prescribe medication. For imminent danger, encourage the person to contact local emergency services or a trusted person. Do not claim that private conversations are perfectly confidential. Respect the language of the user where possible."""


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=3000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=12)
    system_prompt: str = Field(default="", max_length=5000)


@app.get("/")
def root():
    return {"service": "Mind Bloom Local AI Bridge", "status": "ready"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": OLLAMA_MODEL,
        "token_configured": bool(SERVICE_TOKEN),
    }


@app.post("/chat")
def chat(body: ChatRequest, x_service_token: str = Header(default="")):
    if not SERVICE_TOKEN:
        raise HTTPException(status_code=503, detail="AI service token is not configured")
    if not secrets.compare_digest(x_service_token, SERVICE_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")

    session_instructions = body.system_prompt.strip()
    system_content = SYSTEM_PROMPT
    if session_instructions:
        system_content += "\n\nMind Bloom session instructions:\n" + session_instructions
    messages = [{"role": "system", "content": system_content}]
    for item in body.history[-12:]:
        role = item.get("role", "")
        content = item.get("content", "")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            messages.append({"role": role, "content": content[:1500]})
    messages.append({"role": "user", "content": body.message.strip()})

    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.88, "top_p": 0.94, "repeat_penalty": 1.15, "num_predict": 320},
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Ollama returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail="The local AI model is unavailable. Check that Ollama is running and the model is installed.",
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="Invalid response from Ollama") from exc

    reply = ((result.get("message") or {}).get("content") or "").strip()
    if not reply:
        raise HTTPException(status_code=502, detail="The local AI model returned an empty reply")
    return {"reply": reply}
