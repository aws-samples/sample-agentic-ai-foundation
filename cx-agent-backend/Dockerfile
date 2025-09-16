# Use ARM64 Python 3.11 base image with uv pre-installed
FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:python3.11-bookworm-slim

# Set working directory
WORKDIR /app

# Configure uv to install packages globally and compile bytecode for performance
ENV UV_PROJECT_ENVIRONMENT="/usr/local/"
ENV UV_COMPILE_BYTECODE=1

# Copy dependency configuration and install Python dependencies
COPY pyproject.toml .
RUN uv sync

# Copy application source code
COPY src/ ./src/

# Set Python path
ENV PYTHONPATH="/app/src"

# Expose FastAPI server port
EXPOSE 8080

# Start the CX Agent service
CMD ["python", "src/run.py"]