# Deep chat and Quick research: answering level by level

Status: implemented 2026-10-30 (commits 3d2d54a … d05a55d, revised 1b6a004); first live bench below. Scope agreed with the user: Deep chat and Quick research
(not the web-only Deep research); the word floor is replaced by a coverage check, answers
stay detailed; StrlSchG/StrlSchV (public law) may be loaded for tests and the bench.

## Problem

Example question: "Wie können Rückstände entlassen werden?" Expected work order:

1. **Level 1 (core):** the top-ranked sections (§ 62 StrlSchG, § 29 StrlSchV), read in full.
2. **Level 2 (secondary):** the entities those sections use — defined terms (Rückstände →
   § 5 Abs. 32, Bauprodukte → § 5 Abs. 6, Exposition → § 2 Abs. 1 …) and the provisions
   that apply the core section (§ 29/§ 30 StrlSchV cite § 62 StrlSchG).
3. **Level 3 (tertiary):** the terms inside the level-2 definitions (Materialien → § 5
   Abs. 22).

What the code did before this change (checked against the code and the pasted § 62 text):

- Only the model decided what to read; `_auto_read` opened one hit, after three turns.
- `refs.find_refs` follows explicit `§`/`Anlage` references only; defined terms were never
  resolved (one prompt rule, for "Ist X ein Y?" questions only). Reverse references (the
  regulation citing the act) were not followed at all.
- The evidence ledger picks sentences by word overlap with the question: on § 62 it kept
  the exception "Anmeldung entbehrlich" and dropped the 1 mSv criterion of Abs. 3.
- The fixed word floor (500) made E4B pad: in `ideas/test_deepchat.md` it read DIN
  "Türen und Fenster" after "390 words, minimum is 500"; then one answer was rejected six
  times for an unread § 100 (~70 s) before the model read it.

## Design (all in code; no extra LLM call)

| Step | Where | What |
|---|---|---|
| Unread § auto-read | `chat_agent._code_turn` | A rejection naming unread sections is followed by code's own `raw_read` of them. |
| Definition register | `src/definitions.py` (pure) | Parses `(N) Begriff: …` in "Begriff…" sections and `(N) Begriff ist/sind …` where the heading names the term; matches terms in a text by inflection-tolerant word prefixes. |
| Definition reads | `tools.raw_read` | `file § 5 Abs. 32` serves just that definition; the gate counts that tag as read. |
| Reverse references | `tools` | Sections of other in-scope laws that cite a core section. |
| Level plan | `chat_agent._levels` | After the pre-flight searches: read the top-2 sections (level 1), then ≤ 6 definitions + ≤ 2 citing sections (level 2), then ≤ 4 definitions used inside level 2 (level 3). |
| Level ledger | `evidence`, `run_memory` | Level-1 sections keep the first sentence of every paragraph; quotes carry their level; the ledger prompt writes core rule → conditions and terms → further provisions. |
| Coverage gate | `tools._submit_chat_impl` | Replaces the word floor: one level-1 section and the definitions of the terms the question names must be cited; a once-only terse check keeps answers detailed. (First version forced both top sections and 3 definitions — derived from the one example, revised the same day.) |
| Quick research | `agent.py` | Same level reads before the first turn; same coverage check in place of `RESEARCH_MIN_WORDS`. |

Time budget: every step above is code (lexical lookups, regex), well under a second per
run; it should save model turns. Verified with `scripts/bench_deep_chat.py` (q1, q5, q7)
against the GPU-box numbers (76 / 106 / 78 s).

## Bench 2026-10-30 (gemma4:e4b, pinned daemon, scratch KI: StrlSchG, StrlSchV, KrWG, Rust Book ch. 4.1)

| Set | Runs | Accepted (ledger/submit) | Best effort | Gold read | Mean time |
|---|---|---|---|---|---|
| StrlSch (`fixture_deep_chat_KI.json`) | 7 | 3 | 4 | 9/10 | 89 s (q1 116, q5 76, q7 112; before 76 / 106 / 78) |
| General (`fixture_deep_chat_general.json`) | 7 | 2 | 5 | 7/7 | 78 s |

Findings (the second set shows what one corpus hid):

1. **Markdown section citations are not counted.** Code's own tags for heading sections
   (`[Source: rust-ownership.md Ownership Rules]`) do not match `tools._RAW_CITE_RE` (needs
   `§`, `#` or "Kapitel/Abschnitt"), so every Rust answer "cites 0 sources" (g5–g7). Predates
   the levels; hits every corpus without § numbering.
2. **The ledger writer drops the required definition** (q1, q7, g2–g4): the ledger holds
   `§ 5 Abs. 32`, the answer leaves it out, the gate rejects it, the run ends best effort.
3. **Markdown evidence is thin:** the ledger keeps "First, let's take a look at the ownership
   rules." but not the bullet list that follows, and keeps `{{#rustdoc_include …}}` lines.
4. **The 3-search minimum rejects almost every first submit** (pre-flight counts 2 searches).
5. A question naming four defined terms (g3) is required to cite all four.
