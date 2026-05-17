"""SHA-256 deduplication for uploaded raw files."""

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
import os

load_dotenv()

RAW_DIR = Path(os.getenv("RAW_DIR", "data/raw"))
MANIFEST = RAW_DIR / "manifest.json"


def _load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {}


def _save_manifest(manifest: dict) -> None:
    MANIFEST.write_text(json.dumps(manifest, indent=2))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_duplicate(file_bytes: bytes) -> bool:
    return sha256(file_bytes) in _load_manifest()


def register_file(file_bytes: bytes, filename: str) -> Path:
    """Save file to raw dir and record in manifest. Returns saved path."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    digest = sha256(file_bytes)
    dest = RAW_DIR / filename
    # Avoid name collision without changing the hash key
    if dest.exists():
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        dest = RAW_DIR / f"{stem}_{digest[:8]}{suffix}"
    dest.write_bytes(file_bytes)
    manifest = _load_manifest()
    manifest[digest] = {
        "filename": dest.name,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_manifest(manifest)
    return dest


def list_sources() -> list[str]:
    """Return filenames of all registered sources."""
    return [v["filename"] for v in _load_manifest().values()]


def deregister_source(source_name: str) -> bool:
    """Remove a source from the manifest by filename. Returns True if found."""
    manifest = _load_manifest()
    key = next((k for k, v in manifest.items() if v["filename"] == source_name), None)
    if key is None:
        return False
    del manifest[key]
    _save_manifest(manifest)
    return True
