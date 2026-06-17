import hashlib
import json
import secrets
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_version: str = "fastapi-gateway-v1"
    llm_backend_url: str = ""
    llm_backend_api_key: str = ""
    llm_model: str = "Qwen/Qwen2.5-32B-Instruct-AWQ"
    llm_request_timeout_seconds: float = Field(default=180, gt=0)
    llm_status_timeout_seconds: float = Field(default=2.0, gt=0)
    api_keys: str = ""
    rate_limit_requests_per_minute: int = Field(default=30, gt=0)
    rate_limit_window_seconds: int = Field(default=60, gt=0)
    max_request_body_bytes: int = Field(default=1_000_000, gt=0)
    max_messages_per_request: int = Field(default=50, gt=0)
    max_prompt_chars: int = Field(default=20_000, gt=0)
    max_completion_tokens: int = Field(default=2_048, gt=0)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def normalized_backend_url(self) -> str:
        return self.llm_backend_url.rstrip("/")

    @property
    def backend_configured(self) -> bool:
        return bool(self.normalized_backend_url)

    @property
    def configured_api_keys(self) -> tuple[str, ...]:
        return tuple(
            key.strip() for key in self.api_keys.split(",") if key.strip()
        )

    @property
    def auth_required(self) -> bool:
        return bool(self.configured_api_keys)


settings = Settings()
app = FastAPI(title="DataSight DSRI LLM Gateway", version=settings.service_version)


class UsageStore:
    def __init__(self) -> None:
        self.started_at = time.time()
        self._lock = Lock()
        self._request_times: dict[str, deque[float]] = defaultdict(deque)
        self._totals: dict[str, int] = defaultdict(int)
        self._by_endpoint: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self._by_client: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )

    def check_rate_limit(self, client_id: str) -> int | None:
        now = time.time()
        window_start = now - settings.rate_limit_window_seconds
        with self._lock:
            timestamps = self._request_times[client_id]
            while timestamps and timestamps[0] <= window_start:
                timestamps.popleft()

            if len(timestamps) >= settings.rate_limit_requests_per_minute:
                retry_after = int(
                    settings.rate_limit_window_seconds - (now - timestamps[0])
                )
                return max(retry_after, 1)

            timestamps.append(now)
            return None

    def record(self, endpoint: str, client_id: str, outcome: str) -> None:
        with self._lock:
            self._totals["requests_total"] += 1
            self._totals[f"{outcome}_total"] += 1
            self._by_endpoint[endpoint]["requests_total"] += 1
            self._by_endpoint[endpoint][f"{outcome}_total"] += 1
            self._by_client[client_id]["requests_total"] += 1
            self._by_client[client_id][f"{outcome}_total"] += 1

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            active_windows = {
                client_id: len(timestamps)
                for client_id, timestamps in self._request_times.items()
            }
            return {
                "status": "ok",
                "mode": "cpu-gateway",
                "version": settings.service_version,
                "started_at_unix": self.started_at,
                "uptime_seconds": round(now - self.started_at, 3),
                "auth_required": settings.auth_required,
                "backend_configured": settings.backend_configured,
                "llm_model": settings.llm_model,
                "limits": {
                    "rate_limit_requests_per_minute": (
                        settings.rate_limit_requests_per_minute
                    ),
                    "rate_limit_window_seconds": settings.rate_limit_window_seconds,
                    "max_request_body_bytes": settings.max_request_body_bytes,
                    "max_messages_per_request": settings.max_messages_per_request,
                    "max_prompt_chars": settings.max_prompt_chars,
                    "max_completion_tokens": settings.max_completion_tokens,
                },
                "active_rate_limit_windows": active_windows,
                "totals": dict(self._totals),
                "by_endpoint": {
                    endpoint: dict(counts)
                    for endpoint, counts in self._by_endpoint.items()
                },
                "by_client": {
                    client_id: dict(counts)
                    for client_id, counts in self._by_client.items()
                },
            }


usage_store = UsageStore()


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
                "message": (
                    "GPU model service is not configured or unavailable. "
                    "Please try again during a booked DSRI GPU slot."
                ),
                "type": "backend_unavailable",
                "code": "llm_backend_unavailable",
            },
            "mode": "cpu-gateway",
            "version": settings.service_version,
        },
    )


def extract_api_key(request: Request) -> str:
    header_key = request.headers.get("x-api-key", "").strip()
    if header_key:
        return header_key

    authorization = request.headers.get("authorization", "").strip()
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token.strip()

    return request.query_params.get("api_key", "").strip()


def client_label(request: Request, api_key: str = "") -> str:
    if api_key:
        digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]
        return f"key:{digest}"

    if request.client and request.client.host:
        return f"ip:{request.client.host}"

    return "ip:unknown"


def authenticate_request(request: Request) -> str:
    api_key = extract_api_key(request)
    allowed_keys = settings.configured_api_keys

    if not allowed_keys:
        return client_label(request, api_key)

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Missing API key.",
                    "type": "authentication_error",
                    "code": "missing_api_key",
                }
            },
        )

    if not any(secrets.compare_digest(api_key, key) for key in allowed_keys):
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Invalid API key.",
                    "type": "authentication_error",
                    "code": "invalid_api_key",
                }
            },
        )

    return client_label(request, api_key)


def enforce_rate_limit(client_id: str) -> None:
    retry_after = usage_store.check_rate_limit(client_id)
    if retry_after is None:
        return

    raise HTTPException(
        status_code=429,
        headers={"Retry-After": str(retry_after)},
        detail={
            "error": {
                "message": "Rate limit exceeded.",
                "type": "rate_limit_exceeded",
                "code": "rate_limit_exceeded",
            },
            "retry_after_seconds": retry_after,
        },
    )


def authorize_metered_request(
    request: Request, endpoint: str, *, record_accepted: bool = True
) -> str:
    try:
        client_id = authenticate_request(request)
    except HTTPException:
        usage_store.record(endpoint, "unauthenticated", "auth_rejected")
        raise

    try:
        enforce_rate_limit(client_id)
    except HTTPException:
        usage_store.record(endpoint, client_id, "rate_limited")
        raise

    if record_accepted:
        usage_store.record(endpoint, client_id, "accepted")
    return client_id


def prompt_char_count(value: Any) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(prompt_char_count(item) for item in value)
    if isinstance(value, dict):
        return sum(prompt_char_count(item) for item in value.values())
    return 0


async def validate_chat_request(request: Request) -> None:
    body = await request.body()
    if len(body) > settings.max_request_body_bytes:
        raise HTTPException(
            status_code=413,
            detail={
                "error": {
                    "message": "Request body is too large.",
                    "type": "request_too_large",
                    "code": "request_body_too_large",
                },
                "max_request_body_bytes": settings.max_request_body_bytes,
            },
        )

    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "Request body must be valid JSON.",
                    "type": "invalid_request_error",
                    "code": "invalid_json",
                }
            },
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "Request body must be a JSON object.",
                    "type": "invalid_request_error",
                    "code": "invalid_json_object",
                }
            },
        )

    messages = payload.get("messages", [])
    if isinstance(messages, list) and len(messages) > settings.max_messages_per_request:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "Too many chat messages in one request.",
                    "type": "invalid_request_error",
                    "code": "too_many_messages",
                },
                "max_messages_per_request": settings.max_messages_per_request,
            },
        )

    if prompt_char_count(messages) > settings.max_prompt_chars:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "Prompt is too large.",
                    "type": "invalid_request_error",
                    "code": "prompt_too_large",
                },
                "max_prompt_chars": settings.max_prompt_chars,
            },
        )

    max_tokens = payload.get("max_tokens")
    if isinstance(max_tokens, int) and max_tokens > settings.max_completion_tokens:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "Requested max_tokens exceeds the gateway limit.",
                    "type": "invalid_request_error",
                    "code": "max_tokens_too_large",
                },
                "max_completion_tokens": settings.max_completion_tokens,
            },
        )


async def gpu_status_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "gpu_available": False,
        "backend_configured": settings.backend_configured,
        "mode": "cpu-gateway",
        "version": settings.service_version,
        "llm_model": settings.llm_model,
    }

    if not settings.backend_configured:
        payload["message"] = (
            "No GPU model service is configured for this DSRI app. "
            "Book GPU time and set LLM_BACKEND_URL to the internal vLLM service."
        )
        return payload

    health_url = f"{settings.normalized_backend_url}/health"
    try:
        async with httpx.AsyncClient(
            timeout=settings.llm_status_timeout_seconds
        ) as client:
            response = await client.get(health_url)
    except httpx.HTTPError:
        payload["message"] = (
            "GPU model service is configured but not currently reachable."
        )
        return payload

    payload["backend_status_code"] = response.status_code
    if 200 <= response.status_code < 300:
        payload["gpu_available"] = True
        payload["message"] = "GPU model service is available."
        return payload

    payload["message"] = (
        "GPU model service is configured but did not report healthy status."
    )
    return payload


async def proxy_to_backend(path: str, method: str, request: Request) -> Response:
    if not settings.backend_configured:
        raise backend_unavailable()

    url = f"{settings.normalized_backend_url}{path}"
    body = await request.body()
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length", "x-api-key", "authorization"}
    }
    params = [
        (key, value)
        for key, value in request.query_params.multi_items()
        if key.lower() != "api_key"
    ]
    if settings.llm_backend_api_key:
        headers["authorization"] = f"Bearer {settings.llm_backend_api_key}"

    try:
        async with httpx.AsyncClient(
            timeout=settings.llm_request_timeout_seconds
        ) as client:
            upstream_response = await client.request(
                method,
                url,
                content=body or None,
                headers=headers,
                params=params,
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


@app.get("/gpu-status")
async def gpu_status() -> dict[str, Any]:
    return await gpu_status_payload()


@app.get("/usage")
async def usage(request: Request) -> dict[str, Any]:
    authorize_metered_request(request, "/usage")
    return usage_store.snapshot()


@app.get("/monitoring/dashboard")
async def monitoring_dashboard(request: Request) -> dict[str, Any]:
    authorize_metered_request(request, "/monitoring/dashboard")
    return usage_store.snapshot()


@app.get("/v1/models", response_model=None)
async def models(request: Request) -> Response:
    authorize_metered_request(request, "/v1/models")
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
    client_id = authorize_metered_request(
        request, "/v1/chat/completions", record_accepted=False
    )
    try:
        await validate_chat_request(request)
    except HTTPException:
        usage_store.record(
            "/v1/chat/completions",
            client_id,
            "validation_rejected",
        )
        raise

    usage_store.record("/v1/chat/completions", client_id, "accepted")
    return await proxy_to_backend("/v1/chat/completions", "POST", request)
