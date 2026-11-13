

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from airchgis.gis.guardrails import check_resolvability
from airchgis.gis.provenance import ProvenanceLog
from airchgis.gis.tools import run_tool


@dataclass
class Workflow:
    name: str
    title: str
    description: str
    run: object

    def spec(self):
        return {"name": self.name, "title": self.title, "description": self.description}


def lidar_micro_relief(dtm, output_dir, aoi=None, target_feature_width_m=None, radius_m=10.0, log=None, prefer="auto"):

    log = log or ProvenanceLog("LiDAR micro-relief")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(dtm).stem
    results = {"log": log, "steps": [], "outputs": {}}

    current = str(dtm)
    if aoi:
        r = run_tool("clip_raster_to_aoi", log=log, prefer=prefer, input=current, aoi=str(aoi), output=str(out / f"{stem}_aoi.tif"))
        results["steps"].append(r)
        current = r["outputs"]["output"]

    guard = {"target_feature_width_m": target_feature_width_m} if target_feature_width_m else {}
    plan = [
        ("local_relief_model", {"radius_m": max(radius_m * 2, 20.0)}, "lrm"),
        ("sky_view_factor", {"radius_m": radius_m}, "svf"),
        ("openness", {"radius_m": radius_m}, "openness_pos"),
        ("openness", {"radius_m": radius_m, "negative": True}, "openness_neg"),
        ("hillshade", {}, "hillshade"),
    ]
    for tool, extra, key in plan:
        r = run_tool(tool, log=log, prefer=prefer, input=current, output=str(out / f"{stem}_{key}.tif"), **extra, **guard)
        results["steps"].append(r)
        if r["status"] == "refused":
            results["status"] = "refused"
            results["message"] = r["message"]
            return results
        results["outputs"][key] = r["outputs"]["output"]
    results["status"] = "warn" if any(s["status"] == "warn" for s in results["steps"]) else "ok"
    results["scripts"] = {k: str(v) for k, v in log.save_scripts(out, stem=f"{stem}_micro_relief").items()}
    return results


def crop_mark_screening(target_feature_width_m, sensor="sentinel-2", n_dates=1, aoi=None, start=None, end=None, log=None):

    log = log or ProvenanceLog("Crop-mark screening")
    r = run_tool("check_resolvability", log=log, feature_width_m=float(target_feature_width_m), sensor=sensor, n_dates=int(n_dates))
    verdict = r["outputs"]
    if verdict["verdict"] == "refuse":
        return {"status": "refused", "message": verdict["message"], "resolvability": verdict, "log": log}
    settings = {
        "sensor": sensor,
        "aoi": str(aoi) if aoi else None,
        "start": start,
        "end": end,
        "target": "Automatic",
        "parcel_interior_statistics": True,
        "open_land_mask": True,
        "steps": ["rank scenes by local contrast, crop phase and antecedent dryness",
                  "per-date anomaly maps inside field parcels",
                  "persistence and multi-year recurrence",
                  "check against known sites (AUC vs random controls)"],
    }
    return {"status": verdict["verdict"], "message": verdict["message"], "resolvability": verdict, "settings": settings, "log": log}


WORKFLOWS = {
    "lidar_micro_relief": Workflow(
        "lidar_micro_relief",
        "LiDAR micro-relief",
        "Finds small banks, ditches and mounds in a terrain model: removes the landscape trend, then shows hollows and ridges "
        "from several complementary visualizations. Every step is saved as a re-runnable script.",
        lidar_micro_relief,
    ),
    "crop_mark_screening": Workflow(
        "crop_mark_screening",
        "Crop-mark screening",
        "Looks for crop and soil marks in Sentinel-2 or Landsat images, after checking that features of the requested width "
        "can be seen at all at that resolution.",
        crop_mark_screening,
    ),
}
