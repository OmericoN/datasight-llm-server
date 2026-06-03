from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="DataSight LLM Server Fallback")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "datasight-fallback"
    messages: list[ChatMessage] = []


@app.get("/")
def root():
    return {
        "status": "ok",
        "mode": "fallback",
        "message": "DataSight DSRI server is running, but CUDA/GPU is not available.",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "mode": "fallback",
        "message": "Health check passed. No model is currently running.",
    }


@app.post("/v1/chat/completions")
def chat_completions(request: ChatCompletionRequest):
    user_messages = [msg.content for msg in request.messages if msg.role == "user"]
    latest_message = user_messages[-1] if user_messages else ""

    return {
        "id": "chatcmpl-datasight-fallback",
        "object": "chat.completion",
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": (
                        "DataSight DSRI fallback server is working. "
                        "CUDA/GPU is not available, so the real model was not started. "
                        f"Received message: {latest_message}"
                    ),
                },
                "finish_reason": "stop",
            }
        ],
    }
