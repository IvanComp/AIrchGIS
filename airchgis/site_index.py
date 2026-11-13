

import json
from functools import lru_cache
from pathlib import Path

from . import geocoding
from .database_enrichment import enrich_database
from .paths import PROJECT_ROOT, RVT_DIR


DATA_PATH = PROJECT_ROOT / "airchgis" / "data" / "cam_m_sites.json"
COORDINATES_PATH = RVT_DIR / "output_rvt_gui" / "cam_m_database" / "coordinate_overrides.json"


def load_overrides(path=COORDINATES_PATH):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    coordinates = raw.get("coordinates", raw)
    if not isinstance(coordinates, dict):
        return {}
    cleaned = {}
    for number, payload in coordinates.items():
        if not isinstance(payload, dict):
            continue
        try:
            lat = float(payload["lat"])
            lon = float(payload["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            cleaned[str(number)] = {"lat": lat, "lon": lon, "source": payload.get("source", "")}
    return cleaned


@lru_cache(maxsize=1)
def _cached_sites(stamp):
    del stamp
    if not DATA_PATH.exists():
        return ()
    database = enrich_database(json.loads(DATA_PATH.read_text(encoding="utf-8")))
    records = database.get("records", [])
    geocoding.apply_geocoding(records)
    overrides = load_overrides()
    sites = []
    for record in records:
        override = overrides.get(record.get("number"))
        lat = override["lat"] if override else record.get("lat")
        lon = override["lon"] if override else record.get("lon")
        if lat is None or lon is None:
            continue
        method = "pubblicata" if override else (record.get("coordinate_method") or "pubblicata")
        sites.append(
            {
                "number": record.get("number", ""),
                "comune": record.get("comune", ""),
                "localita": record.get("localita", ""),
                "definition": record.get("definition", ""),
                "dating": record.get("dating", ""),
                "find_type": record.get("find_type", ""),
                "source_collection": record.get("source_collection", ""),
                "coordinate_precision": record.get("coordinate_precision", ""),
                "coordinate_method": method,
                "coordinate_uncertainty_m": None if override else record.get("coordinate_uncertainty_m"),
                "lat": float(lat),
                "lon": float(lon),
            }
        )
    return tuple(sites)


def georeferenced_sites(methods=None):

    stamp = 0
    for path in (DATA_PATH, COORDINATES_PATH, geocoding.GAZETTEER_PATH):
        if Path(path).exists():
            stamp += Path(path).stat().st_mtime_ns
    sites = list(_cached_sites(stamp))
    if methods is None:
        return sites
    allowed = set(methods)
    return [site for site in sites if site.get("coordinate_method") in allowed]


def sites_in_bounds(bounds, padding=0.0, sites=None, methods=None):

    if not bounds:
        return []
    (south, west), (north, east) = bounds
    south, west = south - padding, west - padding
    north, east = north + padding, east + padding
    pool = georeferenced_sites(methods) if sites is None else sites
    return [
        site
        for site in pool
        if south <= site["lat"] <= north and west <= site["lon"] <= east
    ]


def bounds_from_geometry(geometry):

    if not geometry:
        return None
    points = []
    _flatten(geometry.get("coordinates", []), points)
    if not points:
        return None
    lats = [float(point[1]) for point in points]
    lons = [float(point[0]) for point in points]
    return [[min(lats), min(lons)], [max(lats), max(lons)]]


def _flatten(coordinates, out):
    if not coordinates:
        return
    if isinstance(coordinates[0], (int, float)):
        out.append(coordinates)
        return
    for item in coordinates:
        _flatten(item, out)
