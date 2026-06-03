#!/usr/bin/env bash
set -e

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

echo "Starting DataSight deployment-practice server..."
echo "HOST=${HOST}"
echo "PORT=${PORT}"
echo "No model runtime is configured for this build."

exec python -m app.server
