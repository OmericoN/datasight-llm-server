# DataSight DSRI LLM Gateway

CPU-safe FastAPI gateway for DataSight LLM requests on the Maastricht University DSRI.

This container does not run vLLM, PyTorch, CUDA checks, model downloads, or local inference. It stays deployable on CPU pods and proxies OpenAI-compatible requests only when a separate GPU/vLLM backend is configured.

## Runtime Behavior

The gateway listens on `0.0.0.0:8000`.

```text
GET  /                    Service metadata
GET  /health              DSRI health/readiness endpoint
GET  /ready               Gateway readiness endpoint
GET  /gpu-status          GPU/vLLM backend availability
GET  /usage               Gateway usage and rate-limit counters
GET  /monitoring/dashboard Dashboard-friendly usage payload
GET  /v1/models           Local unavailable model metadata, or proxy to backend
POST /v1/chat/completions Proxy to backend, or 503 if no backend is configured
```

If `LLM_BACKEND_URL` is empty, `/gpu-status` returns `gpu_available: false` and chat requests return `503 Service Unavailable`. This is intentional: CPU pods must not attempt model inference or fake answers.

## Configuration

```text
HOST=0.0.0.0
PORT=8000
SERVICE_VERSION=fastapi-gateway-v1
LLM_BACKEND_URL=
LLM_BACKEND_API_KEY=
LLM_MODEL=Qwen/Qwen2.5-32B-Instruct-AWQ
LLM_REQUEST_TIMEOUT_SECONDS=180
LLM_STATUS_TIMEOUT_SECONDS=2.0
API_KEY=
RATE_LIMIT_REQUESTS_PER_MINUTE=300
RATE_LIMIT_WINDOW_SECONDS=60
MAX_REQUEST_BODY_BYTES=1000000
MAX_MESSAGES_PER_REQUEST=50
MAX_PROMPT_CHARS=20000
MAX_COMPLETION_TOKENS=2048
```

When GPU time is booked and a separate vLLM service is running, set:

```text
LLM_BACKEND_URL=http://datasight-vllm-gpu:8000
LLM_MODEL=Qwen/Qwen2.5-32B-Instruct-AWQ
```

DataSight should keep calling the stable DSRI gateway route. If the GPU backend is unavailable, the gateway remains up and returns `503`.

## API Keys and Limits

Set `API_KEY` to one generated secret to protect expensive and monitoring endpoints:

```text
API_KEY=<secret>
```

When `API_KEY` is set, clients must send it with one of:

```text
Authorization: Bearer <secret>
X-API-Key: <secret>
?api_key=<secret>
```

The `api_key` query argument is supported for simple tools, but headers are safer because URLs can appear in logs and browser history.

Protected routes:

```text
GET  /usage
GET  /monitoring/dashboard
GET  /v1/models
POST /v1/chat/completions
```

Public low-cost routes:

```text
GET /
GET /health
GET /ready
GET /gpu-status
```

Rate limits and request caps are enforced in the gateway before proxying to vLLM. The default request limit is intentionally loose for internal UM VPN usage:

```text
RATE_LIMIT_REQUESTS_PER_MINUTE=300
RATE_LIMIT_WINDOW_SECONDS=60
MAX_REQUEST_BODY_BYTES=1000000
MAX_MESSAGES_PER_REQUEST=50
MAX_PROMPT_CHARS=20000
MAX_COMPLETION_TOKENS=2048
```

The gateway strips incoming `Authorization` and `X-API-Key` headers before proxying to the backend. If the internal vLLM backend also requires an API key, set:

```text
LLM_BACKEND_API_KEY=<backend-secret>
```

## Local Development

Install dependencies:

```bash
uv sync --frozen
```

Run locally:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 18000
```

Health check:

```bash
curl http://127.0.0.1:18000/health
```

Expected response includes:

```json
{
  "status": "ok",
  "mode": "cpu-gateway",
  "version": "fastapi-gateway-v1",
  "llm_backend_configured": false
}
```

GPU status without a backend:

```bash
curl http://127.0.0.1:18000/gpu-status
```

Expected response includes:

```json
{
  "gpu_available": false,
  "backend_configured": false,
  "mode": "cpu-gateway"
}
```

Usage dashboard payload:

```bash
curl http://127.0.0.1:18000/monitoring/dashboard \
  -H "X-API-Key: <secret>"
```

Expected response includes:

```json
{
  "status": "ok",
  "auth_required": true,
  "limits": {
    "rate_limit_requests_per_minute": 300,
    "max_completion_tokens": 2048
  },
  "totals": {}
}
```

Chat without a backend:

```bash
curl http://127.0.0.1:18000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-32B-Instruct-AWQ",
    "messages": [
      {"role": "user", "content": "Hello"}
    ]
  }'
```

Expected status: `503`.

## DSRI Deployment Settings

In the DSRI/OpenShift web UI, create the application from Git:

```text
Application name: datasight-llm-server
Git URL: https://github.com/<owner>/<repo>.git
Build strategy: Dockerfile
Dockerfile path: Dockerfile
Container port: 8000
Service port: 8000
Target port: 8000
Route: enabled
Readiness probe: HTTP GET /health on port 8000
Initial delay: 10-30s
Timeout: 10s
Period: 10s
Failure threshold: 6
```

Do not enable GPU resources on this deployment. The `datasight-llm-server` pod must not contain:

```yaml
nvidia.com/gpu: "1"
```

Use port `8000` everywhere. Do not call the external route with `:8000`; the route is HTTPS externally and forwards internally to the service target port.

After deployment, verify:

```bash
curl https://datasight-llm-server-ub-datasight.apps.dsri2.unimaas.nl/health
```

Expected logs:

```text
Starting DataSight DSRI FastAPI LLM gateway...
HOST=0.0.0.0
PORT=8000
SERVICE_VERSION=fastapi-gateway-v1
LLM_BACKEND_URL=
No local model runtime is configured for this CPU gateway.
```

## Ensuring GitHub Changes Rebuild on DSRI

In DSRI/OpenShift:

```text
Builds -> datasight-llm-server -> Details/YAML
```

Confirm:

```text
source.git.uri points to the GitHub repo
source.git.ref is main
```

Copy the GitHub webhook URL from the build configuration. Then in GitHub:

```text
Repo -> Settings -> Webhooks -> Add webhook
Payload URL: DSRI webhook URL exactly as shown
Content type: application/json
Event: Just the push event
Active: checked
```

Do not publish or commit the webhook URL because it contains a secret.

OpenShift GitHub webhooks trigger builds on push events. The pushed branch must match the BuildConfig Git ref, so pushes to another branch will not rebuild a `main` BuildConfig.

After every push, verify:

```text
Builds -> latest build is Complete
Deployment -> rollout completed
Pods -> newest pod logs show SERVICE_VERSION
Route -> /health returns the current version
```

If the webhook does not fire, manually start a build from the DSRI Builds page and then inspect the GitHub webhook delivery log.

## GPU Backend Contract

The GPU runtime belongs in a separate repository and DSRI application named `datasight-vllm-gpu`.

This repository intentionally does not include a vLLM Dockerfile, CUDA runtime, GPU deployment manifest, or `nvidia.com/gpu` resource request. Its only GPU responsibility is to proxy to the internal backend URL when configured:

```text
LLM_BACKEND_URL=http://datasight-vllm-gpu:8000
```

Operational split:

```text
datasight-llm-server
  CPU-only public gateway
  Route enabled
  Always safe to keep running
  No GPU resource request

datasight-vllm-gpu
  Separate internal GPU backend
  Route disabled
  Service name datasight-vllm-gpu
  Scaled to 0 by default
  Scaled to 1 only during booked GPU windows
```

A detailed implementation scope for the separate GPU repository is in [`docs/datasight-vllm-gpu-scope.md`](docs/datasight-vllm-gpu-scope.md).
