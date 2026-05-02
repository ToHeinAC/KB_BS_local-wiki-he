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

Streamlit is **not required**. Implementer chooses Streamlit, FastAPI + frontend, NiceGUI, Reflex, or any Python-centric stack that meets the UX and the editorial style. PRD §3.9.

## Pages (primary navigation)

| Page | Purpose | PRD §§ |
|---|---|---|
| **Upload** | Drag-and-drop ingest with explicit dedup confirmation; show ingest summary (created / updated / contradictions). Never auto-ingest. | 3.9.2 |
| **Wiki Explorer** | Tree/document navigator, full-text search across pages, rendered Markdown viewer with metadata, optional graph view. | 3.9.3 |
| **Chat** | Chatbot using the wiki as context. Supports filing the answer as a wiki page, launching web research from a question, onboarding message when wiki is empty. | 3.9.4 |
| **Research** | Run the ReAct agent (max 8 iterations); show step-by-step progress; gate behind `TAVILY_API_KEY` with clear setup guidance; allow auto-saving the report. | 3.9.5 |
| **Maintenance** | Wiki stats, run lint/health check, recent activity log, guarded reset (with confirmation). | 3.9.6 |

## Top-bar / chrome

Logo + nav + live wiki stats (`N pages | N sources | last updated`) + Ollama connectivity indicator. PRD §3.9.1.

## Error states (UI surface)

Connectivity and config errors must be visible, not silent (PRD §4.2): Ollama down → offline indicator + `ollama serve` hint; missing model → `ollama pull gemma4:e4b`; missing `TAVILY_API_KEY` → Research page disabled with setup steps; partial PDF extraction → `Partial extraction: N pages read`.
