# DataSight DSRI Practice Server

Small stable HTTP server for practicing DSRI deployment, rollout, service, route, and readiness-probe setup.

This build intentionally does not run an LLM, vLLM, CUDA checks, model downloads, or chat-completion endpoints. It only proves that the container can start reliably and that DSRI can reach the app over port `8000`.

## Runtime

The container runs a Python standard-library HTTP server:

```text
GET /       -> 200 OK
GET /health -> 200 OK
```

All other paths return `404`.

Health response:

```json
{
  "status": "ok",
  "mode": "stable-health-only",
  "version": "stable-health-v1",
  "message": "DataSight DSRI practice deployment is running."
}
```

## DSRI Settings

Use port `8000` throughout:

```text
Application name: datasight-llm-server
Container port: 8000
Service port: 8000
Target port: 8000
Route: enabled
Readiness path: /health
```

The external DSRI route should be called over HTTPS without appending `:8000`.

## Verification

Health check:

```bash
curl https://datasight-llm-server-ub-datasight.apps.dsri2.unimaas.nl/health
```

Expected logs:

```text
Starting DataSight deployment-practice server...
HOST=0.0.0.0
PORT=8000
No model runtime is configured for this build.
DataSight stable health server is ready.
Listening on 0.0.0.0:8000
Version: stable-health-v1
```
