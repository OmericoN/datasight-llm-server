import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "stable-health-v1"


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in {"/", "/health"}:
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "mode": "stable-health-only",
                    "version": VERSION,
                    "message": "DataSight DSRI practice deployment is indeed running.",
                },
            )
            return

        self._send_json(
            HTTPStatus.NOT_FOUND,
            {
                "status": "not_found",
                "mode": "stable-health-only",
                "version": VERSION,
                "message": "This practice deployment only exposes / and /health.",
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.client_address[0]} - {format % args}", flush=True)

    def _send_json(self, status: HTTPStatus, payload: dict[str, str]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), HealthHandler)

    print("DataSight stable health server is ready.", flush=True)
    print(f"Listening on {host}:{port}", flush=True)
    print(f"Version: {VERSION}", flush=True)

    server.serve_forever()


if __name__ == "__main__":
    main()
