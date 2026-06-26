#!/bin/zsh
set -e

cd "$(dirname "$0")"

if [ -x "/opt/homebrew/bin/python3.11" ]; then
  PYTHON_BIN="/opt/homebrew/bin/python3.11"
elif [ -x "/usr/local/bin/python3.11" ]; then
  PYTHON_BIN="/usr/local/bin/python3.11"
elif command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3.11)"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "Python 3 non trovato."
  read -r "x?Premi Invio per chiudere."
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

./.venv/bin/python -m pip install --upgrade pip setuptools wheel
./.venv/bin/python -m pip install -r requirements.txt

if [ -f "Crop marks Tool/.ee_project" ]; then
  export EE_PROJECT="$(cat "Crop marks Tool/.ee_project" | tr -d '[:space:]')"
elif [ -f ".ee_project" ]; then
  export EE_PROJECT="$(cat ".ee_project" | tr -d '[:space:]')"
fi

./.venv/bin/python -m streamlit run archaeoscope_app.py
