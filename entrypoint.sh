#!/usr/bin/env bash
set -e

MODEL_NAME="${MODEL_NAME:-Qwen/Qwen2.5-0.5B-Instruct}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

echo "Starting DataSight LLM server..."
echo "MODEL_NAME=${MODEL_NAME}"
echo "HOST=${HOST}"
echo "PORT=${PORT}"

if python - <<'PY'
import torch
raise SystemExit(0 if torch.cuda.is_available() else 1)
PY
then
  echo "CUDA detected. Starting real vLLM server."

  exec python -m vllm.entrypoints.openai.api_server \
    --host "${HOST}" \
    --port "${PORT}" \
    --model "${MODEL_NAME}" \
    --dtype auto
else
  echo "CUDA not detected. Starting fallback API server."
  echo "This proves DSRI deployment/routing works, but no model is running."

  exec python -m uvicorn app.fallback:app \
    --host "${HOST}" \
    --port "${PORT}"
fi
