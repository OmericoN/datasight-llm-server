#!/usr/bin/env bash
set -e

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
VLLM_MODEL="${VLLM_MODEL:-Qwen/Qwen2.5-32B-Instruct-AWQ}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-${VLLM_MODEL}}"
VLLM_DTYPE="${VLLM_DTYPE:-auto}"

export HF_HOME="${HF_HOME:-/hf-cache}"
export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-${HF_HOME}/hub}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-${HF_HOME}/transformers}"

mkdir -p "${HF_HOME}" "${HUGGINGFACE_HUB_CACHE}" "${TRANSFORMERS_CACHE}"

echo "Starting DataSight vLLM GPU backend..."
echo "HOST=${HOST}"
echo "PORT=${PORT}"
echo "VLLM_MODEL=${VLLM_MODEL}"
echo "SERVED_MODEL_NAME=${SERVED_MODEL_NAME}"
echo "HF_HOME=${HF_HOME}"
echo "HUGGINGFACE_HUB_CACHE=${HUGGINGFACE_HUB_CACHE}"
echo "TRANSFORMERS_CACHE=${TRANSFORMERS_CACHE}"
echo "VLLM_DTYPE=${VLLM_DTYPE}"

exec python -m vllm.entrypoints.openai.api_server \
  --host "${HOST}" \
  --port "${PORT}" \
  --model "${VLLM_MODEL}" \
  --served-model-name "${SERVED_MODEL_NAME}" \
  --dtype "${VLLM_DTYPE}" \
  ${VLLM_EXTRA_ARGS:-}
