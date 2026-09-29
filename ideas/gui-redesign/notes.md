# Broadsheet 2: GUI redesign mockups

Five static mockups for a cleaner newspaper UI. The sources are in [src/](src/), with shared tokens in
[src/broadsheet.css](src/broadsheet.css). They are illustrations, not app code. The current skin is `src/theme.py`,
documented in [docs/ui.md](../../docs/ui.md).

| Screen | What it fixes |
|---|---|
| [01-front-page.png](01-front-page.png) | New entry point. The full nameplate appears here only, with recent activity (`log.md`), the most connected page, "Ask the archive", and the figures from `graph_export.health()`. |
| [02-explorer.png](02-explorer.png) | Paper map with the selected page's neighbourhood labelled. The ranked list becomes a standings table, and the reader sits beside the map as an article. |
| [03-chat.png](03-chat.png) | A 66-character reading measure. Inline `[Source: … §6.1]` tags become numbered citations, with quotes in a margin column; hovering a numeral lights its note. |
| [04-research.png](04-research.png) | The report is laid out as a feature article. The metrics become a figures box, and the trace becomes a timeline of the run. |
| [05-upload.png](05-upload.png) | One review table (level, class, version, duplicate). A disabled button says why it is disabled. Contradiction titles are set as readable sentences. |

## Design rules
- **One accent** (`--oxide`), used only for citations, links and the active state. The classification level is a stamp
  in the running head: plain for Normal, violet for Confidential, reversed ink for Strict.
- **Type has one job per face:**
  - Bodoni Moda for the nameplate only, at opsz 11, because at display sizes its hairlines vanish;
  - Source Serif 4 for headlines and prose;
  - Libre Franklin for every control and label, in sentence case;
  - IBM Plex Mono only for file names.
- **No all-caps mono for sentences, and no sidebar.** Machine status (model, GPU) moves to the one-line folio at the
  page foot.
- **Three button levels:** filled ink, outlined, underlined text. Disabled buttons are dashed but stay readable.

## Mapping to NiceGUI
- The running head is `ui.header`, and the folio is `ui.footer`. The Explorer index, when shown, is `ui.left_drawer`.
- Map and reader form a plain two-column `ui.row`, or `ui.splitter` if the width should be draggable.
- The graph reuses `src/assets/graph/index.html` with `PALETTES.paper`, in a `ui.element` or iframe. Double-click
  opens the reader through an event, not a rerun.
- Tables are `ui.table`, and folds are `ui.expansion`. Answers are `ui.markdown`, with citations post-processed into
  `<sup>` plus margin notes.
- `broadsheet.css` loads as-is with `ui.add_css`. NiceGUI has no rerun model, so the Streamlit workarounds in
  docs/ui.md are no longer needed:
  - the `stHeader` padding;
  - the `stButtonGroup` hooks;
  - the rule that primary navigation must not use `st.tabs` (because of Upload's `st.stop()`);
  - the rule never to gate a button's `disabled=` on a text widget.

Re-render a screen with headless Chrome:
`"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --hide-scrollbars
--force-device-scale-factor=2 --window-size=1600,1000 --virtual-time-budget=6000
--screenshot=<name>.png file://$PWD/src/<name>.html`
