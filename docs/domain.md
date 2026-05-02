---
name: domain.md
description: Project domain — what LocalWiki is, why Karpathy-style, and key design rationale
version: 1.0.0
author: Tobias Hein
---

# Domain

> Authoritative spec: [`PRD.md`](../PRD.md) §1 (Executive Summary) and §10 (Key Design Decisions & Rationale).

## What LocalWiki is

A fully local Python web app that implements Andrej Karpathy's *LLM Knowledge Bases* pattern. Users drop documents in; a local LLM (Ollama, default `gemma4:e4b`) compiles them into a self-maintained, interlinked Markdown wiki. Users can navigate the wiki, chat against it, and optionally challenge or enrich it through web research via a manual ReAct agent.

Replaces RAG-style vector search with a persistent, human-readable, git-trackable wiki. No vector DB. No embeddings. No cloud LLM. The only external network dependency is **Tavily**, used solely by the optional Research feature.

## Guiding principle

**Keep It Simple.** When two solutions deliver the requirement, the simpler one wins. Concretely (PRD §4.4): one file per module, no async, no database, no Docker, no configuration UI, `uv` for env + deps, no forced UI framework.

## Key design decisions (rationale digest)

| Decision | Rationale |
|---|---|
| `index.md` instead of vector DB | Karpathy pattern works at small/medium scale with zero infra. |
| `gemma4:e4b` via Ollama | Native tool calling; fully local. |
| Manual ReAct loop, no LangChain | Fewer deps, full transparency, easier debugging. |
| SHA-256 dedup | Deterministic, O(1), no false positives. |
| `SCHEMA.md` in every system prompt | Reproducible LLM behaviour across sessions. |
| Files over DB | Pages are human-readable and git-trackable. |
| NYT-style UI | Matches a document-centric, reading-heavy workflow. |
| `uv` env management | Reproducible, modern, locked deps, simple commands. |
| 100-test cap | Forces focus on high-signal coverage, keeps suite fast. |

Full table: PRD §10.

## Out of scope

- Cloud LLM APIs (OpenAI, Anthropic, etc.)
- Embeddings / vector retrieval
- LangChain / agent frameworks
- Multi-user, auth, permissions
- Hosted deployments (local only)
