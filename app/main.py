from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_version: str = "fastapi-gateway-v1"
    llm_backend_url: str = ""
    llm_model: str = "Qwen/Qwen2.5-0.5B-Instruct"
    llm_request_timeout_seconds: float = Field(default=180, gt=0)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def normalized_backend_url(self) -> str:
        return self.llm_backend_url.rstrip("/")

    @property
    def backend_configured(self) -> bool:
        return bool(self.normalized_backend_url)


settings = Settings()
app = FastAPI(title="DataSight DSRI LLM Gateway", version=settings.service_version)


def service_metadata() -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": "cpu-gateway",
        "version": settings.service_version,
        "llm_backend_configured": settings.backend_configured,
        "llm_model": settings.llm_model,
        "message": "DataSight DSRI FastAPI gateway is running.",
    }


def backend_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "error": {
                "message": "LLM backend is not configured or unavailable.",
                "type": "backend_unavailable",
                "code": "llm_backend_unavailable",
            },
            "mode": "cpu-gateway",
            "version": settings.service_version,
        },
    )


async def proxy_to_backend(path: str, method: str, request: Request) -> Response:
    if not settings.backend_configured:
        raise backend_unavailable()

    url = f"{settings.normalized_backend_url}{path}"
    body = await request.body()
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length"}
    }

    try:
        async with httpx.AsyncClient(
            timeout=settings.llm_request_timeout_seconds
        ) as client:
            upstream_response = await client.request(
                method,
                url,
                content=body or None,
                headers=headers,
                params=request.query_params,
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "error": {
                    "message": "Timed out while waiting for the LLM backend.",
                    "type": "backend_timeout",
                    "code": "llm_backend_timeout",
                },
                "mode": "cpu-gateway",
                "version": settings.service_version,
            },
        ) from exc
    except httpx.HTTPError as exc:
        raise backend_unavailable() from exc

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        media_type=upstream_response.headers.get("content-type"),
    )


@app.get("/")
async def root() -> dict[str, Any]:
    return service_metadata()


@app.get("/health")
async def health() -> dict[str, Any]:
    return service_metadata()


@app.get("/ready")
async def ready() -> dict[str, Any]:
    return service_metadata()


@app.get("/v1/models", response_model=None)
async def models(request: Request) -> Response:
    if settings.backend_configured:
        return await proxy_to_backend("/v1/models", "GET", request)

    return JSONResponse(
        {
            "object": "list",
            "data": [
                {
                    "id": settings.llm_model,
                    "object": "model",
                    "available": False,
                    "owned_by": "datasight-dsri-gateway",
                }
            ],
            "mode": "cpu-gateway",
            "version": settings.service_version,
        }
    )


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    return await proxy_to_backend("/v1/chat/completions", "POST", request)
