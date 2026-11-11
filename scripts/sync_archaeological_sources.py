#!/usr/bin/env python3
import argparse
import shutil
import sys
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from airch import source_registry
from airch.database_enrichment import load_json


def main():
    parser = argparse.ArgumentParser(description="Sincronizza le fonti documentarie di AIrch.")
    parser.add_argument("--maps", action="store_true", help="Scarica anche le 52 tavole comunali CAM-M.")
    parser.add_argument("--force", action="store_true", help="Riscarica o ricopia i file gia presenti.")
    args = parser.parse_args()

    manifest = source_registry.load_manifest()
    cache_dir = source_registry.SOURCE_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)

    for document in manifest.get("documents", []):
        target = source_registry.local_document_path(document, cache_dir)
        if target.exists() and not args.force:
            print(f"OK  {document['key']}: {target}")
            continue
        source = find_legacy_file(document)
        if source:
            shutil.copy2(source, target)
            print(f"COPY {document['key']}: {source} -> {target}")
        elif document.get("download_url"):
            download(document["download_url"], target)
            print(f"GET {document['key']}: {target}")
        else:
            print(f"MISS {document['key']}: copia locale autorizzata non trovata")
            continue
        status = source_registry.document_status(document, cache_dir, verify_hash=True)
        if not status["verified"]:
            target.unlink(missing_ok=True)
            raise SystemExit(f"Verifica fallita per {document['key']}: {status['reason']}")

    if args.maps:
        sync_maps(cache_dir, args.force)


def find_legacy_file(document):
    downloads = Path.home() / "Downloads"
    for filename in document.get("legacy_filenames", []):
        candidate = downloads / filename
        if candidate.is_file():
            return candidate
    return None


def sync_maps(cache_dir, force=False):
    database = load_json(PROJECT_ROOT / "airch" / "data" / "cam_m_sites.json")
    map_dir = cache_dir / "cam_m_maps"
    map_dir.mkdir(parents=True, exist_ok=True)
    items = sorted(database.get("map_links", {}).items())
    ok = 0
    for comune, url in items:
        suffix = Path(url.split("?", 1)[0]).suffix or ".jpg"
        filename = safe_name(comune) + suffix
        target = map_dir / filename
        if not target.exists() or force:
            download(url, target)
        if target.stat().st_size > 10_000:
            ok += 1
            print(f"MAP {comune}: {target.name}")
    print(f"Tavole comunali disponibili: {ok}/{len(items)}")


def download(url, target):
    request = urllib.request.Request(url, headers={"User-Agent": "AIrch/1.0"})
    temporary = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    temporary.replace(target)


def safe_name(value):
    return "_".join(str(value).replace("’", " ").replace("'", " ").split())


if __name__ == "__main__":
    main()
