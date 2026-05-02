"""Tests for dedup.py — SHA-256 deduplication engine."""

import json

import pytest

import dedup


# --- sha256 ---

def test_sha256_is_64_char_hex():
    result = dedup.sha256(b"hello")
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


def test_sha256_deterministic():
    assert dedup.sha256(b"same") == dedup.sha256(b"same")


def test_sha256_differs_for_different_inputs():
    assert dedup.sha256(b"a") != dedup.sha256(b"b")


# --- is_duplicate ---

def test_is_duplicate_false_for_new_file(raw_dir):
    assert dedup.is_duplicate(b"brand new content") is False


def test_is_duplicate_true_after_register(raw_dir):
    data = b"some bytes"
    dedup.register_file(data, "doc.txt")
    assert dedup.is_duplicate(data) is True


def test_is_duplicate_empty_bytes(raw_dir):
    assert dedup.is_duplicate(b"") is False


# --- register_file ---

def test_register_file_returns_path(raw_dir):
    result = dedup.register_file(b"content", "file.txt")
    from pathlib import Path
    assert isinstance(result, Path)


def test_register_file_creates_file(raw_dir):
    path = dedup.register_file(b"hello world", "test.txt")
    assert path.exists()


def test_register_file_writes_correct_bytes(raw_dir):
    data = b"exact bytes"
    path = dedup.register_file(data, "exact.txt")
    assert path.read_bytes() == data


def test_register_file_creates_manifest(raw_dir):
    dedup.register_file(b"data", "f.txt")
    assert (raw_dir / "manifest.json").exists()


def test_register_file_records_hash_in_manifest(raw_dir):
    data = b"tracked"
    dedup.register_file(data, "f.txt")
    manifest = json.loads((raw_dir / "manifest.json").read_text())
    assert dedup.sha256(data) in manifest


def test_register_file_records_timestamp(raw_dir):
    dedup.register_file(b"ts", "f.txt")
    manifest = json.loads((raw_dir / "manifest.json").read_text())
    entry = next(iter(manifest.values()))
    assert "added_at" in entry


def test_register_file_name_collision_appends_hash(raw_dir):
    data1 = b"first"
    data2 = b"second"
    p1 = dedup.register_file(data1, "doc.txt")
    p2 = dedup.register_file(data2, "doc.txt")
    assert p1 != p2
    assert p2.name != "doc.txt"


def test_register_file_creates_raw_dir_if_absent(tmp_path, monkeypatch):
    raw = tmp_path / "new_raw"
    monkeypatch.setattr(dedup, "RAW_DIR", raw)
    monkeypatch.setattr(dedup, "MANIFEST", raw / "manifest.json")
    dedup.register_file(b"x", "x.txt")
    assert raw.exists()


def test_duplicate_after_second_call(raw_dir):
    data = b"repeated"
    dedup.register_file(data, "r.txt")
    assert dedup.is_duplicate(data) is True


def test_manifest_is_valid_json(raw_dir):
    dedup.register_file(b"valid", "v.txt")
    content = (raw_dir / "manifest.json").read_text()
    parsed = json.loads(content)
    assert isinstance(parsed, dict)


def test_two_files_same_name_get_different_paths(raw_dir):
    p1 = dedup.register_file(b"alpha", "same.txt")
    p2 = dedup.register_file(b"beta", "same.txt")
    assert p1 != p2


def test_manifest_persists_across_reads(raw_dir):
    data = b"persist"
    dedup.register_file(data, "p.txt")
    # Re-load manifest via private helper to confirm persistence
    manifest = dedup._load_manifest()
    assert dedup.sha256(data) in manifest
