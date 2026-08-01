import logging
from datetime import date

import folium
import streamlit as st
from folium.plugins import Draw
from streamlit_folium import st_folium

from . import candidate_store
from . import cropmarks_engine as cropmarks
from .archaeological_database import render_archaeological_database
from .paths import LOGO_PATH
from .rvt_web import render_rvt_web


LOGGER = logging.getLogger(__name__)


MASE_URL = "https://sim.mase.gov.it/portalediaccesso/mappe/#/viewer/new/"
GOOGLE_EARTH_URL = (
    "https://earth.google.com/web/@42.06329556,13.45871116,984.71472258a,"
    "13332.72240541d,35y,0h,0t,0r/data=CgRCAggBMikKJwolCiExdXloZDBqRERpNUh"
    "zdWs2c3V0SkxHY2VWQ1VFbkwtNFggAToDCgEwQgIIAEoNCP___________wEQAA"
)
PRIMARY_TOOLS = ("RVT", "Crop Marks", "Database", "Candidati")


def main():
    st.set_page_config(page_title="ArchaeoScope", layout="wide")
    init_state()
    tool = render_navbar()
    if tool == "RVT":
        render_rvt_web()
    elif tool == "Crop Marks":
        render_cropmarks()
    elif tool == "Database":
        render_archaeological_database()
    else:
        render_candidates()


def init_state():
    for key, value in {
        "as_crop_result": None,
        "as_crop_geometry": None,
        "as_crop_active_layer": None,
        "as_crop_source_record": None,
        "as_active_tool": "RVT",
    }.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_app_styles():
    st.markdown(
        """
        <style>
            :root {
                --as-brown-950: #0f0c08;
                --as-brown-900: #15100b;
                --as-brown-850: #1b130d;
                --as-brown-800: #21170f;
                --as-brown-700: #302014;
                --as-brown-600: #4a2c16;
                --as-gold-500: #d4af37;
                --as-gold-400: #f1c75b;
                --as-text: #f7ecd7;
                --as-muted: #c7b899;
                --as-line: rgba(212, 175, 55, 0.24);
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
                background:
                    linear-gradient(180deg, rgba(241, 199, 91, 0.05), rgba(15, 12, 8, 0) 220px),
                    var(--as-brown-950);
                color: var(--as-text);
            }
            .block-container {
                padding-top: 1.05rem;
                padding-bottom: 2.2rem;
            }
            section[data-testid="stSidebar"] {
                background-color: var(--as-brown-800);
                border-right: 1px solid rgba(212, 175, 55, 0.18);
            }
            .as-brand {
                color: var(--as-gold-400);
                font-size: 1.42rem;
                font-weight: 800;
                line-height: 1;
                letter-spacing: 0;
                margin: 0;
                white-space: nowrap;
            }
            .as-nav-rule {
                border-bottom: 1px solid var(--as-line);
                margin: 0.85rem 0 1.1rem;
            }
            div[data-testid="stButton"] > button {
                background: var(--as-brown-800);
                border: 1px solid rgba(212, 175, 55, 0.36);
                border-radius: 8px;
                color: var(--as-text);
                font-weight: 700;
                min-height: 2.55rem;
            }
            div[data-testid="stButton"] > button:hover {
                background: var(--as-brown-700);
                border-color: var(--as-gold-500);
                color: var(--as-gold-400);
            }
            div[data-testid="stButton"] > button[kind="primary"] {
                background: linear-gradient(180deg, var(--as-gold-400), var(--as-gold-500));
                border-color: var(--as-gold-400);
                color: #171008;
            }
            .as-utility {
                align-items: center;
                display: flex;
                gap: 0.45rem;
                justify-content: flex-end;
            }
            .as-utility-label {
                color: var(--as-muted);
                font-size: 0.72rem;
                font-weight: 800;
                letter-spacing: 0.08em;
                margin-right: 0.2rem;
                text-transform: uppercase;
            }
            .as-utility-link {
                align-items: center;
                border: 1px solid rgba(212, 175, 55, 0.22);
                border-radius: 999px;
                color: #eadcc5 !important;
                display: inline-flex;
                font-size: 0.78rem;
                font-weight: 800;
                gap: 0.34rem;
                padding: 0.36rem 0.62rem;
                text-decoration: none !important;
                white-space: nowrap;
            }
            .as-utility-icon {
                font-size: 0.9rem;
                line-height: 1;
            }
            .as-utility-link:hover {
                background: rgba(212, 175, 55, 0.12);
                border-color: rgba(241, 199, 91, 0.48);
                color: var(--as-gold-400) !important;
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
    logo_col, title_col, tool_col, utility_col = st.columns(
        [0.045, 0.175, 0.47, 0.31],
        gap="small",
        vertical_alignment="center",
    )
    with logo_col:
        st.image(str(LOGO_PATH), width=40)
    with title_col:
        st.markdown('<div class="as-brand">ArchaeoScope</div>', unsafe_allow_html=True)
    with tool_col:
        tool = render_tool_switch()
    with utility_col:
        st.markdown(
            f"""
            <div class="as-utility">
                <span class="as-utility-label">Risorse</span>
                <a class="as-utility-link" href="{MASE_URL}" target="_blank" rel="noopener"><span class="as-utility-icon">🛰️</span>MASE</a>
                <a class="as-utility-link" href="{GOOGLE_EARTH_URL}" target="_blank" rel="noopener"><span class="as-utility-icon">🌍</span>Google Earth</a>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown('<div class="as-nav-rule"></div>', unsafe_allow_html=True)
    return tool


def render_tool_switch():
    active = st.session_state.get("as_active_tool", "RVT")
    if active not in PRIMARY_TOOLS:
        active = "Database"
        st.session_state.as_active_tool = active

    for column, label, key in zip(
        st.columns(len(PRIMARY_TOOLS), gap="small"),
        PRIMARY_TOOLS,
        ("as_nav_rvt", "as_nav_crop", "as_nav_database", "as_nav_candidates"),
    ):
        with column:
            if st.button(
                label,
                key=key,
                type="primary" if active == label else "secondary",
                width="stretch",
            ):
                st.session_state.as_active_tool = label
                st.rerun()
    return st.session_state.as_active_tool


def render_header():
    render_app_styles()
    logo_col, title_col = st.columns([0.05, 0.95], vertical_alignment="center")
    with logo_col:
        st.image(str(LOGO_PATH), width=40)
    with title_col:
        st.markdown('<div class="as-brand">ArchaeoScope</div>', unsafe_allow_html=True)
    st.markdown('<div class="as-nav-rule"></div>', unsafe_allow_html=True)


def render_cropmarks(standalone=False):
    if standalone:
        init_state()
        render_header()
        st.title("Sentinel-2 crop marks enhancement")
        st.write("Disegna un poligono o un rettangolo sulla mappa, imposta periodo e nuvole, poi avvia l'analisi.")

    source_record = st.session_state.get("as_crop_source_record")
    if source_record:
        source_label = " · ".join(
            value
            for value in [
                source_record.get("number"),
                source_record.get("comune"),
                source_record.get("localita"),
            ]
            if value
        )
        st.info(f"AOI derivata dalla scheda documentale: {source_label}")

    with st.sidebar:
        project = st.text_input("Google Earth Engine project", cropmarks.default_project(), key="as_crop_project")
        start = st.date_input("Da", date(max(2016, date.today().year - 3), 1, 1), key="as_crop_start")
        end = st.date_input("A", date.today(), key="as_crop_end")
        cloud = st.slider("Nuvole massime scena (%)", 0, 100, 35, key="as_crop_cloud")
        pixel_cloud = st.slider(
            "Probabilita nuvola per pixel (%)",
            0,
            100,
            cropmarks.DEFAULT_PIXEL_CLOUD,
            key="as_crop_pixel_cloud",
        )
        topn = st.slider("Date migliori da combinare", 1, 20, 8, key="as_crop_topn")
        mode = st.selectbox("Immagine base", ["Migliore singola data", "Mediana migliori date"], key="as_crop_mode")
        persistence_threshold = st.slider(
            "Soglia persistenza locale",
            0.8,
            2.5,
            cropmarks.DEFAULT_PERSISTENCE_THRESHOLD,
            0.05,
            key="as_crop_persistence_threshold",
            help="Contrasto locale minimo per contare un'anomalia in una data.",
        )
        export = st.checkbox("Esporta GeoTIFF su Google Drive", False, key="as_crop_export")
        folder = st.text_input("Cartella Drive", "S2_cropmarks", key="as_crop_folder")
        run = st.button("Avvia analisi", type="primary")
        reset = st.button("Reset analisi")

    if reset:
        st.session_state.as_crop_result = None
        st.session_state.as_crop_geometry = None
        st.session_state.as_crop_source_record = None
        st.session_state.as_crop_active_layer = None
        st.rerun()

    draw_map = folium.Map(location=[41.5, 15.5], zoom_start=9, tiles=None)
    cropmarks.add_base_tiles(draw_map, esri_show=True)
    if st.session_state.as_crop_geometry:
        folium.GeoJson(
            st.session_state.as_crop_geometry,
            name="AOI attiva",
            style_function=lambda _feature: {"color": "#ffd166", "weight": 3, "fillOpacity": 0.08},
        ).add_to(draw_map)
        bounds = cropmarks.geometry_bounds(st.session_state.as_crop_geometry)
        if bounds:
            draw_map.fit_bounds(bounds, padding=(24, 24))
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
                    pixel_cloud=pixel_cloud,
                    persistence_threshold=persistence_threshold,
                )
            except Exception as exc:
                st.session_state.as_crop_result = None
                LOGGER.exception("Analisi Crop Marks non completata")
                st.error(f"Analisi non completata: {exc}")
                st.caption("Se l'area o il periodo sono molto estesi, riducili e riprova.")

    result = st.session_state.as_crop_result
    if result:
        metric_cols = st.columns(4)
        metric_cols[0].metric("Scene trovate", result.get("scene_count", 0))
        metric_cols[1].metric("Scene valide", result.get("valid_scene_count", 0))
        metric_cols[2].metric("Date combinate", min(result["params"]["topn"], result.get("valid_scene_count", 0)))
        metric_cols[3].metric("Layer disponibili", len(result["layer_specs"]))

        st.subheader("Date migliori")
        display_df = result["df"].copy()
        for column in ["cloud", "pixel_cloud_mean", "score"] + [
            name for name in display_df.columns if name.endswith("_mean")
        ]:
            display_df[column] = display_df[column].astype(float).round(3)
        st.dataframe(display_df, width="stretch", hide_index=True)
        st.info(
            "Lo score e una priorita di indagine basata su contrasti spettrali normalizzati: "
            "non rappresenta una probabilita archeologica. Le anomalie persistenti sono quelle "
            "che ricompaiono nelle date selezionate."
        )

        if len(result["df"]) > 1:
            chart = result["df"].copy()
            chart["date"] = chart["date"].astype("datetime64[ns]")
            chart = chart.sort_values("date").set_index("date")
            chart_columns = ["ndvi_mean", "savi_mean", "ndmi_mean"]
            st.subheader("Serie temporale media nell'AOI")
            st.line_chart(chart[chart_columns], height=260)

        st.subheader("Mappa dei layer generati")
        layer_names = list(result["layer_specs"].keys())
        if st.session_state.as_crop_active_layer not in layer_names:
            preferred = "Persistenza complessiva" if result["params"]["topn"] > 1 else "False color 8-4-3"
            st.session_state.as_crop_active_layer = preferred if preferred in layer_names else layer_names[0]
        active_layer = st.selectbox(
            "Filtro",
            layer_names,
            key="as_crop_active_layer",
            format_func=lambda name: f"{result['layer_specs'][name]['group']} · {name}",
        )
        if active_layer not in result["layer_urls"]:
            with st.spinner("Preparazione del layer selezionato..."):
                result["layer_urls"][active_layer] = cropmarks.layer_url(result, active_layer)
        result_map = folium.Map(location=result["center"], zoom_start=14, tiles=None)
        cropmarks.add_base_tiles(result_map, esri_show=True)
        folium.GeoJson(
            result["geometry"],
            name="AOI",
            style_function=lambda _x: {"color": "yellow", "weight": 2, "fillOpacity": 0},
        ).add_to(result_map)
        cropmarks.add_layer(result_map, result["layer_urls"][active_layer], active_layer, show=True)
        folium.LayerControl(collapsed=False).add_to(result_map)
        st_folium(result_map, width=1200, height=760, key=f"as_crop_result_map_{active_layer}", returned_objects=[])

        cols = st.columns(3)
        with cols[0]:
            if result["download"]:
                st.link_button("Scarica GeoTIFF", result["download"])
            elif st.button("Prepara download GeoTIFF", width="stretch"):
                try:
                    with st.spinner("Preparazione download..."):
                        result["download"] = cropmarks.prepare_download(result)
                    st.rerun()
                except Exception as exc:
                    st.warning(f"Download diretto non disponibile: {exc}. Usa l'export Drive.")
        with cols[1]:
            if result["task_id"]:
                st.success("Export Drive avviato. Task ID: " + result["task_id"])
        with cols[2]:
            st.write("Confronta persistenza, deficit ed eccesso di vegetazione con RGB, suolo e LiDAR prima di classificare il candidato.")

        render_candidate_save_form(result, active_layer)

    render_crop_candidate_archive()


def render_candidate_save_form(result, active_layer):
    source = compact_source_record(st.session_state.get("as_crop_source_record"))
    default_title = (
        f"{source.get('localita') or source.get('comune')} · {source.get('number')}"
        if source
        else f"AOI {result['center'][0]:.5f}, {result['center'][1]:.5f}"
    )
    with st.expander("Salva come candidato", expanded=False):
        with st.form("as_candidate_save_form"):
            title = st.text_input("Titolo candidato", value=default_title)
            status = st.selectbox("Stato", candidate_store.CANDIDATE_STATUSES)
            notes = st.text_area(
                "Note interpretative",
                placeholder="Forma osservata, possibili falsi positivi, confronti documentali o LiDAR...",
            )
            submitted = st.form_submit_button("Salva dossier", type="primary", width="stretch")
        if submitted:
            ranking = result["df"].head(15).to_dict(orient="records")
            candidate = candidate_store.save_candidate(
                {
                    "title": title.strip() or default_title,
                    "status": status,
                    "notes": notes.strip(),
                    "geometry": result["geometry"],
                    "center": result["center"],
                    "source_record": source,
                    "analysis_params": result["params"],
                    "selected_layer": active_layer,
                    "scene_count": result.get("scene_count"),
                    "valid_scene_count": result.get("valid_scene_count"),
                    "ranking": ranking,
                }
            )
            st.success(f"Dossier {candidate['id']} salvato nell'archivio Candidati.")


def render_crop_candidate_archive():
    candidates = candidate_store.load_candidates()
    if not candidates:
        return
    with st.expander(f"Archivio locale · {len(candidates)} candidati", expanded=False):
        recent = list(reversed(candidates[-8:]))
        st.dataframe(
            [
                {
                    "ID": item.get("id"),
                    "Titolo": item.get("title"),
                    "Stato": item.get("status"),
                    "Aggiornato": item.get("updated_at"),
                }
                for item in recent
            ],
            hide_index=True,
            width="stretch",
        )


def render_candidates():
    st.title("Candidati e dossier di verifica")
    st.caption(
        "Archivio locale delle anomalie da confrontare con fonti, immagini storiche, LiDAR e ricognizione. "
        "Lo stato esprime una decisione di lavoro, non una certificazione archeologica."
    )
    candidates = candidate_store.load_candidates()
    if not candidates:
        st.info("Nessun candidato salvato. Avvia un'analisi Crop Marks e usa «Salva come candidato».")
        return

    status_filter = st.multiselect(
        "Filtra per stato",
        candidate_store.CANDIDATE_STATUSES,
        default=list(candidate_store.CANDIDATE_STATUSES),
        key="as_candidate_status_filter",
    )
    filtered = [item for item in candidates if item.get("status") in status_filter]
    metric_cols = st.columns(4)
    metric_cols[0].metric("Totale", len(candidates))
    metric_cols[1].metric("Visibili", len(filtered))
    metric_cols[2].metric("Interessanti", sum(item.get("status") == "Interessante" for item in candidates))
    metric_cols[3].metric("Verificati", sum(item.get("status") == "Verificato" for item in candidates))

    if filtered:
        candidate_map = folium.Map(location=[43.2, 13.3], zoom_start=8, tiles=None, control_scale=True)
        cropmarks.add_base_tiles(candidate_map, esri_show=True)
        all_bounds = []
        colors = {
            "Da verificare": "#ffd166",
            "Interessante": "#ef476f",
            "Falso positivo": "#8d99ae",
            "Verificato": "#06d6a0",
        }
        for item in filtered:
            geometry = item.get("geometry")
            if not geometry:
                continue
            color = colors.get(item.get("status"), "#ffd166")
            folium.GeoJson(
                geometry,
                tooltip=f"{item.get('title', 'Candidato')} · {item.get('status', '')}",
                style_function=lambda _feature, feature_color=color: {
                    "color": feature_color,
                    "weight": 3,
                    "fillColor": feature_color,
                    "fillOpacity": 0.16,
                },
            ).add_to(candidate_map)
            bounds = cropmarks.geometry_bounds(geometry)
            if bounds:
                all_bounds.extend(bounds)
        if all_bounds:
            candidate_map.fit_bounds(all_bounds, padding=(24, 24))
        st_folium(candidate_map, width=1200, height=520, key="as_candidate_map", returned_objects=[])

    labels = {
        item["id"]: f"{item.get('title', 'Candidato')} · {item.get('status', '')} · {item['id']}"
        for item in filtered
    }
    if not labels:
        st.info("Nessun candidato corrisponde ai filtri.")
        return
    selected_id = st.selectbox("Dossier", list(labels), format_func=labels.get, key="as_candidate_selected")
    selected = next(item for item in filtered if item.get("id") == selected_id)

    detail_col, action_col = st.columns([0.62, 0.38], gap="large")
    with detail_col:
        st.subheader(selected.get("title") or selected_id)
        source = selected.get("source_record") or {}
        if source:
            st.write(
                "Fonte: "
                + " · ".join(
                    str(value)
                    for value in [source.get("source_collection"), source.get("number"), source.get("comune"), source.get("localita")]
                    if value
                )
            )
        st.write(selected.get("notes") or "Nessuna nota interpretativa.")
        ranking = selected.get("ranking") or []
        if ranking:
            st.markdown("**Date prioritarie**")
            st.dataframe(ranking, hide_index=True, width="stretch")
    with action_col:
        status = st.selectbox(
            "Stato del dossier",
            candidate_store.CANDIDATE_STATUSES,
            index=candidate_store.CANDIDATE_STATUSES.index(selected.get("status", "Da verificare")),
            key=f"as_candidate_status_{selected_id}",
        )
        notes = st.text_area(
            "Note",
            value=selected.get("notes") or "",
            key=f"as_candidate_notes_{selected_id}",
        )
        if st.button("Aggiorna dossier", type="primary", width="stretch"):
            candidate_store.update_candidate(selected_id, {"status": status, "notes": notes})
            st.success("Dossier aggiornato.")
            st.rerun()
        if st.button("Riapri in Crop Marks", width="stretch"):
            st.session_state.as_crop_geometry = selected.get("geometry")
            st.session_state.as_crop_source_record = selected.get("source_record")
            st.session_state.as_crop_result = None
            st.session_state.as_crop_active_layer = None
            st.session_state.as_active_tool = "Crop Marks"
            st.rerun()

    download_cols = st.columns(2)
    download_cols[0].download_button(
        "Esporta archivio JSON",
        candidate_store.candidates_json(candidates),
        file_name="archaeoscope_candidates.json",
        mime="application/json",
        width="stretch",
    )
    download_cols[1].download_button(
        "Esporta aree GeoJSON",
        candidate_store.candidates_geojson(candidates),
        file_name="archaeoscope_candidates.geojson",
        mime="application/geo+json",
        width="stretch",
    )


def compact_source_record(record):
    if not record:
        return None
    fields = (
        "number",
        "source_collection",
        "comune",
        "localita",
        "definition",
        "dating",
        "find_type",
        "lat",
        "lon",
        "coordinate_precision",
        "coordinate_source",
        "source_pdf_page",
        "official_map_url",
    )
    return {field: record.get(field) for field in fields if record.get(field) not in (None, "", [])}

if __name__ == "__main__":
    main()
