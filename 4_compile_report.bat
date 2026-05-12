@echo off
docker run --rm -v "%cd%\Report:/workspace" -w /workspace aergus/latex bash -c "chmod +x build.sh && ./build.sh"

