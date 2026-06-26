import os
import subprocess
import sys
import time
import webbrowser
from datetime import date
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from folium.plugins import Draw
from streamlit_folium import st_folium

from . import __version__
from . import cropmarks_engine as cropmarks
from .paths import (
    CROP_README,
    CROP_TOOL_DIR,
    LOGO_PATH,
    PROJECT_ROOT,
    ROOT_README,
    RVT_DIR,
    RVT_ENTRYPOINT,
    RVT_README,
    count_files,
    latest_files,
)


PAGE_OPTIONS = [
    "Command Center",
    "Sentinel-2 Crop Marks",
    "RVT LiDAR",
    "Workflow Integrato",
    "Impostazioni",
]


def main():
    st.set_page_config(page_title="ArchaeoScope", layout="wide")
    apply_theme()
    init_state()
    render_sidebar()

    page = st.session_state.get("nd_page", PAGE_OPTIONS[0])
    if page == "Sentinel-2 Crop Marks":
        render_cropmarks_page()
    elif page == "RVT LiDAR":
        render_rvt_page()
    elif page == "Workflow Integrato":
        render_workflow_page()
    elif page == "Impostazioni":
        render_settings_page()
    else:
        render_command_center()


def apply_theme():
    st.markdown(
        """
        <style>
        :root {
            --nd-bg: #11130f;
            --nd-panel: #1b1e18;
            --nd-panel-2: #23271f;
            --nd-text: #f4f0e8;
            --nd-muted: #b8b3a7;
            --nd-line: #383d32;
            --nd-teal: #4fb7a5;
            --nd-amber: #d8843a;
            --nd-green: #b8ce68;
            --nd-red: #d2635f;
        }
        .stApp {
            background: var(--nd-bg);
            color: var(--nd-text);
        }
        [data-testid="stSidebar"] {
            background: #161911;
            border-right: 1px solid var(--nd-line);
        }
        h1, h2, h3 {
            letter-spacing: 0;
        }
        .nd-title {
            font-size: 34px;
            line-height: 1.05;
            font-weight: 760;
            margin: 0 0 8px 0;
        }
        .as-brand {
            display: flex;
            align-items: center;
            gap: 14px;
            margin: 0 0 18px 0;
        }
        .as-brand-logo {
            width: 70px;
            height: 70px;
            flex: 0 0 70px;
        }
        .as-brand-logo svg {
            width: 70px;
            height: 70px;
            display: block;
        }
        .as-sidebar-logo svg {
            width: 82px;
            height: 82px;
            display: block;
            margin-bottom: 8px;
        }
        .nd-subtitle {
            color: var(--nd-muted);
            font-size: 15px;
            margin: 0 0 18px 0;
        }
        .nd-card {
            border: 1px solid var(--nd-line);
            background: var(--nd-panel);
            border-radius: 8px;
            padding: 16px 16px 14px 16px;
            min-height: 132px;
        }
        .nd-card h3 {
            margin: 0 0 8px 0;
            font-size: 18px;
        }
        .nd-card p {
            color: var(--nd-muted);
            margin: 0;
            font-size: 14px;
            line-height: 1.38;
        }
        .nd-strip {
            border: 1px solid var(--nd-line);
            background: var(--nd-panel-2);
            border-radius: 8px;
            padding: 14px 16px;
        }
        .nd-pill {
            display: inline-block;
            border: 1px solid var(--nd-line);
            border-radius: 999px;
            padding: 5px 10px;
            margin-right: 8px;
            color: var(--nd-muted);
            font-size: 12px;
        }
        .nd-good {
            color: var(--nd-green);
        }
        .nd-warn {
            color: var(--nd-amber);
        }
        .nd-bad {
            color: var(--nd-red);
        }
        div[data-testid="stMetric"] {
            border: 1px solid var(--nd-line);
            background: var(--nd-panel);
            border-radius: 8px;
            padding: 12px 14px;
        }
        .stButton > button, .stDownloadButton > button {
            border-radius: 8px;
            border: 1px solid #4f5b48;
            background: #252a21;
            color: var(--nd-text);
            min-height: 38px;
        }
        .stButton > button:hover, .stDownloadButton > button:hover {
            border-color: var(--nd-teal);
            color: #ffffff;
        }
        .stLinkButton > a {
            border-radius: 8px;
        }
        div[data-testid="stDataFrame"] {
            border: 1px solid var(--nd-line);
            border-radius: 8px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def init_state():
    defaults = {
        "nd_page": PAGE_OPTIONS[0],
        "nd_crop_result": None,
        "nd_crop_geometry": None,
        "nd_rvt_python": default_rvt_python(),
        "nd_rvt_process": None,
        "nd_rvt_log": str(PROJECT_ROOT / ".rvt_launch.log"),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_sidebar():
    st.sidebar.markdown(f'<div class="as-sidebar-logo">{logo_svg()}</div>', unsafe_allow_html=True)
    st.sidebar.markdown("### ArchaeoScope")
    st.sidebar.caption(f"ArchaeoScope workspace v{__version__}")
    st.sidebar.radio("Area", PAGE_OPTIONS, key="nd_page")
    st.sidebar.divider()
    project = cropmarks.default_project()
    st.sidebar.caption("Earth Engine")
    st.sidebar.markdown(f"`{project or 'non configurato'}`")
    st.sidebar.caption("Workspace")
    st.sidebar.markdown(f"`{PROJECT_ROOT}`")


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


def navigate(page):
    st.session_state.nd_page = page
    st.rerun()


def render_header(title, subtitle):
    st.markdown(
        f"""
        <div class="as-brand">
          <div class="as-brand-logo">{logo_svg()}</div>
          <div>
            <div class="nd-title">{title}</div>
            <div class="nd-subtitle">{subtitle}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def logo_svg():
    try:
        return LOGO_PATH.read_text(encoding="utf-8")
    except Exception:
        return ""


def render_command_center():
    render_header("ArchaeoScope", "Un unico banco di lavoro per segnali da satellite, rilievo LiDAR e verifica archeologica.")

    cols = st.columns(3)
    with cols[0]:
        st.markdown(
            """
            <div class="nd-card">
              <h3>Sentinel-2 Crop Marks</h3>
              <p>Disegno AOI, date migliori, indici vegetazionali, Tasseled Cap, PCA, anomalie, download GeoTIFF ed export Drive.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Apri analisi Sentinel-2", width="stretch"):
            navigate("Sentinel-2 Crop Marks")
    with cols[1]:
        st.markdown(
            """
            <div class="nd-card">
              <h3>RVT LiDAR</h3>
              <p>GUI completa RVT con DTM, DSM, nDSM, First-Last, metodi RVT, basemap, annotazioni, report, KML e viewer 3D.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Apri banco LiDAR", width="stretch"):
            navigate("RVT LiDAR")
    with cols[2]:
        st.markdown(
            """
            <div class="nd-card">
              <h3>Workflow Integrato</h3>
              <p>Sequenza operativa unica: screening multispettrale, controllo morfologico LiDAR, raccolta output e report finale.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Apri workflow", width="stretch"):
            navigate("Workflow Integrato")

    st.divider()
    render_workspace_status()
    st.divider()
    render_recent_outputs()


def render_workspace_status():
    st.subheader("Stato workspace")
    rvt_data_count = count_files(RVT_DIR / "image", {".tif", ".tiff", ".asc", ".zip"})
    rvt_output_count = count_files(RVT_DIR / "output_rvt_gui")
    generated_count = count_files(RVT_DIR / "generated_dtm")
    crop_venv = CROP_TOOL_DIR / ".venv"

    cols = st.columns(4)
    cols[0].metric("Raster LiDAR", rvt_data_count)
    cols[1].metric("Output RVT", rvt_output_count)
    cols[2].metric("DTM generati", generated_count)
    cols[3].metric("Crop env", "presente" if crop_venv.exists() else "assente")


def render_recent_outputs():
    st.subheader("Output recenti")
    html_files = latest_files(RVT_DIR / "output_rvt_gui", "*.html", 6)
    pdf_files = latest_files(RVT_DIR / "output_rvt_gui", "*.pdf", 6)
    kml_files = latest_files(RVT_DIR / "output_rvt_gui", "*.kml", 6)
    rows = []
    for kind, files in (("3D HTML", html_files), ("PDF", pdf_files), ("KML", kml_files)):
        for path in files:
            rows.append({"tipo": kind, "file": path.name, "cartella": str(path.parent.relative_to(PROJECT_ROOT))})
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.info("Nessun output recente trovato.")


def render_cropmarks_page(standalone=False):
    if standalone:
        apply_theme()
        init_state()
    render_header("Sentinel-2 Crop Marks", "Screening multispettrale con Earth Engine, indici, PCA e mappe di anomalia.")

    control, canvas = st.columns([0.32, 0.68], gap="large")
    with control:
        st.markdown('<div class="nd-strip">Parametri analisi</div>', unsafe_allow_html=True)
        project = st.text_input("Google Earth Engine project", cropmarks.default_project(), key="nd_crop_project")
        start = st.date_input("Da", date(2016, 1, 1), key="nd_crop_start")
        end = st.date_input("A", date(2019, 12, 31), key="nd_crop_end")
        cloud = st.slider("Cloud cover metadata (%)", 0, 100, 10, key="nd_crop_cloud")
        topn = st.slider("Date migliori da combinare", 1, 20, 5, key="nd_crop_topn")
        mode = st.selectbox("Immagine base", ["Migliore singola data", "Mediana migliori date"], key="nd_crop_mode")
        export = st.checkbox("Export GeoTIFF su Google Drive", False, key="nd_crop_export")
        folder = st.text_input("Cartella Drive", "S2_cropmarks", key="nd_crop_folder")

        run = st.button("Avvia analisi", type="primary", width="stretch")
        reset = st.button("Reset analisi", width="stretch")
        if reset:
            st.session_state.nd_crop_result = None
            st.session_state.nd_crop_geometry = None
            st.rerun()

    with canvas:
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
        draw = st_folium(
            draw_map,
            width=1200,
            height=560,
            key="nd_crop_draw_map",
            returned_objects=["all_drawings"],
        )

    if run:
        if start > end:
            st.error("La data iniziale deve precedere la data finale.")
            st.stop()
        drawings = draw.get("all_drawings") or []
        if drawings:
            st.session_state.nd_crop_geometry = drawings[-1]["geometry"]
        if not st.session_state.nd_crop_geometry:
            st.error("Disegna prima un poligono o un rettangolo sulla mappa.")
            st.stop()
        if project:
            cropmarks.save_default_project(project)
        with st.spinner("Analisi in corso. Attendo Earth Engine..."):
            try:
                st.session_state.nd_crop_result = cropmarks.run_analysis(
                    project,
                    start,
                    end,
                    cloud,
                    topn,
                    mode,
                    export,
                    folder,
                    st.session_state.nd_crop_geometry,
                )
            except Exception as exc:
                st.session_state.nd_crop_result = None
                st.error(str(exc))
                st.exception(exc)

    result = st.session_state.nd_crop_result
    if result:
        st.divider()
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
        st_folium(
            result_map,
            width=1200,
            height=760,
            key="nd_crop_result_map",
            returned_objects=[],
        )

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


def render_rvt_page():
    render_header("RVT LiDAR", "Il motore RVT resta completo: lo avvii da qui e lavori nella GUI desktop originale.")

    left, right = st.columns([0.36, 0.64], gap="large")
    with left:
        st.markdown('<div class="nd-strip">Launcher RVT</div>', unsafe_allow_html=True)
        python_path = st.text_input("Python per RVT", st.session_state.nd_rvt_python, key="nd_rvt_python")
        proc = st.session_state.get("nd_rvt_process")
        running = process_running(proc)
        status = '<span class="nd-good">attivo</span>' if running else '<span class="nd-warn">non avviato</span>'
        st.markdown(f"Processo RVT: {status}", unsafe_allow_html=True)
        cols = st.columns(2)
        with cols[0]:
            if st.button("Avvia RVT", type="primary", width="stretch", disabled=running):
                launch_rvt(python_path)
                st.rerun()
        with cols[1]:
            if st.button("Termina", width="stretch", disabled=not running):
                stop_process(proc)
                st.session_state.nd_rvt_process = None
                st.rerun()

        if st.button("Verifica dipendenze RVT", width="stretch"):
            ok, output = check_rvt_dependencies(python_path)
            if ok:
                st.success(output)
            else:
                st.error(output)

        log_path = Path(st.session_state.nd_rvt_log)
        if log_path.exists():
            with st.expander("Log ultimo avvio"):
                st.code(log_path.read_text(encoding="utf-8", errors="replace")[-4000:])

        st.divider()
        open_cols = st.columns(2)
        with open_cols[0]:
            if st.button("Apri cartella RVT", width="stretch"):
                open_path(RVT_DIR)
        with open_cols[1]:
            if st.button("Apri output RVT", width="stretch"):
                open_path(RVT_DIR / "output_rvt_gui")

    with right:
        render_rvt_inventory()


def render_rvt_inventory():
    st.subheader("Dataset e output")
    places = scan_rvt_places()
    if places:
        st.dataframe(pd.DataFrame(places), width="stretch", hide_index=True)
    else:
        st.info("Nessun posto Database completo rilevato.")

    st.subheader("Viewer 3D recenti")
    html_files = latest_files(RVT_DIR / "output_rvt_gui", "*.html", 8)
    if html_files:
        for path in html_files:
            cols = st.columns([0.78, 0.22])
            cols[0].markdown(f"`{path.relative_to(PROJECT_ROOT)}`")
            if cols[1].button("Apri", key=f"open_html_{path}", width="stretch"):
                open_path(path)
    else:
        st.caption("Nessun HTML 3D trovato.")


def render_workflow_page():
    render_header("Workflow Integrato", "Dallo screening dell'area candidata alla verifica morfologica e alla raccolta degli output.")

    cols = st.columns(3)
    cards = [
        (
            "1. Screening multispettrale",
            "AOI su mappa, ranking date Sentinel-2, indici, PCA, anomaly score e GeoTIFF multibanda.",
            "Sentinel-2 Crop Marks",
            "Apri Sentinel-2",
        ),
        (
            "2. Controllo morfologico",
            "DTM/DSM, metodi RVT, basemap storica, annotazioni, misura, report, KML e 3D Cloud.",
            "RVT LiDAR",
            "Apri RVT",
        ),
        (
            "3. Raccolta output",
            "Tieni insieme HTML 3D, PDF, KML, GeoTIFF e note operative per confrontare i segnali.",
            None,
            "Aggiorna output",
        ),
    ]
    for col, (title, body, target, label) in zip(cols, cards):
        with col:
            st.markdown(f'<div class="nd-card"><h3>{title}</h3><p>{body}</p></div>', unsafe_allow_html=True)
            if st.button(label, key=f"workflow_{title}", width="stretch"):
                if target:
                    navigate(target)
                else:
                    st.rerun()

    st.divider()
    render_recent_outputs()


def render_settings_page():
    render_header("Impostazioni", "Configurazione locale per Earth Engine, interprete RVT e documentazione.")

    col_a, col_b = st.columns(2, gap="large")
    with col_a:
        st.subheader("Earth Engine")
        project = st.text_input("Project ID", cropmarks.default_project(), key="nd_settings_project")
        if st.button("Salva project ID", width="stretch"):
            cropmarks.save_default_project(project)
            st.success("Project ID salvato.")

        if st.button("Verifica Earth Engine", width="stretch"):
            try:
                cropmarks.init_ee(project)
                st.success("Earth Engine inizializzato correttamente.")
            except Exception as exc:
                st.error(str(exc))

    with col_b:
        st.subheader("RVT")
        python_path = st.text_input("Interprete Python RVT", st.session_state.nd_rvt_python, key="nd_settings_rvt_python")
        if st.button("Usa questo interprete", width="stretch"):
            st.session_state.nd_rvt_python = python_path
            st.success("Interprete aggiornato.")
        if st.button("Check stack LiDAR", width="stretch"):
            ok, output = check_rvt_dependencies(python_path)
            if ok:
                st.success(output)
            else:
                st.error(output)

    st.divider()
    st.subheader("Documentazione")
    doc_cols = st.columns(3)
    with doc_cols[0]:
        if st.button("README principale", width="stretch"):
            open_path(ROOT_README)
    with doc_cols[1]:
        if st.button("README RVT", width="stretch"):
            open_path(RVT_README)
    with doc_cols[2]:
        if st.button("README Crop Marks", width="stretch"):
            open_path(CROP_README)


def process_running(proc):
    return proc is not None and getattr(proc, "poll", lambda: 1)() is None


def launch_rvt(python_path):
    log_path = Path(st.session_state.nd_rvt_log)
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
    st.session_state.nd_rvt_process = proc


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
    path = Path(path)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif os.name == "nt":
            os.startfile(str(path))  # noqa: S606,S607
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        if path.is_file():
            webbrowser.open(path.resolve().as_uri())


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
