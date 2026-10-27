FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
RUN pip install --no-cache-dir uv==0.9.14
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-editable
COPY alembic.ini ./
COPY migrations ./migrations
COPY tests ./tests

RUN useradd --create-home chatbot && chown -R chatbot:chatbot /app
USER chatbot
EXPOSE 8080
CMD ["uvicorn", "chatbot.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
