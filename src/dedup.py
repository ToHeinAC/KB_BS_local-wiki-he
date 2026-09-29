"""SHA-256 deduplication for uploaded raw files."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

import db_context

load_dotenv()

# sha256(original upload bytes) -> {"filename": ..., "added_at": ...}
Manifest = dict[str, dict[str, str]]


def _raw_dir() -> Path:
    return db_context.raw_dir()


def _manifest_path() -> Path:
    return _raw_dir() / "manifest.json"


def _load_manifest() -> Manifest:
    p = _manifest_path()
    if p.exists():
        return json.loads(p.read_text())
    return {}


def _save_manifest(manifest: Manifest) -> None:
    p = _manifest_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest, indent=2))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_duplicate(file_bytes: bytes) -> bool:
    return sha256(file_bytes) in _load_manifest()


def register_file(file_bytes: bytes, filename: str, content: bytes | None = None) -> Path:
    """Save a file to the raw dir and record it in the manifest. Returns saved path.

    The manifest is keyed by sha256(file_bytes) — pass the *original* upload here
    so re-uploading the same source is detected as a duplicate. When ``content``
    is given (e.g. Markdown converted from a PDF), it is what gets written to disk
    while the dedup key still tracks the original bytes.
    """
    return register_digest(
        sha256(file_bytes), filename, content if content is not None else file_bytes
    )


def register_digest(digest: str, filename: str, content: bytes, added_at: str = "") -> Path:
    """Store `content` as `filename` under an already known dedup key.

    Moving a source between classification levels keeps the key of the original
    upload, so re-uploading that file is still recognised as a duplicate.
    """
    raw = _raw_dir()
    raw.mkdir(parents=True, exist_ok=True)
    dest = raw / filename
    # Avoid name collision without changing the hash key
    if dest.exists():
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        dest = raw / f"{stem}_{digest[:8]}{suffix}"
    dest.write_bytes(content)
    manifest = _load_manifest()
    manifest[digest] = {
        "filename": dest.name,
        "added_at": added_at or datetime.now(UTC).isoformat(),
    }
    _save_manifest(manifest)
    return dest


def entry_for(filename: str) -> tuple[str, dict[str, str]] | None:
    """(dedup key, manifest entry) of a registered source, or None."""
    return next(((k, v) for k, v in _load_manifest().items() if v["filename"] == filename), None)


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
