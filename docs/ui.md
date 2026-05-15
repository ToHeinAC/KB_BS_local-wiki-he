---
name: ui.md
description: comprehensive documentation of the project´s user interfaces (graphical, etc.)
version: 1.0.0
author: Tobias Hein
---

# UI

> Authoritative spec: [`PRD.md`](../PRD.md) §2.4 (GUI Design Direction) and §3.9 (Web Application).

## Visual style — New York Times editorial

The UI must feel like a premium digital publication, not a SaaS dashboard. Concretely (PRD §2.4):

- **Typography first.** Serif-forward or editorial pairing for headings, clean legible body font, strong hierarchy.
- **Generous whitespace**, narrow readable content widths, subtle dividers.
- **Restrained monochrome palette.** Emphasis comes from spacing/scale/rules — not bright accents or dense card grids.
- **No SaaS aesthetics.** No neon, no overly rounded chrome, no playful tone.
- **Documents/citations/research read like articles.** Whatever framework is chosen must be re-styled to this language; the framework's default look is not acceptable.

## Framework choice

**Streamlit** is the chosen UI framework. Port is fixed at **8520** (8511 reserved on this host). Run with:

```bash
uv run streamlit run app.py --server.port 8520
```

## Pages (primary navigation)

| Page | Purpose | PRD §§ |
|---|---|---|
| **Upload** | Drag-and-drop ingest with explicit dedup confirmation. Before ingesting, shows an optional metadata form (fields from `templates/insert.md`: name, fullname, description, effective as of, part of) to make LLM output more precise. Shows ingest summary (created / updated / contradictions). Never auto-ingest. | 3.9.2 |
| **Wiki Explorer** | Tree-by-`type` navigator (Concepts / Entities / Source Summaries / Comparisons / Other) when search is empty; full-text search across titles, filenames, and page bodies (excerpt highlighted) when active. Rendered Markdown viewer: body rendered clean (no YAML frontmatter); collapsible **Sources** expander at the bottom lists original `data/raw/` documents and related wiki pages. Graph view: interactive vis.js network rendered inline (no pyvis dependency); two toggles — **Node names** (shows page title, up to 5 words) and **Edge themes** (shows first 3 words of linked page's title as edge label). Orphan count shown below graph. | 3.9.3 |
| **Chat** | Chatbot with a **Fast | Deep** mode toggle. **Fast** (default): one-shot 2-stage RAG over wiki pages (`wiki_engine.query_with_sources`); answer appears with a Sources panel listing the wiki pages and original `data/raw/` documents used. **Deep**: agentic LangGraph loop over `data/raw/` originals only (`chat_agent.run_chat_agent`) — no web, halved quality gates vs Research for ~2× speed, paginated reads of long docs, section-suffixed citations (e.g. `[Source: StrlSchG.md §62]`); each Deep answer renders an Agent trace expander with the step-by-step tool feed. Both modes share the same "Save answer to wiki" button (`insights/insight-*.md`). | 3.9.4 |
| **Research** | Run the ReAct agent (max 8 iterations); show step-by-step progress; gate behind `TAVILY_API_KEY`. Optional wiki context injection; auto-save final report to wiki. | 3.9.5 |
| **Maintenance** | Wiki stats, run lint/health check, recent activity log, guarded reset (with confirmation). | 3.9.6 |

## Top-bar / chrome

Logo + nav + live wiki stats (`N pages | N sources | last updated`) + Ollama connectivity indicator. PRD §3.9.1.

## Error states (UI surface)

Connectivity and config errors must be visible, not silent (PRD §4.2): Ollama down → offline indicator + `ollama serve` hint; missing model → `ollama pull gemma4:e4b`; missing `TAVILY_API_KEY` → Research page disabled with setup steps; partial PDF extraction → `Partial extraction: N pages read`.
