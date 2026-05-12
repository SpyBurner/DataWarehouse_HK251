@echo off
echo Building LaTeX report in %cd%...
docker run --rm -v "%cd%:/workspace" -w /workspace aergus/latex bash -c "chmod +x build.sh && ./build.sh"
echo Build finished.
