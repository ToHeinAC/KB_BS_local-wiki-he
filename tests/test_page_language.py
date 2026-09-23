"""Page-language pinning: a page keeps the language it was created in.

Covers umlaut-safe slugs, clean source references, the `lang` stamp, the
cross-language merge (translate the new lines, protect original terms, labelled
fallback), language-safe Reconcile/polish, the normalize maintenance pass, and
cross-language routing (aliases + bge-m3 titles).
"""

import frontmatter
import pytest

import ollama_client
import wiki_engine as w


def _fake_llm(monkeypatch, ingest_response="", translation=""):
    """Route `ollama_client.generate` by prompt: translation vs everything else."""
    calls = []

    def gen(system, prompt, temperature=0.3, model_id=None):
        calls.append((system, prompt))
        if prompt.startswith("Translate"):
            return translation(prompt) if callable(translation) else translation
        return ingest_response

    monkeypatch.setattr(ollama_client, "generate", gen)
    return calls


@pytest.fixture(autouse=True)
def _no_embed(monkeypatch):
    def boom(texts, model_id):
        raise RuntimeError("no embed in tests")
    monkeypatch.setattr(ollama_client, "embed", boom)


def _meta(path):
    return frontmatter.load(str(path)).metadata


# --- step 1: umlaut-safe slugs ------------------------------------------------

def test_title_to_filename_folds_umlauts():
    assert w._title_to_filename("Überwachung der Äquivalentdosis") == \
        "ueberwachung-der-aequivalentdosis.md"


def test_slug_tokens_fold_umlauts():
    toks = w._canonical_slug_tokens("Überwachung")
    assert any(t.startswith("ueberwach") for t in toks)


def test_summary_slug_folds_umlauts(wiki_dir):
    ctx = w.ingest_begin("Text.", "Harness Engineering für KI.md")
    assert ctx["summary_slug"] == "harness-engineering-fuer-ki"


def test_summary_slug_reuses_legacy_page(wiki_dir):
    (wiki_dir / "summary-harness-engineering-f-r-ki.md").write_text("---\ntitle: X\n---\nold\n")
    ctx = w.ingest_begin("Text.", "Harness Engineering für KI.md")
    assert ctx["summary_slug"] == "harness-engineering-f-r-ki"


# --- step 9: clean source references ------------------------------------------

_TEIL_RESPONSE = (
    "=== concept-alpha.md ===\n---\ntitle: Alpha\ntype: concept\n"
    'sources: ["doc.md [Teil 1/2]"]\n---\n'
    "Alpha is the first letter [doc.md [Teil 1/2].md] and also [doc.md.md].\n=== END ==="
)


def test_ingest_prompt_cites_clean_source_name(wiki_dir, monkeypatch):
    calls = _fake_llm(monkeypatch, _TEIL_RESPONSE)
    ctx = w.ingest_begin("Alpha text.", "doc.md")
    w.ingest_piece(ctx, "Alpha text.", 0, 2)
    prompt = calls[0][1]
    assert "[doc.md]" in prompt and "part 1 of 2" in prompt
    assert "[Teil" not in prompt and ".md.md" not in prompt


def test_ingest_cleans_teil_and_double_md_refs(wiki_dir, monkeypatch):
    _fake_llm(monkeypatch, _TEIL_RESPONSE)
    w.ingest("Alpha text.", "doc.md")
    page = (wiki_dir / "concept-alpha.md").read_text()
    assert _meta(wiki_dir / "concept-alpha.md")["sources"] == ["doc.md"]
    assert "[Teil" not in page and ".md.md" not in page
    assert "[doc.md]" in page


# --- step 4: `lang` stamped at creation ---------------------------------------

def _page(fname, title, body, lang=None):
    lang_line = f"lang: {lang}\n" if lang else ""
    return (f"=== {fname} ===\n---\ntitle: {title}\ntype: concept\n{lang_line}---\n"
            f"{body}\n=== END ===")


def test_new_page_stamped_with_its_language(wiki_dir, monkeypatch):
    de = _page("concept-dosis.md", "Dosis", "Die Dosis ist die Energie, die mit dem Gewebe wirkt.")
    en = _page("concept-dose.md", "Dose", "The dose is the energy that is absorbed by the tissue.")
    _fake_llm(monkeypatch, de + "\n" + en)
    w.ingest("Die Quelle beschreibt die Dosis und die Wirkung.", "src.md")
    assert _meta(wiki_dir / "concept-dosis.md")["lang"] == "de"
    assert _meta(wiki_dir / "concept-dose.md")["lang"] == "en"


# --- step 5: cross-language merge ---------------------------------------------

_EN_ONTOLOGY = (
    "---\ntitle: Ontology\ntype: concept\nlang: en\nsources: [\"a.md\"]\n---\n"
    "## Key facts\n- An ontology is a formal specification of the domain.\n\n"
    "The ontology gives the agent a structure and it is used for the inference.\n"
)
_DE_CONTRIBUTION = _page(
    "concept-ontology.md", "Ontologie",
    "## Key facts\n- Eine Ontologie ist eine formale Spezifikation und sie ist die Grundlage.\n\n"
    "Sie liefert die **Begrenzungen** für den Agenten mit 20 mSv [doc.md].",
)
_EN_TRANSLATION = (
    "## Key facts\n- An ontology is a formal specification and it is the foundation.\n\n"
    "It provides the **constraints** (*Begrenzungen*) for the agent with 20 mSv [doc.md]."
)
_DE_SOURCE = "Eine deutsche Quelle über die Ontologie und den Agenten."


def test_cross_language_merge_translates_new_lines(wiki_dir, monkeypatch):
    (wiki_dir / "concept-ontology.md").write_text(_EN_ONTOLOGY)
    calls = _fake_llm(monkeypatch, _DE_CONTRIBUTION, _EN_TRANSLATION)
    w.ingest(_DE_SOURCE, "doc.md")
    page = (wiki_dir / "concept-ontology.md").read_text()
    meta = _meta(wiki_dir / "concept-ontology.md")
    assert "Sie liefert" not in page and "Eine Ontologie" not in page
    assert "It provides the **constraints** (*Begrenzungen*)" in page
    assert meta["lang"] == "en"
    assert meta["aliases"] == ["Ontologie"]  # titles only: aliases drive routing
    translate = [p for _, p in calls if p.startswith("Translate")]
    assert len(translate) == 1 and "Begrenzungen" in translate[0]
    assert "The ontology gives the agent" not in translate[0]  # only the new lines


def test_cross_language_merge_falls_back_to_labelled_quote(wiki_dir, monkeypatch):
    (wiki_dir / "concept-ontology.md").write_text(_EN_ONTOLOGY)
    dropped_number = _EN_TRANSLATION.replace("20 mSv", "some dose")
    _fake_llm(monkeypatch, _DE_CONTRIBUTION, dropped_number)
    w.ingest(_DE_SOURCE, "doc.md")
    page = (wiki_dir / "concept-ontology.md").read_text()
    assert "## Original (DE)" in page
    assert "> Sie liefert die **Begrenzungen** für den Agenten mit 20 mSv [doc.md]." in page
    assert "some dose" not in page


def test_same_language_merge_makes_no_translation_call(wiki_dir, monkeypatch):
    (wiki_dir / "concept-ontology.md").write_text(_EN_ONTOLOGY)
    en = _page("concept-ontology.md", "Ontology",
               "The ontology is also used for the checks of the constraints.")
    calls = _fake_llm(monkeypatch, en)
    w.ingest("An English source about the ontology and the agent.", "b.md")
    assert not [p for _, p in calls if p.startswith("Translate")]
    assert "used for the checks" in (wiki_dir / "concept-ontology.md").read_text()


def test_contradiction_note_follows_page_language():
    out = w._contradiction_check("Grenzwert 20 mSv", "Grenzwert 50 mSv", {}, {}, page_lang="de")
    assert any("widersprechen" in c for c in out)


# --- step 6: Reconcile / polish never switch a page's language ----------------

_DE_PAGE = ("---\ntitle: Grenzwert\ntype: concept\nlang: de\n---\n"
            "Der Grenzwert liegt bei 20 mSv pro Jahr und gilt für die Arbeitskräfte.\n")


def test_resolve_skips_rewrite_in_wrong_language(wiki_dir, monkeypatch):
    (wiki_dir / "a.md").write_text(_DE_PAGE)
    calls = _fake_llm(monkeypatch, "=== a.md ===\n---\ntitle: Limit\n---\n"
                      "The limit is 20 mSv per year and it applies to the workers.\n=== END ===")
    res = w.resolve_contradiction("20 vs 50 mSv", ["a.md"])
    assert res["updated"] == [] and res["skipped"] == ["a.md"]
    assert "Der Grenzwert" in (wiki_dir / "a.md").read_text()
    assert "SPRACHE" in calls[0][0]


def test_resolve_accepts_rewrite_in_page_language(wiki_dir, monkeypatch):
    (wiki_dir / "a.md").write_text(_DE_PAGE)
    _fake_llm(monkeypatch, "=== a.md ===\n---\ntitle: Grenzwert\n---\n"
              "Der Grenzwert liegt bei 20 mSv pro Jahr, das ist der gültige Wert.\n=== END ===")
    res = w.resolve_contradiction("20 vs 50 mSv", ["a.md"])
    assert res["updated"] == ["a.md"]
    assert _meta(wiki_dir / "a.md")["lang"] == "de"


def test_polish_rejects_language_drift(monkeypatch):
    _fake_llm(monkeypatch, "The limit is 20 mSv per year and it applies to the workers.")
    assert w._polish_page(_DE_PAGE) == _DE_PAGE


# --- step 7: normalize existing pages -----------------------------------------

_MIXED = (
    "---\ntitle: Ontology\ntype: concept\nsources:\n- a.md\n- x.md [Teil 1/2]\n---\n"
    "## Key facts\n- An ontology is a formal specification of the domain for the agents.\n"
    "- It models the entities and the relations of the domain.\n\n"
    "The ontology gives the agent a structure and it is used for the inference.\n\n"
    "- Eine Ontologie ist eine formale Spezifikation und sie ist die Grundlage für den Agenten.\n"
    "- Sie liefert die **Begrenzungen** und die Struktur für das System [x.md [Teil 1/2].md].\n\n"
    "## Definition und Funktion\n"
    "Eine Ontologie ist ein formales System zur Klassifizierung und Strukturierung von Wissen.\n"
)
_MIXED_TRANSLATION = (
    "- An ontology is a formal specification and it is the foundation for the agent.\n"
    "- It provides the **constraints** (*Begrenzungen*) and the structure for the system [x.md].\n\n"
    "## Definition and function\n"
    "An ontology is a formal system for classifying and structuring knowledge."
)


def test_normalize_dry_run_reports_without_writing(wiki_dir, monkeypatch):
    (wiki_dir / "concept-ontology.md").write_text(_MIXED)
    calls = _fake_llm(monkeypatch, translation=_MIXED_TRANSLATION)
    report = w.normalize_pages(dry_run=True)
    info = report["concept-ontology.md"]
    assert info["lang"] == "en" and info["references"] and info["foreign_lines"] >= 4
    assert (wiki_dir / "concept-ontology.md").read_text() == _MIXED
    assert calls == []


def test_normalize_translates_foreign_runs_in_place(wiki_dir, monkeypatch):
    (wiki_dir / "concept-ontology.md").write_text(_MIXED)
    _fake_llm(monkeypatch, translation=_MIXED_TRANSLATION)
    w.normalize_pages(dry_run=False)
    page = (wiki_dir / "concept-ontology.md").read_text()
    meta = _meta(wiki_dir / "concept-ontology.md")
    assert "Eine Ontologie" not in page and "## Definition and function" in page
    assert "[Teil" not in page and meta["sources"] == ["a.md", "x.md"]
    assert meta["lang"] == "en" and "aliases" not in meta
    assert "(*Begrenzungen*)" in page  # original term kept inline
    assert "The ontology gives the agent a structure" in page  # untouched


def test_translation_keeps_bullet_markers(wiki_dir, monkeypatch):
    (wiki_dir / "concept-ontology.md").write_text(_MIXED)
    no_bullets = _MIXED_TRANSLATION.replace("- An ontology", "An ontology").replace("- It provides", "It provides")
    _fake_llm(monkeypatch, translation=no_bullets)
    w.normalize_pages(dry_run=False)
    page = (wiki_dir / "concept-ontology.md").read_text()
    assert "- An ontology is a formal specification and it is the foundation" in page
    assert "- It provides the **constraints**" in page


def test_normalize_quotes_run_when_translation_fails(wiki_dir, monkeypatch):
    (wiki_dir / "concept-ontology.md").write_text(_MIXED)
    _fake_llm(monkeypatch, translation="")
    w.normalize_pages(dry_run=False)
    page = (wiki_dir / "concept-ontology.md").read_text()
    assert "> **Original (DE):**" in page
    assert "> - Eine Ontologie ist eine formale Spezifikation" in page


# --- step 8: cross-language routing -------------------------------------------

def _existing(wiki_dir, fname, title, body, lang, aliases=None):
    alias_line = f"aliases: {aliases}\n" if aliases else ""
    (wiki_dir / fname).write_text(
        f"---\ntitle: {title}\ntype: concept\nlang: {lang}\n{alias_line}---\n{body}\n")


def _content(title, body):
    return f"---\ntitle: {title}\ntype: concept\n---\n{body}\n"


_DE_BODY = "Die Ausführung wird dauerhaft gespeichert und sie ist für den Agenten wichtig."


def test_routes_by_alias(wiki_dir):
    _existing(wiki_dir, "concept-ontology.md", "Ontology",
              "The ontology is the model of the domain.", "en", '["Ontologie"]')
    ctx = {"registry": w._build_registry(), "lang": "de"}
    target = w._resolve_target(_content("Ontologie", _DE_BODY), "concept-ontologie.md", ctx)
    assert target == "concept-ontology.md"


def _fake_embed(monkeypatch, vecs):
    monkeypatch.setattr(ollama_client, "embed", lambda texts, model_id: [vecs[t] for t in texts])


def test_routes_cross_language_by_title_similarity(wiki_dir, monkeypatch):
    _existing(wiki_dir, "concept-durable-execution.md", "Durable Execution",
              "Durable execution persists the state of the workflow.", "en")
    _existing(wiki_dir, "concept-gpu.md", "GPU", "The GPU is the processor for the models.", "en")
    _fake_embed(monkeypatch, {"Dauerhafte Ausführung": [1.0, 0.0],
                              "Durable Execution": [0.95, 0.31], "GPU": [0.0, 1.0]})
    ctx = {"registry": w._build_registry(), "lang": "de"}
    target = w._resolve_target(_content("Dauerhafte Ausführung", _DE_BODY),
                               "concept-dauerhafte-ausfuehrung.md", ctx)
    assert target == "concept-durable-execution.md"


def test_no_cross_language_route_without_clear_winner(wiki_dir, monkeypatch):
    _existing(wiki_dir, "concept-a.md", "Durable Execution", "The state is persisted.", "en")
    _existing(wiki_dir, "concept-b.md", "Durable Storage", "The data is persisted.", "en")
    _fake_embed(monkeypatch, {"Dauerhafte Ausführung": [1.0, 0.0],
                              "Durable Execution": [0.95, 0.31], "Durable Storage": [0.93, 0.37]})
    ctx = {"registry": w._build_registry(), "lang": "de"}
    target = w._resolve_target(_content("Dauerhafte Ausführung", _DE_BODY), "concept-x.md", ctx)
    assert target == "concept-x.md"


def test_no_cross_language_route_when_embed_unavailable(wiki_dir):
    _existing(wiki_dir, "concept-durable-execution.md", "Durable Execution",
              "Durable execution persists the state of the workflow.", "en")
    ctx = {"registry": w._build_registry(), "lang": "de"}
    target = w._resolve_target(_content("Dauerhafte Ausführung", _DE_BODY), "concept-x.md", ctx)
    assert target == "concept-x.md"
