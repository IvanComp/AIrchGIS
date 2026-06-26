import os
import subprocess
import sys
import time
from datetime import date, datetime

import folium
import streamlit as st
from folium.plugins import Draw
from streamlit_folium import st_folium

from . import cropmarks_engine as cropmarks
from .paths import LOGO_PATH, PROJECT_ROOT, RVT_DIR, RVT_ENTRYPOINT


def main():
    st.set_page_config(page_title="ArchaeoScope", layout="wide")
    init_state()
    render_header()

    rvt_col, crop_col = st.columns([0.18, 0.82], gap="large")
    with rvt_col:
        render_rvt()
    with crop_col:
        render_cropmarks()


def init_state():
    for key, value in {
        "as_crop_result": None,
        "as_crop_geometry": None,
        "as_rvt_process": None,
        "as_rvt_error": None,
    }.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_header():
    logo_col, title_col = st.columns([0.06, 0.94])
    with logo_col:
        st.image(str(LOGO_PATH), width=64)
    with title_col:
        st.title("ArchaeoScope")


def render_rvt():
    st.subheader("RVT")
    running = process_running(st.session_state.as_rvt_process)
    if st.session_state.as_rvt_error:
        st.error(st.session_state.as_rvt_error)
    if st.button("RVT", type="primary", width="stretch", disabled=running):
        st.session_state.as_rvt_error = None
        try:
            process = launch_rvt()
            time.sleep(0.8)
            if process.poll() is None:
                st.session_state.as_rvt_process = process
            else:
                st.session_state.as_rvt_process = None
                st.session_state.as_rvt_error = "RVT non si e avviato."
        except Exception:
            st.session_state.as_rvt_process = None
            st.session_state.as_rvt_error = "RVT non si e avviato."
        st.rerun()
    if running and st.button("Chiudi RVT", width="stretch"):
        stop_process(st.session_state.as_rvt_process)
        st.session_state.as_rvt_process = None
        st.session_state.as_rvt_error = None
        st.rerun()


def render_cropmarks(standalone=False):
    if standalone:
        init_state()
        render_header()

    st.title("Sentinel-2 crop marks enhancement")
    st.write("Disegna un poligono o un rettangolo sulla mappa, imposta periodo e nuvole, poi avvia l'analisi.")

    with st.sidebar:
        project = st.text_input("Google Earth Engine project", cropmarks.default_project(), key="as_crop_project")
        start = st.date_input("Da", date(2016, 1, 1), key="as_crop_start")
        end = st.date_input("A", date(2019, 12, 31), key="as_crop_end")
        cloud = st.slider("Cloud cover massimo metadata (%)", 0, 100, 10, key="as_crop_cloud")
        topn = st.slider("Date migliori da combinare", 1, 20, 5, key="as_crop_topn")
        mode = st.selectbox("Immagine base", ["Migliore singola data", "Mediana migliori date"], key="as_crop_mode")
        export = st.checkbox("Esporta GeoTIFF su Google Drive", False, key="as_crop_export")
        folder = st.text_input("Cartella Drive", "S2_cropmarks", key="as_crop_folder")
        run = st.button("Avvia analisi", type="primary")
        reset = st.button("Reset analisi")

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
    draw = st_folium(draw_map, width=1200, height=520, key="as_crop_draw_map", returned_objects=["all_drawings"])

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
        with st.spinner("Analisi in corso. Non interagire con la pagina finche non appare il risultato."):
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
        st.info("La tabella ordina le date con maggiore contrasto spettrale. Lo score non e una probabilita archeologica.")

        st.subheader("Mappa dei layer generati")
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
                st.link_button("Scarica GeoTIFF", result["download"])
            else:
                st.warning("Download diretto non creato: area troppo grande. Usa export su Drive.")
        with cols[1]:
            if result["task_id"]:
                st.success("Export Drive avviato. Task ID: " + result["task_id"])
        with cols[2]:
            st.write("Layer utili: False color, Crop band, Soil band, TCT RGB, PCA, Local contrast.")


def process_running(proc):
    return proc is not None and getattr(proc, "poll", lambda: 1)() is None


def launch_rvt():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    log = open(PROJECT_ROOT / ".rvt_launch.log", "a", encoding="utf-8")
    log.write(f"\n--- {datetime.now().isoformat(timespec='seconds')} ---\n")
    log.flush()
    return subprocess.Popen(
        [default_rvt_python(), str(RVT_ENTRYPOINT)],
        cwd=str(RVT_DIR),
        stdout=log,
        stderr=log,
        env=env,
        start_new_session=True,
    )


def default_rvt_python():
    env = os.environ.get("RVT_PYTHON", "").strip()
    if env and rvt_python_works(env):
        return env
    candidates = [
        str(PROJECT_ROOT / ".venv-rvt" / "bin" / "python"),
        "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12",
        "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3",
        "/usr/local/bin/python3",
        os.path.expanduser("~/.pyenv/shims/python3"),
        "/usr/local/bin/python",
        "/usr/bin/python3",
        os.path.expanduser("~/.pyenv/shims/python"),
        "/opt/homebrew/bin/python3.13",
        sys.executable,
        os.path.expanduser("~/venvs/rvt/bin/python"),
        os.path.expanduser("~/.venvs/rvt/bin/python"),
        "/opt/homebrew/bin/python3.11",
    ]
    for candidate in candidates:
        if rvt_python_works(candidate):
            return candidate
    return sys.executable


def rvt_python_works(candidate):
    if not candidate or not os.path.exists(candidate) or not os.access(candidate, os.X_OK):
        return False
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    code = "import tkinter, numpy, rasterio, matplotlib, PIL, requests, rvt.vis, rvt.blend"
    try:
        subprocess.run(
            [candidate, "-c", code],
            cwd=str(RVT_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            timeout=15,
            check=True,
        )
    except Exception:
        return False
    return True


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


if __name__ == "__main__":
    main()
