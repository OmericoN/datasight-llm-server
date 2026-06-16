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
LLM_MODEL=Qwen/Qwen2.5-32B-Instruct-AWQ
LLM_REQUEST_TIMEOUT_SECONDS=180
LLM_STATUS_TIMEOUT_SECONDS=2.0
```

When GPU time is booked and a separate vLLM service is running, set:

```text
LLM_BACKEND_URL=http://datasight-vllm-gpu:8000
LLM_MODEL=Qwen/Qwen2.5-32B-Instruct-AWQ
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

This repo includes optional GPU backend artifacts:

```text
gpu/Dockerfile                 Separate vLLM image for GPU deployment only
gpu/entrypoint-vllm.sh         Starts vLLM with a configurable model
dsri/vllm-gpu-pvc.yaml         Reference PVC for persistent Hugging Face cache
dsri/vllm-gpu-deployment.yaml  Reference GPU deployment with /hf-cache mount
dsri/vllm-gpu-service.yaml     Internal service used by the CPU gateway
```

The root `Dockerfile` remains the always-on CPU gateway. It should not request `nvidia.com/gpu`, import CUDA libraries, load models, or run vLLM. The GPU backend uses `gpu/Dockerfile` and should be deployed only when DSRI GPU booking/resources are available, so vLLM, PyTorch, CUDA, and model downloads are not added to the always-on gateway image.

### Persistent Model Cache

Create a DSRI Persistent Volume Claim before deploying the GPU backend:

```text
PVC name: pvc-datasight-hf-cache
Storage class: ocs-storagecluster-cephfs
Access mode: RWX if available, otherwise RWO
Size: 150-250Gi to start
Mount path: /hf-cache
```

DSRI storage notes:

```text
Ephemeral pod storage is lost when the pod is restarted or deleted.
Persistent storage can be reused across pod restarts.
DSRI persistent storage is not automatically backed up.
Use the DSRI web UI Add Storage action to mount an existing PVC into an application.
```

The GPU backend maps Hugging Face cache paths to the PVC:

```text
HF_HOME=/hf-cache
HUGGINGFACE_HUB_CACHE=/hf-cache/hub
TRANSFORMERS_CACHE=/hf-cache/transformers
VLLM_MODEL=Qwen/Qwen2.5-32B-Instruct-AWQ
SERVED_MODEL_NAME=Qwen/Qwen2.5-32B-Instruct-AWQ
```

On the first startup for a model, vLLM/Hugging Face downloads model files into `/hf-cache`. On later restarts with the same PVC mounted, the backend should reuse that cache instead of downloading from scratch.

### Deploying the GPU Backend

When DSRI GPU time is booked:

```text
1. Create or confirm the PVC pvc-datasight-hf-cache exists.
2. Create a second DSRI application/build from this repo using Dockerfile path gpu/Dockerfile.
3. Name the GPU application/service datasight-vllm-gpu.
4. Mount pvc-datasight-hf-cache into the GPU app at /hf-cache.
5. Enable one GPU only on the GPU backend deployment, not on the CPU gateway.
6. Expose the GPU backend as an internal Service on port 8000.
7. Do not create a public Route for the GPU backend unless you need direct debugging access.
8. Set the CPU gateway env var LLM_BACKEND_URL=http://datasight-vllm-gpu:8000.
9. Keep DataSight pointed at the stable CPU gateway route.
```

DSRI GPU notes:

```text
GPU access is reservation-based.
Enabling GPU resources restarts the pod.
Keep replica count at 1 while debugging.
Only the GPU backend deployment should request nvidia.com/gpu: 1.
```

The reference manifests in `dsri/` show the intended PVC mount, service name, model env vars, and GPU resource request. Replace `<project>` in `dsri/vllm-gpu-deployment.yaml` with your DSRI/OpenShift project name if you apply it directly.

### Switching Models Later

To switch models, update the GPU backend environment:

```text
VLLM_MODEL=<new-model-id>
SERVED_MODEL_NAME=<new-model-id>
```

Then update the CPU gateway metadata:

```text
LLM_MODEL=<new-model-id>
```

No code change or rebuild is required for an env-only model switch. Use a DSRI/OpenShift rollout/restart so the GPU backend starts vLLM with the new model. If the new model is not already present in `/hf-cache`, it downloads once into the mounted PVC.

This architecture avoids CPU pods trying to run the model and keeps `/health` available even when GPU scheduling is unavailable.
