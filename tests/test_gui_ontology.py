"""Ontology workbench of the Broadsheet frontend (src/gui_ontology.py), under Maintenance."""

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import frontmatter
import pytest
import yaml
from nicegui import ui
from nicegui.testing import User

import auth
import db_context
import dedup
import gui_app
import gui_ontology
import gui_session
import ollama_client
import ontology
import ontology_store
import wiki_engine

ADMIN = auth.DEFAULT_USER


@pytest.fixture(autouse=True)
def _pages(user: User, gui_env: Path) -> None:
    gui_session._SESSIONS.clear()
    gui_app.register()


def _page(name: str, title: str) -> None:
    post = frontmatter.Post(f"# {title}\n\n{title} Body text.", title=title, type="concept")
    (db_context.wiki_dir() / name).write_text(frontmatter.dumps(post))


def _create(modules: list[str]) -> None:
    plan = ontology_store.prepare_state({"schema": {"modules": modules}})
    wiki_engine.apply_ontology(plan, user=ADMIN, via="create")


def _typed_db() -> None:
    _create(["core", "legal-de"])
    dedup.register_file(b"Interne Notiz zur Wartung", "notiz.md")
    dedup.register_file(b"Bericht 2024", "bericht.md")
    ontology_store.append_rows([ontology.assertion("src:bericht.md", "class", "permit", by="rule")])


async def _see(user: User, text: str) -> None:
    await user.should_see(text, retries=100)


async def _until(check: Any, tries: int = 100) -> None:
    for _ in range(tries):
        if check():
            return
        await asyncio.sleep(0.05)


async def _find(user: User, marker: str) -> Any:
    for _ in range(100):
        try:
            return user.find(marker)
        except AssertionError:
            await asyncio.sleep(0.05)
    return user.find(marker)


async def _element(user: User, marker: str) -> Any:
    (element,) = (await _find(user, marker)).elements
    return element


async def _open(user: User, name: str = ADMIN, pw: str = auth.DEFAULT_PASSWORD) -> None:
    await user.open("/login")
    user.find("Username").type(name)
    user.find("Password").type(pw)
    user.find("sign-in").click()
    await user.should_see("Front page")
    await user.open("/maintenance")
    await _see(user, "Wiki pages")
    section = await _element(user, "maint-section")
    section.set_value("Ontology")


async def _view(user: User, name: str) -> None:
    toggle = await _element(user, "onto-view")
    assert isinstance(toggle, ui.toggle)
    toggle.set_value(name)


async def _import(user: User, text: str, name: str = "edited.yaml") -> None:
    await _view(user, "Import")
    up = await _element(user, "onto-upload")
    assert isinstance(up, ui.upload)
    file = ui.upload.SmallFileUpload(
        name=name, content_type="application/x-yaml", _data=text.encode()
    )  # type: ignore[call-arg]
    await up.handle_uploads(cast(list[ui.upload.FileUpload], [file]))


# --- pure helpers ---------------------------------------------------------------------------


def test_the_views_are_the_streamlit_ones() -> None:
    assert gui_ontology.VIEWS == (
        "Overview", "Classes", "Facts", "Edit", "Proposals", "Cues", "Lint", "History", "Import",
    )  # fmt: skip


def test_class_tree_lines_indent_children_under_their_parent() -> None:
    parent = ontology.ClassDef(
        id="doc", labels={"de": "Dok", "en": "Doc"}, module="core", definition=""
    )
    child = ontology.ClassDef(
        id="memo", labels={"de": "Notiz", "en": "Memo"}, module="core", definition="", broader="doc"
    )
    lines = gui_ontology.class_tree({"doc": parent, "memo": child}, {"memo": 2})
    assert [(depth, text.split(" · ")[0]) for depth, text in lines] == [
        (0, "**Dok** / Doc `doc`"),
        (1, "**Notiz** / Memo `memo`"),
    ]
    assert lines[1][1].endswith("2 fact(s)")


def test_fact_rows_flatten_every_section() -> None:
    facts = {"sources": {"a.md": {"class": "report", "work": "w", "version_date": "2024-01-01"}}}
    assert gui_ontology.fact_rows(facts) == [
        {"Kind": "sources", "Subject": "a.md", "Class": "report", "Work": "w",
         "Other": "version_date = 2024-01-01"},
    ]  # fmt: skip


# --- page ------------------------------------------------------------------------------------


async def test_without_an_ontology_a_maintainer_can_create_one(user: User) -> None:
    await _open(user)
    await _see(user, "No ontology for this database.")
    await _see(user, "no detection cues")  # core alone has none
    modules = await _element(user, "onto-modules")
    assert isinstance(modules, ui.select)
    modules.set_value(["core", "legal-de"])
    await user.should_not_see("no detection cues", retries=100)
    (await _find(user, "onto-create")).click()
    await _see(user, "Revision 1")
    assert ontology_store.exists()


async def test_a_reader_cannot_create_an_ontology(user: User) -> None:
    await _open(user, "reader", "pw")
    await _see(user, "Only maintainers of this database can create one.")
    await user.should_not_see("Create ontology")


async def test_reimporting_an_unchanged_file_changes_nothing(user: User) -> None:
    _create(["core"])
    await _open(user)
    await _import(user, ontology_store.export_text(ADMIN))
    await _see(user, "nothing changed")
    assert len(ontology_store.history()) == 1


async def test_an_import_is_previewed_then_applied(user: User) -> None:
    dedup.register_file(b"typed", "typed.md")
    _create(["core"])
    doc = yaml.safe_load(ontology_store.export_text(ADMIN))
    doc["facts"] = {"sources": {"typed.md": {"class": "report"}}}
    await _open(user)
    await _import(user, yaml.safe_dump(doc))
    await _see(user, "Preview:")
    (await _find(user, "onto-apply")).click()
    await _see(user, "Applied revision 2.")
    assert [r["seq"] for r in ontology_store.history()] == [1, 2]
    assert [r["file"] for r in ontology_store.history()][-1] == "edited.yaml"


async def test_a_readers_import_is_previewed_but_not_applicable(user: User) -> None:
    _create(["core"])
    dedup.register_file(b"typed", "typed.md")
    doc = yaml.safe_load(ontology_store.export_text(ADMIN))
    doc["facts"] = {"sources": {"typed.md": {"class": "report"}}}
    await _open(user, "reader", "pw")
    await _import(user, yaml.safe_dump(doc))
    await _see(user, "Only maintainers of this database can apply an import.")
    await user.should_not_see("Apply import")


async def test_views_render_and_restore_makes_a_new_revision(user: User) -> None:
    dedup.register_file(b"typed", "typed.md")
    _create(["core"])
    doc = yaml.safe_load(ontology_store.export_text(ADMIN))
    doc["facts"] = {
        "sources": {"typed.md": {"class": "report", "work": "w-typed"}},
        "works": {"w-typed": {"class": "report", "aliases": ["Typed"]}},
    }
    plan = ontology_store.prepare_import(yaml.safe_dump(doc))
    wiki_engine.apply_ontology(plan, user=ADMIN, via="import")
    await _open(user)
    await _see(user, "Sources with facts 1")
    await _view(user, "Facts")
    await _see(user, "w-typed")
    await _view(user, "Classes")
    await _see(user, "2 fact(s)")
    await _view(user, "History")
    revision = await _element(user, "onto-revision")
    revision.set_value(1)
    ok = await _element(user, "onto-restore-ok")
    ok.set_value(True)
    restore = await _element(user, "onto-restore")
    await _until(lambda: restore.enabled)
    (await _find(user, "onto-restore")).click()
    await _see(user, "Applied revision 3.")
    assert [r["via"] for r in ontology_store.history()] == ["create", "import", "restore"]
    assert ontology_store.current_state()["facts"] == {}


async def test_overview_offers_the_standard_exports(user: User) -> None:
    _typed_db()
    await _open(user)
    await _see(user, "Schema as SKOS (Turtle)")
    await _see(user, "Facts as JSON-LD")
    await _see(user, "Export current (YAML)")


async def test_fact_proposals_show_attributes_and_can_be_confirmed(user: User) -> None:
    _create(["core", "legal-de"])
    dedup.register_file(b"note", "note.md")
    ontology_store.append_rows(
        [
            ontology.assertion(
                "src:note.md", "class", "report", by="llm", status="proposed", evidence="A quote."
            ),
            ontology.assertion(
                "src:note.md",
                "incorporates",
                "din-6812",
                by="rule",
                status="proposed",
                evidence="Die DIN.",
                attributes={"mode": "static", "edition": "2013-06"},
            ),
        ]
    )
    await _open(user)
    await _see(user, "2 open proposal(s)")
    await _view(user, "Proposals")
    await _see(user, "(edition=2013-06, mode=static)")
    row = next(r for r in ontology_store.proposals() if r["predicate"] == "class")
    (await _find(user, f"onto-ok-{row['id']}")).click()
    await _see(user, "Confirmed, revision 2.")
    assert ontology_store.source_facts("note.md") == {"class": "report"}


async def test_lint_lists_findings(user: User) -> None:
    _create(["core", "legal-de"])
    ontology_store.append_rows(
        [
            ontology.assertion("work:a", "based_on", "b", by="rule"),
            ontology.assertion("work:b", "based_on", "a", by="rule"),
        ]
    )
    await _open(user)
    await _view(user, "Lint")
    await _see(user, "cycle in based_on")


async def test_the_edit_view_has_no_pending_change_until_edited(user: User) -> None:
    _typed_db()
    await _open(user)
    await _view(user, "Edit")
    await _see(user, "Local classes")
    (await _find(user, "onto-edit-preview")).click()
    await _see(user, "nothing changed")


async def test_a_local_class_added_in_the_editor_is_applied(user: User) -> None:
    _typed_db()
    await _open(user)
    await _view(user, "Edit")
    (await _find(user, "onto-add-class")).click()
    field = await _element(user, "onto-class-0-id")
    field.set_value("memo")
    (await _element(user, "onto-class-0-broader")).set_value("report")
    (await _element(user, "onto-class-0-label_de")).set_value("Notiz")
    (await _element(user, "onto-class-0-label_en")).set_value("Memo")
    (await _element(user, "onto-class-0-definition")).set_value("Internal memo")
    (await _find(user, "onto-edit-preview")).click()
    await _see(user, "Preview:")
    (await _find(user, "onto-edit-apply")).click()
    await _see(user, "Applied revision 2.")
    schema, _ = ontology_store.load()
    assert schema is not None
    assert "memo" in schema.classes


async def test_cue_tester_and_reclassify(user: User) -> None:
    _typed_db()
    await _open(user)
    await _view(user, "Cues")
    (await _find(user, "onto-cue")).type(r"\bNotiz\b")
    await _see(user, "Matches 1 of")
    (await _find(user, "onto-reclassify")).click()
    await _see(user, "Re-classified")
    assert ontology_store.history()[-1]["via"] == "reclassify"
    assert "bericht.md" not in ontology_store.current_state()["facts"].get("sources", {})


async def test_reclassify_without_cues_does_not_claim_everything_matches(user: User) -> None:
    dedup.register_file(b"Bericht 2024", "bericht.md")
    _create(["core"])
    await _open(user)
    await _view(user, "Cues")
    await _see(user, "0 of 1 documents classified")
    await user.should_not_see("already matches")


async def test_a_class_suggestion_can_be_requested_and_accepted(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _typed_db()
    answer = {
        "id": "memo", "broader": "report", "label_de": "Notiz", "label_en": "Memo",
        "definition": "Internal memo", "cue": r"\bNotiz\b",
    }  # fmt: skip
    monkeypatch.setattr(ollama_client, "generate", lambda *a, **k: json.dumps(answer))
    await _open(user)
    await _view(user, "Proposals")
    pick = await _element(user, "onto-unclassified")
    pick.set_value("notiz.md")
    (await _find(user, "onto-suggest")).click()
    await _see(user, "Suggestion memo added for review.")
    [proposal] = ontology_store.schema_proposals()
    (await _find(user, f"onto-sok-{proposal['id']}")).click()
    await _see(user, "Class added")
    assert ontology_store.source_facts("notiz.md") == {"class": "memo"}


async def test_concept_pages_can_be_sent_for_classification(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create(["core", "ai-tech"])
    _page("alpha.md", "Alpha")
    _page("beta.md", "Beta")

    def answer(system: str, prompt: str, **_k: object) -> str:
        title = "Alpha" if "# Alpha" in prompt else "Beta"
        return json.dumps({"class": "technique", "quote": f"{title} Body text."})

    monkeypatch.setattr(ollama_client, "generate", answer)
    await _open(user)
    await _view(user, "Proposals")
    (await _find(user, "onto-classify-pages")).click()
    await _see(user, "2 page class proposal(s)")
    assert {r["subject"] for r in ontology_store.proposals()} == {"page:alpha.md", "page:beta.md"}
