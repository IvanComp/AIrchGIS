

import json
import math
import re
import unicodedata
from functools import lru_cache
from pathlib import Path


GAZETTEER_PATH = Path(__file__).resolve().parent / "data" / "gazetteer.json"


MAX_ANCHOR_DISTANCE_KM = 9.0

PRECISION_TOPONYM = "toponimo (derivata)"
PRECISION_MUNICIPALITY = "municipality (derived)"


UNCERTAINTY_TOPONYM_M = 900
UNCERTAINTY_MUNICIPALITY_M = 4000


GENERIC_TOKENS = {
    "localita",
    "loc",
    "contrada",
    "fondo",
    "podere",
    "casa",
    "case",
    "casale",
    "villa",
    "via",
    "strada",
    "zona",
    "area",
    "presso",
    "sotto",
    "sopra",
    "vicino",
    "nord",
    "sud",
    "est",
    "ovest",
}


def normalise(value):

    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9 ]+", " ", text).casefold()
    return re.sub(r"\s+", " ", text).strip()


def haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


class Gazetteer:


    def __init__(self, payload):
        self.metadata = payload.get("metadata", {})
        self.places = payload.get("places", [])
        self.municipalities = {
            normalise(name): value for name, value in (payload.get("municipalities") or {}).items()
        }
        self.index = {}
        for place in self.places:
            for key in place.get("keys", []):
                if len(key) >= 4:
                    self.index.setdefault(key, []).append(place)

        self.keys_by_length = sorted(self.index, key=len, reverse=True)

    def __len__(self):
        return len(self.places)

    def anchor(self, comune):
        return self.municipalities.get(normalise(comune))

    def candidates(self, toponym):

        key = normalise(toponym)
        if not key:
            return []
        if key in self.index:
            return list(self.index[key])
        tokens = [token for token in key.split() if token not in GENERIC_TOKENS]
        if not tokens:
            return []
        token_set = set(tokens)
        for candidate_key in self.keys_by_length:
            if len(candidate_key) < 5:
                break
            parts = candidate_key.split()
            if len(parts) > len(tokens):
                continue
            if all(part in token_set for part in parts) and candidate_key in key:
                return list(self.index[candidate_key])
        return []


@lru_cache(maxsize=1)
def _cached_gazetteer(stamp):
    del stamp
    if not GAZETTEER_PATH.exists():
        return None
    try:
        payload = json.loads(GAZETTEER_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return Gazetteer(payload)


def load_gazetteer():

    stamp = GAZETTEER_PATH.stat().st_mtime_ns if GAZETTEER_PATH.exists() else 0
    return _cached_gazetteer(stamp)


def geocode_record(record, gazetteer, allow_municipality=True):

    if gazetteer is None:
        return None
    if record.get("lat") is not None and record.get("lon") is not None:
        return None

    comune = record.get("comune")
    anchor = gazetteer.anchor(comune)
    candidates = gazetteer.candidates(record.get("localita"))
    if candidates and anchor:
        near = [
            (haversine_km(anchor["lat"], anchor["lon"], place["lat"], place["lon"]), place)
            for place in candidates
        ]
        near = [item for item in near if item[0] <= MAX_ANCHOR_DISTANCE_KM]
        near.sort(key=lambda item: item[0])
        if near:
            distance, place = near[0]
            return {
                "lat": place["lat"],
                "lon": place["lon"],
                "coordinate_precision": PRECISION_TOPONYM,
                "coordinate_uncertainty_m": UNCERTAINTY_TOPONYM_M,
                "coordinate_source": (
                    f"toponimo «{place['name']}» from GeoNames gazetteer, "
                    f"a {distance:.1f} km from the centre of {comune}"
                ),
                "coordinate_method": "toponimo",
                "coordinate_match": place["name"],
            }
    if candidates and not anchor:
        place = candidates[0]
        return {
            "lat": place["lat"],
            "lon": place["lon"],
            "coordinate_precision": PRECISION_TOPONYM,
            "coordinate_uncertainty_m": UNCERTAINTY_TOPONYM_M * 2,
            "coordinate_source": f"toponimo «{place['name']}» from GeoNames gazetteer, municipality not anchored",
            "coordinate_method": "toponimo",
            "coordinate_match": place["name"],
        }
    if anchor and allow_municipality:
        return {
            "lat": anchor["lat"],
            "lon": anchor["lon"],
            "coordinate_precision": PRECISION_MUNICIPALITY,
            "coordinate_uncertainty_m": UNCERTAINTY_MUNICIPALITY_M,
            "coordinate_source": f"centre of the municipality of {comune}, approximate position",
            "coordinate_method": "comune",
            "coordinate_match": comune,
        }
    return None


_UNSET = object()


def apply_geocoding(records, gazetteer=_UNSET, allow_municipality=True):

    gazetteer = load_gazetteer() if gazetteer is _UNSET else gazetteer
    stats = {"published": 0, "toponym": 0, "municipality": 0, "unresolved": 0}
    if gazetteer is None:
        stats["unresolved"] = sum(
            1 for record in records if record.get("lat") is None or record.get("lon") is None
        )
        stats["published"] = len(records) - stats["unresolved"]
        return stats
    for record in records:
        if record.get("lat") is not None and record.get("lon") is not None:
            stats["published"] += 1
            record.setdefault("coordinate_method", "pubblicata")
            continue
        derived = geocode_record(record, gazetteer, allow_municipality=allow_municipality)
        if not derived:
            stats["unresolved"] += 1
            continue


        record.setdefault("catalog_precision", record.get("coordinate_precision", ""))
        record.update(derived)
        stats["toponym" if derived["coordinate_method"] == "toponimo" else "municipality"] += 1
    return stats


def is_derived(record):
    return record.get("coordinate_method") in {"toponimo", "comune"}
