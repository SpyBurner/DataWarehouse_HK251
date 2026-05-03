FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the environment file early so configuration changes invalidate the cache.
COPY .env .
COPY . .

EXPOSE 8501