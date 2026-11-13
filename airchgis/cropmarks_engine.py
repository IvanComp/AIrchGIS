

import math
import os

import ee
import folium
import pandas as pd

from .paths import CROP_EE_PROJECT_FILE, ROOT_EE_PROJECT_FILE
from .scene_ranking import (
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
BANDS = S2_BANDS

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
SENSOR_LANDSAT = "Historical Landsat (1984 →)"
SENSOR_BOTH = "Sentinel-2 + Landsat"
SENSOR_OPTIONS = (SENSOR_S2, SENSOR_LANDSAT, SENSOR_BOTH)

WORLDCOVER_ASSET = "ESA/WorldCover/v200/2021"


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


BOUNDARY_PERCENTILE = 92
PARCEL_EDGE_BUFFER_M = 60

S2_SCALE = 20
LANDSAT_SCALE = 30

MODE_BEST = "Best single date"
MODE_MEDIAN = "Median of best dates (context only)"
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
    raise ValueError("Draw a polygon or a rectangle.")


def analysis_mask(open_land_only=True):

    cover = ee.Image(WORLDCOVER_ASSET).select("Map")
    if open_land_only:
        keep = OPEN_LAND_CLASSES
    else:
        keep = [value for value in range(0, 101) if value not in (50, 80, 70)]
    return cover.remap(keep, [1] * len(keep), 0).rename("analysis_mask")


def mask_s2(img, max_pixel_cloud=DEFAULT_PIXEL_CLOUD):
    scl = img.select("SCL")
    cloud_probability = ee.Image(img.get("cloud_probability_image")).select("probability")
    edge_mask = img.select("B8A").mask().updateMask(img.select("B9").mask())
    mask = (
        scl.neq(0)
        .And(scl.neq(1))
        .And(scl.neq(2))
        .And(scl.neq(3))
        .And(scl.neq(6))
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

    qa = img.select("QA_PIXEL")
    clear = (
        qa.bitwiseAnd(1 << 1).eq(0)
        .And(qa.bitwiseAnd(1 << 3).eq(0))
        .And(qa.bitwiseAnd(1 << 4).eq(0))
        .And(qa.bitwiseAnd(1 << 5).eq(0))
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


def local_contrast(img, band, radius=CONTRAST_RADIUS):

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


def rainfall_climatology(aoi):

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

    dates = [scene["date"] for scene in scenes if scene.get("date")]
    try:
        climatology = rainfall_climatology(aoi)
        rainfall = antecedent_rainfall(aoi, dates)
    except Exception:
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


def pca(img, bands, aoi, scale):


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

    distances = []
    for dr, dc in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        shifted = signature.convolve(_shift_kernel(dr, dc))
        distances.append(signature.subtract(shifted).pow(2).reduce(ee.Reducer.mean()).sqrt())
    return ee.ImageCollection(distances).max().rename("boundary_strength")


def field_boundaries(signature, aoi, scale, percentile=BOUNDARY_PERCENTILE):

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


CLASS_OTHER, CLASS_CEREAL, CLASS_SUMMER, CLASS_GRASS = 0, 1, 2, 3
CLASS_LABELS = {CLASS_OTHER: "altro", CLASS_CEREAL: "cereale", CLASS_SUMMER: "estiva", CLASS_GRASS: "prato"}
GRASS_MAX_AMPLITUDE = 0.30
GRASS_MIN_FLOOR = 0.35
CEREAL_PEAK_MONTHS = (4, 6)
CEREAL_MIN_DROP = 0.25
SUMMER_MAX_WINTER = 0.30

CANOPY_GATE = 0.35
BARE_GATE = 0.25

MIN_EFFECTIVE_DATES = 3


def parcel_curve(signature, radius_m=PARCEL_EDGE_BUFFER_M):

    return signature.select(MONTH_BANDS).focal_mean(radius=radius_m, units="meters")


def crop_class(curve):

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

    crop_type = classes.select("crop_class")
    if target == "Soil marks (bare soil)":
        return crop_type.eq(CLASS_CEREAL).Or(crop_type.eq(CLASS_SUMMER)).rename("target_parcel")
    if target == "Crop marks (vegetation)":
        return crop_type.eq(CLASS_CEREAL).rename("target_parcel")
    return crop_type.neq(CLASS_GRASS).And(crop_type.neq(CLASS_OTHER)).rename("target_parcel")


def date_weight(img, eligible, target):

    ndvi = img.select("NDVI")
    if target == "Soil marks (bare soil)":
        stage = ndvi.lt(BARE_GATE)
    elif target == "Crop marks (vegetation)":
        stage = ndvi.gte(CANOPY_GATE)
    else:
        stage = ndvi.gte(CANOPY_GATE).Or(ndvi.lt(BARE_GATE))
    return eligible.And(stage).rename("weight").float()


def parcel_interior(boundaries, radius_m=PARCEL_EDGE_BUFFER_M):

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

    brightness = local_signed_z(img, "TCT_brightness").abs()
    soil = local_signed_z(img, "Soil_band").abs()
    return brightness.max(soil).rename("Soil_mark_index")


def structure_coherence(image, radius=COHERENCE_RADIUS):

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

    if not years:
        return None
    per_year = []
    for year in years:
        subset = collection.filter(ee.Filter.eq("year", int(year)))
        persistence = temporal_persistence(subset, threshold).select("Persistent_any")
        per_year.append(persistence.gt(0))
    return ee.ImageCollection(per_year).sum().divide(len(years)).rename("Multi_year_recurrence").float()


def anomalies(img, aoi):

    zs = [z(img, band, aoi) for band in ["NDVI", "GNDVI", "Crop_band", "Soil_band", "NDMI", "TCT_greenness"]]
    anomaly = ee.ImageCollection(zs).sum().rename("Anomaly_score")
    local = anomaly.subtract(anomaly.focal_mean(radius=60, units="meters")).rename("Local_contrast")
    edges = ee.Algorithms.CannyEdgeDetector(local, 0.7, 1).rename("Edges")
    return anomaly.addBands(local).addBands(edges).float()


SOIL_BANDS = ["TCT_brightness", "Soil_band"]


def local_signed_z_multi(img, bands, radius=DEFAULT_LOCAL_RADIUS):

    kernel = ee.Kernel.circle(radius=radius, units="meters")
    values = img.select(bands)
    mean = values.reduceNeighborhood(ee.Reducer.mean(), kernel).rename(bands)
    std = values.reduceNeighborhood(ee.Reducer.stdDev(), kernel).rename(bands).max(ee.Image.constant(1e-4))
    return values.subtract(mean).divide(std)


def date_marks(img):

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
    add_layer_spec(specs, "RGB 4-3-2", base, {"bands": ["B4", "B3", "B2"], "min": 0.02, "max": 0.35}, "Imagery")
    add_layer_spec(specs, "False color 8-4-3", base, {"bands": ["B8", "B4", "B3"], "min": 0.02, "max": 0.45}, "Imagery")
    add_layer_spec(
        specs, "Healthy vegetation 8-11-2", base, {"bands": ["B8", "B11", "B2"], "min": 0.02, "max": 0.45}, "Imagery"
    )
    add_layer_spec(
        specs, "Analysed-area mask", mask.selfMask(), {"min": 0, "max": 1, "palette": ["ffd166"]}, "Imagery"
    )
    add_layer_spec(
        specs,
        "Detected parcel boundaries",
        boundaries.selfMask(),
        {"min": 0, "max": 1, "palette": ["ef476f"]},
        "Imagery",
    )
    add_layer_spec(
        specs,
        "Parcel interior (where anomalies are searched)",
        interior.selfMask(),
        {"min": 0, "max": 1, "palette": ["4cc9f0"]},
        "Imagery",
    )
    if classes is not None:
        add_layer_spec(
            specs,
            "Parcel crop class",
            classes.select("crop_class"),
            {"min": 0, "max": 3, "palette": ["3d3d3d", "f1c75b", "e07a5f", "2a9d8f"]},
            "Imagery",
        )
    if eligible is not None:
        add_layer_spec(
            specs,
            "Parcels suitable for the target mark",
            eligible.selfMask(),
            {"min": 0, "max": 1, "palette": ["06d6a0"]},
            "Imagery",
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
        add_layer_spec(specs, name, base.select(band), {"min": vmin, "max": vmax, "palette": palette}, "Vegetation")
    if red_edge:
        add_layer_spec(
            specs, "MCARI", base.select("MCARI"), {"min": -0.2, "max": 0.4, "palette": ["2166ac", "f7f7f7", "b2182b"]}, "Vegetation"
        )

    wet = ["8c510a", "f6e8c3", "01665e"]
    for name, band, vmin, vmax, palette in [
        ("NDMI", "NDMI", -0.6, 0.6, wet),
        ("NDWI", "NDWI", -0.6, 0.6, wet),
        ("MSI", "MSI", 0.4, 2.5, ["01665e", "f6e8c3", "8c510a"]),
        ("Crop band", "Crop_band", -0.9, 0.1, ["542788", "f7f7f7", "b35806"]),
        ("Soil band", "Soil_band", -1.0, 0.2, ["2166ac", "f7f7f7", "b2182b"]),
    ]:
        add_layer_spec(specs, name, base.select(band), {"min": vmin, "max": vmax, "palette": palette}, "Moisture and soil")

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
        "Vegetation deficit - possible walls",
        detection.select("Vegetation_deficit"),
        {"min": 0, "max": 1.6, "palette": ["ffffff", "ffd166", "ef476f", "6a040f"]},
        "Anomalie",
    )
    add_layer_spec(
        specs,
        "Vegetation excess - possible ditches",
        detection.select("Vegetation_excess"),
        {"min": 0, "max": 1.6, "palette": ["ffffff", "bde0fe", "219ebc", "023047"]},
        "Anomalie",
    )
    add_layer_spec(
        specs,
        "Linear marks - oriented anomalies",
        detection.select("Linear_marks"),
        {"min": 0, "max": 1.2, "palette": ["000000", "3a0ca3", "f72585", "ffd166"]},
        "Anomalie",
    )
    add_layer_spec(
        specs,
        "Directional coherence",
        detection.select("Coherence"),
        {"min": 0, "max": 1, "palette": ["000000", "4cc9f0", "ffffff"]},
        "Anomalie",
    )
    add_layer_spec(
        specs,
        "Soil marks - bare-soil contrast",
        detection.select("Soil_mark_index"),
        {"min": 0, "max": 2.5, "palette": ["ffffff", "e9c46a", "bc6c25", "3d1e00"]},
        "Anomalie",
    )

    add_layer_spec(
        specs,
        "Overall persistence",
        detection.select("Persistent_any"),
        {"min": 0, "max": 1, "palette": ["000000", "fee08b", "d73027"]},
        "Temporal persistence",
    )
    add_layer_spec(
        specs,
        "Deficit persistence",
        detection.select("Persistent_deficit"),
        {"min": 0, "max": 1, "palette": ["000000", "ffd166", "9d0208"]},
        "Temporal persistence",
    )
    add_layer_spec(
        specs,
        "Excess persistence",
        detection.select("Persistent_excess"),
        {"min": 0, "max": 1, "palette": ["000000", "90e0ef", "0077b6"]},
        "Temporal persistence",
    )
    add_layer_spec(
        specs,
        "Multi-year recurrence",
        detection.select("Multi_year_recurrence"),
        {"min": 0, "max": 1, "palette": ["000000", "fca311", "e63946", "ffffff"]},
        "Temporal persistence",
    )

    add_layer_spec(
        specs,
        "Anomaly score (context, single date)",
        context.select("Anomaly_score"),
        {"min": 0, "max": 10, "palette": ["000000", "ffff00", "ff0000"]},
        "Contesto",
    )
    add_layer_spec(
        specs,
        "Local contrast (context, single date)",
        context.select("Local_contrast"),
        {"min": -2, "max": 2, "palette": ["0000ff", "ffffff", "ff0000"]},
        "Contesto",
    )
    add_layer_spec(
        specs, "Edges (contesto)", context.select("Edges"), {"min": 0, "max": 1, "palette": ["000000", "00ffff"]}, "Contesto"
    )
    add_layer_spec(
        specs,
        "Usable dates per pixel",
        detection.select("Effective_dates"),
        {"min": 0, "max": 12, "palette": ["000000", "4cc9f0", "ffd166"]},
        "Contesto",
    )
    return specs


def pca_layer_specs(base, aoi, scale, red_edge):

    pcs = pca(base, pca_bands(red_edge), aoi, max(scale, 30)).select(["PC1", "PC2", "PC3", "PC4", "PC5", "PC6"])
    specs = {}
    add_layer_spec(specs, "PCA PC1-PC2-PC3", pcs, {"bands": ["PC1", "PC2", "PC3"], "min": -2, "max": 2}, "PCA")
    add_layer_spec(specs, "PCA PC2-PC3-PC4", pcs, {"bands": ["PC2", "PC3", "PC4"], "min": -2, "max": 2}, "PCA")
    return specs


def sites_inside(geometry, sites):

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
        raise ValueError("No image found with these parameters.")

    mask = analysis_mask(open_land_only)
    measured = granules.map(lambda image: scene_statistics(image, aoi, mask, scale)).filter(
        ee.Filter.gt("valid_pixels", 10)
    )
    valid_count = measured.size().getInfo()
    if valid_count == 0:
        raise ValueError(
            "No image with valid pixels after masking. Widen the area, raise the cloud threshold "
            "or turn off the open-area filter."
        )

    scenes = scene_table(measured, min(MAX_RANKED_SCENES, valid_count))
    rainfall_available = False
    if use_rainfall:
        scenes, rainfall_available = attach_rainfall(scenes, aoi)
    ranked = select_for_composite(rank_scenes(scenes, target=target), topn)
    df = scenes_dataframe(ranked)

    selected_ids = [scene["scene_id"] for scene in ranked if scene["selected_for_composite"]]
    if not selected_ids:
        raise ValueError("No selectable date with the current filters.")
    top = granules.filter(ee.Filter.inList("scene_id", selected_ids))
    dated = top.map(
        lambda image: image.set("year", ee.Date(image.get("system:time_start")).get("year"))
    )
    years = sorted({scene["date"][:4] for scene in ranked if scene["selected_for_composite"]})


    best = ee.Image(granules.filter(ee.Filter.eq("scene_id", selected_ids[0])).first()).clip(aoi)
    base = top.median().clip(aoi) if str(mode).startswith("Median") else best

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
    ("coverage", "coverage"),
    ("phenology", "phase"),
    ("rain_30d_mm", "rain_30d_mm"),
    ("rain_30d_normal_mm", "rain_30d_normal_mm"),
    ("dryness", "dryness"),
    ("contrast", "local_contrast"),
    ("score", "score"),
    ("scene_id", "id"),
]


def scenes_dataframe(scenes):

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
        "rain_30d_mm",
        "rain_30d_normal_mm",
        "coverage",
        "dryness",
        "local_contrast",
        "score",
    ] + [band.lower() + "_mean" for band in TIMESERIES_BANDS]
    for column in numeric:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame
