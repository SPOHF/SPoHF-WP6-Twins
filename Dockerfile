# Multi-stage build for minimal image size
FROM python:3.12-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy all files needed for install
COPY pyproject.toml uv.lock README.md ./
COPY src/ src/

# Install dependencies and package
RUN uv sync --frozen --no-dev

# Production stage
FROM python:3.12-slim

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser
USER appuser
WORKDIR /home/appuser/app

# Copy virtual environment and source from builder
COPY --from=builder --chown=appuser:appuser /app/.venv /home/appuser/app/.venv
COPY --from=builder --chown=appuser:appuser /app/src /home/appuser/app/src

# Set path to use venv and add src to PYTHONPATH
ENV PATH="/home/appuser/app/.venv/bin:$PATH"
ENV PYTHONPATH="/home/appuser/app/src"
ENV PYTHONUNBUFFERED=1

# Expose dashboard port
EXPOSE 8000

# Default: run dashboard (can override to run sync)
CMD ["python", "-m", "wp6_data.dashboard"]
