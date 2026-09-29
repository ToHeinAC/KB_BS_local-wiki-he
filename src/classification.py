"""Classification levels and shard ids — pure, no I/O.

Every DB has one physical sub-store ("shard") per level. The normal shard keeps
the bare DB name (existing data needs no migration); higher shards append the
level: `KI@confidential`, `KI@strict`. `@` is not a DB-name character and is
not a citation-section marker (`#`, `§`), so a shard id never collides with
either. Access decisions live in `db_context`; this module only names things.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

LEVELS: tuple[str, ...] = ("normal", "confidential", "strict")
LEVEL_LABELS: tuple[str, ...] = ("Normal", "Confidential", "Strictly confidential")
LEVEL_SEP = "@"


def level_index(name: str) -> int:
    """Index of a level given by key (`strict`) or display label; ValueError otherwise."""
    key = (name or "").strip()
    if key in LEVELS:
        return LEVELS.index(key)
    if key in LEVEL_LABELS:
        return LEVEL_LABELS.index(key)
    raise ValueError(f"Unknown classification level: {name!r}")


def level_label(level: int) -> str:
    return LEVEL_LABELS[level]


def shard_id(db: str, level: int) -> str:
    if not 0 <= level < len(LEVELS):
        raise ValueError(f"Unknown classification level: {level!r}")
    return db if level == 0 else f"{db}{LEVEL_SEP}{LEVELS[level]}"


def parse_shard(shard: str) -> tuple[str, int]:
    """Split a shard id into (db, level). Only canonical ids parse."""
    db, sep, suffix = (shard or "").partition(LEVEL_SEP)
    if not db:
        raise ValueError(f"Invalid shard id: {shard!r}")
    if not sep:
        return db, 0
    if suffix not in LEVELS[1:]:
        raise ValueError(f"Invalid shard id: {shard!r}")
    return db, LEVELS.index(suffix)


def label(shard: str) -> str:
    """Display name: the bare DB for normal, `DB · Level` above it."""
    db, level = parse_shard(shard)
    return db if level == 0 else f"{db} · {level_label(level)}"


def high_water(shards: Iterable[str]) -> int:
    """Highest level among `shards` — the level derived content must be saved at."""
    return max((parse_shard(s)[1] for s in shards), default=0)


@dataclass
class UploadPlan:
    by_level: dict[int, list[str]] = field(default_factory=dict[int, list[str]])
    missing: list[str] = field(default_factory=list[str])
    denied: list[str] = field(default_factory=list[str])

    @property
    def ok(self) -> bool:
        return not self.missing and not self.denied


def plan_upload(rows: Mapping[str, str | None], max_level: int) -> UploadPlan:
    """Group files by chosen level; unclassified and above-clearance files block ingest."""
    plan = UploadPlan()
    for name, choice in rows.items():
        if not choice:
            plan.missing.append(name)
            continue
        level = level_index(choice)
        if level > max_level:
            plan.denied.append(name)
        else:
            plan.by_level.setdefault(level, []).append(name)
    return plan
