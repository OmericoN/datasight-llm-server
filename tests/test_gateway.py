import importlib
import os
import unittest

from fastapi.testclient import TestClient


class GatewayWithoutBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.pop("LLM_BACKEND_URL", None)
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


if __name__ == "__main__":
    unittest.main()
