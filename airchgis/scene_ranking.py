

import math


RANK_FEATURES = (
    ("NDVI", 0.045, 1.0),
    ("GNDVI", 0.040, 0.8),
    ("SAVI", 0.045, 1.0),
    ("NDMI", 0.035, 0.8),
    ("Crop_band", 0.030, 0.8),
    ("Soil_band", 0.030, 0.8),
    ("TCT_greenness", 0.035, 0.8),
)
RANK_BANDS = [item[0] for item in RANK_FEATURES]
TIMESERIES_BANDS = ["NDVI", "GNDVI", "SAVI", "NDMI", "TCT_greenness"]

TARGETS = ("Automatico", "Crop marks (vegetation)", "Soil marks (bare soil)")


BARE_NDVI = 0.25

CANOPY_NDVI = 0.45

BARE_FRACTION = 0.55

PHENOLOGY_SOIL = "bare soil"
PHENOLOGY_CANOPY = "vegetation"
PHENOLOGY_MIXED = "mixed"


DRYNESS_WEIGHT = 0.45

TARGET_WEIGHTS = {
    "Crop marks (vegetation)": {PHENOLOGY_CANOPY: 1.0, PHENOLOGY_MIXED: 0.6, PHENOLOGY_SOIL: 0.15},
    "Soil marks (bare soil)": {PHENOLOGY_CANOPY: 0.15, PHENOLOGY_MIXED: 0.6, PHENOLOGY_SOIL: 1.0},
}


def phenology_class(ndvi_mean, bare_fraction):

    ndvi_mean = float(ndvi_mean or 0.0)
    bare_fraction = float(bare_fraction or 0.0)
    if bare_fraction >= BARE_FRACTION or ndvi_mean < BARE_NDVI:
        return PHENOLOGY_SOIL
    if ndvi_mean >= CANOPY_NDVI:
        return PHENOLOGY_CANOPY
    return PHENOLOGY_MIXED


def target_weight(phenology, target):
    weights = TARGET_WEIGHTS.get(target)
    if not weights:
        return 1.0
    return weights.get(phenology, 0.5)


def contrast_score(stats):

    total_weight = sum(item[2] for item in RANK_FEATURES)
    score = 0.0
    for band, reference, weight in RANK_FEATURES:
        value = stats.get(band + "_contrast")
        if value is None:
            continue
        normalised = min(float(value) / reference, 3.0)
        score += normalised * weight
    return score / total_weight if total_weight else 0.0


def dryness_index(recent_mm, climatology_mm):

    if climatology_mm in (None, 0) or recent_mm is None:
        return 0.0
    ratio = float(recent_mm) / max(float(climatology_mm), 1.0)
    return max(0.0, min(1.0, 1.0 - ratio))


MIN_COVERAGE = 0.90


def coverage_weight(valid_pixels, max_valid_pixels):

    if not max_valid_pixels:
        return 1.0
    coverage = max(0.0, min(1.0, float(valid_pixels) / float(max_valid_pixels)))
    return 0.55 + 0.45 * coverage


def coverage(valid_pixels, max_valid_pixels):
    if not max_valid_pixels:
        return 1.0
    return max(0.0, min(1.0, float(valid_pixels or 0) / float(max_valid_pixels)))


def rank_scenes(scenes, target="Automatico", dryness_weight=DRYNESS_WEIGHT, min_coverage=MIN_COVERAGE):

    prepared = []
    max_valid = max((float(scene.get("valid_pixels") or 0) for scene in scenes), default=0.0)
    for scene in scenes:
        item = dict(scene)
        item["contrast"] = contrast_score(scene)
        item["coverage"] = coverage(scene.get("valid_pixels"), max_valid)
        item["phenology"] = phenology_class(scene.get("ndvi_mean"), scene.get("bare_fraction"))
        item["dryness"] = dryness_index(scene.get("rain_30d_mm"), scene.get("rain_30d_normal_mm"))
        prepared.append(item)

    max_contrast = max((item["contrast"] for item in prepared), default=0.0) or 1.0
    for item in prepared:
        if item["coverage"] < min_coverage:
            item["score"] = 0.0
            continue
        item["score"] = (
            (item["contrast"] / max_contrast)
            * target_weight(item["phenology"], target)
            * (1.0 + dryness_weight * item["dryness"])
        )
    prepared.sort(key=lambda item: item["score"], reverse=True)
    return prepared


def select_for_composite(scenes, topn):

    seen_dates = set()
    selected = 0
    out = []
    for scene in scenes:
        item = dict(scene)
        date = item.get("date")
        rejected = "score" in item and item["score"] <= 0
        keep = selected < int(topn) and date not in seen_dates and not rejected
        item["selected_for_composite"] = keep
        if keep:
            seen_dates.add(date)
            selected += 1
        out.append(item)
    return out


def roc_auc(positive, control):

    positive = [float(value) for value in positive if value is not None and not math.isnan(float(value))]
    control = [float(value) for value in control if value is not None and not math.isnan(float(value))]
    if not positive or not control:
        return None
    wins = 0.0
    for site_value in positive:
        for control_value in control:
            if site_value > control_value:
                wins += 1.0
            elif site_value == control_value:
                wins += 0.5
    return wins / (len(positive) * len(control))


def percentile_bucket(value, percentiles):

    if value is None or not percentiles:
        return None
    reached = 0
    for level in sorted(percentiles):
        threshold = percentiles[level]
        if threshold is None:
            continue
        if float(value) >= float(threshold):
            reached = level
    return reached
