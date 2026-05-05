docker build -t steam-anomaly-detection .
docker run -it --rm --name steam-anomaly -v steam-data:/app/data -v steam-outputs:/app/outputs steam-anomaly-detection