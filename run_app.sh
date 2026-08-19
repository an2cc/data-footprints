#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Anna Caellas-Camprubí
# SPDX-License-Identifier: EUPL-1.2
set -e

cd "$(dirname "$0")"

echo "=========================================="
echo "Data Footprints - startup"
echo "=========================================="
echo

if [ ! -f "app.py" ]; then
  echo "ERROR: app.py was not found in:"
  pwd
  exit 1
fi

if [ ! -f "requirements.txt" ]; then
  echo "ERROR: requirements.txt was not found."
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Python environment .venv was not found."
  echo "Creating it now..."
  echo

  if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
  elif command -v python >/dev/null 2>&1; then
    PYTHON=python
  else
    echo "ERROR: Python was not found."
    exit 1
  fi

  "$PYTHON" -m venv .venv
  ".venv/bin/python" -m pip install --upgrade pip
  ".venv/bin/python" -m pip install -r requirements.txt
fi

echo
echo "Starting Data Footprints..."
echo "The browser should open at http://localhost:8501"
echo "To stop the application, return to this window and press Ctrl+C."
echo

exec ".venv/bin/python" -m streamlit run app.py
