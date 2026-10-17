FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY . .
RUN useradd -m app && chown -R app /app
USER app
