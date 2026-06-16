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
