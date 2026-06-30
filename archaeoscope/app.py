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
        "as_crop_active_layer": None,
        "as_active_tool": "RVT",
    }.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_app_styles():
    st.markdown(
        """
        <style>
            :root {
                --as-brown-900: #15100b;
                --as-brown-800: #21170f;
                --as-brown-700: #302014;
                --as-brown-600: #4a2c16;
                --as-gold-500: #d4af37;
                --as-gold-400: #f1c75b;
                --as-text: #f7ecd7;
                --as-muted: #c7b899;
            }
            header[data-testid="stHeader"],
            div[data-testid="stToolbar"],
            div[data-testid="stDecoration"],
            div[data-testid="stStatusWidget"],
            div[data-testid="stDeployButton"],
            button[data-testid="stDeployButton"],
            .stDeployButton,
            #MainMenu,
            footer {
                display: none;
                visibility: hidden;
            }
            .stApp {
                background: var(--as-brown-900);
                color: var(--as-text);
            }
            .block-container {
                padding-top: 1.4rem;
            }
            section[data-testid="stSidebar"] {
                background-color: var(--as-brown-800);
                border-right: 1px solid rgba(212, 175, 55, 0.18);
            }
            .as-brand {
                color: var(--as-gold-400);
                font-size: 1.35rem;
                font-weight: 800;
                line-height: 1;
                letter-spacing: 0;
                margin: 0;
                white-space: nowrap;
            }
            .as-nav-rule {
                border-bottom: 1px solid rgba(212, 175, 55, 0.32);
                margin: 0.35rem 0 1.1rem;
            }
            div[data-testid="stButton"] > button,
            div[data-testid="stLinkButton"] > a {
                background: var(--as-brown-800);
                border: 1px solid rgba(212, 175, 55, 0.36);
                color: var(--as-text);
                font-weight: 700;
            }
            div[data-testid="stButton"] > button:hover,
            div[data-testid="stLinkButton"] > a:hover {
                background: var(--as-brown-700);
                border-color: var(--as-gold-500);
                color: var(--as-gold-400);
            }
            div[data-testid="stButton"] > button[kind="primary"] {
                background: linear-gradient(180deg, var(--as-gold-400), var(--as-gold-500));
                border-color: var(--as-gold-400);
                color: #171008;
            }
            div[data-testid="stRadio"] [role="radiogroup"] label,
            div[data-testid="stCheckbox"] label,
            div[data-testid="stSlider"] label,
            div[data-testid="stSelectbox"] label {
                color: var(--as-text);
            }
            div[data-baseweb="select"] > div,
            div[data-testid="stTextInput"] input,
            div[data-testid="stNumberInput"] input,
            div[data-testid="stDateInput"] input,
            textarea {
                background-color: var(--as-brown-700);
                border-color: rgba(212, 175, 55, 0.28);
                color: var(--as-text);
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_navbar():
    render_app_styles()
    logo_col, title_col, tool_col, mase_col, earth_col, _spacer = st.columns(
        [0.035, 0.15, 0.19, 0.09, 0.14, 0.395],
        gap="small",
        vertical_alignment="center",
    )
    with logo_col:
        st.image(str(LOGO_PATH), width=32)
    with title_col:
        st.markdown('<div class="as-brand">ArchaeoScope</div>', unsafe_allow_html=True)
    with tool_col:
        tool = render_tool_switch()
    with mase_col:
        st.link_button("🛰️ MASE", MASE_URL, width="content")
    with earth_col:
        st.link_button("🌍 Google Earth", GOOGLE_EARTH_URL, width="content")
    st.markdown('<div class="as-nav-rule"></div>', unsafe_allow_html=True)
    return tool


def render_tool_switch():
    active = st.session_state.as_active_tool
    rvt_col, crop_col = st.columns(2, gap="small")
    with rvt_col:
        if st.button("RVT", key="as_nav_rvt", type="primary" if active == "RVT" else "secondary", width="stretch"):
            st.session_state.as_active_tool = "RVT"
    with crop_col:
        if st.button(
            "Crop Marks",
            key="as_nav_crop",
            type="primary" if active == "Crop Marks" else "secondary",
            width="stretch",
        ):
            st.session_state.as_active_tool = "Crop Marks"
    return st.session_state.as_active_tool


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
        layer_names = list(result["layers"].keys())
        if st.session_state.as_crop_active_layer not in layer_names:
            st.session_state.as_crop_active_layer = "False color 8-4-3" if "False color 8-4-3" in layer_names else layer_names[0]
        active_layer = st.selectbox(
            "Filtro",
            layer_names,
            key="as_crop_active_layer",
        )
        result_map = folium.Map(location=result["center"], zoom_start=14, tiles=None)
        cropmarks.add_base_tiles(result_map, esri_show=True)
        folium.GeoJson(
            result["geometry"],
            name="AOI",
            style_function=lambda _x: {"color": "yellow", "weight": 2, "fillOpacity": 0},
        ).add_to(result_map)
        cropmarks.add_layer(result_map, result["layers"][active_layer], active_layer, show=True)
        folium.LayerControl(collapsed=False).add_to(result_map)
        st_folium(result_map, width=1200, height=760, key=f"as_crop_result_map_{active_layer}", returned_objects=[])

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
            st.write("Layer utili: False color, Crop band, Soil band, Possibili strutture - erba bassa, Local contrast.")

if __name__ == "__main__":
    main()
