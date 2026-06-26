#!/bin/zsh
set -e

cd "$(dirname "$0")"

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

if [ -x ".venv/bin/python" ]; then
  if ! ./.venv/bin/python - <<'PY' >/dev/null 2>&1
import tkinter
import rasterio
import rvt.vis
PY
  then
    rm -rf .venv
  fi
fi

if [ ! -x ".venv/bin/python" ]; then
  "$PYTHON_BIN" -m venv --system-site-packages .venv
fi

./.venv/bin/python -m pip install --upgrade pip setuptools wheel
./.venv/bin/python -m pip install -r requirements.txt

if [ -f "Crop marks Tool/.ee_project" ]; then
  export EE_PROJECT="$(cat "Crop marks Tool/.ee_project" | tr -d '[:space:]')"
elif [ -f ".ee_project" ]; then
  export EE_PROJECT="$(cat ".ee_project" | tr -d '[:space:]')"
fi

export PYTHONDONTWRITEBYTECODE=1

./.venv/bin/python -m streamlit run archaeoscope_app.py
