#!/bin/bash
# Report build script for LaTeX
# Runs pdflatex twice to ensure TOC and references are updated

# Create Build directory if it doesn't exist
mkdir -p Build

# First pass
pdflatex -interaction=nonstopmode -output-directory=Build main.tex

# Second pass
pdflatex -interaction=nonstopmode -output-directory=Build main.tex
