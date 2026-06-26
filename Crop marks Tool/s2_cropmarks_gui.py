from pathlib import Path
import sys

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from archaeoscope.app import render_cropmarks_page  # noqa: E402


st.set_page_config(page_title="Sentinel-2 Crop Marks", layout="wide")
render_cropmarks_page(standalone=True)
