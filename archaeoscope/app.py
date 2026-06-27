import base64
from datetime import date
from html import escape

import folium
import streamlit as st
from folium.plugins import Draw
from streamlit_folium import st_folium

from . import cropmarks_engine as cropmarks
from .paths import LOGO_PATH
from .rvt_web import render_rvt_web


MASE_URL = "https://sim.mase.gov.it/portalediaccesso/mappe/#/viewer/new/"
GOOGLE_EARTH_URL = (
    "https://earth.google.com/web/@42.06329556,13.45871116,984.71472258a,"
    "13332.72240541d,35y,0h,0t,0r/data=CgRCAggBMikKJwolCiExdXloZDBqRERpNUh"
    "zdWs2c3V0SkxHY2VWQ1VFbkwtNFggAToDCgEwQgIIAEoNCP___________wEQAA"
)


def main():
    st.set_page_config(page_title="ArchaeoScope", layout="wide")
    init_state()
    tool = render_navbar()
    if tool == "RVT":
        render_rvt_web()
    else:
        render_cropmarks()


def init_state():
    for key, value in {
        "as_crop_result": None,
        "as_crop_geometry": None,
        "as_active_tool": "RVT",
    }.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_app_styles():
    st.markdown(
        """
        <style>
            .block-container {
                padding-top: 1rem;
            }
            .as-nav {
                align-items: center;
                border-bottom: 1px solid rgba(130, 145, 170, 0.22);
                display: flex;
                gap: 0.7rem;
                margin-bottom: 1.35rem;
                min-height: 2.8rem;
                padding-bottom: 0.7rem;
                width: 100%;
            }
            .as-logo {
                height: 2rem;
                width: 2rem;
            }
            .as-brand {
                color: inherit;
                font-size: 1.45rem;
                font-weight: 800;
                line-height: 1;
                letter-spacing: 0;
                margin-right: 0.25rem;
                white-space: nowrap;
            }
            .as-tabs {
                border: 1px solid rgba(130, 145, 170, 0.34);
                border-radius: 0.45rem;
                display: inline-flex;
                overflow: hidden;
            }
            .as-tab,
            .as-link {
                align-items: center;
                color: rgba(245, 245, 245, 0.9);
                display: inline-flex;
                font-size: 0.88rem;
                font-weight: 700;
                height: 2rem;
                justify-content: center;
                line-height: 1;
                text-decoration: none;
                white-space: nowrap;
            }
            .as-tab {
                min-width: 6.2rem;
                padding: 0 0.85rem;
            }
            .as-tab + .as-tab {
                border-left: 1px solid rgba(130, 145, 170, 0.24);
            }
            .as-tab-active {
                background: rgba(255, 75, 75, 0.14);
                color: rgb(255, 87, 87);
            }
            .as-spacer {
                flex: 1 1 auto;
            }
            .as-link {
                border: 1px solid rgba(130, 145, 170, 0.34);
                border-radius: 0.45rem;
                padding: 0 0.85rem;
            }
            @media (max-width: 760px) {
                .as-nav {
                    flex-wrap: wrap;
                }
                .as-spacer {
                    display: none;
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False)
def logo_data_uri():
    suffix = LOGO_PATH.suffix.lstrip(".") or "png"
    encoded = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    return f"data:image/{suffix};base64,{encoded}"


def active_tool_from_query():
    query_tool = st.query_params.get("tool")
    if isinstance(query_tool, list):
        query_tool = query_tool[0] if query_tool else None
    if query_tool == "crop-marks":
        st.session_state.as_active_tool = "Crop Marks"
    elif query_tool == "rvt":
        st.session_state.as_active_tool = "RVT"
    return st.session_state.as_active_tool


def render_navbar():
    render_app_styles()
    tool = active_tool_from_query()
    rvt_class = " as-tab-active" if tool == "RVT" else ""
    crop_class = " as-tab-active" if tool == "Crop Marks" else ""
    st.markdown(
        f"""
        <nav class="as-nav" aria-label="ArchaeoScope navigation">
            <img class="as-logo" src="{logo_data_uri()}" alt="">
            <div class="as-brand">ArchaeoScope</div>
            <div class="as-tabs" role="tablist" aria-label="Tools">
                <a class="as-tab{rvt_class}" href="?tool=rvt" role="tab">RVT</a>
                <a class="as-tab{crop_class}" href="?tool=crop-marks" role="tab">Crop Marks</a>
            </div>
            <div class="as-spacer"></div>
            <a class="as-link" href="{escape(MASE_URL)}" target="_blank" rel="noreferrer">🛰️ MASE</a>
            <a class="as-link" href="{escape(GOOGLE_EARTH_URL)}" target="_blank" rel="noreferrer">🌍 Google Earth</a>
        </nav>
        """,
        unsafe_allow_html=True,
    )
    return tool


def render_header():
    render_app_styles()
    st.markdown(
        f"""
        <nav class="as-nav" aria-label="ArchaeoScope">
            <img class="as-logo" src="{logo_data_uri()}" alt="">
            <div class="as-brand">ArchaeoScope</div>
        </nav>
        """,
        unsafe_allow_html=True,
    )


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

if __name__ == "__main__":
    main()
