import copy
import json
import re
from collections import defaultdict
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent / "data"
PVS_PATH = DATA_DIR / "potenza_valley_sites.json"
PVS_2017_PATH = DATA_DIR / "pvs_2017_enrichment.json"
SOURCE_MANIFEST_PATH = DATA_DIR / "source_manifest.json"


def load_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return {} if default is None else copy.deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8"))


def enrich_database(database, pvs_database=None, pvs_2017=None):
    """Join independently extracted sources without mutating the source payloads."""
    enriched = copy.deepcopy(database)
    records = enriched.get("records", [])
    pvs_database = pvs_database or load_json(PVS_PATH, {"records": []})
    pvs_2017 = pvs_2017 or load_json(PVS_2017_PATH, {"records": []})
    pvs_by_id = {
        str(record.get("source_id", "")).zfill(3): copy.deepcopy(record)
        for record in pvs_database.get("records", [])
        if record.get("source_id")
    }

    accepted, review = citation_links(records, pvs_by_id)
    linked_standalone_numbers = set()
    coordinates_added_2006 = 0
    sources_attached_2006 = 0
    for cam_number, source_id in accepted.items():
        target = find_record(records, cam_number)
        source = pvs_by_id.get(source_id)
        if not target or not source:
            continue
        if attach_external_source(target, source, "pvs_2006_catalogue"):
            sources_attached_2006 += 1
        target.setdefault("documentary_links", []).append(
            documentary_link("pvs_2006_catalogue", source_id, "explicit bibliographic citation", "alta")
        )
        if not has_coordinates(target) and has_coordinates(source):
            transfer_coordinates(target, source, "PVS 2006")
            coordinates_added_2006 += 1
        linked_standalone_numbers.add(f"PVS.{source_id}")

    # Remove only duplicate standalone PVS rows whose CAM-M correspondence is
    # univocal and independently supported by an explicit source citation.
    before_dedup = len(records)
    records[:] = [record for record in records if record.get("number") not in linked_standalone_numbers]
    deduplicated = before_dedup - len(records)

    coordinates_added_2017 = 0
    sources_attached_2017 = 0
    standalone_added_2017 = 0
    for source in pvs_2017.get("records", []):
        source = copy.deepcopy(source)
        source_id = str(source.get("source_id", "")).zfill(3)
        target_number = source.get("target_cam_number")
        target = find_record(records, target_number) if target_number else None
        if target:
            if attach_external_source(target, source, "pvs_2017"):
                sources_attached_2017 += 1
            target.setdefault("documentary_links", []).append(
                documentary_link("pvs_2017", source_id, "CAM-M reference to PVS 2017 record", "alta")
            )
            if not has_coordinates(target) and has_coordinates(source):
                transfer_coordinates(target, source, "PVS 2017")
                coordinates_added_2017 += 1
            merge_validation_flags(target, source)
        elif source.get("include_as_standalone"):
            records.append(standalone_2017_record(source))
            standalone_added_2017 += 1

    for record in records:
        document_keys = record_document_keys(record)
        record["source_document_keys"] = document_keys
        record["provenance_status"] = provenance_status(record)

    metadata = enriched.setdefault("metadata", {})
    metadata["source_manifest"] = "airch/data/source_manifest.json"
    metadata["enrichment"] = {
        "citation_links_accepted": len(accepted),
        "citation_links_for_review": len(review),
        "pvs_duplicate_rows_removed": deduplicated,
        "coordinates_added_from_pvs_2006": coordinates_added_2006,
        "coordinates_added_from_pvs_2017": coordinates_added_2017,
        "external_sources_attached_2006": sources_attached_2006,
        "external_sources_attached_2017": sources_attached_2017,
        "standalone_pvs_2017_added": standalone_added_2017,
        "review_queue": review,
    }
    enriched["records"] = records
    enriched["stats"] = dynamic_stats(records)
    return enriched


def citation_links(records, pvs_by_id):
    candidates = {}
    source_targets = defaultdict(list)
    for record in records:
        if record.get("source_collection") != "CAM-M":
            continue
        source_ids = pvs_2006_reference_ids(record.get("bibliography", ""))
        if source_ids:
            candidates[record.get("number")] = source_ids
            for source_id in source_ids:
                source_targets[source_id].append(record.get("number"))

    accepted = {}
    review = []
    for cam_number, source_ids in sorted(candidates.items()):
        record = find_record(records, cam_number)
        if len(source_ids) != 1:
            review.append(review_item(cam_number, source_ids, "CAM-M record linked to several PVS records"))
            continue
        source_id = source_ids[0]
        source = pvs_by_id.get(source_id)
        if len(source_targets[source_id]) != 1:
            review.append(review_item(cam_number, source_ids, "PVS record cited by several CAM-M records"))
            continue
        if not source or not has_coordinates(source):
            review.append(review_item(cam_number, source_ids, "PVS coordinates not available"))
            continue
        if normalise(record.get("comune")) != normalise(source.get("comune")):
            review.append(review_item(cam_number, source_ids, "CAM-M/PVS municipality mismatch"))
            continue
        accepted[cam_number] = source_id
    return accepted, review


def pvs_2006_reference_ids(bibliography):
    source_ids = []
    for clause in re.split(r";", str(bibliography or "")):
        lowered = clause.casefold()
        if "2006" not in lowered or "scheda" not in lowered:
            continue
        if "vermeulen" not in lowered and "potenza" not in lowered:
            continue
        source_ids.extend(re.findall(r"\bscheda\s+(\d{1,3})\b", clause, flags=re.IGNORECASE))
    return sorted({source_id.zfill(3) for source_id in source_ids})


def attach_external_source(target, source, document_key):
    external_sources = target.setdefault("external_sources", [])
    source_id = str(source.get("source_id", "")).zfill(3)
    if any(
        str(item.get("source_id", "")).zfill(3) == source_id
        and (item.get("source_document_key") == document_key or item.get("source_collection") in {"PVS", "PVS 2017"})
        for item in external_sources
    ):
        return False
    payload = copy.deepcopy(source)
    payload["source_id"] = source_id
    payload["source_document_key"] = document_key
    payload.setdefault("source_collection", "PVS 2017" if document_key == "pvs_2017" else "PVS")
    payload.setdefault("source_label", "Potenza Valley Survey")
    external_sources.append(payload)
    return True


def transfer_coordinates(target, source, label):
    target["lat"] = float(source["lat"])
    target["lon"] = float(source["lon"])
    source_id = str(source.get("source_id", "")).zfill(3)
    if label == "PVS 2017":
        target["coordinate_source"] = f"PVS 2017, record {source_id}, published WGS84 coordinates"
        target["coordinate_precision"] = "WGS84 pubblicata"
    else:
        target["coordinate_source"] = f"PVS 2006, record {source_id}, UTM EPSG:32633 converted to WGS84"
        target["coordinate_precision"] = "published UTM"
    target["coordinate_status"] = "verified by documentary reference"


def standalone_2017_record(source):
    source_id = str(source.get("source_id", "")).zfill(3)
    return {
        "number": f"PVS.{source_id}",
        "code_prefix": "PVS17",
        "source_collection": "PVS 2017",
        "source_id": source_id,
        "comune": source.get("comune", ""),
        "localita": source.get("localita", ""),
        "coordinate_precision": "WGS84 pubblicata",
        "coordinate_status": "verified by documentary reference",
        "lat": source.get("lat"),
        "lon": source.get("lon"),
        "coordinate_source": f"PVS 2017, record {source_id}, WGS84 pubblicata",
        "definition": source.get("definition", ""),
        "dating": source.get("dating", ""),
        "description": source.get("description", ""),
        "site_size": source.get("site_size", ""),
        "investigation_methods": source.get("investigation_methods", []),
        "source_pdf_page": source.get("source_pdf_page"),
        "source_print_page": source.get("source_print_page"),
        "source_document_keys": ["pvs_2017"],
        "official_map_url": "",
        "external_sources": [],
        "bibliography": "Van Limbergen et al. 2017, Sites catalogue.",
        "archive_sources": "",
        "ceramic_presence": "presente" if source.get("ceramic_terms") else "non indicata",
        "ceramic_terms": source.get("ceramic_terms", []),
        "ceramic_evidence": source.get("description", ""),
        "find_type": source.get("find_type", ""),
        "validation_flags": source.get("validation_flags", []),
        "documentary_links": [
            documentary_link("pvs_2017", source_id, "PVS 2017 record", "alta")
        ],
        "provenance_status": "linked primary source",
    }


def record_document_keys(record):
    keys = []
    if record.get("source_collection") == "CAM-M":
        keys.append("cam_m_2024")
    if record.get("source_collection") == "PVS" or any(
        item.get("source_collection") == "PVS" for item in record.get("external_sources", []) or []
    ):
        keys.append("pvs_2006_catalogue")
    if record.get("source_collection") == "PVS 2017" or any(
        item.get("source_document_key") == "pvs_2017" for item in record.get("external_sources", []) or []
    ):
        keys.append("pvs_2017")
    return list(dict.fromkeys(keys))


def provenance_status(record):
    if record.get("source_document_keys"):
        return "linked primary source"
    if record.get("bibliography") or record.get("archive_sources"):
        return "textual references"
    return "to be completed"


def documentary_link(document_key, source_id, method, confidence):
    return {
        "document_key": document_key,
        "source_id": str(source_id).zfill(3),
        "method": method,
        "confidence": confidence,
    }


def merge_validation_flags(target, source):
    flags = target.setdefault("validation_flags", [])
    for flag in source.get("validation_flags", []) or []:
        if flag not in flags:
            flags.append(flag)


def review_item(cam_number, source_ids, reason):
    return {"cam_number": cam_number, "pvs_source_ids": source_ids, "reason": reason}


def find_record(records, number):
    if not number:
        return None
    return next((record for record in records if record.get("number") == number), None)


def has_coordinates(record):
    return record.get("lat") is not None and record.get("lon") is not None


def normalise(value):
    return str(value or "").casefold().replace("’", "'").strip()


def dynamic_stats(records):
    return {
        "record_count": len(records),
        "with_coordinates": sum(has_coordinates(record) for record in records),
        "with_bibliography": sum(bool(record.get("bibliography")) for record in records),
        "with_archive_sources": sum(bool(record.get("archive_sources")) for record in records),
        "with_primary_source_link": sum(bool(record.get("source_document_keys")) for record in records),
        "with_validation_flags": sum(bool(record.get("validation_flags")) for record in records),
        "by_source": dict(sorted(count_by(records, "source_collection").items())),
        "by_municipality": dict(sorted(count_by(records, "comune").items())),
    }


def count_by(records, field):
    counts = defaultdict(int)
    for record in records:
        counts[str(record.get(field) or "Not stated")] += 1
    return counts
