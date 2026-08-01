import hashlib
import json
from pathlib import Path

from .database_enrichment import SOURCE_MANIFEST_PATH
from .paths import RVT_DIR


SOURCE_CACHE_DIR = RVT_DIR / "output_rvt_gui" / "source_cache"


def load_manifest(path=SOURCE_MANIFEST_PATH):
    path = Path(path)
    if not path.exists():
        return {"documents": [], "web_sources": []}
    return json.loads(path.read_text(encoding="utf-8"))


def document_index(manifest=None):
    manifest = manifest or load_manifest()
    return {document["key"]: document for document in manifest.get("documents", [])}


def local_document_path(document, cache_dir=SOURCE_CACHE_DIR):
    return Path(cache_dir) / document["local_name"]


def document_status(document, cache_dir=SOURCE_CACHE_DIR, verify_hash=False):
    path = local_document_path(document, cache_dir)
    status = {"path": path, "available": path.is_file(), "verified": False, "reason": "non scaricato"}
    if not path.is_file():
        return status
    expected_size = document.get("size_bytes")
    if expected_size and path.stat().st_size != expected_size:
        status["reason"] = "dimensione non corrispondente"
        return status
    if verify_hash and document.get("sha256"):
        digest = sha256_file(path)
        status["verified"] = digest == document["sha256"]
        status["reason"] = "checksum verificato" if status["verified"] else "checksum non corrispondente"
    else:
        status["verified"] = True
        status["reason"] = "file disponibile; dimensione verificata"
    return status


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
