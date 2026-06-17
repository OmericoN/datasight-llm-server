import importlib
import os
import unittest

from fastapi.testclient import TestClient


class GatewayWithoutBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reload_gateway()

    def reload_gateway(self, **env: str) -> None:
        for key in (
            "LLM_BACKEND_URL",
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
                "model": "Qwen/Qwen2.5-32B-Instruct-AWQ",
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
                "model": "Qwen/Qwen2.5-32B-Instruct-AWQ",
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
                "model": "Qwen/Qwen2.5-32B-Instruct-AWQ",
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

    def test_chat_rejects_excessive_max_tokens(self) -> None:
        self.reload_gateway(MAX_COMPLETION_TOKENS="10")

        response = self.client.post(
            "/v1/chat/completions",
            json={
                "model": "Qwen/Qwen2.5-32B-Instruct-AWQ",
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
