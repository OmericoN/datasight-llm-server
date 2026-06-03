# DataSight DSRI LLM Gateway

CPU-safe FastAPI gateway for DataSight LLM requests on the Maastricht University DSRI.

This container does not run vLLM, PyTorch, CUDA checks, model downloads, or local inference. It stays deployable on CPU pods and proxies OpenAI-compatible requests only when a separate GPU/vLLM backend is configured.

## Runtime Behavior

The gateway listens on `0.0.0.0:8000`.

```text
GET  /                    Service metadata
GET  /health              DSRI health/readiness endpoint
GET  /ready               Gateway readiness endpoint
GET  /v1/models           Local unavailable model metadata, or proxy to backend
POST /v1/chat/completions Proxy to backend, or 503 if no backend is configured
```

If `LLM_BACKEND_URL` is empty, chat requests return `503 Service Unavailable`. This is intentional: CPU pods must not attempt model inference or fake answers.

## Configuration

```text
HOST=0.0.0.0
PORT=8000
SERVICE_VERSION=fastapi-gateway-v1
LLM_BACKEND_URL=
LLM_MODEL=Qwen/Qwen2.5-0.5B-Instruct
LLM_REQUEST_TIMEOUT_SECONDS=180
```

When GPU time is booked and a separate vLLM service is running, set:

```text
LLM_BACKEND_URL=http://<gpu-vllm-service-name>:8000
```

DataSight should keep calling the stable DSRI gateway route. If the GPU backend is unavailable, the gateway remains up and returns `503`.

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

Chat without a backend:

```bash
curl http://127.0.0.1:18000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-0.5B-Instruct",
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

## GPU/vLLM Follow-Up

Keep this CPU gateway separate from the GPU model runtime.

When DSRI GPU time is booked:

```text
1. Deploy a separate GPU-backed vLLM service/pod.
2. Set LLM_BACKEND_URL on this gateway to the internal vLLM service URL.
3. Restart/roll out only the gateway config.
4. Keep DataSight pointed at the gateway route.
```

This avoids CPU pods trying to run the model and keeps `/health` available even when GPU scheduling is unavailable.
