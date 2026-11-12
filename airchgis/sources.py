"""Public data sources, offered after the user's own upload.

Each provider says what it covers, at what resolution, under which licence
and how to get the data. Automatic download is implemented only where an
open API works without credentials (Copernicus DEM GLO-30 on AWS), with the
user's own key (OpenTopography) or with the existing Earth Engine setup
(Sentinel-2, Landsat). For the others AIrchGIS shows the link and the format to
expect, and the user uploads what they download.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from airchgis.paths import PROJECT_ROOT

CONFIG_PATH = Path(os.environ.get("AIRCHGIS_CONFIG", Path.home() / ".airchgis" / "config.json"))


@dataclass
class Provider:
    key: str
    name: str
    kind: str  # "terrain" or "multispectral"
    coverage: str
    resolution: str
    licence: str
    access: str  # "automatic", "api key", "earth engine", "manual"
    url: str
    format: str
    notes: str = ""

    def to_dict(self):
        return asdict(self)


PROVIDERS = [
    Provider("ee_s2", "Sentinel-2 (Google Earth Engine)", "multispectral", "Global, from 2016", "10 m (20 m red edge/SWIR)",
             "Copernicus open licence", "earth engine", "https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED",
             "Processed in Earth Engine, no download", "Needs a Google Earth Engine project. Scene ranking with rainfall and WorldCover masks runs only here."),
    Provider("ee_landsat", "Landsat 4-9 (Google Earth Engine)", "multispectral", "Global, from 1984", "30 m", "Public domain (USGS)",
             "earth engine", "https://developers.google.com/earth-engine/datasets/catalog/landsat", "Processed in Earth Engine, no download"),
    Provider("cdse", "Copernicus Data Space Ecosystem", "multispectral", "Global (Sentinel-1/2/3)", "10 m", "Copernicus open licence",
             "manual", "https://browser.dataspace.copernicus.eu/", "SAFE folders with one JP2 per band: upload the B02, B03, B04, B08 (and B05, B11) files of each date",
             "Free account required."),
    Provider("mpc", "Microsoft Planetary Computer", "multispectral", "Global (Sentinel-2 L2A, Landsat C2)", "10-30 m",
             "Copernicus / USGS open licences", "manual", "https://planetarycomputer.microsoft.com/explore?d=sentinel-2-l2a",
             "Cloud-optimized GeoTIFF per band"),
    Provider("usgs_ee", "USGS EarthExplorer", "multispectral", "Global (Landsat, aerial photos)", "30 m (Landsat)", "Public domain",
             "manual", "https://earthexplorer.usgs.gov/", "One GeoTIFF per band (..._SR_B4.TIF)", "Free account required."),
    Provider("cop_dem", "Copernicus DEM GLO-30", "terrain", "Global", "30 m", "Copernicus DEM licence (free, with attribution)",
             "automatic", "https://registry.opendata.aws/copernicus-dem/", "Cloud-optimized GeoTIFF tiles of 1°",
             "A surface model, too coarse for single sites: use it for landscape context and palaeochannels."),
    Provider("opentopo", "OpenTopography", "terrain", "Global DEMs; national LiDAR (USA and others)", "30 m global; 0.5-1 m LiDAR",
             "Per dataset", "api key", "https://portal.opentopography.org/", "GeoTIFF", "Free API key: paste it once, it stays in your user folder."),
    Provider("it_mase", "Italy · MASE national LiDAR", "terrain", "Italy (coasts, rivers, many areas)", "1-2 m", "Open (see portal)",
             "manual", "https://sim.mase.gov.it/portalediaccesso/mappe/#/viewer/new/", "ASCII grid / GeoTIFF DTM and DSM"),
    Provider("uk_defra", "England · DEFRA LiDAR", "terrain", "England", "0.25-2 m", "Open Government Licence",
             "manual", "https://environment.data.gov.uk/survey", "GeoTIFF DTM / DSM tiles"),
    Provider("nl_ahn", "Netherlands · AHN", "terrain", "Netherlands", "0.5 m", "CC0", "manual", "https://www.ahn.nl/", "GeoTIFF DTM / DSM, LAZ"),
    Provider("dk", "Denmark · Danmarks Højdemodel", "terrain", "Denmark", "0.4 m", "Open", "manual", "https://dataforsyningen.dk/", "GeoTIFF, LAZ",
             "Free account required."),
    Provider("si_arso", "Slovenia · ARSO LiDAR", "terrain", "Slovenia", "1 m", "Open (attribution)", "manual",
             "http://gis.arso.gov.si/evode/profile.aspx?id=atlas_voda_Lidar@Arso", "LAZ, ASCII DTM"),
    Provider("es_pnoa", "Spain · PNOA LiDAR (CNIG)", "terrain", "Spain", "0.5-2 m", "CC BY 4.0", "manual",
             "https://centrodedescargas.cnig.es/", "LAZ, GeoTIFF DTM"),
    Provider("fr_ign", "France · IGN LiDAR HD", "terrain", "France", "0.5-1 m", "Etalab Open Licence 2.0", "manual",
             "https://geoservices.ign.fr/lidarhd", "LAZ (classified), GeoTIFF DTM"),
    Provider("us_3dep", "USA · USGS 3DEP", "terrain", "United States", "1 m", "Public domain", "manual",
             "https://apps.nationalmap.gov/downloader/", "GeoTIFF DTM, LAZ"),
]


def providers(kind=None):
    return [p for p in PROVIDERS if kind is None or p.kind == kind]


# ---------------------------------------------------------------- local config (API keys)
def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config_value(key: str, value: str) -> None:
    """Store a value (e.g. an API key) in the user's config file, readable only by the user."""
    cfg = load_config()
    cfg[key] = value
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def has_secret(key: str) -> bool:
    return bool(load_config().get(key))


# ---------------------------------------------------------------- Copernicus DEM GLO-30 (open, no credentials)
COP_DEM_URL = "https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif"


def cop_dem_tile_names(west, south, east, north):
    names = []
    for lat in range(math.floor(south), math.ceil(north)):
        for lon in range(math.floor(west), math.ceil(east)):
            ns = f"N{lat:02d}" if lat >= 0 else f"S{-lat:02d}"
            ew = f"E{lon:03d}" if lon >= 0 else f"W{-lon:03d}"
            names.append(f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM")
    return names


def download_cop_dem(bounds_lonlat, output, max_tiles=4) -> Path:
    """Crop Copernicus DEM GLO-30 to a lon/lat box, reading the cloud-optimized tiles directly."""
    import rasterio
    from rasterio.merge import merge

    west, south, east, north = bounds_lonlat
    names = cop_dem_tile_names(west, south, east, north)
    if len(names) > max_tiles:
        raise ValueError(f"The area spans {len(names)} tiles of 1°: draw a smaller area.")
    sources = []
    try:
        for n in names:
            try:
                sources.append(rasterio.open("/vsicurl/" + COP_DEM_URL.format(name=n)))
            except Exception:
                continue  # sea tiles do not exist
        if not sources:
            raise ValueError("No Copernicus DEM tile covers this area.")
        mosaic, transform = merge(sources, bounds=(west, south, east, north))
        profile = sources[0].profile.copy()
    finally:
        for s in sources:
            s.close()
    profile.update(driver="GTiff", height=mosaic.shape[1], width=mosaic.shape[2], transform=transform, compress="deflate")
    profile.pop("blockxsize", None), profile.pop("blockysize", None), profile.pop("tiled", None)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output, "w", **profile) as dst:
        dst.write(mosaic)
    return output


# ---------------------------------------------------------------- OpenTopography (user's API key)
OPENTOPO_URL = "https://portal.opentopography.org/API/globaldem"
OPENTOPO_DEMS = {"COP30": "Copernicus GLO-30", "SRTMGL1": "SRTM 30 m", "AW3D30": "ALOS World 3D 30 m", "NASADEM": "NASADEM 30 m"}


def download_opentopography(bounds_lonlat, output, dem="COP30", timeout=300) -> Path:
    import requests

    key = load_config().get("opentopography_api_key")
    if not key:
        raise ValueError("Add your OpenTopography API key first.")
    west, south, east, north = bounds_lonlat
    params = {"demtype": dem, "west": west, "south": south, "east": east, "north": north, "outputFormat": "GTiff", "API_Key": key}
    r = requests.get(OPENTOPO_URL, params=params, timeout=timeout)
    if r.status_code != 200 or not r.content[:4] in (b"II*\x00", b"MM\x00*"):
        # never echo the request URL: it contains the key
        raise RuntimeError(f"OpenTopography refused the request (HTTP {r.status_code}).")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(r.content)
    return output
