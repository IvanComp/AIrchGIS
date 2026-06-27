from datetime import date

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
            .as-brand {
                color: inherit;
                font-size: 1.35rem;
                font-weight: 800;
                line-height: 1;
                letter-spacing: 0;
                margin: 0;
                white-space: nowrap;
            }
            .as-nav-rule {
                border-bottom: 1px solid rgba(130, 145, 170, 0.22);
                margin: 0.35rem 0 1.1rem;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_navbar():
    render_app_styles()
    logo_col, title_col, tool_col, mase_col, earth_col, _spacer = st.columns(
        [0.04, 0.18, 0.25, 0.11, 0.16, 0.26],
        gap="small",
        vertical_alignment="center",
    )
    with logo_col:
        st.image(str(LOGO_PATH), width=32)
    with title_col:
        st.markdown('<div class="as-brand">ArchaeoScope</div>', unsafe_allow_html=True)
    with tool_col:
        tool = st.segmented_control(
            "Tool",
            ["RVT", "Crop Marks"],
            key="as_active_tool",
            label_visibility="collapsed",
            width="content",
        )
    with mase_col:
        st.link_button("🛰️ MASE", MASE_URL, width="content")
    with earth_col:
        st.link_button("🌍 Google Earth", GOOGLE_EARTH_URL, width="content")
    st.markdown('<div class="as-nav-rule"></div>', unsafe_allow_html=True)
    return tool


def render_header():
    render_app_styles()
    logo_col, title_col = st.columns([0.04, 0.96], vertical_alignment="center")
    with logo_col:
        st.image(str(LOGO_PATH), width=32)
    with title_col:
        st.markdown('<div class="as-brand">ArchaeoScope</div>', unsafe_allow_html=True)
    st.markdown('<div class="as-nav-rule"></div>', unsafe_allow_html=True)


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
