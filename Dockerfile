FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY src/ ./src/

# Output directory (will be overridden by volume mount)
RUN mkdir -p /app/output

# Default: run once and exit (set REFRESH_INTERVAL_HOURS > 0 for daemon mode)
CMD ["python", "src/main.py"]
