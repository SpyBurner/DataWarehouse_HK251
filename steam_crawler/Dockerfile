FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# .env is copied early so edits bust the Docker layer cache automatically
COPY .env .
COPY . .
