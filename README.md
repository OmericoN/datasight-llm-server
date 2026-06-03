# DataSight LLM Server

Standalone DSRI-hosted LLM service for DataSight.

The container listens on `0.0.0.0:8000` and exposes an OpenAI-compatible chat endpoint. At startup it checks whether CUDA is available:

- CUDA available: starts the real vLLM OpenAI API server.
- CUDA unavailable: starts a lightweight FastAPI fallback server so DSRI build, pod, service, route, and health checks can be verified.

Default model:

```text
Qwen/Qwen2.5-0.5B-Instruct
```

## Endpoints

Fallback mode exposes:

```text
GET  /
GET  /health
POST /v1/chat/completions
```

The fallback server does not run a real model. It returns a dummy assistant response and includes `version: fallback-v1` on health responses so deployments can be verified.

## DSRI Settings

Use port `8000` throughout:

```text
Container port: 8000
Service port: 8000
Target port: 8000
Readiness path: /health
```

The external DSRI route should be called over HTTPS without appending `:8000`.

## Verification

Health check:

```bash
curl https://datasight-llm-server-ub-datasight.apps.dsri2.unimaas.nl/health
```

Fallback chat check:

```bash
curl https://datasight-llm-server-ub-datasight.apps.dsri2.unimaas.nl/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "datasight-fallback",
    "messages": [
      {"role": "user", "content": "Hello from DataSight"}
    ]
  }'
```

Expected fallback logs when no GPU is available:

```text
Starting DataSight LLM server...
MODEL_NAME=Qwen/Qwen2.5-0.5B-Instruct
HOST=0.0.0.0
PORT=8000
CUDA not detected. Starting fallback API server.
This proves DSRI deployment/routing works, but no model is running.
```
