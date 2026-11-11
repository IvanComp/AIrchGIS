#!/bin/zsh
set -e

cd "$(dirname "$0")"

VENV_DIR=".venv_airch"
REQUIREMENTS_FILE="requirements.txt"

if [ -x "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12" ]; then
  PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12"
elif [ -x "/usr/local/bin/python3" ]; then
  PYTHON_BIN="/usr/local/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "Python 3 non trovato."
  read -r "x?Premi Invio per chiudere."
  exit 1
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
fi

REQ_HASH="$(shasum -a 256 "$REQUIREMENTS_FILE" | awk '{print $1}')"
STAMP_FILE="$VENV_DIR/.requirements.sha256"
INSTALLED_HASH=""
if [ -f "$STAMP_FILE" ]; then
  INSTALLED_HASH="$(tr -d '[:space:]' < "$STAMP_FILE")"
fi

if [ "$REQ_HASH" != "$INSTALLED_HASH" ]; then
  "$VENV_DIR/bin/python" -m pip install -r "$REQUIREMENTS_FILE"
  print -r -- "$REQ_HASH" > "$STAMP_FILE"
fi

if ! "$VENV_DIR/bin/python" - <<'PY' >/dev/null 2>&1
import tkinter
import rasterio
import rvt.vis
PY
then
  echo "Ambiente Python incompleto. Elimina solo $VENV_DIR e riavvia AIrch."
  read -r "x?Premi Invio per chiudere."
  exit 1
fi

if [ -f "Crop marks Tool/.ee_project" ]; then
  export EE_PROJECT="$(cat "Crop marks Tool/.ee_project" | tr -d '[:space:]')"
elif [ -f ".ee_project" ]; then
  export EE_PROJECT="$(cat ".ee_project" | tr -d '[:space:]')"
fi

export PYTHONDONTWRITEBYTECODE=1

exec "$VENV_DIR/bin/python" -m streamlit run airch_app.py
