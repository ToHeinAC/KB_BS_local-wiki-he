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

GENERATE_QUESTIONS_PROMPT = """For each chunk below, write 2–4 short natural-language questions that the chunk directly answers. Mix German and English when the chunk language allows. Each question must be self-contained (no pronouns referring to other chunks).

Return STRICT JSON (no prose, no fences). The output must be a JSON array where each element has:
  {{"chunk_id": "<id given below>", "questions": ["<q1>", "<q2>", ...]}}

Keep questions tight (under 100 chars). No multi-part questions. Skip chunks that are purely structural (tables of contents, fußnoten); for those return an empty `questions` array.

Chunks:
{chunks_block}"""

EXTRACT_TERMS_PROMPT = """You are extracting retrieval-helpful structured data from one source document.

Return STRICT JSON (no prose, no markdown fences) with exactly these keys:

{{
  "aliases":  [{{"canonical": "<full term>", "variants": ["<alt spellings, EN/DE, paraphrases>"]}}],
  "acronyms": [{{"acronym": "<short>", "expansion": "<full form>"}}],
  "terms":    [{{"term": "<defined term>", "anchor": "<section/§ where defined>", "short_definition": "<<=160 chars>"}}],
  "facts":    [{{"kind": "<short slug>", "subject": "<thing>", "value": <number>, "unit": "<unit>", "anchor": "<section/§>"}}]
}}

Rules:
- Output JSON only. No commentary. No code fences.
- Empty arrays are fine when nothing applies.
- aliases: cross-language and abbreviation links (e.g. "Strahlenschutzgesetz" ↔ "StrlSchG"; "clearance value" ↔ "Freigabewert").
- acronyms: only ones that are explicitly defined in the source text.
- terms: terms the document itself defines (Begriffsbestimmungen, Glossary, "X means Y"). Include the anchor.
- facts: numeric thresholds, limits, dates, amounts WITH a unit (Bq/g, EUR, %, years). Skip vague numbers.
- Keep the lists short and high-signal; 20 entries per list is more than enough.

Source name: {source_name}

Source text (may be a digest of larger documents):
{text}"""


# --- Deep chat agent (Chat page "Deep" mode, chat_agent.py) ---------------

CHAT_AGENT_SYSTEM = """You are a chat agent that answers user questions strictly from the original source documents in data/raw/. You never invent facts and never use the web.

{raw_block}Tools available:
- raw_search(query OR queries): full-text search over data/raw/. Pass 1-3 sub-queries in parallel. Cite hits as [Source: filename].
- raw_read(filenames, offset=0): read up to 8000 chars from one or more original files. For long files, paginate: the result footer tells you the next offset.
- think_tool(reflection): MANDATORY reflection. Three labelled sections required, see below.
- submit_chat_answer(answer, sources): submit the final answer. REJECTED if answer < {min_words} words or fewer than {min_sources} unique [Source: ...] citations.

Search strategy (critical):
- Use SINGLE keywords or short 2-word phrases. NEVER whole sentences.
- Search is **prefix-based**: query tokens match the first 6 chars of words in the file. So for German compound or inflected nouns use the STEM (e.g. `Rückstand`, not `Rückstände`; `Freigabe`, not `Freigaben`). The English stem still works for English docs.
- If a search returns "(no results)", do NOT just rephrase with synonyms. Either (a) try a single broader stem, or (b) `raw_read` the most likely file with `offset=` to scan deeper. Repeated negative searches waste iterations.

Pagination strategy:
- `raw_read` returns at most 8000 chars per call. The footer `[truncated; pass offset=N to continue]` tells you where to resume. Use this to scan long legal documents section by section.

Citations:
- Cite as `[Source: filename]` or, for distinct sections of the same long file, `[Source: filename §X]` / `[Source: filename #section]`. Section-suffixed citations count as DISTINCT sources for the {min_sources}-source gate, so a single long document can satisfy it via two sections — do NOT pad with unrelated files.

Required workflow:
1. PLAN: think_tool once at the start. Identify 1-3 sub-questions and an initial raw_search plan.
2. SEARCH FIRST: your very first non-think tool call MUST be raw_search with single-stem keywords.
3. TRIAGE: after each tool result, call think_tool with exactly these three sections:
     Have: <facts already grounded, with [Source: ...] tags>
     Gaps vs original question: <bullet list, each gap referencing the original question verbatim>
     Next: <which tool to call next and why; one of raw_read / raw_search / submit_chat_answer>
4. AUTONOMOUS EXPANSION: based on the gaps, raw_read with offset OR raw_search with a different stem. Reflect every 2-3 tool calls.
5. SUBMIT: when you have at least {min_searches} tool calls and at least {min_sources} unique sources (counting section suffixes), call submit_chat_answer with a concise markdown answer (>= {min_words} words). Inline-cite every factual claim.

Discipline:
- Stay focused. This is a chat answer, not a deep research report — be concise.
- Do not repeat the same query. Do not re-read the same file at the same offset.
- Stop once the gaps list is empty."""

RAW_SEARCH_DESCRIPTION = (
    "Tokenized full-text search over original source documents in data/raw/. "
    "Pass `query` (single string) OR `queries` (list of 1-3 sub-queries) — each query is split into "
    "whitespace tokens and matched as a 6-character PREFIX against the file body (so 'Rückstände' "
    "matches 'Rückstand'). Use SINGLE keywords or short 2-word phrases — never full sentences. "
    "Returns up to 3 excerpts per file ranked by how many query tokens hit. Cite results as "
    "[Source: filename] in the final answer. MUST be the first non-think tool call."
)

RAW_READ_DESCRIPTION = (
    "Read up to 8000 chars from one or more original files in data/raw/. Pass a list of filenames "
    "(e.g. ['StrlSchG.md']) and an optional `offset` (default 0) for byte-pagination of long documents. "
    "Result footer tells you the next offset to use. Filenames with section suffixes "
    "(e.g. 'StrlSchG.md §62') are stripped to the bare filename for lookup."
)

SUBMIT_CHAT_DESCRIPTION = (
    "Submit the final chat answer. Validates >= min_words and >= min_sources unique [Source: filename] "
    "citations. On accept, returns the answer to the UI (no file is written; the user saves manually)."
)
