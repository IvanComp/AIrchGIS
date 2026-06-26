import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from folium.plugins import Draw
from streamlit_folium import st_folium

from . import cropmarks_engine as cropmarks
from .paths import LOGO_PATH, PROJECT_ROOT, RVT_DIR, RVT_ENTRYPOINT, count_files, latest_files


def main():
    st.set_page_config(page_title="ArchaeoScope", layout="wide")
    apply_theme()
    init_state()
    render_header()

    rvt_col, crop_col = st.columns([0.34, 0.66], gap="large")
    with rvt_col:
        render_rvt_panel()
    with crop_col:
        render_cropmarks_page(show_header=True)


def apply_theme():
    st.markdown(
        """
        <style>
        :root {
            --as-bg: #11130f;
            --as-panel: #1b1e18;
            --as-panel-2: #23271f;
            --as-text: #f4f0e8;
            --as-muted: #b8b3a7;
            --as-line: #383d32;
            --as-teal: #4fb7a5;
            --as-green: #b8ce68;
            --as-amber: #d8843a;
        }
        .stApp {
            background: var(--as-bg);
            color: var(--as-text);
        }
        h1, h2, h3 {
            letter-spacing: 0;
        }
        .as-brand {
            display: flex;
            align-items: center;
            gap: 14px;
            margin: 0 0 18px 0;
        }
        .as-logo svg {
            width: 72px;
            height: 72px;
            display: block;
        }
        .as-title {
            font-size: 36px;
            line-height: 1.05;
            font-weight: 760;
            margin: 0;
        }
        .as-subtitle {
            color: var(--as-muted);
            font-size: 15px;
            margin-top: 6px;
        }
        .as-panel {
            border: 1px solid var(--as-line);
            background: var(--as-panel);
            border-radius: 8px;
            padding: 16px;
        }
        .as-panel-title {
            font-size: 20px;
            font-weight: 700;
            margin-bottom: 6px;
        }
        .as-panel-copy {
            color: var(--as-muted);
            font-size: 14px;
            line-height: 1.4;
            margin-bottom: 14px;
        }
        .as-strip {
            border: 1px solid var(--as-line);
            background: var(--as-panel-2);
            border-radius: 8px;
            padding: 12px 14px;
            margin-bottom: 12px;
            font-weight: 650;
        }
        .as-good { color: var(--as-green); }
        .as-warn { color: var(--as-amber); }
        .stButton > button, .stDownloadButton > button {
            border-radius: 8px;
            border: 1px solid #4f5b48;
            background: #252a21;
            color: var(--as-text);
            min-height: 38px;
        }
        .stButton > button:hover, .stDownloadButton > button:hover {
            border-color: var(--as-teal);
            color: #ffffff;
        }
        div[data-testid="stDataFrame"] {
            border: 1px solid var(--as-line);
            border-radius: 8px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def init_state():
    defaults = {
        "as_crop_result": None,
        "as_crop_geometry": None,
        "as_rvt_python": default_rvt_python(),
        "as_rvt_process": None,
        "as_rvt_log": str(PROJECT_ROOT / ".rvt_launch.log"),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_header():
    st.markdown(
        f"""
        <div class="as-brand">
          <div class="as-logo">{logo_svg()}</div>
          <div>
            <div class="as-title">ArchaeoScope</div>
            <div class="as-subtitle">RVT LiDAR e Sentinel-2 Crop Marks nella stessa pagina.</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_cropmarks_page(show_header=False, standalone=False):
    if standalone:
        apply_theme()
        init_state()
        render_header()

    if show_header:
        st.markdown('<div class="as-strip">Sentinel-2 Crop Marks</div>', unsafe_allow_html=True)

    with st.expander("Parametri analisi", expanded=True):
        project = st.text_input("Google Earth Engine project", cropmarks.default_project(), key="as_crop_project")
        c1, c2 = st.columns(2)
        with c1:
            start = st.date_input("Da", date(2016, 1, 1), key="as_crop_start")
        with c2:
            end = st.date_input("A", date(2019, 12, 31), key="as_crop_end")
        cloud = st.slider("Cloud cover metadata (%)", 0, 100, 10, key="as_crop_cloud")
        topn = st.slider("Date migliori da combinare", 1, 20, 5, key="as_crop_topn")
        mode = st.selectbox("Immagine base", ["Migliore singola data", "Mediana migliori date"], key="as_crop_mode")
        export = st.checkbox("Export GeoTIFF su Google Drive", False, key="as_crop_export")
        folder = st.text_input("Cartella Drive", "S2_cropmarks", key="as_crop_folder")
        run_col, reset_col = st.columns(2)
        with run_col:
            run = st.button("Avvia analisi", type="primary", width="stretch")
        with reset_col:
            reset = st.button("Reset analisi", width="stretch")

    if reset:
        st.session_state.as_crop_result = None
        st.session_state.as_crop_geometry = None
        st.rerun()

    draw_map = folium.Map(location=[41.5, 15.5], zoom_start=9, tiles=None)
    cropmarks.add_base_tiles(draw_map, esri_show=True)
    Draw(
        export=False,
        draw_options={
            "polyline": False,
            "polygon": True,
            "rectangle": True,
            "circle": False,
            "marker": False,
            "circlemarker": False,
        },
        edit_options={"edit": True},
    ).add_to(draw_map)
    folium.LayerControl(collapsed=False).add_to(draw_map)
    draw = st_folium(draw_map, width=1200, height=560, key="as_crop_draw_map", returned_objects=["all_drawings"])

    if run:
        if start > end:
            st.error("La data iniziale deve precedere la data finale.")
            st.stop()
        drawings = draw.get("all_drawings") or []
        if drawings:
            st.session_state.as_crop_geometry = drawings[-1]["geometry"]
        if not st.session_state.as_crop_geometry:
            st.error("Disegna prima un poligono o un rettangolo sulla mappa.")
            st.stop()
        if project:
            cropmarks.save_default_project(project)
        with st.spinner("Analisi in corso. Attendo Earth Engine..."):
            try:
                st.session_state.as_crop_result = cropmarks.run_analysis(
                    project,
                    start,
                    end,
                    cloud,
                    topn,
                    mode,
                    export,
                    folder,
                    st.session_state.as_crop_geometry,
                )
            except Exception as exc:
                st.session_state.as_crop_result = None
                st.error(str(exc))
                st.exception(exc)

    result = st.session_state.as_crop_result
    if result:
        st.subheader("Date migliori")
        st.dataframe(result["df"], width="stretch", hide_index=True)
        st.caption("Lo score ordina le date per contrasto spettrale; non e una probabilita archeologica.")

        st.subheader("Layer generati")
        result_map = folium.Map(location=result["center"], zoom_start=14, tiles=None)
        cropmarks.add_base_tiles(result_map, esri_show=True)
        folium.GeoJson(
            result["geometry"],
            name="AOI",
            style_function=lambda _x: {"color": "yellow", "weight": 2, "fillOpacity": 0},
        ).add_to(result_map)
        for name, url in result["layers"].items():
            cropmarks.add_layer(result_map, url, name, show=(name == "False color 8-4-3"))
        folium.LayerControl(collapsed=False).add_to(result_map)
        st_folium(result_map, width=1200, height=760, key="as_crop_result_map", returned_objects=[])

        cols = st.columns(3)
        with cols[0]:
            if result["download"]:
                st.link_button("Scarica GeoTIFF", result["download"], width="stretch")
            else:
                st.warning("Download diretto non creato: area probabilmente troppo grande.")
        with cols[1]:
            if result["task_id"]:
                st.success("Export Drive avviato. Task ID: " + result["task_id"])
        with cols[2]:
            st.markdown("Layer chiave: `False color`, `Crop band`, `Soil band`, `TCT RGB`, `PCA`, `Local contrast`.")


def render_rvt_panel():
    st.markdown(
        """
        <div class="as-panel">
          <div class="as-panel-title">RVT LiDAR</div>
          <div class="as-panel-copy">Avvia la GUI RVT esistente. Tutte le funzioni RVT restano nel tool desktop originale.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    python_path = st.text_input("Python per RVT", key="as_rvt_python")
    proc = st.session_state.get("as_rvt_process")
    running = process_running(proc)
    status = '<span class="as-good">attivo</span>' if running else '<span class="as-warn">non avviato</span>'
    st.markdown(f"Processo RVT: {status}", unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Avvia RVT", type="primary", width="stretch", disabled=running):
            launch_rvt(python_path)
            st.rerun()
    with c2:
        if st.button("Termina", width="stretch", disabled=not running):
            stop_process(proc)
            st.session_state.as_rvt_process = None
            st.rerun()

    if st.button("Verifica dipendenze RVT", width="stretch"):
        ok, output = check_rvt_dependencies(python_path)
        if ok:
            st.success(output)
        else:
            st.error(output)

    c3, c4 = st.columns(2)
    with c3:
        if st.button("Apri cartella RVT", width="stretch"):
            open_path(RVT_DIR)
    with c4:
        if st.button("Apri output RVT", width="stretch"):
            open_path(RVT_DIR / "output_rvt_gui")

    log_path = Path(st.session_state.as_rvt_log)
    if log_path.exists():
        with st.expander("Log ultimo avvio"):
            st.code(log_path.read_text(encoding="utf-8", errors="replace")[-4000:])

    st.markdown('<div class="as-strip">Output RVT recenti</div>', unsafe_allow_html=True)
    html_files = latest_files(RVT_DIR / "output_rvt_gui", "*.html", 6)
    if html_files:
        for path in html_files:
            st.markdown(f"`{path.relative_to(PROJECT_ROOT)}`")
    else:
        st.caption("Nessun HTML 3D trovato.")

    with st.expander("Dataset RVT"):
        places = scan_rvt_places()
        if places:
            st.dataframe(pd.DataFrame(places), width="stretch", hide_index=True)
        else:
            st.caption("Nessun posto Database completo rilevato.")


def logo_svg():
    try:
        return LOGO_PATH.read_text(encoding="utf-8")
    except Exception:
        return ""


def default_rvt_python():
    env = os.environ.get("RVT_PYTHON", "").strip()
    if env:
        return env
    candidates = [
        Path.home() / "venvs" / "rvt" / "bin" / "python",
        Path.home() / ".venvs" / "rvt" / "bin" / "python",
        Path("/opt/homebrew/bin/python3.11"),
        Path("/usr/local/bin/python3.11"),
    ]
    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return sys.executable


def process_running(proc):
    return proc is not None and getattr(proc, "poll", lambda: 1)() is None


def launch_rvt(python_path):
    log_path = Path(st.session_state.as_rvt_log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    log = log_path.open("a", encoding="utf-8")
    log.write(f"\n--- RVT launch {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log.flush()
    proc = subprocess.Popen(
        [python_path, str(RVT_ENTRYPOINT)],
        cwd=str(RVT_DIR),
        stdout=log,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,
    )
    st.session_state.as_rvt_process = proc


def stop_process(proc):
    if not process_running(proc):
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def check_rvt_dependencies(python_path):
    code = (
        "import tkinter; "
        "import numpy, rasterio, matplotlib; "
        "import rvt.vis, rvt.blend; "
        "print('OK: tkinter, numpy, rasterio, matplotlib, rvt-py')"
    )
    try:
        result = subprocess.run(
            [python_path, "-c", code],
            cwd=str(RVT_DIR),
            text=True,
            capture_output=True,
            timeout=20,
        )
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output or f"Exit code {result.returncode}"


def open_path(path):
    try:
        subprocess.Popen(["open", str(path)])
    except Exception:
        pass


def scan_rvt_places():
    db = RVT_DIR / "image" / "Database"
    if not db.exists():
        return []
    rows = []
    for place in sorted([p for p in db.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
        if place.name.startswith("."):
            continue
        rows.append(
            {
                "posto": place.name,
                "DTM": count_files(place / "DTM", {".tif", ".tiff", ".asc", ".zip"}),
                "DSM first": count_files(place / "DSM_First", {".tif", ".tiff", ".asc", ".zip"})
                + count_files(place / "DSM_Fisrt", {".tif", ".tiff", ".asc", ".zip"})
                + count_files(place / "DSMfirst", {".tif", ".tiff", ".asc", ".zip"}),
                "DSM last": count_files(place / "DSM_Last", {".tif", ".tiff", ".asc", ".zip"})
                + count_files(place / "DSMlast", {".tif", ".tiff", ".asc", ".zip"}),
                "geojson": "si" if list(place.glob("*.geojson")) or list(place.glob("*.json")) else "no",
            }
        )
    return rows


if __name__ == "__main__":
    main()
