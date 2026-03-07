import json
import os
import subprocess
import tempfile
from pathlib import Path

import rasterio
from rasterio.mask import mask
from shapely.geometry import shape, mapping
from shapely.ops import transform as shp_transform
from pyproj import Transformer


SMRF_DEFAULTS = {
    "slope": 0.2,
    "window": 16.0,
    "threshold": 0.45,
    "scalar": 1.25,
}

CLASSIFICATION_PROFILES = {
    "smrf_default": {
        "filter": "smrf",
        "params": {"slope": 0.2, "window": 16.0, "threshold": 0.45, "scalar": 1.25},
    },
    "smrf_conservative": {
        "filter": "smrf",
        "params": {"slope": 0.15, "window": 12.0, "threshold": 0.30, "scalar": 1.10},
    },
    "smrf_aggressive": {
        "filter": "smrf",
        "params": {"slope": 0.30, "window": 24.0, "threshold": 0.70, "scalar": 1.50},
    },
    "pmf_default": {
        "filter": "pmf",
        "params": {
            "cell_size": 1.0,
            "slope": 1.0,
            "initial_distance": 0.15,
            "max_distance": 2.5,
            "max_window_size": 33,
        },
    },
}


def load_aoi_polygon(aoi_geojson_path):
    with open(aoi_geojson_path, "r", encoding="utf-8") as f:
        gj = json.load(f)
    feats = [ft for ft in gj.get("features", []) if ft.get("geometry", {}).get("type") in ("Polygon", "MultiPolygon")]
    if not feats:
        raise ValueError("AOI GeoJSON: nessun Polygon/MultiPolygon trovato.")
    return shape(feats[0]["geometry"])


def reproject_geom(geom, src_epsg, dst_epsg):
    if src_epsg == dst_epsg:
        return geom
    t = Transformer.from_crs(src_epsg, dst_epsg, always_xy=True)
    return shp_transform(lambda x, y: t.transform(x, y), geom)


def crop_raster_to_aoi(src_tif, aoi_geojson, out_tif):
    aoi_wgs84 = load_aoi_polygon(aoi_geojson)
    with rasterio.open(src_tif) as src:
        dst_epsg = src.crs.to_epsg() if src.crs else None
        if dst_epsg is None:
            raise ValueError("GeoTIFF senza EPSG esplicito; serve un CRS leggibile.")
        aoi_in_raster_crs = reproject_geom(aoi_wgs84, 4326, dst_epsg)
        out_image, out_transform = mask(src, [mapping(aoi_in_raster_crs)], crop=True, filled=True)
        out_meta = src.meta.copy()
        out_meta.update({"height": out_image.shape[1], "width": out_image.shape[2], "transform": out_transform})
        with rasterio.open(out_tif, "w", **out_meta) as dst:
            dst.write(out_image)


def run_pdal_pipeline(pipeline):
    p = subprocess.run(
        ["pdal", "pipeline", "--stdin"],
        input=json.dumps(pipeline).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode("utf-8"))


def pdal_raster_to_las_or_laz(input_tif, output_path, srs_wkt, write_laz):
    pipeline = {
        "pipeline": [
            {"type": "readers.gdal", "filename": input_tif},
            {"type": "writers.las", "filename": output_path, "a_srs": srs_wkt},
        ]
    }
    if write_laz:
        pipeline["pipeline"][1]["compression"] = "laszip"
    run_pdal_pipeline(pipeline)


def pdal_classify_point_cloud(input_cloud, output_cloud, write_laz=True, profile=None):
    profile = profile or CLASSIFICATION_PROFILES["smrf_default"]
    filter_name = profile["filter"]
    params = profile["params"]
    if filter_name == "smrf":
        ground_filter = {
            "type": "filters.smrf",
            "ignore": "Classification[7:7]",
            "slope": float(params["slope"]),
            "window": float(params["window"]),
            "threshold": float(params["threshold"]),
            "scalar": float(params["scalar"]),
        }
    elif filter_name == "pmf":
        ground_filter = {
            "type": "filters.pmf",
            "ignore": "Classification[7:7]",
            "cell_size": float(params["cell_size"]),
            "slope": float(params["slope"]),
            "initial_distance": float(params["initial_distance"]),
            "max_distance": float(params["max_distance"]),
            "max_window_size": int(params["max_window_size"]),
        }
    else:
        raise ValueError(f"Profilo non supportato: {filter_name}")

    pipeline = {
        "pipeline": [
            {"type": "readers.las", "filename": input_cloud},
            ground_filter,
            {"type": "writers.las", "filename": output_cloud},
        ]
    }
    if write_laz:
        pipeline["pipeline"][-1]["compression"] = "laszip"
    run_pdal_pipeline(pipeline)


def pdal_make_dtm_from_classified(input_cloud, output_tif, resolution):
    pipeline = {
        "pipeline": [
            {"type": "readers.las", "filename": input_cloud},
            {"type": "filters.range", "limits": "Classification[2:2]"},
            {
                "type": "writers.gdal",
                "filename": output_tif,
                "resolution": float(resolution),
                "output_type": "min",
                "gdaldriver": "GTiff",
                "window_size": 3,
                "nodata": -9999,
            },
        ]
    }
    run_pdal_pipeline(pipeline)


def process_one(tif_path, out_dir, aoi_geojson=None, prefer_laz=True, classify=True):
    os.makedirs(out_dir, exist_ok=True)

    with rasterio.open(tif_path) as src:
        srs_wkt = src.crs.to_wkt() if src.crs else None
        if srs_wkt is None:
            raise ValueError("GeoTIFF senza CRS.")
        resolution = abs(float(src.res[0])) if src.res else 1.0

    base = os.path.splitext(os.path.basename(tif_path))[0]

    with tempfile.TemporaryDirectory() as td:
        in_tif = tif_path
        if aoi_geojson and os.path.exists(aoi_geojson):
            cropped = os.path.join(td, f"{base}_crop.tif")
            crop_raster_to_aoi(tif_path, aoi_geojson, cropped)
            in_tif = cropped

        if prefer_laz:
            out_path = os.path.join(out_dir, f"{base}.laz")
            try:
                pdal_raster_to_las_or_laz(in_tif, out_path, srs_wkt, write_laz=True)
                return _classify_output(out_path, out_dir, base, prefer_laz, classify, resolution)
            except RuntimeError:
                pass

        out_path = os.path.join(out_dir, f"{base}.las")
        pdal_raster_to_las_or_laz(in_tif, out_path, srs_wkt, write_laz=False)
        return _classify_output(out_path, out_dir, base, prefer_laz, classify, resolution)


def _classify_output(out_path, out_dir, base, prefer_laz, classify, resolution):
    if not classify:
        return out_path, None, None
    outputs = []
    dtm_outputs = []
    for profile_name, profile in CLASSIFICATION_PROFILES.items():
        if prefer_laz:
            classified_path = os.path.join(out_dir, f"{base}_classified_{profile_name}.laz")
            try:
                pdal_classify_point_cloud(out_path, classified_path, write_laz=True, profile=profile)
                outputs.append(classified_path)
                dtm_path = os.path.join(out_dir, f"{base}_dtm_{profile_name}.tif")
                pdal_make_dtm_from_classified(classified_path, dtm_path, resolution)
                dtm_outputs.append(dtm_path)
                continue
            except RuntimeError:
                pass
        classified_path = os.path.join(out_dir, f"{base}_classified_{profile_name}.las")
        pdal_classify_point_cloud(out_path, classified_path, write_laz=False, profile=profile)
        outputs.append(classified_path)
        dtm_path = os.path.join(out_dir, f"{base}_dtm_{profile_name}.tif")
        pdal_make_dtm_from_classified(classified_path, dtm_path, resolution)
        dtm_outputs.append(dtm_path)
    return out_path, outputs, dtm_outputs


def list_rasters(root_dir):
    root = Path(root_dir)
    if not root.exists():
        return []
    out = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".tif", ".tiff"}:
            out.append(p)
    return sorted(out)


def find_nearest_geojson(start_path, stop_dir):
    stop_dir = Path(stop_dir).resolve()
    cur = Path(start_path).resolve().parent
    while True:
        for p in sorted(cur.glob("*.geojson")) + sorted(cur.glob("*.json")):
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            feats = obj.get("features", []) if isinstance(obj, dict) else []
            if any(ft.get("geometry", {}).get("type") in {"Polygon", "MultiPolygon"} for ft in feats):
                return str(p)
        if cur == stop_dir or cur.parent == cur:
            break
        cur = cur.parent
    return None


def collapse_duplicate_levels(rel_path: Path):
    parts = list(rel_path.parts)
    if len(parts) >= 2 and parts[0].lower() == parts[1].lower():
        return Path(*parts[1:])
    return rel_path


def main():
    script_dir = Path(__file__).resolve().parent
    input_root = (script_dir / "to_convert").resolve()
    output_root = (script_dir / "out_laz").resolve()

    rasters = list_rasters(input_root)
    if not rasters:
        print(f"Nessun raster trovato in: {input_root}")
        return

    ok = 0
    fail = 0
    for tif in rasters:
        rel_parent = tif.parent.relative_to(input_root)
        rel_parent = collapse_duplicate_levels(rel_parent)
        out_dir = output_root / rel_parent
        aoi = find_nearest_geojson(tif, input_root)
        try:
            cloud_path, classified_path, dtm_paths = process_one(
                str(tif),
                str(out_dir),
                aoi_geojson=aoi,
                prefer_laz=True,
                classify=True,
            )
            ok += 1
            if classified_path:
                joined = ", ".join(classified_path)
                dtm_joined = ", ".join(dtm_paths or [])
                print(f"OK: {tif} -> {cloud_path} | classified -> {joined} | dtm -> {dtm_joined}")
            else:
                print(f"OK: {tif} -> {cloud_path}")
        except Exception as e:
            fail += 1
            print(f"ERRORE: {tif} -> {e}")

    print(f"Completato. OK={ok}, FAIL={fail}, OUT={output_root}")


if __name__ == "__main__":
    main()
