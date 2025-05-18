# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies only in builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install pip and build tools
RUN pip install --upgrade pip setuptools wheel

# Copy only pyproject.toml and README for dependency install
COPY pyproject.toml README.md ./

# Install Python dependencies (including Postgres/ORM) via pyproject.toml
RUN pip install --user .

# Copy the rest of the code
COPY . .

# Final image
FROM python:3.12-slim
WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local
COPY --from=builder /app /app
ENV PATH=/root/.local/bin:$PATH

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
