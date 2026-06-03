FROM python:3.12-slim

WORKDIR /app

COPY entrypoint.sh /entrypoint.sh
COPY app ./app

RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
