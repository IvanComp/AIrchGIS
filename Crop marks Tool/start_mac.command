#!/bin/zsh
set -e
cd "$(dirname "$0")"
PROJECT_FILE=".ee_project"
if [ -x "/opt/homebrew/bin/python3.11" ]; then
  PY311="/opt/homebrew/bin/python3.11"
elif [ -x "/usr/local/bin/python3.11" ]; then
  PY311="/usr/local/bin/python3.11"
elif command -v python3.11 >/dev/null 2>&1; then
  PY311="$(command -v python3.11)"
else
  echo "Python 3.11 non trovato. Installa con: brew install python@3.11"
  read -r "x?Premi Invio per chiudere."
  exit 1
fi
if [ ! -x ".venv/bin/python" ] || ! ./.venv/bin/python -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)" >/dev/null 2>&1; then
  rm -rf .venv
  "$PY311" -m venv .venv
fi
./.venv/bin/python -m pip install --upgrade pip setuptools wheel
./.venv/bin/python -m pip install -r requirements.txt
if [ -f "$PROJECT_FILE" ]; then
  PROJECT_ID="$(cat "$PROJECT_FILE" | tr -d '[:space:]')"
else
  echo "Inserisci il Google Earth Engine project ID. Esempio: ee-ivan-cropmarks"
  read -r "PROJECT_ID?Project ID: "
  echo "$PROJECT_ID" > "$PROJECT_FILE"
fi
export EE_PROJECT="$PROJECT_ID"
./.venv/bin/earthengine set_project "$PROJECT_ID" || true
if ! ./.venv/bin/python -c "import ee, os; ee.Initialize(project=os.environ['EE_PROJECT']); print('Earth Engine OK')"; then
  echo "Autenticazione o registrazione Earth Engine necessaria. Apro il login."
  ./.venv/bin/earthengine authenticate --force
  ./.venv/bin/earthengine set_project "$PROJECT_ID" || true
  if ! ./.venv/bin/python -c "import ee, os; ee.Initialize(project=os.environ['EE_PROJECT']); print('Earth Engine OK')"; then
    echo "Il progetto non e ancora pronto. Controlla:"
    echo "https://console.cloud.google.com/earth-engine/configuration?project=$PROJECT_ID"
    read -r "x?Premi Invio per chiudere."
    exit 1
  fi
fi
./.venv/bin/python -m streamlit run s2_cropmarks_gui.py
