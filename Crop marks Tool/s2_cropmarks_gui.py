from pathlib import Path
import sys

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from airchgis.app import render_cropmarks  # noqa: E402


st.set_page_config(page_title="AIrchGIS · Crop Marks", layout="wide")
render_cropmarks(standalone=True)
