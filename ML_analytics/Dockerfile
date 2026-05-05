FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Declare container mount points. Use named volumes at runtime, e.g.
#   docker run -v steam-data:/app/data -v steam-outputs:/app/outputs <image>
VOLUME ["/app/data", "/app/outputs"]

# Copy the environment file early so configuration changes invalidate the cache.
COPY .env .
COPY . .

CMD ["python3", "batch_analysis.py", "--force-run"]