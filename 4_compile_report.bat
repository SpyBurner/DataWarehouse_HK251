@echo off
docker compose run --rm texlive bash -c "chmod +x build.sh && ./build.sh"

