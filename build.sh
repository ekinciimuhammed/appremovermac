#!/bin/bash
# App Remover Pro - DMG Build Script
# This script ensures the environment is ready and calls the python build script.

# 1. Go to project root
cd "$(dirname "$0")"

echo "🔍 Checking environment..."

echo "📦 Installing/Updating dependencies (customtkinter, tkinterdnd2, pyinstaller)..."
# Use 'python -m pip' to ensure we are installing to the same environment we execute from
python -m pip install --upgrade pip
python -m pip install customtkinter tkinterdnd2 pyinstaller

# 4. Run Build Script
echo "🏗️ Starting DMG build process..."
# Use 'python' to match the active conda environment
python build_dmg.py

echo "✅ Done!"

