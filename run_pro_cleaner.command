#!/bin/bash
cd "$(dirname "$0")"

# Check if venv exists
if [ ! -d ".venv" ]; then
    echo "Configuring environment..."
    python3 -m venv .venv
    .venv/bin/pip install customtkinter tkinterdnd2
fi

echo "Starting App Remover Pro..."
.venv/bin/python3 app_remover.py
