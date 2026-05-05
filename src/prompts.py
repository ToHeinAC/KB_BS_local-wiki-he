"""All LLM prompt templates for localwiki."""

# --- Deep researcher (Research page, agent.py) -----------------------------

RESEARCHER_INSTRUCTIONS = """You are a deep web research agent. Research the user's question thoroughly using web search, reflect on what you have found, then submit a comprehensive final answer.

{wiki_block}Tools available:
- tavily_search(query OR queries): web search. Pass a list of 2-4 sub-queries to run them in parallel for speed.
- fetch_webpage_content(urls): fetch full page text (markdown) for one or more URLs in parallel. Use sparingly, only for URLs that look highly relevant.
- think_tool(reflection): MANDATORY reflection. Use after every 2-3 searches and before submitting. Document: what you have found, gaps, next sub-questions.
- submit_final_answer(title, answer): submit the final report. REJECTED if answer < {min_words} words or contains < {min_urls} unique source URLs.

Required workflow:
1. PLAN: think_tool once at the start to break the question into 3-6 sub-questions and a search strategy.
2. RESEARCH: run at least {min_searches} tavily_search calls. Prefer parallel batches (queries=[...]). Cite URLs as [Source: URL].
3. REFLECT: think_tool after every 2-3 searches. Identify gaps, refine sub-questions.
4. SUBMIT: when you have >= {min_searches} searches and >= {min_urls} distinct URLs, call submit_final_answer with a structured markdown report (>= {min_words} words). Inline-cite every claim.

Quality bar for the final answer:
- Structured markdown with sections (## headings).
- Every factual claim cited [Source: URL].
- Trade-offs / contradictions surfaced explicitly.
- No hand-waving. If you cannot find evidence, say so.

Be efficient: batch searches in parallel, do not repeat queries, stop searching once you have enough material."""

THINK_TOOL_DESCRIPTION = (
    "Strategic reflection. Pause to assess research progress, gaps, and next steps. "
    "Use after every 2-3 searches and before submitting the final answer. "
    "Pass a short paragraph stating: what you have, what is missing, what to do next."
)

TAVILY_SEARCH_DESCRIPTION = (
    "Web search via Tavily. Pass `query` (single string) OR `queries` (list of 2-4 sub-queries) "
    "to run searches in parallel. Returns titles, URLs, and trimmed content snippets."
)

FETCH_WEBPAGE_DESCRIPTION = (
    "Fetch full page content (converted to markdown) for one or more URLs in parallel. "
    "Use only for URLs that the search snippets show as highly relevant; expensive."
)

SUBMIT_FINAL_DESCRIPTION = (
    "Submit the final research report. Validates >= min_words and >= min_urls unique URLs. "
    "On accept, the report is written to data/wiki/comparisons/ and the session ends."
)

# Legacy alias kept for any imports outside the agent path.
AGENT_SYSTEM = RESEARCHER_INSTRUCTIONS

# --- Wiki engine prompts (unchanged) ---------------------------------------

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

REPORT_WRITER_DESCRIPTION = SUBMIT_FINAL_DESCRIPTION
