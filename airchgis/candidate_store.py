import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .paths import RVT_DIR


CANDIDATE_DIR = RVT_DIR / "output_rvt_gui" / "airchgis_candidates"
CANDIDATE_PATH = CANDIDATE_DIR / "candidates.json"
CANDIDATE_STATUSES = ("To verify", "Promising", "False positive", "Verified")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_candidates(path=CANDIDATE_PATH):
    path = Path(path)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, dict):
        payload = payload.get("candidates", [])
    return payload if isinstance(payload, list) else []


def save_candidate(candidate, path=CANDIDATE_PATH):
    path = Path(path)
    candidates = load_candidates(path)
    clean = json_safe(copy.deepcopy(candidate))
    now = utc_now()
    clean.setdefault("id", uuid4().hex[:12])
    clean.setdefault("created_at", now)
    clean["updated_at"] = now
    clean.setdefault("status", CANDIDATE_STATUSES[0])

    replaced = False
    for index, existing in enumerate(candidates):
        if existing.get("id") == clean["id"]:
            clean.setdefault("created_at", existing.get("created_at", now))
            candidates[index] = clean
            replaced = True
            break
    if not replaced:
        candidates.append(clean)

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {"version": 1, "candidates": candidates}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    temporary.replace(path)
    return clean


def update_candidate(candidate_id, updates, path=CANDIDATE_PATH):
    candidates = load_candidates(path)
    for candidate in candidates:
        if candidate.get("id") == candidate_id:
            candidate.update(json_safe(updates))
            return save_candidate(candidate, path)
    raise KeyError(f"Candidate {candidate_id} not found.")


def candidates_json(candidates):
    return json.dumps(json_safe(candidates), ensure_ascii=False, indent=2)


def candidates_geojson(candidates):
    features = []
    for candidate in candidates:
        geometry = candidate.get("geometry")
        if not geometry:
            continue
        source = candidate.get("source_record") or {}
        properties = {
            "id": candidate.get("id"),
            "title": candidate.get("title"),
            "status": candidate.get("status"),
            "notes": candidate.get("notes"),
            "created_at": candidate.get("created_at"),
            "updated_at": candidate.get("updated_at"),
            "source_number": source.get("number"),
            "source_collection": source.get("source_collection"),
            "source_place": source.get("localita"),
        }
        features.append(
            {"type": "Feature", "geometry": geometry, "properties": properties}
        )
    return json.dumps(
        {"type": "FeatureCollection", "features": features},
        ensure_ascii=False,
        indent=2,
    )


def json_safe(value):
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
