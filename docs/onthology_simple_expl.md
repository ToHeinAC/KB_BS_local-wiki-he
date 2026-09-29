# Ontology in the GUI: a beginner's guide

What a user can do with a database's ontology through the app's screens, explained
without jargon. Technical reference: [ontology.md](ontology.md).

## First: what is an "ontology" here?

Think of your database as a library. The ontology is its **catalogue system**: a filing
card for each document saying what kind of document it is and how it relates to the
others.

Without it, the app only sees text. With it, the app also knows things like:
- "This file is a **Rechtsverordnung** (an ordinance, a type of regulation)."
- "This file is the **2018 version of the StrlSchV**. An older 2001 version exists too."
- "This ordinance is **based on** that law" or "it **incorporates** DIN 6812."

A database only has an ontology if someone created one. Without one, every screen
behaves exactly as it did before.

## Vocabulary in 60 seconds

| Word | Meaning |
|---|---|
| **Class** | The kind of document, like "ordinance", "permit", "research paper". Classes form a tree: an ordinance is a kind of legal instrument, which is a kind of document. |
| **Module** | A ready-made set of classes: `core` (general), `legal-de` (German/EU law), `ai-tech` (AI documents). |
| **Local extension** | Extra classes that only this one database uses. |
| **Work** | The law "as such", across all its versions, e.g. `de-strlschv-2018`. |
| **Version date** | When a particular version of the text took effect. |
| **Fact** | One entry on a filing card, e.g. "file X has class = ordinance". |
| **Relation** | A link between documents: `based_on`, `transposes`, `amends`, `repeals`, `incorporates`, `cites`, … |
| **Proposal** | A suggestion from the model or the rules that waits for a person to click Confirm or Reject. |
| **Revision** | A numbered save point. Every change creates a new one, and nothing is ever erased. |
| **Reader / Maintainer** | Readers can look and export. Maintainers can also change things. |

## Where you meet the ontology in the GUI

### 1. The Upload page: labelling documents as they arrive

- When you upload files, the review table gets extra columns: **Class**, **Work** and a
  read-only **Other versions in this DB**.
- The app fills these in automatically by recognising typical wording near the top of the
  document, such as "verordnet".
- You can correct any value. A value you set yourself always beats automatic ones, now and
  later.
- The existing **effective as of** column becomes the version date.
- If the rules find no class, the model may add a **proposal**. It only counts if the
  model's quote really appears in the document.
- At upload, the app also spots relations such as "transposes Directive 2013/59/Euratom"
  or DIN references.

### 2. Search and chat: it helps without you doing anything

- If your question names a law ("StrlSchV") or a class ("Verwaltungsvorschrift"),
  matching documents are pushed up the result list.
- **Point in time:** "What did the StrlSchV say in 2017?" picks the version that was in
  force then. Outdated versions move to the bottom, but they are never hidden.
- What you'll see:
  - Search hits show a badge like `ontology: ordinance · de-strlschv-2018 · date`, marked
    in force / superseded / not yet in force.
  - Explorer search shows a line such as *Ontology — "StrlSchV" → de-strlschv-2018;
    3 source(s) favoured*.
  - Agent traces have an **Ontology frame** expander, and *Why these sources* lists every
    ontology match.
- Deep chat has a safety check: if the answer cites only superseded versions while the
  current one is in the database, the answer is rejected once and the agent is pointed to
  the current file.

### 3. The graph

- Relations appear as coloured arrows between documents.
- The **Pyramid** layout stacks documents by legal rank: constitution at the top, then
  laws, ordinances, and so on.
- Pages whose sources are all superseded get a **dashed ring** ("outdated").

### 4. Maintenance → Ontology: the workbench

This is the control room. The header always shows the current revision, the last change
by a person, the last automatic change, and an **Export current (YAML)** button.

If the database has no ontology yet, a maintainer sees **Create ontology**. You pick
modules there, and it warns you if none of them can auto-detect anything.

The nine views, left to right:

| View | What you do there | Who |
|---|---|---|
| **Overview** | Summary, plus downloads in standard formats: SKOS/Turtle for the schema, JSON-LD for the facts | All |
| **Classes** | Browse the class tree with labels and definitions | All |
| **Facts** | See each document's filing card: class, work, date, relations | All |
| **Edit** | Two tables: your local classes (add, rename, deprecate, set detection patterns) and one row per document (class, work, version date). You see a preview first, then click **Apply changes**. | Maintainer |
| **Proposals** | Confirm or reject suggestions. **Classify concept pages** asks the model to label wiki topic pages. **Ask the model for a new class** handles a document no class fits; the model's answer is checked by code before it is shown. | Maintainer |
| **Cues** | *Cue tester*: type a detection pattern and see "matches n of m documents" with the matching line. *Re-classify*: a dry run of what current patterns would change, then **Apply re-classify**. Your own manual decisions are never touched. | Test: all; Apply: maintainer |
| **Lint** | Warnings about problems: circular "based on" chains, an ordinance "based on" something lower-ranked, two versions with the same date, frequently referenced laws that are missing from the database | All |
| **History** | Every revision: who, when, how, what changed. **Download revision N**, or **Restore** an old one, which becomes a *new* revision so history is never rewritten. | Download: all; Restore: maintainer |
| **Import** | Upload an edited YAML file. You get a preview with a change table. If someone changed the same thing meanwhile, you choose **Keep current** or **Use mine** for each conflict, then **Apply import**. | Maintainer |

### 5. Things that happen automatically

- **Deleting a source** also withdraws its facts. They are marked as retracted, not
  erased, and a revision is recorded.
- After an ingest, import, restore or review, the summary pages in the wiki are
  re-stamped with `class` / `work` / `version_date`.
- Every change adds a line to the Activity log.

## Typical use cases, as recipes

1. **Start an ontology for a legal database:** Workbench → Create ontology → choose
   `core` + `legal-de` → upload documents → check the Class/Work columns in the upload
   table.
2. **A document was labelled wrongly:** Workbench → Edit → change its class in the
   documents table → Apply. Your choice now stays put.
3. **Many documents are unlabelled:** Proposals → confirm or reject. Or Cues → write a
   pattern → test it → Apply re-classify.
4. **My document type doesn't exist:** Edit → add a local class, with labels in German and
   English, a one-line definition and a cue. Or let the model suggest one under
   Proposals, but test its cue first; model cues can be too broad.
5. **Retire a class:** Mark it deprecated and set a replacement (`replaced_by`). Its
   documents move over automatically. Classes are never deleted.
6. **Bulk editing in a text editor:** Export YAML → edit → Import → review the preview →
   Apply.
7. **"I broke something":** History → Restore the last good revision.
8. **Hand it to another tool:** Overview → SKOS or JSON-LD download.
9. **Find inconsistencies:** Lint view, or Maintenance → Lint, which has an ontology
   section.
10. **Ask a legal-history question in chat:** Just include the date or year
    ("Stand 2017"). The app works out which version applies.

## Ground rules worth knowing

- **Your decisions win.** Precedence is: person > rules > model.
- **Nothing is ever erased.** Removing something writes a new "undo" entry, and every
  change is a revision you can restore.
- **The shared modules** (`core`, `legal-de`, `ai-tech`) can't be changed in the GUI;
  that happens via git. You can only add local classes.
- **Rank only orders and warns.** The app never decides which law wins a legal conflict.
- **An ontology only helps.** Questions that name no law or class get exactly the same
  results as without one.
