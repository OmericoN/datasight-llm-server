#!/usr/bin/env bash
set -e

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
SERVICE_VERSION="${SERVICE_VERSION:-fastapi-gateway-v1}"

echo "Starting DataSight DSRI FastAPI LLM gateway..."
echo "HOST=${HOST}"
echo "PORT=${PORT}"
echo "SERVICE_VERSION=${SERVICE_VERSION}"
echo "LLM_BACKEND_URL=${LLM_BACKEND_URL:-}"
echo "No local model runtime is configured for this CPU gateway."

exec uvicorn app.main:app --host "${HOST}" --port "${PORT}"
