"""Multispectral screening engine for crop marks and soil marks.

The engine builds a stack of harmonised optical scenes (Sentinel-2 and, for the
pre-2016 record, the Landsat archive), ranks the acquisitions by how legible a
buried structure would be on each of them, and derives anomaly maps from the
best dates.

Three constraints shape the design:

* a mark is a *local* contrast at the scale of a wall or a ditch, so both the
  ranking and the anomaly maps work on the residual after removing the
  neighbourhood mean, never on the variance of the whole area of interest;
* built-up land, woodland and water produce far stronger contrasts than any
  archaeological feature, so statistics are computed over an open-land mask;
* crop marks are a moisture-stress phenomenon, so the antecedent rainfall of
  each acquisition is retrieved and used to weight the ranking.

Scores are investigation priorities, not probabilities.
"""

import math
import os

import ee
import folium
import pandas as pd

from .paths import CROP_EE_PROJECT_FILE, ROOT_EE_PROJECT_FILE
from .scene_ranking import (  # re-exported for callers and tests
    BARE_NDVI,
    DRYNESS_WEIGHT,
    RANK_BANDS,
    RANK_FEATURES,
    TARGETS,
    TIMESERIES_BANDS,
    rank_scenes,
    roc_auc,
    select_for_composite,
)


CORE_BANDS = ["B2", "B3", "B4", "B8", "B11", "B12"]
S2_BANDS = ["B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B11", "B12"]
BANDS = S2_BANDS  # kept for backwards compatibility

BASE_INDEX_BANDS = [
    "NDVI",
    "GNDVI",
    "DVI",
    "GDVI",
    "GRVI",
    "SR",
    "EVI",
    "SAVI",
    "NDMI",
    "NDWI",
    "MSI",
    "Crop_band",
    "Soil_band",
    "TCT_brightness",
    "TCT_greenness",
    "TCT_wetness",
]
RED_EDGE_INDEX_BANDS = ["MCARI"]
INDEX_BANDS = BASE_INDEX_BANDS + RED_EDGE_INDEX_BANDS

SENSOR_S2 = "Sentinel-2 (2016 →)"
SENSOR_LANDSAT = "Landsat storico (1984 →)"
SENSOR_BOTH = "Sentinel-2 + Landsat"
SENSOR_OPTIONS = (SENSOR_S2, SENSOR_LANDSAT, SENSOR_BOTH)

WORLDCOVER_ASSET = "ESA/WorldCover/v200/2021"
# Shrubland, grassland, cropland and bare ground: the surfaces where a buried
# structure can express itself. Trees, built-up, water and snow are excluded.
OPEN_LAND_CLASSES = [20, 30, 40, 60]
EXCLUDED_CLASSES = [10, 50, 70, 80, 90, 95, 100]

RAINFALL_COLLECTION = "ECMWF/ERA5_LAND/DAILY_AGGR"
RAINFALL_CLIMATOLOGY = "ECMWF/ERA5_LAND/MONTHLY_AGGR"
RAINFALL_BAND = "total_precipitation_sum"
CLIMATOLOGY_YEARS = ("1991-01-01", "2021-01-01")

DEFAULT_PIXEL_CLOUD = 40
DEFAULT_PERSISTENCE_THRESHOLD = 1.35
DEFAULT_LOCAL_RADIUS = 60
CONTRAST_RADIUS = 60
COHERENCE_RADIUS = 90
MAX_RANKED_SCENES = 60

# --- parcel segmentation -----------------------------------------------------
# A circular kernel that straddles a field boundary compares two different crops
# and reports the margin as a strong, perfectly straight anomaly. Every local
# statistic is therefore computed inside a parcel, and no candidate is produced
# within one kernel radius of a boundary.
BOUNDARY_PERCENTILE = 92        # share of the area that is field interior
PARCEL_EDGE_BUFFER_M = 60       # equals DEFAULT_LOCAL_RADIUS

S2_SCALE = 20
LANDSAT_SCALE = 30

MODE_BEST = "Migliore singola data"
MODE_MEDIAN = "Mediana migliori date (solo contesto)"
COMPOSITE_MODES = (MODE_BEST, MODE_MEDIAN)


def default_project():
    env = os.environ.get("EE_PROJECT", "").strip()
    if env:
        return env
    for project_file in (CROP_EE_PROJECT_FILE, ROOT_EE_PROJECT_FILE):
        if project_file.exists():
            return project_file.read_text(encoding="utf-8").strip()
    return ""


def save_default_project(project):
    project = (project or "").strip()
    if not project:
        return
    CROP_EE_PROJECT_FILE.write_text(project + "\n", encoding="utf-8")


def add_base_tiles(m, esri_show=True):
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Esri World Imagery",
        overlay=False,
        control=True,
        show=esri_show,
    ).add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", overlay=False, control=True, show=not esri_show).add_to(m)
    folium.TileLayer("CartoDB positron", name="CartoDB Positron", overlay=False, control=True, show=False).add_to(m)


def init_ee(project):
    project = (project or "").strip()
    if project:
        ee.Initialize(project=project)
    else:
        ee.Initialize()


def flat_coords(x, out):
    if not x:
        return
    if isinstance(x[0], (int, float)):
        out.append(x)
    else:
        for y in x:
            flat_coords(y, out)


def center(g):
    pts = []
    flat_coords(g["coordinates"], pts)
    if not pts:
        return [41.5, 15.5]
    return [sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)]


def geometry_bounds(g):
    pts = []
    flat_coords(g.get("coordinates", []), pts)
    if not pts:
        return None
    lons = [float(point[0]) for point in pts]
    lats = [float(point[1]) for point in pts]
    return [[min(lats), min(lons)], [max(lats), max(lons)]]


def square_aoi(lat, lon, radius_m=750):
    lat = float(lat)
    lon = float(lon)
    radius_m = max(50.0, float(radius_m))
    lat_delta = radius_m / 111_320.0
    lon_scale = max(0.1, abs(math.cos(math.radians(lat))))
    lon_delta = radius_m / (111_320.0 * lon_scale)
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon - lon_delta, lat - lat_delta],
                [lon + lon_delta, lat - lat_delta],
                [lon + lon_delta, lat + lat_delta],
                [lon - lon_delta, lat + lat_delta],
                [lon - lon_delta, lat - lat_delta],
            ]
        ],
    }


def geom(g):
    if g["type"] == "Polygon":
        return ee.Geometry.Polygon(g["coordinates"])
    if g["type"] == "MultiPolygon":
        return ee.Geometry.MultiPolygon(g["coordinates"])
    raise ValueError("Disegna un poligono o un rettangolo.")


# ---------------------------------------------------------------------------
# Surface mask
# ---------------------------------------------------------------------------


def analysis_mask(open_land_only=True):
    """Where anomaly statistics are meaningful.

    Built-up areas, canopy and water dominate any local contrast measure; a
    roof edge scores higher than any ditch. Restricting to open land is what
    makes the anomaly maps readable.
    """
    cover = ee.Image(WORLDCOVER_ASSET).select("Map")
    if open_land_only:
        keep = OPEN_LAND_CLASSES
    else:
        keep = [value for value in range(0, 101) if value not in (50, 80, 70)]
    return cover.remap(keep, [1] * len(keep), 0).rename("analysis_mask")


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


def mask_s2(img, max_pixel_cloud=DEFAULT_PIXEL_CLOUD):
    scl = img.select("SCL")
    cloud_probability = ee.Image(img.get("cloud_probability_image")).select("probability")
    edge_mask = img.select("B8A").mask().updateMask(img.select("B9").mask())
    mask = (
        scl.neq(0)
        .And(scl.neq(1))
        .And(scl.neq(2))   # dark area and topographic shadow
        .And(scl.neq(3))
        .And(scl.neq(6))   # water
        .And(scl.neq(8))
        .And(scl.neq(9))
        .And(scl.neq(10))
        .And(scl.neq(11))
        .And(cloud_probability.lt(float(max_pixel_cloud)))
        .And(edge_mask)
    )
    scaled = img.select(S2_BANDS).divide(10000)
    return (
        scaled.addBands(cloud_probability.rename("cloud_probability"))
        .updateMask(mask)
        .copyProperties(img, ["system:time_start"])
        .set("scene_id", img.get("system:index"))
        .set("sensor", "Sentinel-2")
        .set("scene_cloud", img.get("CLOUDY_PIXEL_PERCENTAGE"))
    )


def s2_collection(aoi, start, end, cloud, pixel_cloud):
    criteria = ee.Filter.And(ee.Filter.bounds(aoi), ee.Filter.date(str(start), str(end)))
    source = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filter(criteria)
        .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", cloud))
    )
    cloud_probability = ee.ImageCollection("COPERNICUS/S2_CLOUD_PROBABILITY").filter(criteria)
    joined = ee.Join.saveFirst("cloud_probability_image").apply(
        primary=source,
        secondary=cloud_probability,
        condition=ee.Filter.equals(leftField="system:index", rightField="system:index"),
    )
    return ee.ImageCollection(joined).map(lambda image: mask_s2(image, pixel_cloud))


LANDSAT_COLLECTIONS = (
    ("LANDSAT/LT05/C02/T1_L2", ["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B7"], "Landsat 5"),
    ("LANDSAT/LE07/C02/T1_L2", ["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B7"], "Landsat 7"),
    ("LANDSAT/LC08/C02/T1_L2", ["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"], "Landsat 8"),
    ("LANDSAT/LC09/C02/T1_L2", ["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"], "Landsat 9"),
)


def mask_landsat(img, source_bands, label):
    """Collection 2 level-2 surface reflectance, harmonised to the S2 naming."""
    qa = img.select("QA_PIXEL")
    clear = (
        qa.bitwiseAnd(1 << 1).eq(0)  # dilated cloud
        .And(qa.bitwiseAnd(1 << 3).eq(0))  # cloud
        .And(qa.bitwiseAnd(1 << 4).eq(0))  # cloud shadow
        .And(qa.bitwiseAnd(1 << 5).eq(0))  # snow
    )
    scaled = img.select(source_bands, CORE_BANDS).multiply(0.0000275).add(-0.2)
    return (
        scaled.addBands(ee.Image.constant(0).rename("cloud_probability").float())
        .updateMask(clear)
        .copyProperties(img, ["system:time_start"])
        .set("scene_id", ee.String(label).cat("_").cat(img.get("system:index")))
        .set("sensor", label)
        .set("scene_cloud", img.get("CLOUD_COVER"))
    )


def landsat_collection(aoi, start, end, cloud):
    criteria = ee.Filter.And(ee.Filter.bounds(aoi), ee.Filter.date(str(start), str(end)))
    merged = None
    for asset, source_bands, label in LANDSAT_COLLECTIONS:
        collection = (
            ee.ImageCollection(asset)
            .filter(criteria)
            .filter(ee.Filter.lte("CLOUD_COVER", cloud))
            .map(lambda image, bands=source_bands, name=label: mask_landsat(image, bands, name))
        )
        merged = collection if merged is None else merged.merge(collection)
    return ee.ImageCollection(merged)


def build_collection(sensor, aoi, start, end, cloud, pixel_cloud):
    """Return the scene collection and whether red-edge indices are available."""
    if sensor == SENSOR_LANDSAT:
        return landsat_collection(aoi, start, end, cloud), False
    if sensor == SENSOR_BOTH:
        s2 = s2_collection(aoi, start, end, cloud, pixel_cloud).map(
            lambda image: image.select(CORE_BANDS + ["cloud_probability"])
        )
        landsat = landsat_collection(aoi, start, end, cloud)
        return ee.ImageCollection(s2.merge(landsat)), False
    return s2_collection(aoi, start, end, cloud, pixel_cloud), True


def sensor_scale(sensor):
    return LANDSAT_SCALE if sensor in (SENSOR_LANDSAT, SENSOR_BOTH) else S2_SCALE


def sensor_export_scale(sensor):
    return 30 if sensor in (SENSOR_LANDSAT, SENSOR_BOTH) else 10


# ---------------------------------------------------------------------------
# Spectral indices
# ---------------------------------------------------------------------------


def add_indices(img, red_edge=True):
    bands = S2_BANDS if red_edge else CORE_BANDS
    v = {band: img.select(band) for band in bands}
    out = [
        img.normalizedDifference(["B8", "B4"]).rename("NDVI"),
        img.normalizedDifference(["B8", "B3"]).rename("GNDVI"),
        img.expression("B8-B4", v).rename("DVI"),
        img.expression("B8-B3", v).rename("GDVI"),
        img.expression("B8/(B3+0.0001)", v).rename("GRVI"),
        img.expression("B8/(B4+0.0001)", v).rename("SR"),
        img.expression("2.5*((B8-B4)/(B8+6*B4-7.5*B2+1+0.0001))", v).rename("EVI"),
        img.expression("1.5*(B8-B4)/(B8+B4+0.5)", v).rename("SAVI"),
        img.expression("(B8-B11)/(B8+B11)", v).rename("NDMI"),
        img.expression("(B3-B8)/(B3+B8+0.0001)", v).rename("NDWI"),
        img.expression("B11/(B8+0.0001)", v).rename("MSI"),
        img.expression("-0.38*B3-0.71*B2+0.2*B4-0.56*B8", v).rename("Crop_band"),
        img.expression("0.09*B2+0.27*B3-0.71*B4-0.65*B8", v).rename("Soil_band"),
        img.expression("0.3037*B2+0.2793*B3+0.4743*B4+0.5585*B8+0.5082*B11+0.1863*B12", v).rename(
            "TCT_brightness"
        ),
        img.expression("-0.2848*B2-0.2435*B3-0.5436*B4+0.7243*B8+0.0840*B11-0.1800*B12", v).rename(
            "TCT_greenness"
        ),
        img.expression("0.1509*B2+0.1973*B3+0.3279*B4+0.3406*B8-0.7112*B11-0.4572*B12", v).rename(
            "TCT_wetness"
        ),
    ]
    if red_edge:
        out.append(
            img.expression("((B5-B4)-0.2*(B5-B3))*(B5/(B4+0.0001))", v).rename("MCARI")
        )
    return img.addBands(out).float()


def index_bands(red_edge):
    return BASE_INDEX_BANDS + (RED_EDGE_INDEX_BANDS if red_edge else [])


def pca_bands(red_edge):
    return CORE_BANDS + index_bands(red_edge)


def output_bands(red_edge):
    return CORE_BANDS + index_bands(red_edge)


def safe_num(d, k):
    v = ee.Dictionary(d).get(k)
    return ee.Number(ee.Algorithms.If(ee.Algorithms.IsEqual(v, None), 0, v))


# ---------------------------------------------------------------------------
# Per-scene statistics
# ---------------------------------------------------------------------------


def local_contrast(img, band, radius=CONTRAST_RADIUS):
    """Absolute deviation of a band from its own neighbourhood mean.

    This is the quantity a crop mark actually produces. Ranking on it, rather
    than on the standard deviation of the whole area, stops large fields of a
    different crop from outranking a date that shows fine structure.
    """
    values = img.select(band)
    smooth = values.focal_mean(radius=radius, units="meters")
    return values.subtract(smooth).abs().rename(band + "_contrast")


def scene_statistics(img, aoi, mask, scale):
    contrast = ee.Image.cat([local_contrast(img, band) for band in RANK_BANDS])
    bare = img.select("NDVI").lt(BARE_NDVI).rename("bare")
    stack = (
        contrast.addBands(img.select(TIMESERIES_BANDS))
        .addBands(bare)
        .addBands(img.select("cloud_probability"))
        .updateMask(mask)
    )
    reducer = ee.Reducer.mean().combine(reducer2=ee.Reducer.count(), sharedInputs=True)
    stats = ee.Dictionary(
        stack.reduceRegion(
            reducer=reducer,
            geometry=aoi,
            scale=scale,
            maxPixels=1e8,
            bestEffort=True,
            tileScale=4,
        )
    )
    scene = (
        img.set("valid_pixels", safe_num(stats, "NDVI_count"))
        .set("pixel_cloud_mean", safe_num(stats, "cloud_probability_mean"))
        .set("bare_fraction", safe_num(stats, "bare_mean"))
        .set("date", ee.Date(img.get("system:time_start")).format("YYYY-MM-dd"))
        .set("year", ee.Date(img.get("system:time_start")).get("year"))
        .set("rank_contrast", safe_num(stats, "NDVI_contrast_mean"))
    )
    for band in RANK_BANDS:
        scene = scene.set(band + "_contrast", safe_num(stats, band + "_contrast_mean"))
    for band in TIMESERIES_BANDS:
        scene = scene.set(band.lower() + "_mean", safe_num(stats, band + "_mean"))
    return scene


def scene_table(collection, limit):
    """Pull the per-scene statistics down in a single request."""
    selectors = [
        "scene_id",
        "date",
        "sensor",
        "scene_cloud",
        "pixel_cloud_mean",
        "valid_pixels",
        "bare_fraction",
    ]
    selectors += [band + "_contrast" for band in RANK_BANDS]
    selectors += [band.lower() + "_mean" for band in TIMESERIES_BANDS]
    rows = (
        collection.limit(int(limit), "rank_contrast", False)
        .reduceColumns(reducer=ee.Reducer.toList(len(selectors)), selectors=selectors)
        .get("list")
        .getInfo()
    )
    return [dict(zip(selectors, row)) for row in rows]


# ---------------------------------------------------------------------------
# Rainfall context
# ---------------------------------------------------------------------------


def rainfall_climatology(aoi):
    """Mean monthly rainfall (mm) over 1991-2020 for the area of interest."""
    collection = ee.ImageCollection(RAINFALL_CLIMATOLOGY).filterDate(*CLIMATOLOGY_YEARS).select(RAINFALL_BAND)

    def monthly(month):
        month = ee.Number(month)
        image = collection.filter(ee.Filter.calendarRange(month, month, "month")).mean()
        value = image.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=aoi, scale=11000, maxPixels=1e8, bestEffort=True
        ).get(RAINFALL_BAND)
        return ee.Feature(None, {"month": month, "mm": ee.Number(ee.Algorithms.If(value, value, 0)).multiply(1000)})

    features = ee.FeatureCollection(ee.List.sequence(1, 12).map(monthly))
    rows = features.reduceColumns(ee.Reducer.toList(2), ["month", "mm"]).get("list").getInfo()
    return {int(month): float(mm) for month, mm in rows}


def antecedent_rainfall(aoi, dates, windows=(30, 90)):
    """Rainfall (mm) accumulated in the days preceding each acquisition."""
    if not dates:
        return {}
    collection = ee.ImageCollection(RAINFALL_COLLECTION).select(RAINFALL_BAND)

    def per_date(date):
        date = ee.Date(date)
        properties = {"date": date.format("YYYY-MM-dd")}
        for window in windows:
            total = collection.filterDate(date.advance(-int(window), "day"), date).sum()
            value = total.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=aoi, scale=11000, maxPixels=1e8, bestEffort=True
            ).get(RAINFALL_BAND)
            properties[f"p{window}"] = ee.Number(ee.Algorithms.If(value, value, 0)).multiply(1000)
        return ee.Feature(None, properties)

    selectors = ["date"] + [f"p{window}" for window in windows]
    features = ee.FeatureCollection(ee.List(sorted(set(dates))).map(per_date))
    rows = features.reduceColumns(ee.Reducer.toList(len(selectors)), selectors).get("list").getInfo()
    return {row[0]: {f"p{window}": row[index + 1] for index, window in enumerate(windows)} for row in rows}


def attach_rainfall(scenes, aoi):
    """Add antecedent rainfall and its climatological reference to each scene."""
    dates = [scene["date"] for scene in scenes if scene.get("date")]
    try:
        climatology = rainfall_climatology(aoi)
        rainfall = antecedent_rainfall(aoi, dates)
    except Exception:  # rainfall context is an enrichment, never a blocker
        return scenes, False
    for scene in scenes:
        entry = rainfall.get(scene.get("date")) or {}
        scene["rain_30d_mm"] = entry.get("p30")
        scene["rain_90d_mm"] = entry.get("p90")
        month = int(scene["date"][5:7]) if scene.get("date") else None
        normal_30 = climatology.get(month)
        scene["rain_30d_normal_mm"] = normal_30
        scene["rain_90d_normal_mm"] = ninety_day_normal(climatology, month)
    return scenes, True


def ninety_day_normal(climatology, month):
    if not climatology or not month:
        return None
    months = [((month - offset - 1) % 12) + 1 for offset in range(3)]
    values = [climatology.get(item) for item in months]
    if any(value is None for value in values):
        return None
    return sum(values)


# ---------------------------------------------------------------------------
# Anomaly maps
# ---------------------------------------------------------------------------


def pca(img, bands, aoi, scale):
    # toArray needs every band valid on every pixel: a partially masked pixel
    # yields a shorter array and the centred covariance collapses to NaN, which
    # is what used to make the whole export fail with an opaque 400.
    image = img.select(bands)
    image = image.updateMask(image.mask().reduce(ee.Reducer.min()))
    means = ee.Dictionary(
        image.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=aoi,
            scale=scale,
            maxPixels=1e8,
            bestEffort=True,
            tileScale=4,
        )
    )
    centered = image.subtract(ee.Image.constant([safe_num(means, x) for x in bands]).rename(bands))
    arr = centered.toArray()
    cov = arr.reduceRegion(
        reducer=ee.Reducer.centeredCovariance(),
        geometry=aoi,
        scale=scale,
        maxPixels=1e8,
        bestEffort=True,
        tileScale=4,
    )
    eig = ee.Array(cov.get("array")).eigen()
    vals = eig.slice(1, 0, 1)
    vecs = eig.slice(1, 1)
    pcs = ee.Image(vecs).matrixMultiply(arr.toArray(1))
    names = ["PC" + str(i + 1) for i in range(len(bands))]
    sd = ee.Image(vals.sqrt()).arrayProject([0]).arrayFlatten([["SD" + str(i + 1) for i in range(len(bands))]])
    return pcs.arrayProject([0]).arrayFlatten([names]).divide(sd).float()


def z(img, band, aoi):
    values = ee.Dictionary(
        img.select(band).reduceRegion(
            reducer=ee.Reducer.mean().combine(reducer2=ee.Reducer.stdDev(), sharedInputs=True),
            geometry=aoi,
            scale=20,
            maxPixels=1e8,
            bestEffort=True,
            tileScale=4,
        )
    )
    mean = safe_num(values, band + "_mean")
    stddev = safe_num(values, band + "_stdDev").max(0.0001)
    return img.select(band).subtract(mean).divide(stddev).abs().rename("Z_" + band)


def seasonal_signature(collection, aoi, scale, crs="EPSG:32633"):
    """One NDVI median per month: the annual behaviour of each pixel.

    Two pixels in the same field follow the same curve through sowing, growth
    and harvest. Two pixels across a boundary do not, whatever a single date
    happens to show.
    """
    months = [
        collection.filter(ee.Filter.calendarRange(month, month, "month"))
        .select("NDVI")
        .median()
        .rename(f"m{month:02d}")
        for month in range(1, 13)
    ]
    return ee.Image.cat(months).clip(aoi).unmask(0).reproject(crs=crs, scale=scale)


def _shift_kernel(dr, dc):
    weights = [[0.0] * 3 for _ in range(3)]
    weights[1 + dr][1 + dc] = 1.0
    return ee.Kernel.fixed(3, 3, weights)


def boundary_strength(signature):
    """How differently a pixel behaves from its four neighbours over the year."""
    distances = []
    for dr, dc in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        shifted = signature.convolve(_shift_kernel(dr, dc))
        distances.append(signature.subtract(shifted).pow(2).reduce(ee.Reducer.mean()).sqrt())
    return ee.ImageCollection(distances).max().rename("boundary_strength")


def field_boundaries(signature, aoi, scale, percentile=BOUNDARY_PERCENTILE):
    """Binary field-margin mask, thresholded on the area's own distribution."""
    strength = boundary_strength(signature)
    threshold = ee.Number(
        strength.reduceRegion(
            reducer=ee.Reducer.percentile([percentile]),
            geometry=aoi,
            scale=scale,
            maxPixels=1e8,
            bestEffort=True,
            tileScale=4,
        ).values().get(0)
    )
    return strength.gte(threshold).rename("parcel_boundary")


MONTH_BANDS = [f"m{month:02d}" for month in range(1, 13)]

# Winter cereal in the Marche is sown in autumn, stays green through winter,
# peaks in April-May and is harvested in June: the crop-mark crop. A summer crop
# leaves the ground bare all winter and peaks in July-August. Permanent grass
# never goes bare and never peaks.
CLASS_OTHER, CLASS_CEREAL, CLASS_SUMMER, CLASS_GRASS = 0, 1, 2, 3
CLASS_LABELS = {CLASS_OTHER: "altro", CLASS_CEREAL: "cereale", CLASS_SUMMER: "estiva", CLASS_GRASS: "prato"}
GRASS_MAX_AMPLITUDE = 0.30
GRASS_MIN_FLOOR = 0.35
CEREAL_PEAK_MONTHS = (4, 6)
CEREAL_MIN_DROP = 0.25
SUMMER_MAX_WINTER = 0.30
# A crop mark needs a canopy to express itself; a soil mark needs bare ground.
CANOPY_GATE = 0.35
BARE_GATE = 0.25
# A pixel judged on one or two acquisitions is not evidence.
MIN_EFFECTIVE_DATES = 3


def parcel_curve(signature, radius_m=PARCEL_EDGE_BUFFER_M):
    """The annual NDVI curve of the field a pixel belongs to.

    Smoothing the seasonal signature over ``radius_m`` and reading it inside
    :func:`parcel_interior` gives the field's own year: the kernel is the same
    size as the buffer, so it cannot reach across a margin into another crop.

    Labelling the parcels and reducing over connected components would be more
    exact and was tried first; on Earth Engine it exhausts the memory limit over
    areas of this size, and the gain does not justify it - the classification
    below only needs the shape of the curve.
    """
    return signature.select(MONTH_BANDS).focal_mean(radius=radius_m, units="meters")


def crop_class(curve):
    """Classify each parcel from the shape of its year.

    The AOI mean NDVI that the ranking used to rely on mixes a wheat field at
    0.8 with a ploughed one at 0.1 and calls the average a phenological state.
    This asks the question per field instead.
    """
    peak = curve.reduce(ee.Reducer.max())
    floor = curve.reduce(ee.Reducer.min())
    amplitude = peak.subtract(floor)
    peak_month = curve.toArray().arrayArgmax().arrayGet([0]).add(1)
    winter = curve.select(["m12", "m01", "m02"]).reduce(ee.Reducer.mean())
    summer = curve.select(["m07", "m08"]).reduce(ee.Reducer.mean())

    grass = amplitude.lt(GRASS_MAX_AMPLITUDE).And(floor.gt(GRASS_MIN_FLOOR))
    cereal = (
        peak_month.gte(CEREAL_PEAK_MONTHS[0])
        .And(peak_month.lte(CEREAL_PEAK_MONTHS[1]))
        .And(peak.subtract(summer).gt(CEREAL_MIN_DROP))
    )
    summer_crop = winter.lt(SUMMER_MAX_WINTER).And(peak_month.gte(6))

    classes = (
        ee.Image.constant(CLASS_OTHER)
        .where(summer_crop, CLASS_SUMMER)
        .where(cereal, CLASS_CEREAL)
        .where(grass, CLASS_GRASS)
        .rename("crop_class")
        .toInt()
    )
    return classes.addBands(peak_month.rename("peak_month")).addBands(amplitude.rename("ndvi_amplitude"))


def target_parcels(classes, target):
    """Which fields can express the kind of mark being looked for."""
    crop_type = classes.select("crop_class")
    if target == "Soil marks (suolo nudo)":
        return crop_type.eq(CLASS_CEREAL).Or(crop_type.eq(CLASS_SUMMER)).rename("target_parcel")
    if target == "Crop marks (vegetazione)":
        return crop_type.eq(CLASS_CEREAL).rename("target_parcel")
    return crop_type.neq(CLASS_GRASS).And(crop_type.neq(CLASS_OTHER)).rename("target_parcel")


def date_weight(img, eligible, target):
    """How much this acquisition can say about this pixel.

    Zero on a field that cannot carry the mark, and zero on a date when that
    field was in the wrong state - bare when a crop mark is wanted, under canopy
    when a soil mark is.
    """
    ndvi = img.select("NDVI")
    if target == "Soil marks (suolo nudo)":
        stage = ndvi.lt(BARE_GATE)
    elif target == "Crop marks (vegetazione)":
        stage = ndvi.gte(CANOPY_GATE)
    else:
        stage = ndvi.gte(CANOPY_GATE).Or(ndvi.lt(BARE_GATE))
    return eligible.And(stage).rename("weight").float()


def parcel_interior(boundaries, radius_m=PARCEL_EDGE_BUFFER_M):
    """1 where a neighbourhood of ``radius_m`` stays inside a single field.

    This is what makes a plain circular kernel a within-parcel statistic: no
    candidate is produced in the band where the kernel could straddle a margin.
    """
    return boundaries.focal_max(radius=radius_m, units="meters").Not().rename("parcel_interior")


def local_signed_z(img, band, radius=DEFAULT_LOCAL_RADIUS):
    kernel = ee.Kernel.circle(radius=radius, units="meters")
    band_img = img.select(band)
    local_mean = band_img.reduceNeighborhood(ee.Reducer.mean(), kernel)
    local_std = band_img.reduceNeighborhood(ee.Reducer.stdDev(), kernel).max(ee.Image.constant(0.0001))
    return band_img.subtract(local_mean).divide(local_std).rename("local_z")


def local_deficit_z(img, band, radius=DEFAULT_LOCAL_RADIUS):
    return local_signed_z(img, band, radius).multiply(-1).max(ee.Image.constant(0)).rename("deficit")


def local_excess_z(img, band, radius=DEFAULT_LOCAL_RADIUS):
    return local_signed_z(img, band, radius).max(ee.Image.constant(0)).rename("excess")


VEGETATION_BANDS = ["NDVI", "GNDVI", "SAVI", "TCT_greenness"]


def vegetation_deficit(img):
    return ee.ImageCollection([local_deficit_z(img, band) for band in VEGETATION_BANDS]).mean().rename(
        "Vegetation_deficit"
    )


def vegetation_excess(img):
    return ee.ImageCollection([local_excess_z(img, band) for band in VEGETATION_BANDS]).mean().rename(
        "Vegetation_excess"
    )


def soil_mark_index(img):
    """Brightness and soil-colour contrast, the signature of a soil mark.

    Ploughed soil over a buried wall dries lighter, over a filled ditch darker.
    The index is symmetric because both cases are informative.
    """
    brightness = local_signed_z(img, "TCT_brightness").abs()
    soil = local_signed_z(img, "Soil_band").abs()
    return brightness.max(soil).rename("Soil_mark_index")


def structure_coherence(image, radius=COHERENCE_RADIUS):
    """Orientation coherence of the local gradient field, in [0, 1].

    Natural soil variation is isotropic; walls, ditches, roads and field limits
    are not. Values near 1 mark a locally linear structure.
    """
    gradient = image.gradient()
    gx = gradient.select("x")
    gy = gradient.select("y")
    kernel = ee.Kernel.circle(radius=radius, units="meters")
    jxx = gx.multiply(gx).reduceNeighborhood(ee.Reducer.mean(), kernel)
    jyy = gy.multiply(gy).reduceNeighborhood(ee.Reducer.mean(), kernel)
    jxy = gx.multiply(gy).reduceNeighborhood(ee.Reducer.mean(), kernel)
    trace = jxx.add(jyy).max(ee.Image.constant(1e-12))
    spread = jxx.subtract(jyy).pow(2).add(jxy.multiply(2).pow(2)).sqrt()
    return spread.divide(trace).clamp(0, 1).rename("Coherence")


def temporal_persistence(images, threshold=DEFAULT_PERSISTENCE_THRESHOLD):
    threshold = float(threshold)

    def classify(image):
        image = ee.Image(image)
        deficit = vegetation_deficit(image)
        excess = vegetation_excess(image)
        return (
            deficit.gte(threshold).rename("Persistent_deficit")
            .addBands(excess.gte(threshold).rename("Persistent_excess"))
            .addBands(deficit.max(excess).gte(threshold).rename("Persistent_any"))
            .float()
        )

    return ee.ImageCollection(images.map(classify)).mean().float()


def multi_year_recurrence(collection, years, threshold=DEFAULT_PERSISTENCE_THRESHOLD):
    """Share of distinct years in which the anomaly reappears.

    A mark visible on four dates of one dry spring is one observation. A mark
    visible in four different years is evidence.
    """
    if not years:
        return None
    per_year = []
    for year in years:
        subset = collection.filter(ee.Filter.eq("year", int(year)))
        persistence = temporal_persistence(subset, threshold).select("Persistent_any")
        per_year.append(persistence.gt(0))
    return ee.ImageCollection(per_year).sum().divide(len(years)).rename("Multi_year_recurrence").float()


def anomalies(img, aoi):
    """Legacy single-image anomaly stack, kept for the context layers only."""
    zs = [z(img, band, aoi) for band in ["NDVI", "GNDVI", "Crop_band", "Soil_band", "NDMI", "TCT_greenness"]]
    anomaly = ee.ImageCollection(zs).sum().rename("Anomaly_score")
    local = anomaly.subtract(anomaly.focal_mean(radius=60, units="meters")).rename("Local_contrast")
    edges = ee.Algorithms.CannyEdgeDetector(local, 0.7, 1).rename("Edges")
    return anomaly.addBands(local).addBands(edges).float()


SOIL_BANDS = ["TCT_brightness", "Soil_band"]


def local_signed_z_multi(img, bands, radius=DEFAULT_LOCAL_RADIUS):
    """Signed z-scores of several bands against a circular neighbourhood.

    Used together with :func:`parcel_interior`, which keeps only the pixels
    farther than ``radius`` from any parcel boundary. Inside that mask the
    kernel cannot cross into another field, so this *is* the within-parcel
    statistic, at a fraction of the cost of a connected-components reduction.
    """
    kernel = ee.Kernel.circle(radius=radius, units="meters")
    values = img.select(bands)
    mean = values.reduceNeighborhood(ee.Reducer.mean(), kernel).rename(bands)
    std = values.reduceNeighborhood(ee.Reducer.stdDev(), kernel).rename(bands).max(ee.Image.constant(1e-4))
    return values.subtract(mean).divide(std)


def date_marks(img):
    """Deficit and excess of a single acquisition, measured inside the parcel.

    The signed z-scores are averaged before being split into deficit and excess:
    averaging the clipped halves instead would let a band that is positive and
    one that is negative both contribute, inflating weak, incoherent signals.
    """
    zs = local_signed_z_multi(img, VEGETATION_BANDS + SOIL_BANDS)
    signed = zs.select(VEGETATION_BANDS).reduce(ee.Reducer.mean())
    zero = ee.Image.constant(0)
    deficit = signed.multiply(-1).max(zero).rename("Vegetation_deficit")
    excess = signed.max(zero).rename("Vegetation_excess")
    soil = zs.select(SOIL_BANDS).abs().reduce(ee.Reducer.max()).rename("Soil_mark_index")
    return (
        deficit.addBands(excess)
        .addBands(deficit.max(excess).rename("Mark_strength"))
        .addBands(soil)
        .float()
        .copyProperties(img, ["system:time_start", "date", "year", "scene_id"])
    )


DETECTION_BANDS = ["Vegetation_deficit", "Vegetation_excess", "Mark_strength", "Soil_mark_index"]


def detection_layers(collection, threshold, years, interior, eligible=None, target="Automatico"):
    """Anomaly maps built date by date, then aggregated with per-pixel weights.

    A crop mark is a transient anomaly, so it must be measured on each
    acquisition and combined afterwards: compositing the reflectance first and
    looking for anomalies in the composite removes exactly what is being looked
    for.

    Each acquisition also contributes only where it can say something. A date is
    excellent over a wheat field about to be harvested and worthless over the
    ploughed field next to it, so the weight is per pixel, not per scene, and
    the aggregation is a weighted mean rather than a plain one.
    """
    threshold = float(threshold)
    if eligible is None:
        eligible = ee.Image.constant(1)

    def measure(image):
        image = ee.Image(image)
        marks = ee.Image(date_marks(image))
        weight = date_weight(image, eligible, target)
        flags = (
            marks.select(["Vegetation_deficit", "Vegetation_excess", "Mark_strength"])
            .gte(threshold)
            .rename(["Persistent_deficit", "Persistent_excess", "Persistent_any"])
        )
        return (
            marks.addBands(flags)
            .multiply(weight)
            .addBands(weight)
            .float()
            .copyProperties(image, ["system:time_start", "date", "year", "scene_id"])
        )

    per_date = ee.ImageCollection(collection.map(measure))
    weighted = per_date.sum()
    total_weight = weighted.select("weight")
    usable = total_weight.gte(MIN_EFFECTIVE_DATES)
    aggregated = weighted.select(DETECTION_BANDS + PERSISTENCE_BANDS).divide(total_weight.max(1e-6))

    recurrence = None
    if years:
        per_year = [
            ee.Image(per_date.filter(ee.Filter.eq("year", int(year))).select("Persistent_any").max()).gt(0)
            for year in years
        ]
        recurrence = (
            ee.ImageCollection(per_year).sum().divide(len(years)).rename("Multi_year_recurrence").float()
        )

    strength = aggregated.select("Mark_strength")
    coherence = structure_coherence(strength)
    linear = strength.multiply(coherence).rename("Linear_marks")

    mask = interior.And(usable)
    stack = (
        aggregated.addBands(coherence)
        .addBands(linear)
        .addBands(total_weight.rename("Effective_dates"))
        .updateMask(mask)
        .float()
    )
    if recurrence is not None:
        stack = stack.addBands(recurrence.updateMask(mask))
    return stack, per_date


PERSISTENCE_BANDS = ["Persistent_deficit", "Persistent_excess", "Persistent_any"]


# ---------------------------------------------------------------------------
# Layers
# ---------------------------------------------------------------------------


def tile(img, vis):
    return ee.Image(img).getMapId(vis)["tile_fetcher"].url_format


def add_tile(layer_dict, name, img, vis):
    layer_dict[name] = tile(img, vis)


def add_layer_spec(layer_dict, name, img, vis, group):
    layer_dict[name] = {"image": ee.Image(img), "vis": vis, "group": group}


def layer_url(result, name):
    spec = result["layer_specs"][name]
    return tile(spec["image"], spec["vis"])


def prepare_download(result):
    return ee.Image(result["download_image"]).getDownloadURL(
        {
            "name": "s2_cropmarks",
            "region": result["download_region"],
            "scale": result.get("export_scale", 10),
            "filePerBand": False,
            "format": "GEO_TIFF",
        }
    )


def add_layer(m, url, name, show=False, opacity=1.0):
    folium.raster_layers.TileLayer(
        tiles=url,
        attr="Google Earth Engine",
        name=name,
        overlay=True,
        control=True,
        show=show,
        opacity=opacity,
    ).add_to(m)


def build_layer_specs(base, detection, context, boundaries, interior, mask, red_edge, classes=None, eligible=None):
    specs = {}
    add_layer_spec(specs, "RGB 4-3-2", base, {"bands": ["B4", "B3", "B2"], "min": 0.02, "max": 0.35}, "Immagini")
    add_layer_spec(specs, "False color 8-4-3", base, {"bands": ["B8", "B4", "B3"], "min": 0.02, "max": 0.45}, "Immagini")
    add_layer_spec(
        specs, "Healthy vegetation 8-11-2", base, {"bands": ["B8", "B11", "B2"], "min": 0.02, "max": 0.45}, "Immagini"
    )
    add_layer_spec(
        specs, "Maschera aree analizzate", mask.selfMask(), {"min": 0, "max": 1, "palette": ["ffd166"]}, "Immagini"
    )
    add_layer_spec(
        specs,
        "Confini di parcella riconosciuti",
        boundaries.selfMask(),
        {"min": 0, "max": 1, "palette": ["ef476f"]},
        "Immagini",
    )
    add_layer_spec(
        specs,
        "Interno parcella (dove si cercano anomalie)",
        interior.selfMask(),
        {"min": 0, "max": 1, "palette": ["4cc9f0"]},
        "Immagini",
    )
    if classes is not None:
        add_layer_spec(
            specs,
            "Classe colturale della parcella",
            classes.select("crop_class"),
            {"min": 0, "max": 3, "palette": ["3d3d3d", "f1c75b", "e07a5f", "2a9d8f"]},
            "Immagini",
        )
    if eligible is not None:
        add_layer_spec(
            specs,
            "Parcelle idonee alla traccia cercata",
            eligible.selfMask(),
            {"min": 0, "max": 1, "palette": ["06d6a0"]},
            "Immagini",
        )

    green = ["313695", "ffffbf", "1a9850"]
    for name, band, vmin, vmax, palette in [
        ("NDVI", "NDVI", -0.2, 0.8, green),
        ("GNDVI", "GNDVI", -0.2, 0.8, green),
        ("DVI", "DVI", -0.2, 0.6, green),
        ("GDVI", "GDVI", -0.2, 0.6, green),
        ("GRVI", "GRVI", 0, 8, ["542788", "f7f7f7", "1a9850"]),
        ("Simple ratio", "SR", 0, 8, ["542788", "f7f7f7", "1a9850"]),
        ("EVI", "EVI", -0.2, 0.8, green),
        ("SAVI", "SAVI", -0.2, 0.8, green),
    ]:
        add_layer_spec(specs, name, base.select(band), {"min": vmin, "max": vmax, "palette": palette}, "Vegetazione")
    if red_edge:
        add_layer_spec(
            specs, "MCARI", base.select("MCARI"), {"min": -0.2, "max": 0.4, "palette": ["2166ac", "f7f7f7", "b2182b"]}, "Vegetazione"
        )

    wet = ["8c510a", "f6e8c3", "01665e"]
    for name, band, vmin, vmax, palette in [
        ("NDMI", "NDMI", -0.6, 0.6, wet),
        ("NDWI", "NDWI", -0.6, 0.6, wet),
        ("MSI", "MSI", 0.4, 2.5, ["01665e", "f6e8c3", "8c510a"]),
        ("Crop band", "Crop_band", -0.9, 0.1, ["542788", "f7f7f7", "b35806"]),
        ("Soil band", "Soil_band", -1.0, 0.2, ["2166ac", "f7f7f7", "b2182b"]),
    ]:
        add_layer_spec(specs, name, base.select(band), {"min": vmin, "max": vmax, "palette": palette}, "Umidita e suolo")

    for name, band, vmin, vmax, palette in [
        ("TCT brightness", "TCT_brightness", -0.2, 0.8, ["000004", "f89540", "fcfdbf"]),
        ("TCT greenness", "TCT_greenness", -0.3, 0.5, ["542788", "f7f7f7", "1a9850"]),
        ("TCT wetness", "TCT_wetness", -0.4, 0.4, wet),
    ]:
        add_layer_spec(specs, name, base.select(band), {"min": vmin, "max": vmax, "palette": palette}, "Tasseled Cap")
    add_layer_spec(
        specs,
        "TCT RGB",
        base,
        {"bands": ["TCT_brightness", "TCT_greenness", "TCT_wetness"], "min": [-0.2, -0.3, -0.4], "max": [0.8, 0.5, 0.4]},
        "Tasseled Cap",
    )

    add_layer_spec(
        specs,
        "Vegetazione in deficit - possibili muri",
        detection.select("Vegetation_deficit"),
        {"min": 0, "max": 1.6, "palette": ["ffffff", "ffd166", "ef476f", "6a040f"]},
        "Anomalie",
    )
    add_layer_spec(
        specs,
        "Vegetazione in eccesso - possibili fossati",
        detection.select("Vegetation_excess"),
        {"min": 0, "max": 1.6, "palette": ["ffffff", "bde0fe", "219ebc", "023047"]},
        "Anomalie",
    )
    add_layer_spec(
        specs,
        "Marks lineari - anomalie orientate",
        detection.select("Linear_marks"),
        {"min": 0, "max": 1.2, "palette": ["000000", "3a0ca3", "f72585", "ffd166"]},
        "Anomalie",
    )
    add_layer_spec(
        specs,
        "Coerenza direzionale",
        detection.select("Coherence"),
        {"min": 0, "max": 1, "palette": ["000000", "4cc9f0", "ffffff"]},
        "Anomalie",
    )
    add_layer_spec(
        specs,
        "Soil marks - contrasto suolo nudo",
        detection.select("Soil_mark_index"),
        {"min": 0, "max": 2.5, "palette": ["ffffff", "e9c46a", "bc6c25", "3d1e00"]},
        "Anomalie",
    )

    add_layer_spec(
        specs,
        "Persistenza complessiva",
        detection.select("Persistent_any"),
        {"min": 0, "max": 1, "palette": ["000000", "fee08b", "d73027"]},
        "Persistenza temporale",
    )
    add_layer_spec(
        specs,
        "Persistenza deficit",
        detection.select("Persistent_deficit"),
        {"min": 0, "max": 1, "palette": ["000000", "ffd166", "9d0208"]},
        "Persistenza temporale",
    )
    add_layer_spec(
        specs,
        "Persistenza eccesso",
        detection.select("Persistent_excess"),
        {"min": 0, "max": 1, "palette": ["000000", "90e0ef", "0077b6"]},
        "Persistenza temporale",
    )
    add_layer_spec(
        specs,
        "Ricorrenza pluriennale",
        detection.select("Multi_year_recurrence"),
        {"min": 0, "max": 1, "palette": ["000000", "fca311", "e63946", "ffffff"]},
        "Persistenza temporale",
    )

    add_layer_spec(
        specs,
        "Anomaly score (contesto, singola data)",
        context.select("Anomaly_score"),
        {"min": 0, "max": 10, "palette": ["000000", "ffff00", "ff0000"]},
        "Contesto",
    )
    add_layer_spec(
        specs,
        "Local contrast (contesto, singola data)",
        context.select("Local_contrast"),
        {"min": -2, "max": 2, "palette": ["0000ff", "ffffff", "ff0000"]},
        "Contesto",
    )
    add_layer_spec(
        specs, "Edges (contesto)", context.select("Edges"), {"min": 0, "max": 1, "palette": ["000000", "00ffff"]}, "Contesto"
    )
    add_layer_spec(
        specs,
        "Date utili per pixel",
        detection.select("Effective_dates"),
        {"min": 0, "max": 12, "palette": ["000000", "4cc9f0", "ffd166"]},
        "Contesto",
    )
    return specs



def pca_layer_specs(base, aoi, scale, red_edge):
    """PCA layers, built lazily so a degenerate decomposition cannot break export."""
    pcs = pca(base, pca_bands(red_edge), aoi, max(scale, 30)).select(["PC1", "PC2", "PC3", "PC4", "PC5", "PC6"])
    specs = {}
    add_layer_spec(specs, "PCA PC1-PC2-PC3", pcs, {"bands": ["PC1", "PC2", "PC3"], "min": -2, "max": 2}, "PCA")
    add_layer_spec(specs, "PCA PC2-PC3-PC4", pcs, {"bands": ["PC2", "PC3", "PC4"], "min": -2, "max": 2}, "PCA")
    return specs


# ---------------------------------------------------------------------------
# Validation against the documentary catalogue
# ---------------------------------------------------------------------------


def sites_inside(geometry, sites):
    """Keep only the catalogue points that fall inside the analysed area."""
    bounds = geometry_bounds(geometry or {})
    if not bounds:
        return []
    (south, west), (north, east) = bounds
    return [
        site
        for site in sites
        if south <= float(site["lat"]) <= north and west <= float(site["lon"]) <= east
    ]


def validate_against_sites(result, sites, band="Persistent_any", control_points=40):
    """Compare the anomaly raster at known sites against random controls.

    This does not prove that an anomaly is archaeological. It answers a narrower
    and still useful question: inside this area, does the detector give known
    sites higher values than arbitrary locations?
    """
    image = result.get("validation_image")
    if image is None:
        return None
    sites = sites_inside(result.get("geometry"), sites)
    if not sites:
        return None
    aoi = result["download_region"]
    scale = result.get("analysis_scale", S2_SCALE)
    image = ee.Image(image).select(band)

    features = [
        ee.Feature(ee.Geometry.Point([float(site["lon"]), float(site["lat"])]), {"number": site.get("number", "")})
        for site in sites
    ]
    site_values = (
        image.reduceRegions(collection=ee.FeatureCollection(features), reducer=ee.Reducer.mean(), scale=scale)
        .reduceColumns(ee.Reducer.toList(2), ["number", "mean"])
        .get("list")
    )
    controls = ee.FeatureCollection.randomPoints(region=aoi, points=int(control_points), seed=17)
    control_values = (
        image.reduceRegions(collection=controls, reducer=ee.Reducer.mean(), scale=scale)
        .reduceColumns(ee.Reducer.toList(1), ["mean"])
        .get("list")
    )
    percentiles = image.reduceRegion(
        reducer=ee.Reducer.percentile([50, 75, 90, 95, 99]),
        geometry=aoi,
        scale=scale,
        maxPixels=1e8,
        bestEffort=True,
        tileScale=4,
    )
    payload = ee.Dictionary(
        {"sites": site_values, "controls": control_values, "percentiles": percentiles}
    ).getInfo()

    site_rows = [
        {"number": number, "value": value}
        for number, value in payload.get("sites", [])
        if value is not None
    ]
    control_rows = [row[0] for row in payload.get("controls", []) if row and row[0] is not None]
    return {
        "band": band,
        "sites": site_rows,
        "controls": control_rows,
        "percentiles": {
            int(key.split("_")[-1].replace("p", "")): value
            for key, value in (payload.get("percentiles") or {}).items()
            if value is not None
        },
        "auc": roc_auc([row["value"] for row in site_rows], control_rows),
        "site_mean": (sum(row["value"] for row in site_rows) / len(site_rows)) if site_rows else None,
        "control_mean": (sum(control_rows) / len(control_rows)) if control_rows else None,
    }


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def run_analysis(
    project,
    start,
    end,
    cloud,
    topn,
    mode,
    export,
    folder,
    geojson_geometry,
    pixel_cloud=DEFAULT_PIXEL_CLOUD,
    persistence_threshold=DEFAULT_PERSISTENCE_THRESHOLD,
    sensor=SENSOR_S2,
    target="Automatico",
    open_land_only=True,
    use_rainfall=True,
):
    init_ee(project)
    aoi = geom(geojson_geometry)
    scale = sensor_scale(sensor)
    collection, red_edge = build_collection(sensor, aoi, start, end, cloud, pixel_cloud)
    granules = collection.map(lambda image: add_indices(image, red_edge))

    total = granules.size().getInfo()
    if total == 0:
        raise ValueError("Nessuna immagine trovata con questi parametri.")

    mask = analysis_mask(open_land_only)
    measured = granules.map(lambda image: scene_statistics(image, aoi, mask, scale)).filter(
        ee.Filter.gt("valid_pixels", 10)
    )
    valid_count = measured.size().getInfo()
    if valid_count == 0:
        raise ValueError(
            "Nessuna immagine con pixel validi dopo la maschera. Allarga l'area, alza la soglia nuvole "
            "o disattiva il filtro sulle aree aperte."
        )

    scenes = scene_table(measured, min(MAX_RANKED_SCENES, valid_count))
    rainfall_available = False
    if use_rainfall:
        scenes, rainfall_available = attach_rainfall(scenes, aoi)
    ranked = select_for_composite(rank_scenes(scenes, target=target), topn)
    df = scenes_dataframe(ranked)

    selected_ids = [scene["scene_id"] for scene in ranked if scene["selected_for_composite"]]
    if not selected_ids:
        raise ValueError("Nessuna data selezionabile con i filtri correnti.")
    top = granules.filter(ee.Filter.inList("scene_id", selected_ids))
    dated = top.map(
        lambda image: image.set("year", ee.Date(image.get("system:time_start")).get("year"))
    )
    years = sorted({scene["date"][:4] for scene in ranked if scene["selected_for_composite"]})

    # The reference image is for looking at, never for detecting on: see
    # detection_layers.
    best = ee.Image(granules.filter(ee.Filter.eq("scene_id", selected_ids[0])).first()).clip(aoi)
    base = top.median().clip(aoi) if str(mode).startswith("Mediana") else best

    signature = seasonal_signature(granules, aoi, scale)
    boundaries = field_boundaries(signature, aoi, scale)
    interior = parcel_interior(boundaries).And(mask)
    classes = crop_class(parcel_curve(signature))
    eligible = target_parcels(classes, target)
    detection, per_date = detection_layers(
        dated, persistence_threshold, years, interior, eligible=eligible, target=target
    )
    detection = detection.clip(aoi)
    context = anomalies(base, aoi)

    out = (
        base.select(output_bands(red_edge))
        .addBands(context)
        .addBands(detection)
        .addBands(mask.rename("Analysis_mask"))
        .addBands(boundaries.rename("Parcel_boundary"))
        .addBands(classes)
        .clip(aoi)
        .float()
    )

    layer_specs = build_layer_specs(
        base, detection, context, boundaries, interior, mask.clip(aoi), red_edge, classes, eligible
    )
    # The PCA eigen decomposition fails on large or heavily masked areas and
    # would invalidate every export that carried it, so it is built lazily and
    # kept out of the exported image.
    layer_specs.update(pca_layer_specs(base, aoi, scale, red_edge))

    task_id = None
    if export:
        task = ee.batch.Export.image.toDrive(
            image=out,
            description="s2_cropmarks_export",
            folder=folder,
            region=aoi,
            scale=sensor_export_scale(sensor),
            maxPixels=1e13,
            fileFormat="GeoTIFF",
        )
        task.start()
        task_id = task.id

    return {
        "df": df,
        "scenes": ranked,
        "layer_specs": layer_specs,
        "layer_urls": {},
        "download": None,
        "download_image": out,
        "download_region": aoi,
        "validation_image": detection,
        "parcel_boundaries": boundaries,
        "crop_classes": classes,
        "selected_collection": dated,
        "best_image": best,
        "per_date_marks": per_date,
        "analysis_scale": scale,
        "export_scale": sensor_export_scale(sensor),
        "task_id": task_id,
        "center": center(geojson_geometry),
        "geometry": geojson_geometry,
        "years": years,
        "rainfall_available": rainfall_available,
        "params": {
            "start": str(start),
            "end": str(end),
            "cloud": cloud,
            "pixel_cloud": pixel_cloud,
            "topn": topn,
            "mode": mode,
            "persistence_threshold": persistence_threshold,
            "sensor": sensor,
            "target": target,
            "open_land_only": open_land_only,
        },
        "scene_count": total,
        "valid_scene_count": valid_count,
    }


DISPLAY_COLUMNS = [
    ("date", "date"),
    ("sensor", "sensor"),
    ("scene_cloud", "cloud"),
    ("pixel_cloud_mean", "pixel_cloud_mean"),
    ("valid_pixels", "valid_pixels"),
    ("coverage", "copertura"),
    ("phenology", "fase"),
    ("rain_30d_mm", "pioggia_30gg_mm"),
    ("rain_30d_normal_mm", "pioggia_30gg_media_mm"),
    ("dryness", "siccita"),
    ("contrast", "contrasto_locale"),
    ("score", "score"),
    ("scene_id", "id"),
]


def scenes_dataframe(scenes):
    """Client-side ranking table, with the legacy column names preserved."""
    rows = []
    for scene in scenes:
        row = {label: scene.get(key) for key, label in DISPLAY_COLUMNS}
        for band in TIMESERIES_BANDS:
            row[band.lower() + "_mean"] = scene.get(band.lower() + "_mean")
        row["selected_for_composite"] = scene.get("selected_for_composite", False)
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    numeric = [
        "cloud",
        "pixel_cloud_mean",
        "valid_pixels",
        "pioggia_30gg_mm",
        "pioggia_30gg_media_mm",
        "copertura",
        "siccita",
        "contrasto_locale",
        "score",
    ] + [band.lower() + "_mean" for band in TIMESERIES_BANDS]
    for column in numeric:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame
