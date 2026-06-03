FROM vllm/vllm-openai:latest

WORKDIR /app

COPY entrypoint.sh /entrypoint.sh
COPY app ./app

RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
