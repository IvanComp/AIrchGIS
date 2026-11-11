#!/usr/bin/env python3
"""Build the local toponym gazetteer used to georeference catalogue records.

Downloads the GeoNames dump for Italy, keeps the entries inside the bounding
box of the study area and writes ``airch/data/gazetteer.json``.

    python scripts/build_gazetteer.py

GeoNames data is released under CC BY 4.0; the attribution is stored in the
generated file and shown in the app.
"""

import argparse
import csv
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from airch.geocoding import GAZETTEER_PATH, normalise  # noqa: E402


DUMP_URL = "https://download.geonames.org/export/dump/IT.zip"
LICENSE = "GeoNames, CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)"

# Province of Macerata and a margin over the neighbouring valleys.
DEFAULT_BBOX = (42.75, 12.70, 43.70, 13.95)

# Populated places, districts, farms, hills, churches and ruins: the feature
# types a nineteenth or twentieth century site description actually names.
KEEP_FEATURE_CLASSES = {"P", "S", "T", "H", "L", "A"}
SKIP_FEATURE_CODES = {"HTL", "RSTN", "PKLT", "BUSTP", "MUS", "PS", "RSD"}
MUNICIPALITY_CODES = ("ADM3", "PPLA3")


def download_dump(url=DUMP_URL):
    request = urllib.request.Request(url, headers={"User-Agent": "AIrch gazetteer builder"})
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = response.read()
    archive = zipfile.ZipFile(io.BytesIO(payload))
    name = next(item for item in archive.namelist() if item.endswith(".txt") and item != "readme.txt")
    return archive.read(name).decode("utf-8")


def parse_dump(text, bbox):
    south, west, north, east = bbox
    places = []
    municipalities = {}
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    for row in reader:
        if len(row) < 15:
            continue
        try:
            lat, lon = float(row[4]), float(row[5])
        except ValueError:
            continue
        if not (south <= lat <= north and west <= lon <= east):
            continue
        feature_class, feature_code = row[6], row[7]
        if feature_class not in KEEP_FEATURE_CLASSES or feature_code in SKIP_FEATURE_CODES:
            continue
        name = row[1].strip()
        if not name:
            continue
        alternates = [item.strip() for item in row[3].split(",") if item.strip()]
        keys = sorted({normalise(item) for item in [name, row[2]] + alternates if normalise(item)})
        places.append(
            {
                "name": name,
                "keys": [key for key in keys if len(key) >= 4],
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "code": feature_code,
            }
        )
        if feature_code in MUNICIPALITY_CODES and name not in municipalities:
            municipalities[name] = {"lat": round(lat, 6), "lon": round(lon, 6)}
    return places, municipalities


def build(bbox=DEFAULT_BBOX, destination=GAZETTEER_PATH, url=DUMP_URL):
    text = download_dump(url)
    places, municipalities = parse_dump(text, bbox)
    payload = {
        "metadata": {
            "source": "GeoNames Italy dump",
            "source_url": url,
            "license": LICENSE,
            "bbox": list(bbox),
            "place_count": len(places),
            "municipality_count": len(municipalities),
        },
        "places": places,
        "municipalities": municipalities,
    }
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bbox", nargs=4, type=float, metavar=("SOUTH", "WEST", "NORTH", "EAST"), default=DEFAULT_BBOX)
    parser.add_argument("--url", default=DUMP_URL)
    parser.add_argument("--out", default=str(GAZETTEER_PATH))
    args = parser.parse_args()
    payload = build(tuple(args.bbox), args.out, args.url)
    print(
        f"{payload['metadata']['place_count']} toponimi e "
        f"{payload['metadata']['municipality_count']} comuni scritti in {args.out}"
    )


if __name__ == "__main__":
    main()
