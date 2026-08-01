import copy
import csv
import html
import io
import json
import re
from textwrap import dedent
from datetime import datetime
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

from . import cropmarks_engine as cropmarks
from . import source_registry
from .database_enrichment import enrich_database
from .paths import PROJECT_ROOT, RVT_DIR


DATA_PATH = PROJECT_ROOT / "archaeoscope" / "data" / "cam_m_sites.json"
DATABASE_DIR = RVT_DIR / "output_rvt_gui" / "cam_m_database"
COORDINATES_PATH = DATABASE_DIR / "coordinate_overrides.json"

MACERATA_CENTER = [43.2206, 13.2908]
MACERATA_BOUNDS = [[42.82, 12.78], [43.61, 13.86]]

PERIOD_KEYWORDS = {
    "Paleolitico": ("paleolitico",),
    "Mesolitico": ("mesolitico",),
    "Neolitico": ("neolitico",),
    "Eneolitico": ("eneolitico",),
    "Età del Bronzo": ("bronzo",),
    "Età del Ferro": ("ferro", "piceno", "picena"),
    "Età romana": ("romana", "romano", "repubblicana", "imperiale"),
    "Tardoantico": ("tardoantico", "tardoantica"),
    "Medioevo": ("medievale", "medioevo", "altomedievale"),
    "Non identificata": ("non id",),
}


def render_archaeological_database():
    render_database_styles()
    data = load_database()
    records = merge_coordinates(data.get("records", []), load_coordinate_overrides())
    ensure_database_state(records)

    st.markdown(
        """
        <div class="as-db-heading">
            <div>
                <div class="as-db-eyebrow">Carta archeologica della Provincia di Macerata</div>
                <h1>Database dei siti noti</h1>
            </div>
            <div class="as-db-source">CAM-M</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_source_catalog(data)

    filters = render_filters(records)
    filtered = filter_records(records, filters)
    selected = resolve_selected_record(records, filtered)

    render_metrics(records, filtered)

    map_col, detail_col = st.columns([0.64, 0.36], gap="large")
    with map_col:
        clicked_number = render_database_map(filtered)
        if clicked_number and clicked_number != st.session_state.get("as_db_selected_number"):
            st.session_state.as_db_selected_number = clicked_number
            st.rerun()
    with detail_col:
        render_site_vitrine(selected)
        render_coordinate_tools(selected)

    render_results_table(filtered)
    render_downloads(filtered)


@st.cache_data(show_spinner=False)
def load_database():
    if not DATA_PATH.exists():
        return {"metadata": {}, "records": [], "stats": {}}
    database = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return enrich_database(database)


def render_source_catalog(data):
    enrichment = data.get("metadata", {}).get("enrichment", {})
    manifest = source_registry.load_manifest()
    documents = manifest.get("documents", [])
    statuses = [source_registry.document_status(document) for document in documents]
    cached = sum(status["available"] and status["verified"] for status in statuses)
    map_collection = manifest.get("map_collection", {})

    with st.expander("Fonti, file e qualita dell'integrazione", expanded=False):
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Documenti locali", f"{cached}/{len(documents)}")
        with m2:
            st.metric(
                "Tavole CAM-M verificate",
                f"{map_collection.get('verified_assets', 0)}/{map_collection.get('asset_count', 0)}",
            )
        with m3:
            st.metric("Join documentari", enrichment.get("citation_links_accepted", 0))
        with m4:
            st.metric("Join da rivedere", enrichment.get("citation_links_for_review", 0))

        st.caption(
            f"{enrichment.get('coordinates_added_from_pvs_2006', 0)} coordinate aggiunte da PVS 2006, "
            f"{enrichment.get('coordinates_added_from_pvs_2017', 0)} da PVS 2017; "
            f"{enrichment.get('pvs_duplicate_rows_removed', 0)} duplicati PVS ricondotti alla relativa scheda CAM-M."
        )
        for document, status in zip(documents, statuses):
            info_col, link_col = st.columns([0.76, 0.24], vertical_alignment="center")
            with info_col:
                availability = status["reason"]
                st.markdown(f"**{document['title']}** ({document.get('year', 's.d.')})")
                st.caption(f"{availability} · {document.get('record_coverage', '')} · {document.get('license', '')}")
            with link_col:
                st.link_button("Scheda ufficiale", document["landing_url"], width="stretch")

        review_queue = enrichment.get("review_queue", [])
        if review_queue:
            with st.expander(f"Coda di revisione ({len(review_queue)})", expanded=False):
                st.caption(
                    "Questi collegamenti non sono stati usati per posizionare punti: coinvolgono schede composte, "
                    "coordinate mancanti o comuni discordanti."
                )
                st.dataframe(pd.DataFrame(review_queue), hide_index=True, width="stretch")


def ensure_database_state(records):
    if "as_db_query" not in st.session_state:
        st.session_state.as_db_query = ""
    for key, value in {
        "as_db_comune": "Tutti",
        "as_db_source": "Tutte",
        "as_db_precision": "Tutte",
        "as_db_find_type": "Tutti",
        "as_db_ceramic_presence": "Tutte",
        "as_db_definition": "Tutte",
        "as_db_periods": [],
        "as_db_exact_dating": "Tutte",
        "as_db_only_georef": False,
        "as_db_basemap": "Mappa",
    }.items():
        if key not in st.session_state:
            st.session_state[key] = value
    selected = st.session_state.get("as_db_selected_number")
    numbers = {record["number"] for record in records}
    if selected not in numbers and records:
        st.session_state.as_db_selected_number = records[0]["number"]


def render_filters(records):
    st.markdown('<div class="as-db-filter-band">', unsafe_allow_html=True)
    query = st.text_input(
        "Ricerca nel catalogo",
        key="as_db_query",
        placeholder="numero scheda, località, comune, definizione, datazione, descrizione, fonti",
    )
    c1, c2, c3, c4, c5 = st.columns([0.14, 0.2, 0.24, 0.18, 0.16], gap="small")
    with c1:
        source = st.selectbox("Fonte", ["Tutte"] + unique_values(records, "source_collection"), key="as_db_source")
    with c2:
        comune = st.selectbox("Comune", ["Tutti"] + unique_values(records, "comune"), key="as_db_comune")
    with c3:
        find_type = st.selectbox(
            "Tipo ritrovamento",
            ["Tutti"] + unique_values(records, "find_type"),
            key="as_db_find_type",
        )
    with c4:
        ceramic_presence = st.selectbox(
            "Cocci/ceramica",
            ["Tutte"] + unique_values(records, "ceramic_presence"),
            key="as_db_ceramic_presence",
        )
    with c5:
        precision = st.selectbox(
            "Precisione catalogo",
            ["Tutte"] + unique_values(records, "coordinate_precision"),
            key="as_db_precision",
        )

    c6, c7 = st.columns([0.5, 0.5], gap="small")
    with c6:
        definition = st.selectbox(
            "Definizione",
            ["Tutte"] + unique_values(records, "definition"),
            key="as_db_definition",
        )
    with c7:
        exact_dating = st.selectbox(
            "Datazione specifica",
            ["Tutte"] + unique_values(records, "dating"),
            key="as_db_exact_dating",
        )

    c5, c6 = st.columns([0.72, 0.28], gap="small")
    with c5:
        periods = st.multiselect("Età / macro-periodi", list(PERIOD_KEYWORDS), key="as_db_periods")
    with c6:
        only_georef = st.checkbox("Solo punti georeferenziati", key="as_db_only_georef")
    st.markdown("</div>", unsafe_allow_html=True)
    return {
        "query": query,
        "source": source,
        "comune": comune,
        "find_type": find_type,
        "ceramic_presence": ceramic_presence,
        "precision": precision,
        "definition": definition,
        "periods": periods,
        "exact_dating": exact_dating,
        "only_georef": only_georef,
    }


def render_metrics(records, filtered):
    georef_filtered = sum(1 for record in filtered if has_coordinates(record))
    georef_total = sum(1 for record in records if has_coordinates(record))
    ceramic_filtered = sum(1 for record in filtered if record.get("ceramic_presence") == "presente")
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    with m1:
        st.metric("Schede", len(records))
    with m2:
        st.metric("Risultati", len(filtered))
    with m3:
        st.metric("Comuni", len(unique_values(records, "comune")))
    with m4:
        st.metric("Con cocci", ceramic_filtered)
    with m5:
        st.metric("Con lat/lon", f"{georef_filtered}/{len(filtered)}")
    with m6:
        st.metric("Punti mappa", georef_total)


def render_database_map(records):
    georef_records = [record for record in records if has_coordinates(record)]
    basemap = st.radio(
        "Sfondo mappa",
        ["Mappa", "Satellite"],
        horizontal=True,
        key="as_db_basemap",
    )
    db_map = folium.Map(location=MACERATA_CENTER, zoom_start=9, tiles=None, control_scale=True)
    folium.TileLayer(
        "OpenStreetMap",
        name="Mappa",
        show=basemap == "Mappa",
        control=True,
    ).add_to(db_map)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Satellite",
        overlay=False,
        show=basemap == "Satellite",
        control=True,
    ).add_to(db_map)

    clicked_number = ""
    if georef_records:
        cluster = MarkerCluster(name="Siti georeferenziati").add_to(db_map)
        bounds = []
        for record in georef_records:
            lat = float(record["lat"])
            lon = float(record["lon"])
            bounds.append([lat, lon])
            popup = folium.Popup(marker_popup_html(record), max_width=360)
            folium.Marker(
                location=[lat, lon],
                tooltip=f"{record['number']} - {record.get('localita', '')}",
                popup=popup,
                icon=folium.Icon(color=marker_color(record), icon="info-sign"),
            ).add_to(cluster)
        db_map.fit_bounds(bounds, padding=(24, 24))
    else:
        db_map.fit_bounds(MACERATA_BOUNDS, padding=(8, 8))
        st.warning(
            "Il PDF CAM-M non pubblica coordinate numeriche lat/lon: la mappa mostrerà punti solo dopo import "
            "di coordinate ufficiali o inserimento manuale."
        )

    folium.LayerControl(collapsed=False).add_to(db_map)
    event = st_folium(
        db_map,
        width=1180,
        height=560,
        key=f"as_db_map_{basemap.lower()}",
        returned_objects=["last_object_clicked_popup"],
    )
    popup = event.get("last_object_clicked_popup") if event else ""
    if popup:
        match = re.search(r"data-number=['\"]([^'\"]+)['\"]", popup)
        if match:
            clicked_number = match.group(1)
    return clicked_number


def render_site_vitrine(record):
    if not record:
        st.info("Nessuna scheda selezionata.")
        return

    description = record.get("description") or "Descrizione non presente nel testo estratto."
    source_bits = []
    if record.get("archive_sources"):
        source_bits.append(f"<strong>Fonti archivistiche</strong><br>{escape(record['archive_sources'])}")
    if record.get("bibliography"):
        source_bits.append(f"<strong>Bibliografia</strong><br>{escape(record['bibliography'])}")
    if record.get("ceramic_presence") == "presente":
        terms = ", ".join(record.get("ceramic_terms") or [])
        evidence = record.get("ceramic_evidence") or "Indicazione presente nella scheda."
        source_bits.append(
            f"<strong>Cocci / ceramica</strong><br>{escape(terms or 'presente')}<br>{escape(evidence)}"
        )
    if record.get("matched_cam_number"):
        source_bits.append(f"<strong>Collegamento CAM-M</strong><br>{escape(record['matched_cam_number'])}")
    if record.get("site_size"):
        source_bits.append(f"<strong>Estensione riportata</strong><br>{escape(record['site_size'])}")
    if record.get("investigation_methods"):
        source_bits.append(
            f"<strong>Metodi d'indagine</strong><br>{escape(', '.join(record['investigation_methods']))}"
        )
    source_html = "".join(f"<div class='as-db-source-line'>{bit}</div>" for bit in source_bits)
    external_html = external_sources_html(record)
    coords = coordinate_label(record)
    source_label = record.get("source_collection") or "CAM-M"

    render_html(
        dedent(
            f"""
        <div class="as-db-vitrine">
            <div class="as-db-glass"></div>
            <div class="as-db-object">
                <span>{escape(record["number"])}</span>
            </div>
            <div class="as-db-plaque">
                <div class="as-db-plaque-top">{escape(record.get("comune", ""))}</div>
                <h2>{escape(record.get("localita", ""))}</h2>
                <div class="as-db-tags">
                    <span>{escape(source_label)}</span>
                    <span>{escape(record.get("find_type") or "tipo non definito")}</span>
                    <span>{escape(ceramic_label(record))}</span>
                    <span>{escape(record.get("definition") or "non indicata")}</span>
                    <span>{escape(record.get("dating") or "datazione non indicata")}</span>
                    <span>{escape(record.get("coordinate_precision") or "precisione non indicata")}</span>
                </div>
                <p>{escape(description)}</p>
                <div class="as-db-coords">{escape(coords)}</div>
                {source_html}
                {external_html}
            </div>
        </div>
        """
        )
    )

    document_index = source_registry.document_index()
    record_documents = [
        document_index[key]
        for key in record.get("source_document_keys", [])
        if key in document_index
    ]
    link_count = 1 + len(record_documents)
    link_cols = st.columns(max(1, link_count))
    with link_cols[0]:
        if record.get("official_map_url"):
            st.link_button("Tavola comunale", record["official_map_url"], width="stretch")
        else:
            st.caption("Tavola comunale non disponibile")
    for column, document in zip(link_cols[1:], record_documents):
        with column:
            st.link_button(
                source_button_label(document["key"]),
                document.get("landing_url") or document.get("persistent_url"),
                width="stretch",
            )
    page_labels = record_source_page_labels(record)
    pages = " · ".join(page_labels) if page_labels else "pagine non disponibili"
    st.caption(f"{pages} · Provenienza: {record.get('provenance_status', 'n.d.')}")

    for flag in record.get("validation_flags", []) or []:
        st.warning(flag)

    if has_coordinates(record):
        analysis_cols = st.columns([0.38, 0.62], vertical_alignment="bottom")
        with analysis_cols[0]:
            radius = st.number_input(
                "Raggio AOI (m)",
                min_value=200,
                max_value=5000,
                value=750,
                step=50,
                key=f"as_db_crop_radius_{record['number']}",
            )
        with analysis_cols[1]:
            if st.button(
                "Analizza questa zona con Crop Marks",
                key=f"as_db_to_crop_{record['number']}",
                type="primary",
                width="stretch",
            ):
                st.session_state.as_crop_geometry = cropmarks.square_aoi(
                    record["lat"], record["lon"], radius
                )
                st.session_state.as_crop_source_record = copy.deepcopy(record)
                st.session_state.as_crop_result = None
                st.session_state.as_crop_active_layer = None
                st.session_state.as_active_tool = "Crop Marks"
                st.rerun()
    else:
        st.caption(
            "Per avviare automaticamente l'analisi satellitare, aggiungi prima coordinate verificate alla scheda."
        )


def external_sources_html(record):
    blocks = []
    for source in record.get("external_sources", []) or []:
        source_label = source.get("source_label") or "Fonte integrativa"
        title = f"{source_label} - scheda {source.get('source_id', 'n.d.')}"
        details = [
            f"<strong>{escape(title)}</strong>",
            f"Definizione: {escape(source.get('definition') or 'non indicata')}",
            f"Cronologia: {escape(source.get('dating') or 'non indicata')}",
        ]
        if source.get("reperimento_cartografico"):
            details.append(f"Cartografia: {escape(source['reperimento_cartografico'])}")
        if source.get("ceramic_presence"):
            details.append(f"Cocci/ceramica: {escape(ceramic_label(source))}")
        if source.get("ceramic_evidence"):
            details.append(escape(source["ceramic_evidence"]))
        if source.get("utm_easting") and source.get("utm_northing"):
            details.append(
                f"UTM EPSG:32633: {escape(source['utm_easting'])}-{escape(source['utm_northing'])}"
            )
        if source.get("lat") is not None and source.get("lon") is not None:
            details.append(f"WGS84: {float(source['lat']):.6f}, {float(source['lon']):.6f}")
        if source.get("source_citation"):
            details.append(escape(source["source_citation"]))
        if source.get("site_size"):
            details.append(f"Estensione: {escape(source['site_size'])}")
        if source.get("investigation_methods"):
            details.append(f"Indagini: {escape(', '.join(source['investigation_methods']))}")
        if source.get("source_print_page"):
            details.append(f"Pagina a stampa: {escape(source['source_print_page'])}")
        if source.get("source_pdf_page"):
            details.append(f"Pagina PDF: {escape(source['source_pdf_page'])}")
        blocks.append("<div class='as-db-source-line'>" + "<br>".join(details) + "</div>")
    return "".join(blocks)


def render_coordinate_tools(record):
    if not record:
        return

    with st.expander("Coordinate esatte", expanded=False):
        st.caption("Usa solo coordinate ufficiali o verificate. Le coordinate importate possono essere corrette o integrate qui.")
        uploaded = st.file_uploader(
            "Importa CSV coordinate",
            type=["csv", "txt"],
            key="as_db_coordinate_upload",
            help="Colonne accettate: numero/number/id, lat/latitudine/latitude, lon/lng/longitudine.",
        )
        if uploaded is not None:
            imported, errors = parse_coordinate_csv(uploaded)
            if imported:
                overrides = load_coordinate_overrides()
                overrides.update(imported)
                save_coordinate_overrides(overrides)
                st.success(f"Importate {len(imported)} coordinate.")
                st.rerun()
            if errors:
                st.error("; ".join(errors[:4]))

        with st.form("as_db_manual_coordinates"):
            c1, c2 = st.columns(2)
            with c1:
                lat = st.text_input("Latitudine", value="" if record.get("lat") is None else str(record.get("lat")))
            with c2:
                lon = st.text_input("Longitudine", value="" if record.get("lon") is None else str(record.get("lon")))
            source = st.text_input("Fonte coordinate", value=record.get("coordinate_source") or "inserimento manuale")
            submitted = st.form_submit_button("Salva coordinate", type="primary", width="stretch")
            if submitted:
                try:
                    lat_value = parse_float(lat)
                    lon_value = parse_float(lon)
                    validate_lat_lon(lat_value, lon_value)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    overrides = load_coordinate_overrides()
                    overrides[record["number"]] = {
                        "lat": lat_value,
                        "lon": lon_value,
                        "source": source.strip() or "inserimento manuale",
                        "updated_at": datetime.now().isoformat(timespec="seconds"),
                    }
                    save_coordinate_overrides(overrides)
                    st.success("Coordinate salvate.")
                    st.rerun()


def render_results_table(records):
    st.markdown('<div class="as-db-table-title">Risultati catalogo</div>', unsafe_allow_html=True)
    if not records:
        st.info("Nessun risultato con i filtri correnti.")
        return

    table = pd.DataFrame(
        [
            {
                "Numero": record["number"],
                "Fonte": record.get("source_collection", "CAM-M"),
                "Comune": record.get("comune", ""),
                "Località": record.get("localita", ""),
                "Tipo ritrovamento": record.get("find_type", ""),
                "Cocci/ceramica": ceramic_label(record),
                "Definizione": record.get("definition", ""),
                "Datazione": record.get("dating", ""),
                "Precisione": record.get("coordinate_precision", ""),
                "Lat/Lon": "sì" if has_coordinates(record) else "no",
            }
            for record in records
        ]
    )
    event = st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        height=390,
        key="as_db_results_table",
        on_select="rerun",
        selection_mode="single-row",
    )
    if event and event.selection.rows:
        row_index = event.selection.rows[0]
        if 0 <= row_index < len(records):
            number = records[row_index]["number"]
            if st.session_state.get("as_db_selected_number") != number:
                st.session_state.as_db_selected_number = number
                st.rerun()


def render_downloads(records):
    payload = json.dumps(records, ensure_ascii=False, indent=2)
    csv_data = records_to_csv(records)
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Esporta risultati JSON",
            data=payload,
            file_name="cam_m_database_filtrato.json",
            mime="application/json",
            width="stretch",
        )
    with c2:
        st.download_button(
            "Esporta risultati CSV",
            data=csv_data,
            file_name="cam_m_database_filtrato.csv",
            mime="text/csv",
            width="stretch",
        )


def resolve_selected_record(records, filtered):
    selected_number = st.session_state.get("as_db_selected_number")
    candidates = filtered or records
    if selected_number not in {record["number"] for record in candidates} and candidates:
        selected_number = candidates[0]["number"]
        st.session_state.as_db_selected_number = selected_number
    return next((record for record in records if record["number"] == selected_number), None)


def filter_records(records, filters):
    query = normalise_search(filters["query"])
    filtered = []
    for record in records:
        if filters["source"] != "Tutte" and record.get("source_collection", "CAM-M") != filters["source"]:
            continue
        if filters["comune"] != "Tutti" and record.get("comune") != filters["comune"]:
            continue
        if filters["find_type"] != "Tutti" and record.get("find_type") != filters["find_type"]:
            continue
        if filters["ceramic_presence"] != "Tutte" and record.get("ceramic_presence") != filters["ceramic_presence"]:
            continue
        if filters["precision"] != "Tutte" and record.get("coordinate_precision") != filters["precision"]:
            continue
        if filters["definition"] != "Tutte" and record.get("definition") != filters["definition"]:
            continue
        if filters["exact_dating"] != "Tutte" and record.get("dating") != filters["exact_dating"]:
            continue
        if filters["only_georef"] and not has_coordinates(record):
            continue
        if filters["periods"] and not record_matches_periods(record, filters["periods"]):
            continue
        if query and query not in searchable_text(record):
            continue
        filtered.append(record)
    return sorted(filtered, key=lambda item: (item.get("comune", ""), item.get("number", "")))


def record_matches_periods(record, periods):
    dating = normalise_search(record.get("dating", ""))
    for period in periods:
        if any(keyword in dating for keyword in PERIOD_KEYWORDS.get(period, ())):
            return True
    return False


def searchable_text(record):
    fields = [
        "number",
        "source_collection",
        "source_id",
        "comune",
        "localita",
        "find_type",
        "ceramic_presence",
        "ceramic_terms",
        "ceramic_evidence",
        "definition",
        "dating",
        "coordinate_precision",
        "description",
        "archive_sources",
        "bibliography",
        "matched_cam_number",
        "candidate_cam_numbers",
        "reperimento_cartografico",
        "utm_easting",
        "utm_northing",
        ]
    external = json.dumps(record.get("external_sources", []), ensure_ascii=False)
    return normalise_search(" ".join(str(record.get(field, "")) for field in fields) + " " + external)


def normalise_search(value):
    value = str(value or "").casefold()
    replacements = str.maketrans("àèéìòù", "aeeiou")
    return value.translate(replacements)


def unique_values(records, field):
    values = {str(record.get(field, "")).strip() for record in records if str(record.get(field, "")).strip()}
    return sorted(values, key=lambda value: value.casefold())


def ceramic_label(record):
    presence = record.get("ceramic_presence") or "non indicata"
    if presence == "presente":
        terms = record.get("ceramic_terms") or []
        if terms:
            return "cocci: " + ", ".join(terms[:3])
        return "cocci: presente"
    return "cocci: non indicata"


def load_coordinate_overrides():
    if not COORDINATES_PATH.exists():
        return {}
    try:
        raw = json.loads(COORDINATES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    coordinates = raw.get("coordinates", raw)
    if not isinstance(coordinates, dict):
        return {}
    cleaned = {}
    for number, payload in coordinates.items():
        if not isinstance(payload, dict):
            continue
        try:
            lat = parse_float(payload.get("lat"))
            lon = parse_float(payload.get("lon"))
            validate_lat_lon(lat, lon)
        except ValueError:
            continue
        cleaned[str(number)] = {
            "lat": lat,
            "lon": lon,
            "source": str(payload.get("source") or payload.get("coordinate_source") or "import"),
            "updated_at": str(payload.get("updated_at") or ""),
        }
    return cleaned


def save_coordinate_overrides(overrides):
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "coordinates": overrides,
    }
    COORDINATES_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_coordinates(records, overrides):
    merged = []
    for record in records:
        item = copy.deepcopy(record)
        override = overrides.get(item.get("number"))
        if override:
            item["lat"] = override["lat"]
            item["lon"] = override["lon"]
            item["coordinate_source"] = override.get("source", "")
        merged.append(item)
    return merged


def parse_coordinate_csv(uploaded):
    try:
        df = pd.read_csv(uploaded, sep=None, engine="python")
    except Exception as exc:
        return {}, [f"CSV non leggibile: {exc}"]

    column_lookup = {normalise_column(column): column for column in df.columns}
    number_col = first_existing(column_lookup, ["numero", "number", "id", "scheda", "codice"])
    lat_col = first_existing(column_lookup, ["lat", "latitudine", "latitude", "y"])
    lon_col = first_existing(column_lookup, ["lon", "lng", "longitudine", "longitude", "x"])
    source_col = first_existing(column_lookup, ["fonte", "source", "coordinate_source"])
    if not number_col or not lat_col or not lon_col:
        return {}, ["Il CSV deve contenere colonne numero, latitudine e longitudine."]

    imported = {}
    errors = []
    for index, row in df.iterrows():
        number = str(row.get(number_col, "")).strip()
        if not number:
            continue
        try:
            lat = parse_float(row.get(lat_col))
            lon = parse_float(row.get(lon_col))
            validate_lat_lon(lat, lon)
        except ValueError as exc:
            errors.append(f"Riga {index + 2}: {exc}")
            continue
        imported[number] = {
            "lat": lat,
            "lon": lon,
            "source": str(row.get(source_col, "")).strip() if source_col else "import CSV",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    return imported, errors


def first_existing(column_lookup, candidates):
    for candidate in candidates:
        if candidate in column_lookup:
            return column_lookup[candidate]
    return None


def normalise_column(value):
    return re.sub(r"[^a-z0-9]+", "_", normalise_search(value)).strip("_")


def parse_float(value):
    text = str(value or "").strip().replace(",", ".")
    if not text:
        raise ValueError("coordinata vuota")
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"coordinata non valida: {value}") from exc


def validate_lat_lon(lat, lon):
    if not (-90 <= lat <= 90):
        raise ValueError(f"latitudine fuori range: {lat}")
    if not (-180 <= lon <= 180):
        raise ValueError(f"longitudine fuori range: {lon}")


def has_coordinates(record):
    return record.get("lat") is not None and record.get("lon") is not None


def coordinate_label(record):
    if has_coordinates(record):
        source = record.get("coordinate_source") or "fonte non indicata"
        return f"{record['lat']:.6f}, {record['lon']:.6f} - {source}"
    return "Coordinate numeriche non presenti per questa scheda."


def marker_popup_html(record):
    return f"""
    <div data-number="{escape(record['number'])}" style="font-family: sans-serif; min-width: 240px;">
        <strong>{escape(record['number'])} - {escape(record.get('localita', ''))}</strong><br>
        {escape(record.get('source_collection', 'CAM-M'))}<br>
        {escape(record.get('comune', ''))}<br>
        <em>{escape(record.get('definition', ''))}</em><br>
        {escape(record.get('dating', ''))}
    </div>
    """


def marker_color(record):
    precision = record.get("coordinate_precision")
    if record.get("source_collection") == "PVS" or precision == "UTM":
        return "purple"
    if precision == "esatta":
        return "green"
    if precision == "buona":
        return "blue"
    if precision == "approssimativa":
        return "orange"
    return "red"


def records_to_csv(records):
    output = io.StringIO()
    fieldnames = [
        "number",
        "source_collection",
        "source_id",
        "comune",
        "localita",
        "find_type",
        "ceramic_presence",
        "ceramic_terms",
        "ceramic_evidence",
        "coordinate_precision",
        "definition",
        "dating",
        "description",
        "archive_sources",
        "bibliography",
        "source_pdf_page",
        "lat",
        "lon",
        "coordinate_source",
        "matched_cam_number",
        "candidate_cam_numbers",
        "reperimento_cartografico",
        "utm_easting",
        "utm_northing",
        "utm_crs",
        "official_map_url",
        "source_document_keys",
        "provenance_status",
        "validation_flags",
        "site_size",
        "investigation_methods",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for record in records:
        writer.writerow({field: record.get(field, "") for field in fieldnames})
    return output.getvalue()


def render_html(markup):
    if hasattr(st, "html"):
        st.html(markup)
    else:
        st.markdown(markup, unsafe_allow_html=True)


def escape(value):
    return html.escape(str(value or ""), quote=True)


def source_button_label(document_key):
    return {
        "cam_m_2024": "Fonte CAM-M",
        "pvs_2006_catalogue": "Fonte PVS 2006",
        "pvs_2017": "Fonte PVS 2017",
    }.get(document_key, "Fonte ufficiale")


def record_source_page_labels(record):
    labels = []
    if "cam_m_2024" in record.get("source_document_keys", []) and record.get("source_pdf_page"):
        labels.append(f"CAM-M p. PDF {record['source_pdf_page']}")
    for source in record.get("external_sources", []) or []:
        document_key = source.get("source_document_key")
        page = source.get("source_pdf_page")
        if not document_key or not page:
            continue
        label = {
            "pvs_2006_catalogue": "PVS 2006",
            "pvs_2017": "PVS 2017",
        }.get(document_key, "Fonte")
        page_label = f"{label} p. PDF {page}"
        if source.get("source_print_page"):
            page_label += f" (stampa {source['source_print_page']})"
        if page_label not in labels:
            labels.append(page_label)
    if record.get("source_collection") == "PVS 2017" and record.get("source_pdf_page"):
        page_label = f"PVS 2017 p. PDF {record['source_pdf_page']}"
        if record.get("source_print_page"):
            page_label += f" (stampa {record['source_print_page']})"
        if page_label not in labels:
            labels.append(page_label)
    return labels


def render_database_styles():
    st.markdown(
        """
        <style>
            .as-db-heading {
                align-items: end;
                display: flex;
                gap: 1rem;
                justify-content: space-between;
                margin: 0.2rem 0 1rem;
            }
            .as-db-eyebrow {
                color: #d8c08a;
                font-size: 0.78rem;
                font-weight: 800;
                letter-spacing: 0.12em;
                text-transform: uppercase;
            }
            .as-db-heading h1 {
                color: #fff6df;
                font-size: 2rem;
                line-height: 1.05;
                margin: 0.1rem 0 0;
                letter-spacing: 0;
            }
            .as-db-source {
                border: 1px solid rgba(212, 175, 55, 0.35);
                border-radius: 8px;
                color: #f1c75b;
                font-weight: 900;
                padding: 0.55rem 0.75rem;
            }
            .as-db-filter-band {
                border-bottom: 1px solid rgba(212, 175, 55, 0.22);
                border-top: 1px solid rgba(212, 175, 55, 0.22);
                margin-bottom: 0.9rem;
                padding: 0.75rem 0 0.35rem;
            }
            .as-db-vitrine {
                background:
                    linear-gradient(120deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.01)),
                    #1f160f;
                border: 1px solid rgba(212, 175, 55, 0.38);
                border-radius: 8px;
                box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12);
                margin-bottom: 0.7rem;
                overflow: hidden;
                position: relative;
            }
            .as-db-glass {
                background: linear-gradient(100deg, rgba(255,255,255,0.18), rgba(255,255,255,0.02) 40%, rgba(255,255,255,0.1));
                height: 58px;
            }
            .as-db-object {
                align-items: center;
                background:
                    radial-gradient(circle at 35% 28%, #ffe5a1, #b4862b 45%, #5b3a17 76%);
                border: 1px solid rgba(255, 235, 175, 0.55);
                border-radius: 999px;
                box-shadow: 0 18px 40px rgba(0,0,0,0.36), inset 0 6px 16px rgba(255,255,255,0.18);
                color: #21170f;
                display: flex;
                font-weight: 900;
                height: 116px;
                justify-content: center;
                margin: -22px auto 0;
                width: 116px;
            }
            .as-db-object span {
                font-size: 0.9rem;
                letter-spacing: 0;
            }
            .as-db-plaque {
                padding: 1rem 1.05rem 1.1rem;
            }
            .as-db-plaque-top {
                color: #d8c08a;
                font-size: 0.8rem;
                font-weight: 800;
                text-transform: uppercase;
            }
            .as-db-plaque h2 {
                color: #fff6df;
                font-size: 1.25rem;
                line-height: 1.16;
                margin: 0.25rem 0 0.6rem;
                letter-spacing: 0;
            }
            .as-db-tags {
                display: flex;
                flex-wrap: wrap;
                gap: 0.35rem;
                margin-bottom: 0.75rem;
            }
            .as-db-tags span {
                background: rgba(212, 175, 55, 0.12);
                border: 1px solid rgba(212, 175, 55, 0.24);
                border-radius: 999px;
                color: #f7ecd7;
                font-size: 0.76rem;
                padding: 0.22rem 0.48rem;
            }
            .as-db-plaque p {
                color: #eadcc5;
                font-size: 0.9rem;
                line-height: 1.45;
                margin: 0 0 0.85rem;
                max-height: 260px;
                overflow: auto;
            }
            .as-db-coords {
                border-left: 3px solid #d4af37;
                color: #f1c75b;
                font-size: 0.82rem;
                font-weight: 800;
                margin-bottom: 0.85rem;
                padding-left: 0.55rem;
            }
            .as-db-source-line {
                border-top: 1px solid rgba(212, 175, 55, 0.18);
                color: #cdbf9f;
                font-size: 0.78rem;
                line-height: 1.35;
                padding-top: 0.55rem;
                margin-top: 0.55rem;
            }
            .as-db-table-title {
                color: #fff6df;
                font-size: 1rem;
                font-weight: 900;
                margin: 1rem 0 0.35rem;
            }
            div[data-testid="stMetric"] {
                background: rgba(255, 246, 223, 0.04);
                border: 1px solid rgba(212, 175, 55, 0.18);
                border-radius: 8px;
                padding: 0.55rem 0.7rem;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
