"""UI-agnostic logic shared by both frontends (Streamlit `app.py`, NiceGUI `gui_*.py`).

Nothing here imports `streamlit` or `nicegui`: session state, widgets and rendering stay in the
frontends, and everything they share — constants, the ingest driver, the save paths — lives here
so the two GUIs cannot drift apart. Callers pass the active DB and progress callbacks in.
"""

import contextlib
import gc
import os
import re
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from typing import Any

import requests

import audit as security_audit
import classification
import db_context
import dedup
import file_processor
import ollama_client
import wiki_engine

CHUNK_SUFFIX_RE = re.compile(r"\s*\[Teil\s+\d+/\d+\]\s*$")
# A bare `[…]` that is not a Markdown link and not already a `[Source:`/`[Wiki:` tag.
_TEIL_RE = re.compile(r"\s*\(Teil\s+\d+(?:/\d+)?\)\s*$")
_BARE_TAG_RE = re.compile(r"\[(?!(?:Source|Wiki):)([^\[\]\n]{1,160})\](?!\()")


CITE_SECTION_SUFFIX_RE = re.compile(r"\s*[§#].*$")


RESOLVE_HELP = """\
The last ingest flagged claims that may conflict with existing wiki pages.
Nothing changes until you press **Reconcile**.

**Your options per item**
- **Ignore it** — if the item is not a real conflict, do nothing or press **Dismiss**.
- **Narrow the pages** — remove (×) every page not involved; the LLM rewrites
  *each* selected page in full, so fewer pages means less risk.
- **Give guidance** — say which claim wins and why (optional but recommended).
- **Reconcile** — the LLM rewrites the selected pages; the change is logged.
  Each page keeps its language (a rewrite in another language is not saved).
  There is no undo except re-ingesting.

**Example**
*Dose limit: page A says 20 mSv/year, page B says 50 mSv/year.*
Keep only A and B, write guidance *"20 mSv/year per the 2026 revision is
authoritative; mention 50 mSv as the superseded value"*, then Reconcile.
"""


GRAPH_LAYOUTS = {"Galaxy": "galaxy", "Ranked": "arc", "Clusters": "radial", "Pyramid": "pyramid"}


OVERLAY_LABELS = {
    "Hubs": "hubs",
    "Bridges": "bridges",
    "Orphans": "orphans",
    "Stale": "stale",
    "Outdated": "outdated",
    "Low confidence": "confidence",
}


OVERLAY_HELP = (
    "Highlights only — no node is added or hidden.\n\n"
    "- **Hubs** — pages in the top 10% by PageRank (most central): "
    "wider glow.\n"
    "- **Bridges** — pages in the top 10% by betweenness (they connect "
    "otherwise separate clusters): light ring.\n"
    "- **Orphans** — pages with no links at all, in or out: grey dot.\n"
    "- **Stale** — pages past their freshness window "
    "(`updated` + `expires_after_days`): pulsing amber ring.\n"
    "- **Outdated** — pages built only on superseded versions of a law "
    "(ontology, valid time): dashed ring.\n"
    "- **Low confidence** — pages with `confidence: low` in their "
    "frontmatter: dimmed dot."
)


NAV_GROUPS = {
    "concept": "Concepts",
    "entity": "Entities",
    "source-summary": "Source Summaries",
    "comparison": "Comparisons",
    "insight": "Insights",
    "other": "Other",
}


CONTENT_KEYS = (
    "messages",
    "chat_followup",
    "research_history",
    "last_research_q",
    "last_research_answer",
    "last_report",
    "research_sources",
    "last_research_steps",
    "last_research_metrics",
    "explorer_selected_page",
    "last_contradictions",
    "pending_batch",
    "batch_ingesting",
    "batch_prepared",
    "batch_key",
    "convert_editor",
    "chat_scope",
    "normalize_report",
)


def ontology_line(frame: dict[str, Any]) -> str:
    """One line saying what the ontology stage matched and which sources it favoured."""
    named = ", ".join(f"“{m}”" for m in frame.get("matched", []))
    targets = ", ".join(f"`{t}`" for t in [*frame.get("works", []), *frame.get("classes", [])])
    favoured = len(frame.get("sources", []))
    db = f"{frame['db']}: " if frame.get("db") else ""
    return f"Ontology — {db}{named} → {targets}; {favoured} source(s) favoured"


def level_name(shard: str) -> str:
    return classification.level_label(classification.parse_shard(shard)[1])


def level_key_label(key: str) -> str:
    return classification.level_label(classification.level_index(key))


def shard_ref(name: str) -> str:
    """`name` qualified with the bound shard unless it is the normal level."""
    return name if db_context.level() == 0 else f"{db_context.get_active_db()}::{name}"


def report_ref(report_path: str) -> str:
    return "comparisons/" + report_path.split("comparisons/")[-1]


def ingest_file(
    f: dict[str, Any], pending: dict[str, Any], agg: dict[str, list[str]], user: str, last: bool
) -> None:
    """Register, record ontology facts and ingest one file into the bound shard."""
    dates: dict[str, str] = pending["dates"]
    shared: dict[str, str] = pending["shared"]
    saved = dedup.register_file(f["raw"], f["save_name"], content=f["content_bytes"])
    shard = db_context.get_active_db()
    security_audit.record(
        "classified", user, target=saved.name, shard=shard, sha256=dedup.sha256(f["raw"])
    )
    if pending.get("ontology") is not None:
        review = {
            **pending["ontology"].get(f["save_name"], {}),
            "version_date": dates.get(f["save_name"], ""),
        }
        agg["ontology"] += wiki_engine.record_source_ontology(
            f["text"], saved.name, review, f.get("ontology") or {}, user=user
        )
    chunks = file_processor.chunk_text(f["text"])
    per_meta = {
        k: v
        for k, v in {
            "effective as of": dates.get(f["save_name"], ""),
            "part of": shared["part of"],
            "description": shared["description"],
        }.items()
        if v
    }
    ctx = wiki_engine.ingest_begin(f["text"], saved.name, per_meta or None)
    for j, chunk in enumerate(chunks):
        wiki_engine.ingest_piece(ctx, chunk, j, len(chunks))
    res = wiki_engine.ingest_end(ctx, finalize=last)
    agg["created"] += [shard_ref(p) for p in res["created"]]
    agg["updated"] += [shard_ref(p) for p in res["updated"]]
    agg["contradictions"] += res["contradictions"]


def bind_level(shard: str) -> None:
    """Bind one classification level as the active DB and the only search scope."""
    db_context.set_active_db(shard)
    db_context.set_search_scope([shard])


def grants_shrank(before: Mapping[str, int] | None, after: Mapping[str, int]) -> bool:
    """A grant was lowered or withdrawn since `before`: content read under it must go."""
    return bool(before) and any(after.get(db, -1) < lvl for db, lvl in (before or {}).items())


def visible_duplicate(data: bytes, active_db: str) -> bool:
    """Already ingested at a level the user can see. Higher levels stay invisible:
    a copy there is not reported (that would reveal it); the audit log's hashes show it."""
    for shard in db_context.reachable_shards(active_db):
        with db_context.using_db(shard):
            if dedup.is_duplicate(data):
                return True
    return False


def convert_progress(
    on_progress: Callable[[float, str], None], name: str, index: int, count: int
) -> Callable[[int, int, str], None]:
    """Progress callback for converting file ``index`` of ``count`` in a batch."""

    def _cb(done: int, total: int, label: str) -> None:
        frac = (index + (done / total if total else 1.0)) / count
        on_progress(min(frac, 1.0), f"{name}: {label}")

    return _cb


def ingest_level(
    shard: str,
    group: list[dict[str, Any]],
    pending: dict[str, Any],
    agg: dict[str, list[str]],
    user: str,
    on_file: Callable[[str], AbstractContextManager[Any]],
    tick: Callable[[], None],
) -> None:
    """Ingest one classification level's files, oldest first, into its own shard.

    `on_file(label)` returns a context manager wrapped around each file (a spinner, a status
    line); pass `lambda _l: nullcontext()` for none.
    """
    db_context.ensure_shard(shard)
    with db_context.using_db(shard):
        wiki_engine.init_wiki()
        written = len(agg["created"]) + len(agg["updated"])
        finalized = False
        for i, f in enumerate(group):
            last = i == len(group) - 1
            with on_file(f"Ingesting {f['save_name']} ({level_name(shard)})…"):
                try:
                    ingest_file(f, pending, agg, user, last)
                    finalized = finalized or last
                except Exception as e:
                    agg["failed"].append(f"{f['save_name']}: {e}")
            tick()
        if not finalized and len(agg["created"]) + len(agg["updated"]) > written:
            wiki_engine.rebuild_lex_index()  # last file failed before finalize
        if pending.get("ontology") is not None:
            wiki_engine.finish_ontology_batch(user)


def resolve_by_shard(
    desc: str, refs: list[str], guidance: str, active_db: str
) -> dict[str, list[str]]:
    """Reconcile contradiction pages inside the shard each one lives in."""
    reachable = db_context.reachable_shards(active_db)
    by_shard: dict[str, list[str]] = {} if refs else {active_db: []}
    for ref in refs:
        head, sep, tail = ref.partition("::")
        shard, name = (head, tail) if sep and head in reachable else (active_db, ref)
        by_shard.setdefault(shard, []).append(name)
    out: dict[str, list[str]] = {"updated": [], "skipped": []}
    for shard, names in by_shard.items():
        with db_context.using_db(shard):
            res = wiki_engine.resolve_contradiction(desc, names, guidance)
        out["updated"] += [f"{shard}::{n}" if shard != active_db else n for n in res["updated"]]
        out["skipped"] += res["skipped"]
    return out


def resolve_raw_source(ref: str) -> tuple[bool, bytes | None]:
    """`(previewable, bytes)` for a cited original. Only `.md`/`.txt` files preview; the
    bytes are None when such a file is gone. `ref` may be `DB::file.md [Teil 1/2] §6`."""
    db, name = db_context.split_ref(ref)  # cross-DB chat cites as "DB::file.md"
    base = CHUNK_SUFFIX_RE.sub("", name)
    base = CITE_SECTION_SUFFIX_RE.sub("", base).strip()
    if not base.lower().endswith((".md", ".txt")):
        return False, None
    with db_context.using_db(db):
        return True, wiki_engine.read_raw_source(base)


def _names(ref: str) -> tuple[str, str, str]:
    """A ref, its bare file name (no DB qualifier) and that name's stem."""
    name = ref.split(db_context.SCOPE_SEP)[-1]
    return ref, name, name.removesuffix(".md")


def wiki_aliases(
    sources: Sequence[str], titles: Mapping[str, str], raw_sources: Sequence[str] = ()
) -> dict[str, str]:
    """Lower-cased names a Fast answer may cite by → the citation tag's content.

    The answer's pages first (they keep their DB qualifier), then every page of the database by
    file, stem or title, then the answer's original documents as `Source:`.
    """
    aliases: dict[str, str] = {}

    def add(names: tuple[str, ...], tag: str) -> None:
        for alias in names:
            if alias:
                aliases.setdefault(alias.strip().lower(), tag)

    for ref in sources:
        add((*_names(ref), titles.get(_names(ref)[1], "")), f"Wiki: {ref}")
    for name, title in titles.items():
        add((*_names(name), title), f"Wiki: {name}")
    for ref in raw_sources:
        add(_names(ref), f"Source: {ref}")
    return aliases


def _cited_page(part: str, aliases: Mapping[str, str]) -> str | None:
    """The page one cited name means: a file, stem or title, maybe with a section after `.md`."""
    key = _TEIL_RE.sub("", part).strip().lower()
    for candidate in (key, key.removesuffix(".md")):
        if candidate in aliases:
            return aliases[candidate]
    return aliases.get(key.split(".md ", 1)[0] + ".md") if ".md " in key else None


def tag_wiki_citations(text: str, aliases: Mapping[str, str]) -> str:
    """Turn the Fast prompt's `[page title]` citations into `[Wiki: …]` / `[Source: …]` tags.

    Small models also write `[file.md Section (Teil 4)]` and comma-separated lists. Only names of
    the pages the answer was given are tagged; a bracket with any other name stays as it is.
    """

    def tag(match: re.Match[str]) -> str:
        tags = [_cited_page(part, aliases) for part in re.split(r"[,;]", match.group(1))]
        if not all(tags):
            return match.group(0)
        return " ".join(f"[{tag}]" for tag in dict.fromkeys(tags))

    return _BARE_TAG_RE.sub(tag, text)


def answer_fast(question: str) -> dict[str, Any]:
    """One-shot wiki answer as chat-message fields; a backend error becomes the answer text."""
    try:
        res = wiki_engine.query_with_sources(question)
    except RuntimeError as e:
        return {"content": f"Error: {e}", "sources": [], "raw_sources": [], "audit": None}
    titles = {p["filename"]: str(p.get("title") or "") for p in wiki_engine.list_pages()}
    return {
        "content": tag_wiki_citations(
            res["answer"], wiki_aliases(res["sources"], titles, res["raw_sources"])
        ),
        "sources": res["sources"],
        "raw_sources": res["raw_sources"],
        "audit": res.get("audit"),
    }


def save_answer(
    question: str,
    content: str,
    sources: list[str],
    raw_sources: list[str],
    target: str,
) -> str:
    """File a chat answer into `target` (the write target of what it searched); returns its path.

    `related:` links are intra-shard, so a cross-DB answer only carries over the pages that
    actually live in the shard being written to.
    """
    refs = [db_context.split_ref(s) for s in sources]
    related = [name for db, name in refs if db == target]
    with db_context.using_db(target):
        return wiki_engine.file_answer(
            question, content, related, derived_from=[*sources, *raw_sources]
        )


def read_report(report_path: str, active_db: str) -> str:
    """Re-read the report the research agent filed, at the high-water level it searched."""
    target = db_context.write_target(active_db, db_context.search_scope())
    with db_context.using_db(target):
        return wiki_engine.read_page_parsed(report_ref(report_path))["content"]


def save_research(answer: str, title: str, as_source: bool, target: str) -> str:
    """Ingest a research report into `target`; returns the note to show the user."""
    with db_context.using_db(target):
        if as_source:
            res = wiki_engine.ingest_as_source(answer, f"Research: {title}")
            return (
                "Already registered as a source."
                if res["duplicate"]
                else f"Saved as source `{res['source_name']}`."
            )
        wiki_engine.ingest(answer, f"Research: {title}")
        return "Saved to wiki."


def unload_model() -> None:
    """Ask the pinned Ollama to drop the model from VRAM, then collect garbage."""
    with contextlib.suppress(Exception):
        requests.post(
            f"{ollama_client.host()}/api/generate",
            json={"model": os.getenv("OLLAMA_MODEL", "gemma4:e4b"), "keep_alive": 0},
            timeout=5,
        )
    gc.collect()


def no_status(_label: str) -> AbstractContextManager[Any]:
    """`on_file` for frontends without a per-file status: does nothing."""
    return nullcontext()
