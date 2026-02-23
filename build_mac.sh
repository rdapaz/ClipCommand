#!/bin/bash
# build_mac.sh — build ClipCommand for macOS distribution
# Run from the project root: bash build_mac.sh

set -e

echo "=== ClipCommand macOS Build ==="

# Ensure we're in the venv
if [ -z "$VIRTUAL_ENV" ]; then
    echo "Activating .venv..."
    source .venv/bin/activate
fi

# Install/upgrade build deps
pip install --upgrade pyinstaller

# Clean previous build
rm -rf build/ dist/

# Build
pyinstaller clipcommand.spec

# Package for distribution
echo ""
echo "=== Packaging ==="
cd dist
zip -r ClipCommand-mac.zip ClipCommand/
cd ..

echo ""
echo "=== Done ==="
echo "Distribute:  dist/ClipCommand-mac.zip"
echo "Contents:    dist/ClipCommand/"
echo ""
echo "Recipients unzip and run: ./ClipCommand/ClipCommand"
echo "First run on macOS: right-click → Open to bypass Gatekeeper"
