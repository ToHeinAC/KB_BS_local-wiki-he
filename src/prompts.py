"""All LLM prompt templates for localwiki."""

# --- Deep researcher (Research page, agent.py) -----------------------------

RESEARCHER_INSTRUCTIONS = """You are a deep research agent. Always start at the local wiki, then decide autonomously which further tools to use. After every tool result, explicitly track gaps versus the original query and stay on the main research line.

{wiki_block}Tools available:
- wiki_search(query OR queries): full-text search over the local wiki (data/wiki/). Pass 2-4 sub-queries in parallel for speed. Cite hits as [Wiki: filename.md].
- wiki_read(filenames): read full body of one or more wiki pages in parallel. Use after wiki_search surfaced a promising page.
- tavily_search(query OR queries): web search. Use ONLY for gaps the wiki cannot fill. Parallel sub-queries supported. Cite as [Source: URL].
- fetch_webpage_content(urls): fetch full page markdown in parallel. Use sparingly, only for URLs the search snippets show as highly relevant.
- think_tool(reflection): MANDATORY reflection. Three labelled sections required, see below.
- submit_final_answer(title, answer): submit the final report. REJECTED if answer < {min_words} words or fewer than {min_urls} unique sources ([Wiki: ...] citations count alongside URLs).

Required workflow:
1. PLAN: think_tool once at the start. Break the original question into 3-6 sub-questions. Decide an initial wiki query plan.
2. WIKI FIRST: your very first non-think tool call MUST be wiki_search. Use a parallel batch (queries=[...]) covering the main sub-questions.
3. TRIAGE: after each tool result, call think_tool with exactly these three sections:
     Have: <facts already grounded, with [Wiki: ...] or [Source: ...] tags>
     Gaps vs original query: <bullet list, each gap referencing the original question verbatim>
     Next: <which tool to call next and why; one of wiki_read / tavily_search / fetch_webpage_content / submit_final_answer>
   If a thread is tangential to the original query, list it under an extra `Parked (out of scope):` bullet — do NOT research it.
4. AUTONOMOUS EXPANSION: based on the gaps, choose the right tool. Prefer wiki_read when a wiki hit looks promising. Use tavily_search only for gaps the wiki cannot fill. Repeat triage after every 2-3 tool calls.
5. SUBMIT: when you have at least {min_searches} tool calls (wiki + web combined) and at least {min_urls} unique sources, call submit_final_answer with a structured markdown report (>= {min_words} words). Inline-cite every factual claim.

Quality bar for the final answer:
- Structured markdown with ## headings.
- Every factual claim cited as [Wiki: filename.md] or [Source: URL].
- Trade-offs / contradictions surfaced explicitly.
- No hand-waving. If evidence is missing, say so and list it as a remaining gap.

Discipline:
- Stay on the main research line. Park tangents; never expand them.
- Do not repeat queries. Do not re-read pages.
- Stop searching once the gaps list is empty or only contains parked items."""

THINK_TOOL_DESCRIPTION = (
    "Strategic reflection. MUST be called after every 2-3 tool calls and before submitting. "
    "The reflection string MUST contain exactly three labelled sections:\n"
    "  Have: <facts grounded with [Wiki: ...] or [Source: ...] tags>\n"
    "  Gaps vs original query: <bullet list referencing the original question verbatim>\n"
    "  Next: <which tool to call next and why>\n"
    "Tangential threads must be listed under a 'Parked (out of scope):' bullet and not pursued."
)

WIKI_SEARCH_DESCRIPTION = (
    "Full-text search over the local wiki (data/wiki/). Pass `query` (single string) OR "
    "`queries` (list of 2-4 sub-queries) to search in parallel. Returns filename, title, "
    "and excerpt for each hit. Cite hits in the final report as [Wiki: filename.md]. "
    "This MUST be the first non-think tool call in every research run."
)

WIKI_READ_DESCRIPTION = (
    "Read full body of one or more wiki pages in parallel. Pass a list of filenames "
    "(e.g. ['siemens-ag.md']) surfaced by wiki_search. Use to deepen a promising hit "
    "before deciding whether the wiki already covers a gap."
)

TAVILY_SEARCH_DESCRIPTION = (
    "Web search via Tavily. Use ONLY after wiki_search has shown the gap is not covered "
    "by the local wiki. Pass `query` (single string) OR `queries` (list of 2-4 sub-queries) "
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
{existing_block}
Source text (may be truncated):
{text}

Instructions:
1. Create a detailled source-summary representation page for this document (filename: summary-{summary_slug}.md). Never invent information. 
   Preserve relevant passages from chunk sources in detail. Copy relevant numbers, sizes, and references exactly as they appear in the original, never round or paraphrase. Format every citation as e.g. [{source_name}.md] using the source from the original doc.
2. Create or update concept/entity pages for key topics found in the source.
3. When updating an existing page (provided above as "Existing page content"), MERGE — preserve prior facts, integrate new information, refine wording. Never strip nuance from a prior version.
4. Populate `related` frontmatter with the filenames of conceptually linked pages you saw in the index.
5. Note any contradictions with existing wiki content.
6. Output each page in this exact format:

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

SELECT_AFFECTED_PROMPT = """A new source is being ingested. Identify which existing wiki pages it most likely updates.

Source name: {source_name}

Wiki index (filename — description):
{index_text}

Source excerpt:
{excerpt}

Reply with up to 5 affected filenames, one per line. Filename only (e.g. siemens-ag.md). Reply NONE if no existing page is affected."""

RESOLVE_CONTRADICTION_PROMPT = """Resolve a contradiction in the wiki.

Contradiction: {description}

Affected pages:
{pages_text}

User guidance (may be empty): {user_guidance}

Rewrite each affected page to resolve the contradiction. Preserve all unrelated content. Use the same `=== filename.md === ... === END ===` block format as ingest. Update `confidence` and `updated` frontmatter accordingly."""

FILE_ANSWER_PROMPT = """Format the following Q&A as a wiki insight page. Output ONLY the page body (no frontmatter — it will be added programmatically). Use markdown headings; preserve any [page title] citations from the answer verbatim.

Question: {question}

Answer:
{answer}"""

SELECT_PROMPT = """Wiki index:
{index_text}

User question: {question}

List up to 5 most relevant page filenames (one per line, filename only). If none are relevant, reply NONE."""

ANSWER_PROMPT = """Using only the wiki pages below, answer the user's question.
Wiki pages are summarised knowledge from data/wiki/; their original sources live in data/raw/.
Cite wiki pages inline as [page title].

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
