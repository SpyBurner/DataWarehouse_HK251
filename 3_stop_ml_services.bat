@echo off
setlocal

cd /d "%~dp0"
docker compose stop ml-dashboard ml-pipeline
docker compose rm -f ml-dashboard ml-pipeline
