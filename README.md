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
LLM_MODEL=Qwen/Qwen3.8-27B
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
LLM_MODEL=Qwen/Qwen3.8-27B
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
    "model": "Qwen/Qwen3.8-27B",
    "messages": [
      {"role": "user", "content": "Hello"}
    ]
  }'
```

Expected status: `503`.

## DSRI Deployment

The current project is `ub-ub-datasight` on `https://api.dsri.unimaas.nl:6443`.
The CPU gateway uses [`dsri/gateway.yaml`](dsri/gateway.yaml): a binary Docker
BuildConfig, ImageStream, one CPU replica, private Service, and HTTPS Route.
The GPU backend is a separate application and has no public Route.

Deployed gateway:

```text
https://datasight-llm-server-ub-ub-datasight.apps.dsri.unimaas.nl
```

The older `apps.dsri2.unimaas.nl` URL is not this deployment.

Verified on 2026-10-28: CPU deployment ready; missing/incorrect keys rejected
with 401; `/gpu-status` healthy; exact schema-constrained Qwen3.8-27B inference
through HTTPS passed in 1.26 seconds (1.27 seconds after outage recovery).
A simulated unreachable backend in the deployed gateway returned health 200,
`gpu_available: false`, and chat 503 with `llm_backend_unavailable`; the real
backend URL was restored and inference passed again. The GPU was not stopped.
All 16 local tests passed, including timeout/error mapping and credential removal.

Gateway image digest:
`sha256:51127d92ad812188f5dea16c08c9c06f130052c228abb90e18a2d83b09fc1949`.
The HTTPS Route uses a 200-second
[server timeout](https://docs.redhat.com/en/documentation/openshift_container_platform/4.10/html/networking/configuring-routes#nw-configuring-route-timeouts_configuring-routes)
to accommodate the gateway's 180-second backend read timeout. Clients should
allow enough time for inference and handle backend availability changes.

### First-time API key

The deployment requires Secret `datasight-llm-server-api`, key `API_KEY`.
It has already been generated in this project. Preserve it on redeployment.
For a first deployment where this Secret does not exist, create it from PowerShell without printing its value:

```powershell
$gatewayKey = uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
@{
  apiVersion = 'v1'; kind = 'Secret'
  metadata = @{name = 'datasight-llm-server-api'}
  type = 'Opaque'; stringData = @{API_KEY = $gatewayKey}
} | ConvertTo-Json -Depth 5 | oc -n ub-ub-datasight create -f -
Remove-Variable gatewayKey
```

Never commit a Secret value or pass the API key in a URL. The deployment has no
service-account token mount and does not read OpenShift credentials at runtime.

### Build and deploy

Run these PowerShell commands from this checkout. The explicit six-file archive
excludes `.env`, credentials, virtual environments, caches and other local files.
Review `oc whoami` and existing resources first. For each code release, choose a
new image tag in both the BuildConfig output and Deployment before building;
do not overwrite a released tag. The first release is `cpu-gateway-v1`.

```powershell
uv run --frozen python -m unittest discover -s tests -v
oc -n ub-ub-datasight apply --dry-run=server -f dsri/gateway.yaml
oc -n ub-ub-datasight apply -f dsri/gateway.yaml
$gatewayContext = Join-Path $env:TEMP 'datasight-gateway-context.tar.gz'
tar -czf $gatewayContext Dockerfile entrypoint.sh pyproject.toml uv.lock app/__init__.py app/main.py
oc -n ub-ub-datasight start-build datasight-llm-server --from-archive=$gatewayContext --follow
Remove-Item -LiteralPath $gatewayContext
oc -n ub-ub-datasight rollout status deployment/datasight-llm-server --timeout=300s
oc -n ub-ub-datasight get route datasight-llm-server
```

A first deployment may be waiting to retry an image pull when its build finishes.
If the build is Complete and the pod is still in ImagePullBackOff, restart only
the gateway deployment, then wait for its rollout. Its resource requests and
limits include CPU, RAM and temporary storage; it requests no GPU or model PVC.

This binary BuildConfig does not automatically build on GitHub pushes. Build the
reviewed source archive explicitly for each release. The gateway stays at one
replica: usage counters and rate limits are in memory and reset on restart.

### Calling the gateway

Retrieve the key into a local PowerShell variable without echoing it:

```powershell
$gatewayKey = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String((oc -n ub-ub-datasight get secret datasight-llm-server-api -o jsonpath='{.data.API_KEY}')))
$gatewayUrl = 'https://datasight-llm-server-ub-ub-datasight.apps.dsri.unimaas.nl'
Invoke-RestMethod "$gatewayUrl/gpu-status"
Invoke-RestMethod "$gatewayUrl/v1/models" -Headers @{Authorization = "Bearer $gatewayKey"}
$body = @{
  model = 'Qwen/Qwen3.8-27B'
  messages = @(@{role = 'user'; content = 'Say hello in one sentence.'})
  max_tokens = 64; stream = $false
  chat_template_kwargs = @{enable_thinking = $false}
} | ConvertTo-Json -Depth 5
Invoke-RestMethod "$gatewayUrl/v1/chat/completions" -Method Post -ContentType 'application/json' -Headers @{Authorization = "Bearer $gatewayKey"} -Body $body
Remove-Variable gatewayKey
```

For an OpenAI-compatible client, use the HTTPS URL plus `/v1` as its base URL,
this Secret's key as its API key, and `Qwen/Qwen3.8-27B` as the model. Same-project
DSRI callers can use `http://datasight-llm-server:8000/v1` with the same key.
The OpenShift login token and gateway API key are different credentials.

`/gpu-status` checks backend HTTP health, not the GPU booking system. `/health`
and `/ready` deliberately remain healthy when the backend is down. Chat requests
try the backend directly: unreachable backends return `503` with
`llm_backend_unavailable`; timeouts return `504` with `llm_backend_timeout`.
An application can check availability before dispatch, but must still handle
these errors because a backend can go away after that check. There is no CPU
inference fallback, automatic GPU startup, persistent queue, or streaming flush;
the current proxy buffers responses, so use `stream: false`.

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
