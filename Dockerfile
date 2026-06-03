FROM vllm/vllm-openai:latest

EXPOSE 8000

CMD ["--host", "0.0.0.0", "--port", "8000", "--model", "Qwen/Qwen2.5-0.5B-Instruct"]
