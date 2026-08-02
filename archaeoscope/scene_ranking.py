"""Pure-python ranking logic for satellite scenes.

Earth Engine returns raw per-scene statistics; the decision of *which* dates are
worth compositing is taken here so that it can be inspected and unit tested
without a network round trip.

The ranking answers a specific archaeological question: on which acquisition is
a buried structure most likely to be legible? That depends on three independent
things - how much contrast exists at the scale of a wall or a ditch, whether the
field is under crop or bare soil, and how dry the weeks before the acquisition
have been.
"""

import math


# Local contrast features used to rank a scene, with the contrast value that
# already counts as "strong" for that index and the weight of the feature.
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

TARGETS = ("Automatico", "Crop marks (vegetazione)", "Soil marks (suolo nudo)")

# NDVI below this value over the analysis mask means the field is essentially bare.
BARE_NDVI = 0.25
# NDVI above this value means a closed canopy able to express crop marks.
CANOPY_NDVI = 0.45
# Share of the mask that must be bare before the scene is called a soil-mark scene.
BARE_FRACTION = 0.55

PHENOLOGY_SOIL = "suolo nudo"
PHENOLOGY_CANOPY = "vegetazione"
PHENOLOGY_MIXED = "misto"

# How much a dry antecedent period may boost a scene. Crop marks are a
# moisture-stress phenomenon: the same field shows nothing after a wet month.
DRYNESS_WEIGHT = 0.45

TARGET_WEIGHTS = {
    "Crop marks (vegetazione)": {PHENOLOGY_CANOPY: 1.0, PHENOLOGY_MIXED: 0.6, PHENOLOGY_SOIL: 0.15},
    "Soil marks (suolo nudo)": {PHENOLOGY_CANOPY: 0.15, PHENOLOGY_MIXED: 0.6, PHENOLOGY_SOIL: 1.0},
}


def phenology_class(ndvi_mean, bare_fraction):
    """Classify the surface state of a scene over the analysis mask."""
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
    """Weighted local contrast of a scene, normalised per index.

    ``stats`` maps ``<BAND>_contrast`` to the mean absolute deviation of that
    index from its own neighbourhood mean. Dividing by a per-index reference
    keeps ratio-like indices from dominating linear transforms; the ``min(3)``
    clamp stops a single cloud edge from carrying the whole score.
    """
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
    """0 for a normal or wet antecedent month, 1 for a complete drought."""
    if climatology_mm in (None, 0) or recent_mm is None:
        return 0.0
    ratio = float(recent_mm) / max(float(climatology_mm), 1.0)
    return max(0.0, min(1.0, 1.0 - ratio))


def coverage_weight(valid_pixels, max_valid_pixels):
    """Penalise scenes that only see a fraction of the area of interest."""
    if not max_valid_pixels:
        return 1.0
    coverage = max(0.0, min(1.0, float(valid_pixels) / float(max_valid_pixels)))
    return 0.55 + 0.45 * coverage


def rank_scenes(scenes, target="Automatico", dryness_weight=DRYNESS_WEIGHT):
    """Return ``scenes`` sorted by final score, richest date first.

    Each scene is a dict holding the raw Earth Engine statistics. The function
    adds the derived columns (``contrast``, ``phenology``, ``dryness``,
    ``score``) and never mutates the input.
    """
    prepared = []
    max_valid = max((float(scene.get("valid_pixels") or 0) for scene in scenes), default=0.0)
    for scene in scenes:
        item = dict(scene)
        item["contrast"] = contrast_score(scene)
        item["phenology"] = phenology_class(scene.get("ndvi_mean"), scene.get("bare_fraction"))
        item["dryness"] = dryness_index(scene.get("rain_30d_mm"), scene.get("rain_30d_normal_mm"))
        prepared.append(item)

    max_contrast = max((item["contrast"] for item in prepared), default=0.0) or 1.0
    for item in prepared:
        normalised = item["contrast"] / max_contrast
        item["score"] = (
            normalised
            * coverage_weight(item.get("valid_pixels"), max_valid)
            * target_weight(item["phenology"], target)
            * (1.0 + dryness_weight * item["dryness"])
        )
    prepared.sort(key=lambda item: item["score"], reverse=True)
    return prepared


def select_for_composite(scenes, topn):
    """Flag the best ``topn`` scenes, keeping one scene per calendar date."""
    seen_dates = set()
    selected = 0
    out = []
    for scene in scenes:
        item = dict(scene)
        date = item.get("date")
        keep = selected < int(topn) and date not in seen_dates
        item["selected_for_composite"] = keep
        if keep:
            seen_dates.add(date)
            selected += 1
        out.append(item)
    return out


def roc_auc(positive, control):
    """Mann-Whitney AUC: probability a known site outscores a random control.

    0.5 means the detector is indistinguishable from chance over the sample.
    """
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
    """Describe where ``value`` falls inside the distribution of the area.

    ``percentiles`` maps a percentile (int) to the raster value at that
    percentile, as returned by Earth Engine.
    """
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
