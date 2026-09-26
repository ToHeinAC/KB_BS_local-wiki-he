"""UI tests for src/app.py via Streamlit's in-process AppTest (no server, no browser).

Every run points DATA_ROOT at a temp dir and stubs the Ollama daemon, the GPU widget
and the LLM-facing engine calls, so no real database, model or GPU is touched.
"""

from pathlib import Path

import frontmatter
import pytest
from streamlit import config as st_config
from streamlit.testing.v1 import AppTest

import agent
import auth
import chat_agent
import db_context
import deep_research_agent
import gpu_widget
import graph_widget
import ollama_client
import ollama_server
import theme
import tools
import wiki_engine

APP = str(Path(__file__).resolve().parents[1] / "src" / "app.py")
ADMIN = auth.DEFAULT_USER
DB = db_context.DEFAULT_DB


@pytest.fixture(autouse=True)
def _no_magic():
    """Skip Streamlit's "magic" AST rewrite, a no-op for app.py (it has no bare expressions)
    but ~90 % of each script run: every AppTest re-parses the 2,000-line script."""
    before = st_config.get_option("runner.magicEnabled")
    st_config.set_option("runner.magicEnabled", False)
    yield
    st_config.set_option("runner.magicEnabled", before)


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    monkeypatch.setenv("INGEST_QA", "0")
    monkeypatch.setenv("INGEST_DESCRIPTION", "0")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    status = {"host": "http://127.0.0.1:1", "pinned": False, "gpu": None, "managed": False}
    monkeypatch.setattr(ollama_server, "status", lambda: {**status, "reason": "test"})
    monkeypatch.setattr(gpu_widget, "render_gpu_sidebar", lambda accent="": None)
    auth.ensure_seeded()
    db_context.set_active_db(DB)
    wiki_engine.init_wiki()
    return tmp_path


def _page(name, title, ptype="concept", sources=("doc.md",), related=(), body="Body text."):
    post = frontmatter.Post(f"# {title}\n\n{body}", title=title, type=ptype)
    post.metadata["sources"] = list(sources)
    post.metadata["related"] = list(related)
    (db_context.wiki_dir() / name).write_text(frontmatter.dumps(post))


@pytest.fixture
def wiki(data_root):
    (db_context.raw_dir() / "doc.md").write_text("# Doc\n\nOriginal text.")
    _page("alpha.md", "Alpha", related=["beta.md"])
    _page("beta.md", "Beta", ptype="entity")
    wiki_engine.rebuild_lex_index()
    return data_root


def _app(user: str | None = ADMIN, **state) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30)
    if user:
        at.session_state["user"] = user
    for k, v in state.items():
        at.session_state[k] = v
    return at


def _go(at: AppTest, view: str) -> AppTest:
    at.run()
    at.segmented_control(key="wiki_view").set_value(view).run()
    return at


def _texts(elements) -> str:
    return "\n".join(str(e.value) for e in elements)


def _click_label(at: AppTest, prefix: str) -> AppTest:
    """Click the (single) button whose label starts with ``prefix``."""
    [button] = [b for b in at.button if b.label.startswith(prefix)]
    return button.click().run()


def _ok(at: AppTest) -> AppTest:
    assert not at.exception, at.exception
    return at


# --- login gate + sidebar ---------------------------------------------------


def test_login_gate_shows_form(data_root):
    at = _ok(_app(user=None).run())
    assert [t.label for t in at.text_input] == ["Username", "Password"]


def test_login_with_valid_credentials_enters_app(data_root):
    at = _app(user=None).run()
    at.text_input[0].set_value(ADMIN)
    at.text_input[1].set_value(auth.DEFAULT_PASSWORD)
    at.button[0].click().run()
    assert _ok(at).session_state["user"] == ADMIN
    assert at.session_state["active_db"] == DB


def test_login_with_wrong_password_is_rejected(data_root):
    at = _app(user=None).run()
    at.text_input[0].set_value(ADMIN)
    at.text_input[1].set_value("wrong")
    at.button[0].click().run()
    assert "Invalid username or password." in _texts(_ok(at).error)


def test_login_without_database_access_is_refused(data_root):
    auth.add_user("reader", "pw", [])
    at = _app(user=None).run()
    at.text_input[0].set_value("reader")
    at.text_input[1].set_value("pw")
    at.button[0].click().run()
    assert "no database access" in _texts(_ok(at).error)


def test_user_without_databases_sees_logout_only(data_root):
    auth.add_user("reader", "pw", [])
    at = _ok(_app(user="reader").run())
    assert "no database access" in _texts(at.error)
    at.button[0].click().run()
    assert "user" not in _ok(at).session_state


def test_logout_clears_the_session(data_root):
    at = _app().run()
    at.button(key="logout_btn").click().run()
    assert "user" not in _ok(at).session_state


def test_reset_unloads_and_clears_session(data_root, monkeypatch):
    import requests

    calls = []
    monkeypatch.setattr(requests, "post", lambda *a, **k: calls.append(a))
    at = _app().run()
    at.button(key="reset_btn").click().run()
    assert calls
    assert "user" not in _ok(at).session_state


def test_switching_database_clears_per_db_state(data_root):
    db_context.create_db("Second")
    auth.set_user_dbs(ADMIN, [DB, "Second"])
    at = _app(messages=[{"role": "user", "content": "hi"}]).run()
    at.selectbox(key="db_selector").set_value("Second").run()
    _ok(at)
    assert at.session_state["active_db"] == "Second"
    assert "messages" not in at.session_state


def test_newspaper_skin_renders_masthead(data_root, monkeypatch):
    monkeypatch.setattr(theme, "FRONTEND", "newspaper")
    at = _ok(_app().run())
    assert any("LocalWiki" in m.value for m in at.markdown)


# --- Upload -------------------------------------------------------------------


@pytest.fixture
def ingest_stub(monkeypatch):
    calls = []

    def begin(text, name, meta):
        calls.append(("begin", name, meta))
        return {"name": name}

    def piece(ctx, chunk, j, n):
        calls.append(("piece", ctx["name"], j))

    def end(ctx, finalize=True):
        calls.append(("end", ctx["name"], finalize))
        return {"created": ["new.md"], "updated": ["alpha.md"], "contradictions": ["X vs Y"]}

    monkeypatch.setattr(wiki_engine, "ingest_begin", begin)
    monkeypatch.setattr(wiki_engine, "ingest_piece", piece)
    monkeypatch.setattr(wiki_engine, "ingest_end", end)
    return calls


def test_upload_markdown_runs_three_phases(wiki, ingest_stub):
    at = _app().run()
    at.file_uploader[0].set_value(("notes.md", b"# Notes\n\nStand: 01.02.2024", "text/markdown"))
    at.run()
    assert "1 file(s) ready to ingest." in _texts(_ok(at).info)
    _click_label(at, "Ingest 1 file(s)")
    _ok(at)
    assert ("begin", "notes.md", {"effective as of": "2024-02-01"}) in ingest_stub
    assert ("end", "notes.md", True) in ingest_stub
    assert "Ingest complete." in _texts(at.success)
    assert at.session_state["last_contradictions"] == ["X vs Y"]


def test_upload_skips_duplicates(wiki):
    import dedup

    dedup.register_file(b"same", "same.md")
    at = _app().run()
    at.file_uploader[0].set_value(("same.md", b"same", "text/markdown"))
    at.run()
    assert "Nothing new to ingest." in _texts(_ok(at).info)
    assert "already ingested" in _texts(at.warning)


def test_upload_needs_ollama_for_conversion(wiki, monkeypatch):
    monkeypatch.setattr(ollama_client, "is_available", lambda: False)
    at = _app().run()
    at.file_uploader[0].set_value(("scan.pdf", b"%PDF", "application/pdf"))
    at.run()
    assert "Ollama is not reachable" in _texts(_ok(at).error)


def test_upload_converts_and_offers_markdown_editor(wiki, monkeypatch, ingest_stub):
    import md_convert

    monkeypatch.setattr(ollama_client, "is_available", lambda: True)
    monkeypatch.setattr(
        md_convert, "convert_to_markdown", lambda b, n, cb: cb(1, 1, "x") or "# Conv"
    )
    at = _app().run()
    at.file_uploader[0].set_value(("scan.pdf", b"%PDF", "application/pdf"))
    at.run()
    assert at.text_area(key="convert_editor").value == "# Conv"
    at.text_area(key="convert_editor").set_value("# Edited").run()
    _click_label(at, "Ingest 1 file(s)")
    assert ingest_stub[0] == ("begin", "scan.md", None)
    assert (db_context.raw_dir() / "scan.md").read_text() == "# Edited"


def test_upload_reports_failed_conversion(wiki, monkeypatch):
    import md_convert

    def boom(b, n, cb):
        raise RuntimeError("ocr down")

    monkeypatch.setattr(ollama_client, "is_available", lambda: True)
    monkeypatch.setattr(md_convert, "convert_to_markdown", boom)
    at = _app().run()
    at.file_uploader[0].set_value(("scan.pdf", b"%PDF", "application/pdf"))
    at.run()
    assert "conversion failed: ocr down" in _texts(_ok(at).warning)


def test_upload_reports_ingest_failures(wiki, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("model gone")

    monkeypatch.setattr(wiki_engine, "ingest_begin", boom)
    at = _app().run()
    at.file_uploader[0].set_value(("notes.md", b"# Notes", "text/markdown"))
    at.run()
    _click_label(at, "Ingest 1 file(s)")
    assert "notes.md: model gone" in _texts(_ok(at).error)


def test_resolve_contradiction_panel(wiki, monkeypatch):
    seen = {}

    def resolve(desc, pages, guidance):
        seen.update(desc=desc, pages=pages)
        return {"updated": ["alpha.md"], "skipped": ["beta.md"], "description": desc}

    monkeypatch.setattr(wiki_engine, "resolve_contradiction", resolve)
    at = _app(last_contradictions=["A vs B"], last_contradiction_pages=["alpha.md"]).run()
    at.button(key="resolve_btn_0").click().run()
    assert seen == {"desc": "A vs B", "pages": ["alpha.md"]}
    assert "Updated: `alpha.md`" in _texts(_ok(at).success)
    assert "switched the page's language" in _texts(at.warning)
    at.button(key="resolve_dismiss").click().run()
    assert "last_contradictions" not in _ok(at).session_state


def test_upload_hidden_for_non_maintainer(wiki):
    auth.add_user("reader", "pw", [DB])
    at = _ok(_app(user="reader").run())
    assert "Upload" not in at.segmented_control(key="wiki_view").options


# --- Wiki Explorer ------------------------------------------------------------


def test_explorer_empty_wiki_onboarding(data_root):
    at = _ok(_go(_app(), "Wiki Explorer"))
    assert "No wiki pages yet" in _texts(at.info)


def test_explorer_legacy_graph_and_inspect(wiki):
    at = _ok(_go(_app(), "Wiki Explorer"))
    assert any("Legend" in c.value for c in at.caption)
    at.selectbox(key="explorer_inspect_pick").set_value("Alpha").run()
    _ok(at)


def test_explorer_tree_opens_a_page(wiki):
    at = _go(_app(), "Wiki Explorer")
    at.segmented_control(key="explorer_view").set_value("Tree").run()
    at.button(key="explorer_nav_alpha.md").click().run()
    assert any(m.value == "### alpha.md" for m in _ok(at).markdown)
    at.button(key="view_related_beta.md").click().run()
    at.button(key="dl_wiki_doc.md").click().run()
    _ok(at)


def test_explorer_tree_search(wiki):
    at = _go(_app(), "Wiki Explorer")
    at.segmented_control(key="explorer_view").set_value("Tree").run()
    at.text_input(key="explorer_nav_search").set_value("Alpha").run()
    assert any("result(s)" in c.value for c in _ok(at).caption)
    at.button(key="explorer_hit_alpha.md").click().run()
    assert _ok(at).session_state["explorer_selected_page"] == "alpha.md"


def test_explorer_search_warns_without_index(wiki):
    (db_context.index_dir() / "chunks.sqlite").unlink()
    at = _go(_app(), "Wiki Explorer")
    at.segmented_control(key="explorer_view").set_value("Tree").run()
    at.text_input(key="explorer_nav_search").set_value("nothing").run()
    assert "No search index" in _texts(_ok(at).warning)


@pytest.fixture
def neural(monkeypatch):
    clicks = {"value": None}
    monkeypatch.setattr(graph_widget, "RENDERER", "neural")
    monkeypatch.setattr(graph_widget, "render_graph", lambda **k: clicks["value"])
    monkeypatch.setattr(
        graph_widget, "graph_stats", lambda: {"nodes": [1], "edges": [], "communities": 1}
    )
    monkeypatch.setattr(
        graph_widget,
        "graph_health",
        lambda: {
            "pages": 2,
            "orphans": ["beta.md"],
            "stale": [],
            "low_confidence": [],
            "clusters": [{"label": "Alpha", "size": 2, "recent": 1}],
            "window_days": 30,
        },
    )
    return clicks


def test_neural_graph_panel_and_click(wiki, neural):
    at = _ok(_go(_app(), "Wiki Explorer"))
    assert any("1 nodes" in c.value for c in at.caption)
    at.button(key="explorer_panel_expand").click().run()
    assert any("Bundle health" in m.value for m in _ok(at).markdown)
    at.button(key="health_open_Orphaned_beta.md").click().run()
    assert _ok(at).session_state["explorer_selected_page"] == "beta.md"
    at.button(key="explorer_panel_close").click().run()
    neural["value"] = {"n": 1, "kind": "source", "node": "source::doc.md"}
    at.run()
    neural["value"] = {"n": 2, "kind": "page", "node": "alpha.md"}
    at.run()
    assert _ok(at).session_state["explorer_selected_page"] == "alpha.md"
    at.button(key="open_related_beta.md").click().run()
    at.button(key="explorer_panel_collapse").click().run()
    assert _ok(at).session_state["explorer_panel_open"] is False


def test_neural_graph_render_failure_is_shown(wiki, neural, monkeypatch):
    def boom(**k):
        raise RuntimeError("canvas")

    monkeypatch.setattr(graph_widget, "render_graph", boom)
    at = _ok(_go(_app(), "Wiki Explorer"))
    assert "Graph render failed: canvas" in _texts(at.error)


# --- Wiki Chat ----------------------------------------------------------------


def test_fast_chat_answers_and_files_the_answer(wiki, monkeypatch):
    monkeypatch.setattr(
        wiki_engine,
        "query_with_sources",
        lambda q: {
            "answer": f"Answer to {q}",
            "sources": ["alpha.md"],
            "raw_sources": ["doc.md §1"],
            "audit": {
                "tau": 1.0,
                "kept": [("alpha.md", 2.0)],
                "below_tau": [("x", 0.1)],
                "over_cap": [("y", None)],
            },
        },
    )
    filed = []
    monkeypatch.setattr(wiki_engine, "file_answer", lambda q, a, rel: filed.append(rel) or "f.md")
    at = _go(_app(), "Wiki Chat")
    at.chat_input[0].set_value("What is alpha?").run()
    _ok(at)
    assert at.session_state["messages"][-1]["content"] == "Answer to What is alpha?"
    at.button(key="cpanel_wiki_alpha.md").click().run()
    at.button(key="save_answer").click().run()
    assert filed == [["alpha.md"]]
    at.button(key="followup_1").click().run()
    assert _ok(at).session_state["chat_followup"]["q"] == "What is alpha?"


def test_chat_follow_up_is_condensed(wiki, monkeypatch):
    monkeypatch.setattr(wiki_engine, "condense_followup", lambda q, a, f: "standalone?")
    monkeypatch.setattr(
        wiki_engine,
        "query_with_sources",
        lambda q: {"answer": q, "sources": [], "raw_sources": []},
    )
    at = _go(_app(chat_followup={"q": "Q1", "a": "A1"}), "Wiki Chat")
    at.chat_input[0].set_value("and then?").run()
    last = _ok(at).session_state["messages"][-1]
    assert last["interpreted"] == "standalone?"
    assert last["content"] == "standalone?"


def test_fast_chat_error_is_recorded(wiki, monkeypatch):
    def boom(q):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(wiki_engine, "query_with_sources", boom)
    at = _go(_app(), "Wiki Chat")
    at.chat_input[0].set_value("q").run()
    assert _ok(at).session_state["messages"][-1]["content"] == "Error: ollama down"


def test_deep_chat_streams_the_agent(wiki, monkeypatch):
    steps = [
        {"type": "thought", "content": "hmm"},
        {"type": "tool_call", "name": "raw_search", "args": {"query": "x"}},
        {"type": "tool_result", "name": "raw_search", "result": "hit"},
        {"type": "error", "content": "minor"},
        {
            "type": "final_answer",
            "content": "Deep answer",
            "sources": ["doc.md"],
            "wiki_sources": ["alpha.md"],
        },
    ]
    monkeypatch.setattr(chat_agent, "run_chat_agent", lambda q: iter(steps))
    at = _go(_app(), "Wiki Chat")
    at.segmented_control(key="chat_mode").set_value("Deep").run()
    at.chat_input[0].set_value("deep q").run()
    last = _ok(at).session_state["messages"][-1]
    assert last["content"] == "Deep answer"
    assert last["raw_sources"] == ["doc.md"]
    assert len(last["steps"]) == 5


def test_chat_new_chat_and_history(wiki):
    msgs = []
    for i in range(3):
        msgs += [
            {"role": "user", "content": f"q{i}"},
            {"role": "assistant", "content": f"a{i}", "question": f"q{i}", "interpreted": "iq"},
        ]
    at = _ok(_go(_app(messages=msgs), "Wiki Chat"))
    assert any("Conversation history (2 earlier turn(s))" in e.label for e in at.expander)
    at.button(key="new_chat").click().run()
    assert _ok(at).session_state["messages"] == []


# --- Research -----------------------------------------------------------------


def test_research_without_tavily_key_warns(wiki):
    at = _ok(_go(_app(), "Research"))
    assert "TAVILY_API_KEY not set" in _texts(at.warning)


@pytest.fixture
def tavily(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")


def _research_steps(report_path=None):
    return [
        {"type": "thought", "content": "plan", "label": "Plan"},
        {"type": "notice", "content": "fallback"},
        {"type": "tool_call", "name": "web_search", "args": {"q": "x"}, "note": "n"},
        {"type": "tool_call", "name": "ResearchComplete", "args": {}, "terminal": True},
        {"type": "tool_call", "name": "think", "args": {}},
        {
            "type": "tool_result",
            "name": "web_search",
            "result": "r",
            "note": "n",
            "sources": [{"url": "https://ex.org/a", "title": "A"}],
        },
        {"type": "error", "content": "transient"},
        {
            "type": "final_answer",
            "content": "Report body",
            "report_path": report_path,
            "sources": [{"url": "https://ex.org/b", "title": ""}],
            "metrics": {"tasks": 1, "searches": 2, "sources_checked": 3, "sources_cited": 1},
        },
    ]


def test_quick_research_runs_and_saves(wiki, tavily, monkeypatch):
    monkeypatch.setattr(agent, "run_research_agent", lambda q, ctx: iter(_research_steps()))
    saved = []
    monkeypatch.setattr(wiki_engine, "ingest", lambda text, name: saved.append(name))
    at = _go(_app(), "Research")
    at.text_input[0].set_value("What is new?")
    at.button(key="start_research_btn").click().run()
    _ok(at)
    assert at.session_state["last_research_answer"] == "Report body"
    assert [s.get("url") for s in at.session_state["research_sources"] if s.get("url")] == [
        "https://ex.org/a",
        "https://ex.org/b",
    ]
    at.button(key="save_research_btn").click().run()
    assert saved == ["Research: What is new?"]
    assert _ok(at).session_state["research_saved"] is True


def test_deep_research_reads_back_saved_report(wiki, tavily, monkeypatch):
    (db_context.wiki_dir() / "comparisons").mkdir(exist_ok=True)
    _page("comparisons/report-x.md", "Saved report", ptype="comparison")
    steps = _research_steps(report_path="comparisons/report-x.md")
    monkeypatch.setattr(deep_research_agent, "run_deep_research", lambda q, ctx: iter(steps))
    monkeypatch.setattr(
        wiki_engine,
        "ingest_as_source",
        lambda text, name: {"duplicate": False, "source_name": "r.md"},
    )
    at = _go(_app(), "Research")
    at.segmented_control(key="research_mode").set_value("Deep").run()
    at.text_input[0].set_value("deep?")
    at.button(key="start_research_btn").click().run()
    _ok(at)
    assert "Saved report" in at.session_state["last_research_answer"]
    at.checkbox(key="research_save_as_source").check().run()
    at.button(key="save_research_btn").click().run()
    assert _ok(at).session_state["research_saved_note"] == "Saved as source `r.md`."


def test_research_without_answer_shows_error(wiki, tavily, monkeypatch):
    monkeypatch.setattr(agent, "run_research_agent", lambda q, ctx: iter([]))
    at = _go(_app(), "Research")
    at.text_input[0].set_value("q")
    at.button(key="start_research_btn").click().run()
    assert "ended without producing a result" in _texts(_ok(at).error)


def test_research_requires_a_question(wiki, tavily):
    at = _go(_app(), "Research")
    at.button(key="start_research_btn").click().run()
    assert "Enter a research question first." in _texts(_ok(at).warning)


def test_research_follow_up_and_reset(wiki, tavily, monkeypatch):
    monkeypatch.setattr(agent, "run_research_agent", lambda q, ctx: iter(_research_steps()))
    monkeypatch.setattr(wiki_engine, "condense_followup", lambda q, a, f: "standalone")
    at = _go(_app(), "Research")
    at.text_input[0].set_value("first")
    at.button(key="start_research_btn").click().run()
    at.text_input(key="research_followup_input").set_value("more?")
    at.button(key="research_followup_go").click().run()
    _ok(at)
    assert at.session_state["last_research_interpreted"] == "standalone"
    assert len(at.session_state["research_history"]) == 2
    at.button(key="new_research").click().run()
    assert "research_history" not in _ok(at).session_state


# --- Maintenance --------------------------------------------------------------


def _maint(at: AppTest, section: str) -> AppTest:
    at.run()
    at.button(key="maint_nav_btn").click().run()
    at.segmented_control(key="maint_view").set_value(section).run()
    return _ok(at)


def test_maintenance_search_index_rebuild(wiki):
    (db_context.index_dir() / "chunks.sqlite").unlink()
    at = _maint(_app(), "Search index")
    assert "No index for this database." in _texts(at.warning)
    at.button(key="rebuild_index_btn").click().run()
    assert not _ok(at).warning
    at.button(key="back_to_wiki").click().run()
    assert _ok(at).session_state["nav_maintenance"] is False


def test_maintenance_link_health_and_log(wiki):
    at = _maint(_app(), "Link graph health")
    assert "orphan" in _texts(at.warning)
    at.segmented_control(key="maint_view").set_value("Activity log").run()
    assert _ok(at).code


def test_maintenance_lint(wiki, monkeypatch):
    monkeypatch.setattr(wiki_engine, "lint", lambda: "## Lint report")
    at = _maint(_app(), "Lint")
    at.button(key="run_lint_btn").click().run()
    assert any(m.value == "## Lint report" for m in _ok(at).markdown)


def test_maintenance_delete_source(wiki):
    import dedup

    dedup.register_file(b"doc", "doc.md")
    at = _maint(_app(), "Delete source")
    at.checkbox[0].check().run()
    at.button(key="delete_source_btn").click().run()
    assert dedup.list_sources() == []


def test_maintenance_page_language(wiki, monkeypatch):
    runs = []
    monkeypatch.setattr(
        wiki_engine,
        "normalize_pages",
        lambda dry_run=True: (
            runs.append(dry_run)
            or {"alpha.md": {"lang": "de", "foreign_lines": 2, "references": True}}
        ),
    )
    at = _maint(_app(), "Page language")
    at.button(key="normalize_scan_btn").click().run()
    at.button(key="normalize_run_btn").click().run()
    assert runs == [True, False]
    assert "Updated 1 pages." in _texts(_ok(at).success)


def test_maintenance_admin_creates_database_and_user(wiki):
    at = _maint(_app(), "Admin")
    form_inputs = [t for t in at.text_input if t.label.startswith("New database name")]
    form_inputs[0].set_value("Fresh")
    at.button[[b.label for b in at.button].index("Create database")].click().run()
    assert "Fresh" in db_context.list_dbs()
    user_in = next(t for t in _ok(at).text_input if t.label == "Username")
    pw_in = next(t for t in at.text_input if t.label == "Password")
    user_in.set_value("newbie")
    pw_in.set_value("pw")
    at.button[[b.label for b in at.button].index("Add user")].click().run()
    assert "newbie" in [u["username"] for u in auth.list_users()]
    at.button(key="usave_newbie").click().run()
    at.button(key="udel_newbie").click().run()
    assert "newbie" not in [u["username"] for u in auth.list_users()]


# --- Maintenance → Ontology ------------------------------------------------------------


def test_ontology_section_without_ontology_offers_create(wiki):
    import ontology_store

    at = _maint(_app(), "Ontology")
    assert "No ontology for this database." in _texts(at.info)
    at.button(key="onto_create").click().run()
    assert ontology_store.exists()
    assert "Revision 1" in _texts(_ok(at).markdown)


def _uploaded(at: AppTest, text: str, name: str = "edited.yaml") -> AppTest:
    at.segmented_control(key="onto_view").set_value("Import").run()
    at.file_uploader[0].set_value((name, text.encode(), "application/x-yaml")).run()
    return _ok(at)


def test_ontology_reimport_of_unchanged_file_changes_nothing(wiki):
    import ontology_store

    at = _maint(_app(), "Ontology")
    at.button(key="onto_create").click().run()
    at = _uploaded(at, ontology_store.export_text(ADMIN))
    assert "nothing changed" in _texts(at.info)
    assert len(ontology_store.history()) == 1


def test_ontology_import_preview_and_apply(wiki):
    import yaml

    import dedup
    import ontology_store

    dedup.register_file(b"typed", "typed.md")
    at = _maint(_app(), "Ontology")
    at.button(key="onto_create").click().run()
    doc = yaml.safe_load(ontology_store.export_text(ADMIN))
    doc["facts"] = {"sources": {"typed.md": {"class": "report"}}}
    at = _uploaded(at, yaml.safe_dump(doc))
    assert not at.error, [e.value for e in at.error]
    at.button(key="onto_apply").click().run()
    assert [r["seq"] for r in ontology_store.history()] == [1, 2]
    assert "Applied revision 2" in _texts(_ok(at).success)
    at.segmented_control(key="onto_view").set_value("Overview").run()
    assert "edited.yaml" in _texts(_ok(at).markdown)


def test_ontology_views_render_and_restore_makes_a_new_revision(wiki):
    import yaml

    import dedup
    import ontology_store

    dedup.register_file(b"typed", "typed.md")
    at = _maint(_app(), "Ontology")
    at.button(key="onto_create").click().run()
    doc = yaml.safe_load(ontology_store.export_text(ADMIN))
    doc["facts"] = {
        "sources": {"typed.md": {"class": "report", "work": "w-typed"}},
        "works": {"w-typed": {"class": "report", "aliases": ["Typed"]}},
    }
    at = _uploaded(at, yaml.safe_dump(doc))
    at.button(key="onto_apply").click().run()
    for view in ("Overview", "Facts", "Classes"):
        at.segmented_control(key="onto_view").set_value(view).run()
        _ok(at)
    assert "`report` · 2 fact(s)" in _texts(at.markdown)
    at.segmented_control(key="onto_view").set_value("History").run()
    at.selectbox(key="onto_hist_rev").set_value(1).run()
    at.checkbox(key="onto_restore_ok").check().run()
    at.button(key="onto_restore").click().run()
    assert [r["via"] for r in ontology_store.history()] == ["create", "import", "restore"]
    assert ontology_store.current_state()["facts"] == {}
    assert "Applied revision 3" in _texts(_ok(at).success)


def _legal_ontology() -> None:
    import ontology_store

    plan = ontology_store.prepare_state({"schema": {"modules": ["core", "legal-de"]}})
    wiki_engine.apply_ontology(plan, user=ADMIN, via="create")


def test_upload_into_an_ontology_db_records_detected_facts(wiki, ingest_stub):
    import ontology_store

    _legal_ontology()
    head = (Path(APP).parents[1] / "bench" / "ontology_detect" / "strlschv_2018.md").read_bytes()
    at = _app().run()
    at.file_uploader[0].set_value(("strlschv.md", head, "text/markdown")).run()
    assert "Class and work are detected" in _texts(_ok(at).caption)
    _click_label(at, "Ingest 1 file(s)")
    facts = ontology_store.source_facts("strlschv.md")
    assert (facts["class"], facts["work"]) == ("ordinance", "de-strlschv-2018")
    assert [r["via"] for r in ontology_store.history()] == ["create", "ingest"]


def test_upload_without_ontology_shows_no_ontology_columns(wiki, ingest_stub):
    at = _app().run()
    at.file_uploader[0].set_value(("notes.md", b"# Notes", "text/markdown")).run()
    assert "Class and work are detected" not in _texts(_ok(at).caption)


def test_ontology_proposals_can_be_confirmed(wiki):
    import dedup
    import ontology
    import ontology_store

    _legal_ontology()
    dedup.register_file(b"note", "note.md")
    proposal = ontology.assertion(
        "src:note.md", "class", "report", by="llm", status="proposed", evidence="A quote."
    )
    ontology_store.append_rows([proposal])
    at = _maint(_app(), "Ontology")
    assert "1 open proposal(s)" in _texts(at.markdown)
    at.segmented_control(key="onto_view").set_value("Proposals").run()
    [row] = ontology_store.proposals()
    at.button(key=f"onto_ok_{row['id']}").click().run()
    assert ontology_store.source_facts("note.md") == {"class": "report"}
    assert "Confirmed — revision 2." in _texts(_ok(at).success)


def test_explorer_search_names_the_ontology_match(wiki):
    import ontology
    import ontology_store

    _legal_ontology()
    ontology_store.append_rows(
        [
            ontology.assertion("src:doc.md", "work", "w-alpha", by="rule"),
            ontology.assertion("work:w-alpha", "aliases", "Alpha", by="rule"),
        ]
    )
    at = _go(_app(), "Wiki Explorer")
    at.segmented_control(key="explorer_view").set_value("Tree").run()
    at.text_input(key="explorer_nav_search").set_value("Alpha").run()
    assert "Ontology — “Alpha” → `w-alpha`" in _texts(_ok(at).caption)


def test_explorer_search_without_ontology_has_no_ontology_line(wiki):
    at = _go(_app(), "Wiki Explorer")
    at.segmented_control(key="explorer_view").set_value("Tree").run()
    at.text_input(key="explorer_nav_search").set_value("Alpha").run()
    assert "Ontology —" not in _texts(_ok(at).caption)


def test_deep_chat_shows_the_ontology_frame_and_why_line(wiki, monkeypatch):
    frame = {"matched": ["StrlSchV"], "works": ["w"], "classes": [], "sources": ["doc.md"]}
    steps = [
        {"type": "ontology", "content": "Ontology frame (built by code …)"},
        {"type": "final_answer", "content": "Deep answer", "sources": ["doc.md"]},
    ]
    monkeypatch.setattr(chat_agent, "run_chat_agent", lambda q: iter(steps))
    audit = {"tau": None, "kept": [], "below_tau": [], "over_cap": [], "ontology": [frame]}
    monkeypatch.setattr(tools, "current_run_audit", lambda db=None: audit)
    at = _go(_app(), "Wiki Chat")
    at.segmented_control(key="chat_mode").set_value("Deep").run()
    at.chat_input[0].set_value("deep q").run()
    assert "Ontology — “StrlSchV” → `w`; 1 source(s) favoured" in _texts(_ok(at).markdown)
    assert any(e.label == "Ontology frame" for e in at.expander)
