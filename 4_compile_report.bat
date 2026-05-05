powershell -Command "Remove-Item -Path 'Report\Build\*' -Recurse -Force -ErrorAction SilentlyContinue"
docker compose run --rm texlive pdflatex -interaction=nonstopmode -output-directory=Build main.tex
