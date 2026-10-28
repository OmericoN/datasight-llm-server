import importlib
import json
import os
import unittest
from unittest.mock import patch

import httpx

from fastapi.testclient import TestClient


class GatewayWithoutBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reload_gateway()

    def reload_gateway(self, **env: str) -> None:
        for key in (
            "LLM_BACKEND_URL",
            "LLM_BACKEND_API_KEY",
            "API_KEY",
            "API_KEYS",
            "RATE_LIMIT_REQUESTS_PER_MINUTE",
            "RATE_LIMIT_WINDOW_SECONDS",
            "MAX_COMPLETION_TOKENS",
        ):
            os.environ.pop(key, None)
        os.environ.update(env)

        import app.main

        self.gateway = importlib.reload(app.main)
        self.client = TestClient(self.gateway.app)

    def test_health_returns_ok_without_backend(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["mode"], "cpu-gateway")
        self.assertFalse(body["llm_backend_configured"])

    def test_ready_returns_ok_without_backend(self) -> None:
        response = self.client.get("/ready")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertFalse(body["llm_backend_configured"])

    def test_gpu_status_returns_unavailable_without_backend(self) -> None:
        response = self.client.get("/gpu-status")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["gpu_available"])
        self.assertFalse(body["backend_configured"])
        self.assertIn("No GPU model service is configured", body["message"])

    def test_models_returns_unavailable_metadata_without_backend(self) -> None:
        response = self.client.get("/v1/models")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["object"], "list")
        self.assertFalse(body["data"][0]["available"])
        self.assertEqual(body["mode"], "cpu-gateway")

    def test_chat_returns_503_without_backend(self) -> None:
        response = self.client.post(
            "/v1/chat/completions",
            json={
                "model": "Qwen/Qwen3.8-27B",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(
            body["detail"]["error"]["code"],
            "llm_backend_unavailable",
        )
        self.assertIn("booked DSRI GPU slot", body["detail"]["error"]["message"])

    def test_chat_requires_api_key_when_configured(self) -> None:
        self.reload_gateway(API_KEY="secret-key")

        response = self.client.post(
            "/v1/chat/completions",
            json={
                "model": "Qwen/Qwen3.8-27B",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["detail"]["error"]["code"],
            "missing_api_key",
        )

    def test_chat_accepts_api_key_query_argument(self) -> None:
        self.reload_gateway(API_KEY="secret-key")

        response = self.client.post(
            "/v1/chat/completions?api_key=secret-key",
            json={
                "model": "Qwen/Qwen3.8-27B",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"]["error"]["code"],
            "llm_backend_unavailable",
        )

    def test_models_are_rate_limited_by_api_key(self) -> None:
        self.reload_gateway(
            API_KEY="secret-key",
            RATE_LIMIT_REQUESTS_PER_MINUTE="1",
            RATE_LIMIT_WINDOW_SECONDS="60",
        )

        headers = {"x-api-key": "secret-key"}
        first = self.client.get("/v1/models", headers=headers)
        second = self.client.get("/v1/models", headers=headers)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(
            second.json()["detail"]["error"]["code"],
            "rate_limit_exceeded",
        )

    def test_usage_endpoint_requires_api_key_when_configured(self) -> None:
        self.reload_gateway(API_KEY="secret-key")

        missing_key = self.client.get("/usage")
        with_key = self.client.get("/usage", headers={"x-api-key": "secret-key"})

        self.assertEqual(missing_key.status_code, 401)
        self.assertEqual(with_key.status_code, 200)
        body = with_key.json()
        self.assertTrue(body["auth_required"])
        self.assertIn("limits", body)
        self.assertIn("totals", body)

    def test_legacy_api_keys_uses_only_first_key(self) -> None:
        self.reload_gateway(API_KEYS="first-key,second-key")

        second_key = self.client.get("/usage", headers={"x-api-key": "second-key"})
        first_key = self.client.get("/usage", headers={"x-api-key": "first-key"})

        self.assertEqual(second_key.status_code, 401)
        self.assertEqual(first_key.status_code, 200)

    def test_configured_backend_health_and_proxy(self) -> None:
        for backend_key in ("", "backend-secret"):
            with self.subTest(backend_key_configured=bool(backend_key)):
                self.reload_gateway(
                    LLM_BACKEND_URL="http://backend:8000/", API_KEY="client-secret",
                    LLM_BACKEND_API_KEY=backend_key,
                )
                seen = []
                payload = {
                    "model": self.gateway.settings.llm_model,
                    "messages": [{"role": "user", "content": "Hello"}],
                    "stream": False, "max_tokens": 128,
                    "chat_template_kwargs": {"enable_thinking": False},
                    "response_format": {"type": "json_object"},
                }
                def upstream(request):
                    seen.append(request)
                    if request.url.path == "/health":
                        return httpx.Response(200)
                    if request.url.path == "/v1/models":
                        return httpx.Response(200, json={"data": [{"id": payload["model"]}]})
                    return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

                original_client = httpx.AsyncClient
                transport = httpx.MockTransport(upstream)
                with patch.object(self.gateway.httpx, "AsyncClient", side_effect=lambda **kw: original_client(transport=transport, **kw)):
                    self.assertEqual(self.client.post("/v1/chat/completions", json=payload).status_code, 401)
                    self.assertEqual(seen, [])
                    self.assertTrue(self.client.get("/gpu-status").json()["gpu_available"])
                    headers = {"Authorization": "Bearer client-secret", "X-API-Key": "client-secret"}
                    models = self.client.get("/v1/models", headers=headers)
                    self.assertEqual(models.json()["data"][0]["id"], payload["model"])
                    response = self.client.post("/v1/chat/completions?api_key=client-secret&trace=test", json=payload, headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["choices"][0]["message"]["content"], "hello")
                sent = seen[-1]
                self.assertEqual(json.loads(sent.content), payload)
                self.assertNotIn("x-api-key", sent.headers)
                self.assertNotIn("api_key", sent.url.params)
                self.assertEqual(sent.url.params["trace"], "test")
                self.assertEqual(sent.headers.get("authorization"), f"Bearer {backend_key}" if backend_key else None)

    def test_configured_backend_unavailable_and_timeout(self) -> None:
        for error, status, code in (
            (httpx.ConnectError, 503, "llm_backend_unavailable"),
            (httpx.ReadTimeout, 504, "llm_backend_timeout"),
        ):
            with self.subTest(error=error.__name__):
                self.reload_gateway(LLM_BACKEND_URL="http://backend:8000/")
                def upstream(request):
                    raise error("synthetic failure", request=request)
                original_client = httpx.AsyncClient
                transport = httpx.MockTransport(upstream)
                with patch.object(self.gateway.httpx, "AsyncClient", side_effect=lambda **kw: original_client(transport=transport, **kw)):
                    self.assertEqual(self.client.get("/health").status_code, 200)
                    self.assertFalse(self.client.get("/gpu-status").json()["gpu_available"])
                    response = self.client.post("/v1/chat/completions", json={"messages": []})
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["detail"]["error"]["code"], code)

    def test_unhealthy_backend_status(self) -> None:
        self.reload_gateway(LLM_BACKEND_URL="http://backend:8000")
        original_client = httpx.AsyncClient
        transport = httpx.MockTransport(lambda request: httpx.Response(503, json={"error": "warming up"}))
        with patch.object(self.gateway.httpx, "AsyncClient", side_effect=lambda **kw: original_client(transport=transport, **kw)):
            status = self.client.get("/gpu-status").json()
        self.assertFalse(status["gpu_available"])
        self.assertEqual(status["backend_status_code"], 503)

    def test_chat_rejects_excessive_max_tokens(self) -> None:
        self.reload_gateway(MAX_COMPLETION_TOKENS="10")

        response = self.client.post(
            "/v1/chat/completions",
            json={
                "model": "Qwen/Qwen3.8-27B",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 100,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"]["error"]["code"],
            "max_tokens_too_large",
        )


if __name__ == "__main__":
    unittest.main()
