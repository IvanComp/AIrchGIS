import logging
from datetime import date

import folium
import streamlit as st
from folium.plugins import Draw
from streamlit_folium import st_folium

from . import candidate_store
from . import cropmarks_engine as cropmarks
from . import site_index
from . import ui
from .paths import LOGO_PATH
from .rvt_web import render_rvt_web


LOGGER = logging.getLogger(__name__)


MASE_URL = "https://sim.mase.gov.it/portalediaccesso/mappe/#/viewer/new/"
GOOGLE_EARTH_URL = (
    "https://earth.google.com/web/@42.06329556,13.45871116,984.71472258a,"
    "13332.72240541d,35y,0h,0t,0r/data=CgRCAggBMikKJwolCiExdXloZDBqRERpNUh"
    "zdWs2c3V0SkxHY2VWQ1VFbkwtNFggAToDCgEwQgIIAEoNCP___________wEQAA"
)
PRIMARY_TOOLS = ("RVT", "Crop Marks", "Candidates")


def main():
    try:
        st.set_page_config(page_title="AIrch", layout="wide", page_icon=str(LOGO_PATH))
    except Exception:  # a missing or unsupported icon must never block the app
        st.set_page_config(page_title="AIrch", layout="wide")
    init_state()
    tool = render_navbar()
    if tool == "RVT":
        render_rvt_web()
    elif tool == "Crop Marks":
        render_cropmarks()
    else:
        render_candidates()


def init_state():
    for key, value in {
        "as_crop_result": None,
        "as_crop_geometry": None,
        "as_crop_active_layer": None,
        "as_crop_source_record": None,
        "as_crop_validation": None,
        "as_active_tool": "RVT",
    }.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_navbar():
    ui.inject_styles()
    brand_col, tool_col, utility_col = st.columns(
        [0.22, 0.5, 0.28],
        gap="small",
        vertical_alignment="center",
    )
    with brand_col:
        st.markdown(ui.brand_markup(), unsafe_allow_html=True)
    with tool_col:
        tool = render_tool_switch()
    with utility_col:
        st.markdown(
            f"""
            <div class="as-utility">
                <span class="as-utility-label">Resources</span>
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
        active = "RVT"
        st.session_state.as_active_tool = active

    for column, label, key in zip(
        st.columns(len(PRIMARY_TOOLS), gap="small"),
        PRIMARY_TOOLS,
        ("as_nav_rvt", "as_nav_crop", "as_nav_candidates"),
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
    ui.inject_styles()
    st.markdown(ui.brand_markup(), unsafe_allow_html=True)
    st.markdown('<div class="as-nav-rule"></div>', unsafe_allow_html=True)


CROP_LEGEND = """
<div class="as-legend">
<b>How to read the layers.</b>
<i>Vegetation deficit</i> flags plants weaker than their surroundings: buried walls, roads and road beds.
<i>Vegetation excess</i> flags more vigorous plants: ditches, channels, deeper and wetter fills.
<i>Linear marks</i> weights the same anomalies by their directional coherence, because a man-made structure
is oriented while natural soil variability is not.
<i>Persistence</i> counts how many of the selected dates show the anomaly; <i>Multi-year recurrence</i> counts in how many
different years it reappears, which is the strongest clue.
<i>Soil marks</i> works on bare-soil contrast and only makes sense on dates without vegetation cover.
</div>
"""


def render_cropmarks(standalone=False):
    if standalone:
        init_state()
        render_header()

    ui.section_title(
        "Multispectral screening",
        eyebrow="Crop marks e soil marks",
        hint=(
            "Load your own images, or use a public archive. The engine ranks every acquisition by "
            "local contrast and crop state, then combines only the dates that can actually show something."
        ),
    )

    image_source = st.radio(
        "Images",
        ["upload", "archive"],
        format_func={"upload": "Upload your files", "archive": "Download from a public source"}.get,
        horizontal=True,
        key="as_crop_image_source",
    )
    if image_source == "upload":
        from .spectral.screen import render_field_marks_upload

        render_field_marks_upload()
        render_crop_candidate_archive()
        return

    from .spectral.screen import render_provider_table

    with st.expander("Public image sources: what they cover and how to get them"):
        st.caption(
            "Sentinel-2 and Landsat run below through Google Earth Engine, with rainfall and land-cover weighting that "
            "exists only there. For the other sources, download the images and load them in the upload tab."
        )
        render_provider_table("multispectral")

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
        st.info(f"AOI derived from the catalogue record: {source_label}")

    with st.sidebar:
        project = st.text_input("Google Earth Engine project", cropmarks.default_project(), key="as_crop_project")
        sensor = st.selectbox(
            "Image archive",
            cropmarks.SENSOR_OPTIONS,
            key="as_crop_sensor",
            help="Landsat extends the search back to 1984, at 30 m: useful for palaeochannels, large enclosures and to see "
            "the landscape before recent transformations.",
        )
        default_start = date(1990, 1, 1) if sensor == cropmarks.SENSOR_LANDSAT else date(max(2016, date.today().year - 3), 1, 1)
        start = st.date_input("From", default_start, key="as_crop_start", min_value=date(1984, 1, 1))
        end = st.date_input("To", date.today(), key="as_crop_end", min_value=date(1984, 1, 1))
        target = st.selectbox(
            "Target mark",
            cropmarks.TARGETS,
            key="as_crop_target",
            help="Crop marks need a growing crop, soil marks a ploughed, bare field. "
            "The choice changes which dates enter the composite.",
        )
        cloud = st.slider("Max scene cloud cover (%)", 0, 100, 35, key="as_crop_cloud")
        pixel_cloud = st.slider(
            "Per-pixel cloud probability (%)",
            0,
            100,
            cropmarks.DEFAULT_PIXEL_CLOUD,
            key="as_crop_pixel_cloud",
        )
        topn = st.slider("Best dates to combine", 1, 20, 8, key="as_crop_topn")
        mode = st.selectbox(
            "Reference image",
            cropmarks.COMPOSITE_MODES,
            key="as_crop_mode",
            help="Only used to look at the area. Anomalies are always computed date by date and "
            "aggregated afterwards: a median composite would erase exactly the transient marks.",
        )
        persistence_threshold = st.slider(
            "Local persistence threshold",
            0.8,
            2.5,
            cropmarks.DEFAULT_PERSISTENCE_THRESHOLD,
            0.05,
            key="as_crop_persistence_threshold",
            help="Minimum local contrast to count an anomaly on a date.",
        )
        open_land_only = st.checkbox(
            "Limit the analysis to arable land and open areas",
            True,
            key="as_crop_open_land",
            help="Excludes built-up areas, woodland and water using ESA WorldCover. A roof edge produces more contrast "
            "than any buried wall: without this filter the statistics follow the built-up areas.",
        )
        use_rainfall = st.checkbox(
            "Weight dates by antecedent dryness",
            True,
            key="as_crop_rainfall",
            help="Compares the rainfall of the 30 days before each scene with the 1991-2020 mean (ERA5-Land).",
        )
        show_sites = st.checkbox("Show known sites on the map", True, key="as_crop_show_sites")
        export = st.checkbox("Export GeoTIFF to Google Drive", False, key="as_crop_export")
        folder = st.text_input("Drive folder", "S2_cropmarks", key="as_crop_folder")
        run = st.button("Run analysis", type="primary", width="stretch")
        reset = st.button("Reset analysis", width="stretch")

    if reset:
        st.session_state.as_crop_result = None
        st.session_state.as_crop_geometry = None
        st.session_state.as_crop_source_record = None
        st.session_state.as_crop_active_layer = None
        st.session_state.as_crop_validation = None
        st.rerun()

    draw_map = folium.Map(location=[41.5, 15.5], zoom_start=9, tiles=None)
    cropmarks.add_base_tiles(draw_map, esri_show=True)
    if st.session_state.as_crop_geometry:
        folium.GeoJson(
            st.session_state.as_crop_geometry,
            name="Active AOI",
            style_function=lambda _feature: {"color": "#ffd166", "weight": 3, "fillOpacity": 0.08},
        ).add_to(draw_map)
        bounds = cropmarks.geometry_bounds(st.session_state.as_crop_geometry)
        if bounds:
            draw_map.fit_bounds(bounds, padding=(24, 24))
            if show_sites:
                add_known_sites(draw_map, bounds, padding=0.05)
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
            st.error("The start date must precede the end date.")
            st.stop()
        drawings = draw.get("all_drawings") or []
        if drawings:
            st.session_state.as_crop_geometry = drawings[-1]["geometry"]
        if not st.session_state.as_crop_geometry:
            st.error("Draw a polygon or a rectangle on the map first.")
            st.stop()
        if project:
            cropmarks.save_default_project(project)
        st.session_state.as_crop_validation = None
        with st.spinner("Analysis running. Do not interact with the page until the result appears."):
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
                    sensor=sensor,
                    target=target,
                    open_land_only=open_land_only,
                    use_rainfall=use_rainfall,
                )
            except Exception as exc:
                st.session_state.as_crop_result = None
                LOGGER.exception("Crop Marks analysis not completed")
                st.error(f"Analysis not completed: {exc}")
                st.caption("If the area or the period is very large, reduce it and try again.")

    result = st.session_state.as_crop_result
    if result:
        render_crop_results(result, show_sites)

    render_crop_candidate_archive()


def render_crop_results(result, show_sites=True):
    frame = result["df"]
    selected = frame[frame["selected_for_composite"]] if "selected_for_composite" in frame else frame

    st.markdown(result_chips(result, selected), unsafe_allow_html=True)

    metric_cols = st.columns(4)
    metric_cols[0].metric("Scenes found", result.get("scene_count", 0))
    metric_cols[1].metric("Valid scenes", result.get("valid_scene_count", 0))
    metric_cols[2].metric("Dates combined", int(len(selected)))
    metric_cols[3].metric("Years covered", len(result.get("years") or []))

    ui.section_title("Best dates", eyebrow="Acquisition ranking")
    display_df = frame.copy()
    for column in display_df.columns:
        if display_df[column].dtype.kind == "f":
            display_df[column] = display_df[column].round(3)
    st.dataframe(display_df, width="stretch", hide_index=True)
    st.caption(
        "The score combines local contrast, usable coverage of the area, consistency with the target mark and "
        "dryness of the preceding 30 days. It is an investigation priority, not an archaeological probability."
    )

    if len(frame) > 1:
        chart_col, rain_col = st.columns([0.58, 0.42], gap="large")
        chart = frame.copy()
        chart["date"] = chart["date"].astype("datetime64[ns]")
        chart = chart.sort_values("date").set_index("date")
        with chart_col:
            st.markdown("**Index time series over the area**")
            st.line_chart(
                chart[["ndvi_mean", "savi_mean", "ndmi_mean"]],
                height=250,
                color=["#f1c75b", "#e0a458", "#8fd3d1"],
            )
        with rain_col:
            st.markdown("**Rainfall in the preceding 30 days vs 1991-2020 mean**")
            if result.get("rainfall_available") and chart["rain_30d_mm"].notna().any():
                st.line_chart(
                    chart[["rain_30d_mm", "rain_30d_normal_mm"]],
                    height=250,
                    color=["#8fd3d1", "#c7b899"],
                )
            else:
                st.info("Rainfall context not available for this run.")

    ui.section_title("Map of generated layers", eyebrow="Anomalie")
    st.markdown(CROP_LEGEND, unsafe_allow_html=True)
    layer_names = list(result["layer_specs"].keys())
    if st.session_state.as_crop_active_layer not in layer_names:
        preferred = "Overall persistence" if len(selected) > 1 else "False color 8-4-3"
        st.session_state.as_crop_active_layer = preferred if preferred in layer_names else layer_names[0]
    active_layer = st.selectbox(
        "Filter",
        layer_names,
        key="as_crop_active_layer",
        format_func=lambda name: f"{result['layer_specs'][name]['group']} · {name}",
    )
    if active_layer not in result["layer_urls"]:
        with st.spinner("Preparing the selected layer..."):
            result["layer_urls"][active_layer] = cropmarks.layer_url(result, active_layer)
    result_map = folium.Map(location=result["center"], zoom_start=14, tiles=None)
    cropmarks.add_base_tiles(result_map, esri_show=True)
    folium.GeoJson(
        result["geometry"],
        name="AOI",
        style_function=lambda _x: {"color": "yellow", "weight": 2, "fillOpacity": 0},
    ).add_to(result_map)
    cropmarks.add_layer(result_map, result["layer_urls"][active_layer], active_layer, show=True)
    if show_sites:
        add_known_sites(result_map, cropmarks.geometry_bounds(result["geometry"]), padding=0.03)
    folium.LayerControl(collapsed=False).add_to(result_map)
    st_folium(result_map, width=1200, height=760, key=f"as_crop_result_map_{active_layer}", returned_objects=[])

    cols = st.columns(3)
    with cols[0]:
        if result["download"]:
            st.link_button("Download GeoTIFF", result["download"], width="stretch")
        elif st.button("Prepare GeoTIFF download", width="stretch"):
            try:
                with st.spinner("Preparing download..."):
                    result["download"] = cropmarks.prepare_download(result)
                st.rerun()
            except Exception as exc:
                st.warning(f"Direct download not available: {exc}. Use the Drive export.")
    with cols[1]:
        if result["task_id"]:
            st.success("Drive export started. Task ID: " + result["task_id"])
    with cols[2]:
        st.caption(
            "Compare persistence, vegetation deficit and excess with RGB, soil and LiDAR before "
            "classifying the candidate."
        )

    render_site_validation(result)
    render_candidate_save_form(result, active_layer)


def result_chips(result, selected):
    params = result.get("params", {})
    phases = selected["phase"].value_counts().to_dict() if "phase" in selected else {}
    phase_text = ", ".join(f"{count} {label}" for label, count in phases.items()) or "n.d."
    dryness = selected["dryness"].mean() if "dryness" in selected and selected["dryness"].notna().any() else None
    years = result.get("years") or []
    span = f"{years[0]}-{years[-1]}" if years else "n.d."
    chips = [
        f'<span class="as-chip">Sensor <b>{params.get("sensor", "")}</b></span>',
        f'<span class="as-chip">Mark <b>{params.get("target", "")}</b></span>',
        f'<span class="as-chip">Years <b>{span}</b></span>',
        f'<span class="as-chip">Fasi <b>{phase_text}</b></span>',
    ]
    if dryness is not None:
        css = "as-chip as-chip--hot" if dryness >= 0.4 else "as-chip as-chip--cool"
        chips.append(f'<span class="{css}">Mean dryness <b>{dryness:.2f}</b></span>')
    if params.get("open_land_only"):
        chips.append('<span class="as-chip">Maschera <b>aree aperte</b></span>')
    return f'<div class="as-chips">{"".join(chips)}</div>'


def add_known_sites(target_map, bounds, padding=0.03):
    """Draw the documentary catalogue over an imagery map."""
    if not bounds:
        return 0
    try:
        sites = site_index.sites_in_bounds(
            bounds, padding=padding, methods=("pubblicata", "toponimo")
        )
    except Exception:
        LOGGER.exception("Known sites not available")
        return 0
    if not sites:
        return 0
    group = folium.FeatureGroup(name=f"Known sites ({len(sites)})", show=True)
    for site in sites:
        derived = site.get("coordinate_method") != "pubblicata"
        color = "#ffd166" if derived else "#4cc9f0"
        label = " · ".join(
            value
            for value in [
                site.get("number"),
                site.get("localita"),
                site.get("dating"),
                "position inferred from toponym" if derived else None,
            ]
            if value
        )
        radius_m = site.get("coordinate_uncertainty_m")
        if radius_m:
            folium.Circle(
                location=[site["lat"], site["lon"]],
                radius=float(radius_m),
                color=color,
                weight=1,
                opacity=0.5,
                fill=True,
                fill_opacity=0.06,
            ).add_to(group)
        folium.CircleMarker(
            location=[site["lat"], site["lon"]],
            radius=5,
            color=color,
            weight=2,
            fill=True,
            fill_color=color,
            fill_opacity=0.55,
            tooltip=label or site.get("number", "sito"),
        ).add_to(group)
    group.add_to(target_map)
    return len(sites)


def render_site_validation(result):
    """Does the anomaly map actually favour the sites we already know about?"""
    sites = cropmarks.sites_inside(
        result.get("geometry"), site_index.georeferenced_sites(methods=("pubblicata",))
    )
    with st.expander(f"Check against known sites in the area ({len(sites)})", expanded=False):
        st.caption(
            "Uses only records with published coordinates: testing the detector on positions inferred from the "
            "gazetteer would measure the gazetteer, not the detector."
        )
        if not sites:
            st.caption(
                "No record with published coordinates falls inside this AOI. Widen the area over a zone "
                "that is already catalogued to measure how well the detector separates known sites from the background."
            )
            return
        band = st.selectbox(
            "Layer to check",
            ["Persistent_any", "Vegetation_deficit", "Vegetation_excess", "Linear_marks", "Soil_mark_index"],
            key="as_crop_validation_band",
        )
        if st.button("Compare with random control points", key="as_crop_validate", width="stretch"):
            with st.spinner("Sampling..."):
                try:
                    st.session_state.as_crop_validation = cropmarks.validate_against_sites(result, sites, band=band)
                except Exception as exc:
                    st.session_state.as_crop_validation = None
                    LOGGER.exception("Validation not completed")
                    st.warning(f"Validation not completed: {exc}")
        report = st.session_state.get("as_crop_validation")
        if not report:
            return
        cols = st.columns(3)
        auc = report.get("auc")
        cols[0].metric("AUC sites vs controls", f"{auc:.2f}" if auc is not None else "n.d.")
        cols[1].metric(
            "Mean at known sites",
            f"{report['site_mean']:.3f}" if report.get("site_mean") is not None else "n.d.",
        )
        cols[2].metric(
            "Mean at controls",
            f"{report['control_mean']:.3f}" if report.get("control_mean") is not None else "n.d.",
        )
        st.caption(
            f"Layer {report['band']}: {len(report['sites'])} catalogued sites against "
            f"{len(report['controls'])} random points in the same area. AUC 0.5 means the layer does not "
            "separate known sites from the background; above 0.7 the separation is clear. The sample is small and the catalogued "
            "sites are not a random sample: this is a sanity check, not a statistical validation."
        )
        if report["sites"]:
            st.dataframe(report["sites"], hide_index=True, width="stretch")


def render_candidate_save_form(result, active_layer):
    source = compact_source_record(st.session_state.get("as_crop_source_record"))
    default_title = (
        f"{source.get('localita') or source.get('comune')} · {source.get('number')}"
        if source
        else f"AOI {result['center'][0]:.5f}, {result['center'][1]:.5f}"
    )
    with st.expander("Save as candidate", expanded=False):
        with st.form("as_candidate_save_form"):
            title = st.text_input("Candidate title", value=default_title)
            status = st.selectbox("Status", candidate_store.CANDIDATE_STATUSES)
            notes = st.text_area(
                "Interpretation notes",
                placeholder="Observed shape, possible false positives, documentary or LiDAR comparisons...",
            )
            submitted = st.form_submit_button("Save dossier", type="primary", width="stretch")
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
            st.success(f"Dossier {candidate['id']} saved in the Candidates archive.")


def render_crop_candidate_archive():
    candidates = candidate_store.load_candidates()
    if not candidates:
        return
    with st.expander(f"Local archive · {len(candidates)} candidates", expanded=False):
        recent = list(reversed(candidates[-8:]))
        st.dataframe(
            [
                {
                    "ID": item.get("id"),
                    "Title": item.get("title"),
                    "Status": item.get("status"),
                    "Aggiornato": item.get("updated_at"),
                }
                for item in recent
            ],
            hide_index=True,
            width="stretch",
        )


def render_candidates():
    ui.section_title(
        "Candidates and verification dossiers",
        eyebrow="Working archive",
        hint=(
            "Anomalies to compare with sources, historical imagery, LiDAR and field survey. "
            "The status is a working decision, not an archaeological certification."
        ),
    )
    candidates = candidate_store.load_candidates()
    if not candidates:
        st.info("No candidate saved yet. Run a Crop Marks analysis and use «Save as candidate».")
        return

    status_filter = st.multiselect(
        "Filter by status",
        candidate_store.CANDIDATE_STATUSES,
        default=list(candidate_store.CANDIDATE_STATUSES),
        key="as_candidate_status_filter",
    )
    filtered = [item for item in candidates if item.get("status") in status_filter]
    metric_cols = st.columns(4)
    metric_cols[0].metric("Total", len(candidates))
    metric_cols[1].metric("Shown", len(filtered))
    metric_cols[2].metric("Promising", sum(item.get("status") == "Promising" for item in candidates))
    metric_cols[3].metric("Verified", sum(item.get("status") == "Verified" for item in candidates))

    if filtered:
        candidate_map = folium.Map(location=[43.2, 13.3], zoom_start=8, tiles=None, control_scale=True)
        cropmarks.add_base_tiles(candidate_map, esri_show=True)
        all_bounds = []
        colors = {
            "To verify": "#ffd166",
            "Promising": "#ef476f",
            "False positive": "#8d99ae",
            "Verified": "#06d6a0",
        }
        for item in filtered:
            geometry = item.get("geometry")
            if not geometry:
                continue
            color = colors.get(item.get("status"), "#ffd166")
            folium.GeoJson(
                geometry,
                tooltip=f"{item.get('title', 'Candidate')} · {item.get('status', '')}",
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
        item["id"]: f"{item.get('title', 'Candidate')} · {item.get('status', '')} · {item['id']}"
        for item in filtered
    }
    if not labels:
        st.info("No candidate matches the filters.")
        return
    selected_id = st.selectbox("Dossier", list(labels), format_func=labels.get, key="as_candidate_selected")
    selected = next(item for item in filtered if item.get("id") == selected_id)

    detail_col, action_col = st.columns([0.62, 0.38], gap="large")
    with detail_col:
        st.subheader(selected.get("title") or selected_id)
        source = selected.get("source_record") or {}
        if source:
            st.write(
                "Source: "
                + " · ".join(
                    str(value)
                    for value in [source.get("source_collection"), source.get("number"), source.get("comune"), source.get("localita")]
                    if value
                )
            )
        st.write(selected.get("notes") or "No interpretation notes.")
        ranking = selected.get("ranking") or []
        if ranking:
            st.markdown("**Priority dates**")
            st.dataframe(ranking, hide_index=True, width="stretch")
    with action_col:
        status = st.selectbox(
            "Dossier status",
            candidate_store.CANDIDATE_STATUSES,
            index=candidate_store.CANDIDATE_STATUSES.index(selected.get("status", "To verify")),
            key=f"as_candidate_status_{selected_id}",
        )
        notes = st.text_area(
            "Note",
            value=selected.get("notes") or "",
            key=f"as_candidate_notes_{selected_id}",
        )
        if st.button("Update dossier", type="primary", width="stretch"):
            candidate_store.update_candidate(selected_id, {"status": status, "notes": notes})
            st.success("Dossier updated.")
            st.rerun()
        if st.button("Reopen in Crop Marks", width="stretch"):
            st.session_state.as_crop_geometry = selected.get("geometry")
            st.session_state.as_crop_source_record = selected.get("source_record")
            st.session_state.as_crop_result = None
            st.session_state.as_crop_active_layer = None
            st.session_state.as_active_tool = "Crop Marks"
            st.rerun()

    download_cols = st.columns(2)
    download_cols[0].download_button(
        "Export archive as JSON",
        candidate_store.candidates_json(candidates),
        file_name="airch_candidates.json",
        mime="application/json",
        width="stretch",
    )
    download_cols[1].download_button(
        "Export areas as GeoJSON",
        candidate_store.candidates_geojson(candidates),
        file_name="airch_candidates.geojson",
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
