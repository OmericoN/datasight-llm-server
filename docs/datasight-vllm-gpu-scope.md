# datasight-vllm-gpu Implementation Scope

## Goal

Create a separate DSRI/OpenShift repository and application named `datasight-vllm-gpu`.

This service is the private GPU-backed vLLM backend for the public `datasight-llm-server` CPU gateway. It must expose an OpenAI-compatible API internally on port `8000`, request exactly one GPU only when scaled up, and avoid any public route by default.

The CPU gateway will call:

```text
http://datasight-vllm-gpu:8000
```

## Required Architecture

```text
Public internet / DataSight client
  -> datasight-llm-server
     CPU-only FastAPI gateway
     public DSRI Route
     API keys, rate limits, usage monitoring

OpenShift internal network
  -> datasight-vllm-gpu
     private vLLM OpenAI-compatible backend
     no public Route
     nvidia.com/gpu: 1 only on this deployment
```

The GPU backend must not implement public authentication as the primary protection boundary. The CPU gateway is the public boundary. The GPU backend may still support an internal API key for defense in depth.

## Repository Files

Create this structure in the new repository:

```text
datasight-vllm-gpu/
├── Dockerfile
├── entrypoint-vllm.sh
├── README.md
└── dsri/
    ├── deployment.yaml
    ├── service.yaml
    └── pvc.yaml
```

Do not copy the CPU gateway application code into this repo.

## Dockerfile

Use the official vLLM OpenAI image:

```dockerfile
FROM vllm/vllm-openai:latest

ENV HF_HOME=/hf-cache
ENV HUGGINGFACE_HUB_CACHE=/hf-cache/hub
ENV TRANSFORMERS_CACHE=/hf-cache/transformers
ENV VLLM_MODEL=Qwen/Qwen2.5-32B-Instruct-AWQ
ENV SERVED_MODEL_NAME=Qwen/Qwen2.5-32B-Instruct-AWQ
ENV HOST=0.0.0.0
ENV PORT=8000
ENV VLLM_DTYPE=auto

COPY entrypoint-vllm.sh /entrypoint-vllm.sh
RUN mkdir -p /hf-cache \
  && chmod 0777 /hf-cache \
  && chmod +x /entrypoint-vllm.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint-vllm.sh"]
```

## Entrypoint

Create `entrypoint-vllm.sh`:

```bash
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
```

Use LF line endings for shell scripts.

## DSRI PVC

Create `dsri/pvc.yaml`:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: pvc-datasight-hf-cache
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: ocs-storagecluster-cephfs
  resources:
    requests:
      storage: 200Gi
```

If DSRI does not allow `ReadWriteMany`, use `ReadWriteOnce` with one replica.

## DSRI Service

Create `dsri/service.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: datasight-vllm-gpu
  labels:
    app: datasight-vllm-gpu
spec:
  selector:
    app: datasight-vllm-gpu
  ports:
    - name: http
      port: 8000
      targetPort: 8000
```

Do not create a public Route for this service by default.

## DSRI Deployment

Create `dsri/deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: datasight-vllm-gpu
  labels:
    app: datasight-vllm-gpu
spec:
  replicas: 0
  selector:
    matchLabels:
      app: datasight-vllm-gpu
  template:
    metadata:
      labels:
        app: datasight-vllm-gpu
    spec:
      containers:
        - name: vllm
          image: image-registry.openshift-image-registry.svc:5000/<project>/datasight-vllm-gpu:latest
          imagePullPolicy: Always
          ports:
            - containerPort: 8000
          env:
            - name: HOST
              value: 0.0.0.0
            - name: PORT
              value: "8000"
            - name: VLLM_MODEL
              value: Qwen/Qwen2.5-32B-Instruct-AWQ
            - name: SERVED_MODEL_NAME
              value: Qwen/Qwen2.5-32B-Instruct-AWQ
            - name: VLLM_DTYPE
              value: auto
            - name: HF_HOME
              value: /hf-cache
            - name: HUGGINGFACE_HUB_CACHE
              value: /hf-cache/hub
            - name: TRANSFORMERS_CACHE
              value: /hf-cache/transformers
          volumeMounts:
            - name: hf-cache
              mountPath: /hf-cache
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 120
            periodSeconds: 10
            timeoutSeconds: 10
            failureThreshold: 12
          resources:
            requests:
              cpu: "4"
              memory: 32Gi
              nvidia.com/gpu: "1"
            limits:
              cpu: "16"
              memory: 128Gi
              nvidia.com/gpu: "1"
      volumes:
        - name: hf-cache
          persistentVolumeClaim:
            claimName: pvc-datasight-hf-cache
```

Replace `<project>` with the DSRI/OpenShift project namespace.

The default `replicas` must be `0`. Scaling to `1` is an operational action during a booked GPU window.

## Environment Variables

Required:

```text
HOST=0.0.0.0
PORT=8000
VLLM_MODEL=Qwen/Qwen2.5-32B-Instruct-AWQ
SERVED_MODEL_NAME=Qwen/Qwen2.5-32B-Instruct-AWQ
VLLM_DTYPE=auto
HF_HOME=/hf-cache
HUGGINGFACE_HUB_CACHE=/hf-cache/hub
TRANSFORMERS_CACHE=/hf-cache/transformers
```

Optional:

```text
VLLM_EXTRA_ARGS=<additional vLLM CLI flags>
```

For first DSRI validation, temporarily set a small model before using the 32B model:

```text
VLLM_MODEL=Qwen/Qwen2.5-0.5B-Instruct
SERVED_MODEL_NAME=Qwen/Qwen2.5-0.5B-Instruct
```

Switch to the larger model only after image build, service discovery, PVC mount, and gateway proxying are confirmed.

## Gateway Integration

In the `datasight-llm-server` deployment, set:

```text
LLM_BACKEND_URL=http://datasight-vllm-gpu:8000
LLM_MODEL=<same served model name>
```

If backend-side auth is added to vLLM, set this only on the CPU gateway:

```text
LLM_BACKEND_API_KEY=<backend-secret>
```

Do not expose this backend secret to public clients.

## Operations

Normal idle state:

```text
datasight-llm-server replicas: 1
datasight-vllm-gpu replicas: 0
GPU quota used: 0
```

GPU booked test state:

```text
datasight-llm-server replicas: 1
datasight-vllm-gpu replicas: 1
GPU quota used: 1
```

After the test window:

```text
datasight-vllm-gpu replicas: 0
```

Never assign `nvidia.com/gpu` to `datasight-llm-server`.

## Validation Checklist

Before scaling GPU to `1`:

- The PVC exists and is mounted at `/hf-cache`.
- The `datasight-vllm-gpu` Service exists on port `8000`.
- No public Route exists for `datasight-vllm-gpu`.
- The CPU gateway has `LLM_BACKEND_URL=http://datasight-vllm-gpu:8000`.
- The CPU gateway has `API_KEYS` configured for public use.

During a booked GPU window:

- Scale `datasight-vllm-gpu` to `1`.
- Confirm the pod starts and becomes ready.
- Confirm the CPU gateway `/gpu-status` reports `gpu_available: true`.
- Confirm the CPU gateway `/v1/models` works with an API key.
- Confirm a tiny `/v1/chat/completions` request works with low `max_tokens`.

After testing:

- Scale `datasight-vllm-gpu` back to `0`.
- Confirm GPU quota returns to unused.
- Confirm the CPU gateway still answers `/health`.
- Confirm the CPU gateway returns `503` for chat when the backend is down.

## Acceptance Criteria

- The repository builds a vLLM image from `Dockerfile`.
- The service listens on `0.0.0.0:8000`.
- `/health` returns `200` when vLLM is ready.
- `/v1/models` returns OpenAI-compatible model metadata.
- `/v1/chat/completions` works through the CPU gateway.
- The GPU deployment requests `nvidia.com/gpu: "1"`.
- The GPU deployment defaults to `replicas: 0`.
- No public Route is created for `datasight-vllm-gpu`.
- Model cache persists across pod restarts via `/hf-cache`.
- GPU quota is consumed only when `datasight-vllm-gpu` is scaled to `1`.
