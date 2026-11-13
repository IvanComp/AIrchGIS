"""Streamlit panels: "Enhance & best view" on the Terrain and Field marks screens.

Every action goes through :func:`airchgis.gis.tools.run_tool`, so it is
recorded in the session's provenance log and can be replayed as a script.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from airchgis import data_input as di
from airchgis.enhance import bestview, contrast, metrics, multispectral
from airchgis.gis.provenance import ProvenanceLog
from airchgis.gis.tools import ToolError, run_tool
from airchgis.input_ui import render_file_input

OUT_DIR = di.WORKSPACE_DIR / "outputs" / "enhance"

STEP_LABELS = {"destripe": "Remove banding", "despike": "Remove spikes and pits", "fill_voids": "Fill small voids",
               "denoise": "Reduce noise (edge-preserving)"}
METRIC_LABELS = {"noise_sigma": "Noise (elevation units)", "stripe_energy": "Banding (share of fine detail)",
                 "spike_fraction": "Spikes and pits (share of pixels)", "void_fraction": "Voids (share of pixels)"}


def session_log() -> ProvenanceLog:
    if st.session_state.get("as_provenance_log") is None:
        st.session_state.as_provenance_log = ProvenanceLog("AIrchGIS session")
    return st.session_state.as_provenance_log


def _png(arr, cmap="gray", enhance=None):
    import matplotlib
    from PIL import Image

    a = np.asarray(arr, dtype=np.float64)
    if enhance:
        a, _ = contrast.enhance(a, enhance)
    finite = a[np.isfinite(a)]
    lo, hi = (np.percentile(finite, [2, 98]) if finite.size else (0, 1))
    norm = np.clip((a - lo) / max(hi - lo, 1e-12), 0, 1)
    rgba = (matplotlib.colormaps[cmap](np.nan_to_num(norm)) * 255).astype(np.uint8)
    rgba[..., 3] = np.where(np.isfinite(a), 255, 0)
    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, "PNG")
    return buf.getvalue()


def _hillshade(dem, res):
    import rvt.vis

    f, mask = metrics.finite_fill(dem)
    h = rvt.vis.hillshade(f.astype(np.float32), res, res, sun_azimuth=315, sun_elevation=35, ve_factor=2)
    h = np.asarray(h, dtype=np.float32)
    h[mask] = np.nan
    return h


def _read(path):
    import rasterio

    with rasterio.open(path) as src:
        a = src.read(1).astype(np.float32)
        if src.nodata is not None:
            a[a == src.nodata] = np.nan
    return a


def _write_input(arr, profile, crs, name):
    import rasterio

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.tif"
    prof = dict(profile)
    prof.update(driver="GTiff", count=1, dtype="float32", nodata=-9999.0, crs=crs or prof.get("crs"), compress="deflate",
                height=arr.shape[0], width=arr.shape[1])
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(np.where(np.isfinite(arr), arr, -9999.0).astype(np.float32), 1)
    return path


def _download(path, label, key):
    p = Path(path)
    if p.exists():
        st.download_button(label, p.read_bytes(), file_name=p.name, key=key)


def render_provenance_download(key):
    log = session_log()
    if not log.steps:
        return
    st.download_button("Download the steps as a Python script (re-runnable)", log.to_python().encode(),
                       file_name=f"airchgis_steps_{datetime.now():%Y%m%d_%H%M}.py", key=key)


# ---------------------------------------------------------------- Terrain
def one_sentence(ranking, width):
    """Short explanation of the winner, for the main result."""
    if not ranking:
        return "No view could be computed."
    top = ranking[0]
    text = f"{top['name']} shows features about {width:g} m wide most clearly (visibility {top['score']:.2f}"
    if len(ranking) > 1:
        text += f"; next: {ranking[1]['name']}, {ranking[1]['score']:.2f}"
    return text + ")."


def _show_cleaning(cleaned, dem, res, key, on_apply):
    q = cleaned["quality"]
    rows = [{"measure": METRIC_LABELS[k], "before": q["before"][k], "after": q["after"][k]} for k in METRIC_LABELS]
    st.markdown("Cleaning: before and after")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"before": st.column_config.NumberColumn(format="%.3g"),
                                "after": st.column_config.NumberColumn(format="%.3g")})
    for note in cleaned["summary"]:
        st.caption("· " + note)
    b1, b2 = st.columns(2)
    with b1:
        _download(cleaned["output"], "Download the cleaned terrain (GeoTIFF)", f"{key}_clean_dl")
    if on_apply is not None and b2.button("Use the cleaned terrain in all tools", key=f"{key}_apply",
                                          help="The original stays on disk; reload the data to go back to it."):
        on_apply(_read(cleaned["output"]))
        st.rerun()


def _show_best(bv, sites, key, width, full_table=False, before=None, geo=None):
    if bv["status"] == "refused":
        st.error(bv["message"])
        return
    if bv.get("message"):
        st.warning(bv["message"])
    out = bv["outputs"]
    if not full_table:
        st.success(one_sentence(out["ranking"], width))
        contrast_on = st.toggle("Stronger contrast (display only)", value=False, key=f"{key}_bv_disp",
                                help="Adaptive histogram equalization: easier to see, but values are no longer elevations.")
        best = _read(out["output"])
        if contrast_on:
            best, _ = contrast.enhance(best, "clahe")
        shown = False
        if geo is not None:
            try:
                from airchgis.map.view import georeference, render_map

                transform, crs, elevation = geo
                layers = [georeference(best, transform, crs, "best", f"After: {out['best']}",
                                       "Best view for the width you typed. Switch it off to see the original.")]
                if before is not None:
                    layers.append(georeference(before, transform, crs, "before", "Before: original (hillshade)",
                                               "The terrain as loaded, before cleaning.", visible=False))
                render_map(layers, elevation=elevation, height=600)
                shown = True
            except Exception as exc:
                st.caption(f"Map not available ({exc}); showing the image.")
        if not shown:
            view = st.segmented_control("Show", ["After: best view", "Before: original"], default="After: best view",
                                        key=f"{key}_ba") or "After: best view"
            if view.startswith("Before") and before is not None:
                st.image(_png(before), caption="Original terrain (hillshade)", width="stretch")
            else:
                st.image(_png(best), caption=out["best"], width="stretch")
        _download(out["output"], "Download the best view (GeoTIFF)", f"{key}_bv_dl")
    if full_table:
        table = pd.DataFrame([{"rank": i + 1, "view": x["name"], "visibility": round(x["score"], 2),
                               **({"AUC at your sites": None if x.get("auc") is None else round(x["auc"], 2)} if sites else {})}
                              for i, x in enumerate(out["ranking"])])
        st.dataframe(table, hide_index=True, width="stretch", height=260)
        st.caption(out["explanation"])
        st.caption(f"Scored on the {out['scored_on']}. Visibility: how much features of the chosen width stand out "
                   "from the noise and from the broad landscape. Higher is clearer; it is not a probability.")


def render_terrain_enhance(dem, res, profile, crs, label="DTM", on_apply=None, key="as_enh_t"):
    """One button for the recommended pipeline (clean, rank views, show the best); single steps under Advanced."""
    if dem is None or profile is None or profile.get("transform") is None:
        st.info("Load a georeferenced terrain model first.")
        return
    dem, n_zero = metrics.zero_nodata(dem)
    tag = f"{key}_{abs(hash((dem.shape, float(np.nanmean(dem)) if np.isfinite(dem).any() else 0))) % 10**8}"
    src_path = st.session_state.get(f"{tag}_src")
    if not src_path or not Path(src_path).exists():
        src_path = str(_write_input(np.asarray(dem, dtype=np.float32), profile, crs, f"{label}_{tag}"))
        st.session_state[f"{tag}_src"] = src_path

    width = st.number_input("Width of the features you are looking for (m)", 0.1, 1000.0, float(max(2.0 * res, 4.0)),
                            key=f"{key}_width", help="For example 3 m for a ditch, 10 m for a road, 30 m for an enclosure.")
    with st.expander("Known sites (optional)"):
        site_paths = render_file_input("Known sites", di.SITE_EXTS, f"{key}_sites", "sites", multiple=False)
    sites = str(site_paths[0]) if site_paths else None
    quick = dem.size > 4_000_000

    if st.button("Improve and find the best view", type="primary", key=f"{key}_auto"):
        with st.spinner("Cleaning the terrain and comparing views..."):
            try:
                c = run_tool("clean_terrain", log=session_log(), input=src_path,
                             output=str(OUT_DIR / f"{label}_{tag}_clean.tif"), steps=list(STEP_LABELS))
                st.session_state[f"{tag}_clean"] = c["outputs"]
                st.session_state[f"{key}_width_used"] = float(width)
                st.session_state[f"{tag}_bv"] = run_tool(
                    "best_view", log=session_log(), input=c["outputs"]["output"], output_dir=str(OUT_DIR / f"{tag}_bestview"),
                    target_feature_width_m=float(width), sites=sites, quick=quick)
                st.session_state[f"{tag}_fused"] = None
            except ToolError as exc:
                st.error(str(exc))

    cleaned = st.session_state.get(f"{tag}_clean")
    bv = st.session_state.get(f"{tag}_bv")
    if bv:
        geo = None
        if profile.get("transform") is not None and crs is not None:
            from airchgis.map.view import elevation_grid

            geo = (profile["transform"], crs, elevation_grid(dem, profile["transform"], crs))
        _show_best(bv, sites, key, st.session_state.get(f"{key}_width_used", width), before=_hillshade(dem, res), geo=geo)
    if cleaned or bv:
        with st.expander("Details"):
            if n_zero:
                st.caption(f"{n_zero} pixels with elevation exactly 0 were treated as no data (fill outside the survey).")
            if cleaned:
                _show_cleaning(cleaned, dem, res, key, on_apply)
            if bv and bv["status"] != "refused":
                st.markdown("All views, best first")
                _show_best(bv, sites, f"{key}_det", st.session_state.get(f"{key}_width_used", width), full_table=True)
            render_provenance_download(f"{key}_prov")

    with st.expander("Advanced"):
        st.markdown("**Cleaning steps**")
        steps = st.multiselect("Steps to apply", list(STEP_LABELS), default=list(STEP_LABELS), format_func=STEP_LABELS.get,
                               key=f"{key}_steps")
        if st.button("Clean only", key=f"{key}_clean_go", disabled=not steps):
            try:
                r = run_tool("clean_terrain", log=session_log(), input=src_path, output=str(OUT_DIR / f"{label}_{tag}_clean.tif"), steps=steps)
                st.session_state[f"{tag}_clean"] = r["outputs"]
                st.rerun()
            except ToolError as exc:
                st.error(str(exc))
        current_path = cleaned["output"] if cleaned and st.checkbox("Work on the cleaned terrain", value=True, key=f"{key}_use_clean") else src_path

        if not bv and st.button("Rank the views without cleaning", key=f"{key}_bv_go"):
            try:
                st.session_state[f"{key}_width_used"] = float(width)
                st.session_state[f"{tag}_bv"] = run_tool("best_view", log=session_log(), input=current_path,
                                                         output_dir=str(OUT_DIR / f"{tag}_bestview"),
                                                         target_feature_width_m=float(width), sites=sites, quick=quick)
                st.rerun()
            except ToolError as exc:
                st.error(str(exc))

        st.markdown("**Fused view**")
        st.caption("Blends the four best views with weights chosen to make features stand out most.")
        if st.button("Build the fused view", key=f"{key}_fuse_go"):
            with st.spinner("Blending..."):
                try:
                    st.session_state[f"{tag}_fused"] = run_tool(
                        "fused_view", log=session_log(), input=current_path, output=str(OUT_DIR / f"{tag}_fused.tif"),
                        target_feature_width_m=float(width), method="optimized", n_layers=4, sites=sites)
                except ToolError as exc:
                    st.error(str(exc))
        fz = st.session_state.get(f"{tag}_fused")
        if fz:
            if fz["status"] == "refused":
                st.error(fz["message"])
            else:
                out = fz["outputs"]
                best = out["best_single"]["name"]
                if out["gain_over_best_single"] <= 1.0 + 1e-6:
                    st.info(f"The blend does not show features more clearly than {best}, so the best single view is kept.")
                    if bv and bv["status"] != "refused":
                        st.image(_png(_read(bv["outputs"]["output"])), caption=bv["outputs"]["best"], width="stretch")
                else:
                    st.success(out["note"] + (f" AUC at your sites: {out['auc']:.2f}." if out.get("auc") is not None else ""))
                    try:
                        from airchgis.map.view import elevation_grid, georeference, render_map

                        layers = [georeference(_read(out["output"]), profile["transform"], crs, "fused", "Fused view",
                                               "Blend of the best views.")]
                        if bv and bv["status"] != "refused":
                            layers.append(georeference(_read(bv["outputs"]["output"]), profile["transform"], crs, "best",
                                                       bv["outputs"]["best"], "Best single view.", visible=False))
                        render_map(layers, elevation=elevation_grid(dem, profile["transform"], crs), height=520)
                    except Exception:
                        st.image(_png(_read(out["output"])), caption="Fused view", width="stretch")
                    _download(out["output"], "Download the fused view (GeoTIFF)", f"{key}_fuse_dl")

        st.markdown("**Point cloud**")
        st.caption("Remove isolated points (birds, wrong returns) from a LAS/LAZ file before making a terrain model.")
        pc = render_file_input("Point cloud (LAS/LAZ)", {".las", ".laz"}, f"{key}_pc", "point_clouds", multiple=False)
        if pc and st.button("Remove isolated points", key=f"{key}_pc_go"):
            try:
                r = run_tool("remove_point_outliers", log=session_log(), input=str(pc[0]),
                             output=str(OUT_DIR / f"{Path(pc[0]).stem}_clean{Path(pc[0]).suffix}"))
                st.session_state[f"{key}_pc_out"] = r["outputs"]
            except ToolError as exc:
                st.error(str(exc))
        pco = st.session_state.get(f"{key}_pc_out")
        if pco:
            st.caption(pco["note"])
            _download(pco["output"], "Download the cleaned point cloud", f"{key}_pc_dl")


# ---------------------------------------------------------------- Field marks
def render_scene_quality(load_scenes, key="as_enh_q"):
    """Quality of each date on request (clouds, shadows, haze, band problems)."""
    with st.expander("Image quality per date"):
        if st.button("Check image quality", key=f"{key}_go"):
            try:
                st.session_state[f"{key}_rows"] = multispectral.quality_table(load_scenes())
            except Exception as exc:
                st.error(f"Image quality not available: {exc}")
        rows = st.session_state.get(f"{key}_rows")
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.caption("Simple brightness and haze rules, not a cloud model.")


def render_field_marks_enhance(result, sites=None, key="as_enh_fm"):
    """Rank the computed layers by visibility and show the best one with adaptive contrast."""
    with st.expander("Enhance & best view", expanded=False):
        width = st.number_input("Width of the features sought (m)", 0.5, 2000.0, float(max(2 * result.gsd_m, 20.0)), key=f"{key}_width")
        layers = {k: v for k, v in result.layers.items() if k != "Field boundaries"}
        px = None
        if sites and result.crs is not None:
            from pyproj import Transformer

            tr = Transformer.from_crs("EPSG:4326", result.crs, always_xy=True)
            inv = ~result.transform
            px = []
            for s in sites:
                x, y = tr.transform(s.lon, s.lat)
                c, r = inv * (x, y)
                px.append((r, c))
        r = bestview.rank_layers(layers, result.gsd_m, width, site_pixels=px)
        if not r["ranking"]:
            st.info("No layer to rank.")
            return
        st.success(r["explanation"])
        st.dataframe(pd.DataFrame([{"layer": x["name"], "visibility": round(x["score"], 2),
                                    **({"AUC at your sites": None if x.get("auc") is None else round(x["auc"], 2)} if px else {})}
                                   for x in r["ranking"]]), hide_index=True, width="stretch")
        top = r["ranking"][0]["name"]
        c1, c2 = st.columns(2)
        c1.image(_png(layers[top], "magma"), caption=f"{top}", width="stretch")
        c2.image(_png(layers[top], "magma", enhance="clahe"), caption=f"{top}, adaptive contrast (display only)", width="stretch")
