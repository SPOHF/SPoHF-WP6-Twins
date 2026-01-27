# Multi-stage build for minimal image size
# Supports building separate images for blue (Neo4j) and red (MySQL) dashboards
#
# Build blue: docker build --target blue -t wp6-data-blue .
# Build red:  docker build --target red -t wp6-data-red .
# Build default (blue): docker build -t wp6-data .

FROM python:3.14-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy all files needed for install
COPY pyproject.toml uv.lock README.md ./
COPY src/ src/

# Install dependencies and package
RUN uv sync --frozen --no-dev

# Common runtime stage
FROM python:3.14-slim AS runtime

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser
USER appuser
WORKDIR /home/appuser/app

# Copy virtual environment and source from builder
COPY --from=builder --chown=appuser:appuser /app/.venv /home/appuser/app/.venv
COPY --from=builder --chown=appuser:appuser /app/src /home/appuser/app/src
COPY --chown=appuser:appuser static/ /home/appuser/app/static/

# Set path to use venv and add src to PYTHONPATH
ENV PATH="/home/appuser/app/.venv/bin:$PATH"
ENV PYTHONPATH="/home/appuser/app/src"
ENV PYTHONUNBUFFERED=1

# Expose dashboard port
EXPOSE 8000

# Blue dashboard (Neo4j backend) - default
FROM runtime AS blue
CMD ["python", "-m", "wp6_data.blue.dashboard"]

# Red dashboard (MySQL backend with auth)
FROM runtime AS red
CMD ["python", "-m", "wp6_data.red.dashboard"]

# Default target is blue (for backwards compatibility)
FROM blue
