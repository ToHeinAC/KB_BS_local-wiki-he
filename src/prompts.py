"""All LLM prompt templates for localwiki."""

AGENT_SYSTEM = """You are a research agent with access to web search. Research the question thoroughly and produce a structured report.

{wiki_block}Tools available:
- tavily_search: search the web for information
- report_writer: save the final report (call ONLY when all research is done)

Workflow: break into sub-questions → search → reflect on results → refine if needed → when you have enough information call report_writer with a complete markdown report.
Cite sources as [Source: URL]. Max searches: 6. Be efficient."""

INGEST_PROMPT = """You are ingesting a new source document into the wiki.

Source name: {source_name}

{meta_block}Current wiki index:
{index_text}

Source text (may be truncated):
{text}

Instructions:
1. Create a source-summary page for this document (filename: summary-{summary_slug}.md).
2. Create or update concept/entity pages for key topics found in the source.
3. Note any contradictions with existing wiki content.
4. Output each page in this exact format:

=== filename.md ===
---
title: "Title"
type: source-summary | concept | entity
sources: ["{source_name}"]
related: []
created: "{date}"
updated: "{date}"
confidence: high | medium | low{example_extra}
---

Page content here.

=== END ===

List pages you would UPDATE (already in index): UPDATE: filename.md
List contradictions found: CONTRADICTION: <brief description>
"""

SELECT_PROMPT = """Wiki index:
{index_text}

User question: {question}

List up to 5 most relevant page filenames (one per line, filename only). If none are relevant, reply NONE."""

ANSWER_PROMPT = """Using only the wiki pages below, answer the user's question.
Cite pages inline as [page title].

Wiki pages:
{pages_text}

Question: {question}"""

LINT_PROMPT = """Review all wiki pages below for quality issues.

Report:
1. CONTRADICTIONS: pages with conflicting facts
2. ORPHANS: pages not linked from index or other pages
3. GAPS: important concepts mentioned but lacking their own page
4. STALE: claims that seem outdated or uncertain
5. SUGGESTIONS: 2-3 investigation ideas for future ingestion

Wiki pages:
{all_pages}"""

TAVILY_SEARCH_DESCRIPTION = (
    "Search the web for current information on a topic. "
    "Use to find facts, recent news, or information not in the knowledge base."
)

REPORT_WRITER_DESCRIPTION = (
    "Save a completed research report to the knowledge wiki. "
    "Call ONLY when you have finished all research and are ready to write the final report."
)
