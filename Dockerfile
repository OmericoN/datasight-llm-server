FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv \
  && uv sync --frozen --no-dev

COPY entrypoint.sh /entrypoint.sh
COPY app ./app

RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENV PATH="/app/.venv/bin:${PATH}"

ENTRYPOINT ["/entrypoint.sh"]
