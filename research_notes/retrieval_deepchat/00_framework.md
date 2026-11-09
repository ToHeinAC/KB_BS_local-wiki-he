# Forschungsrahmen: Retrieval und Deep Chat

Stand 2026-11-09 · Status: **Fünf Fragen gewählt (F02, F03, F05, F06, F10), FF1 entschieden (keine Vektordatenbank, auch auf der ganzen Datenbank der RTX 4090), FF2 entschieden (32k-Fenster mit heutigem Budget bleibt), FF3 entschieden (alle Tiefenschritte bleiben, D4 kein Standardpfad)**. Stand der Messungen: [01_zwischenstand.md](01_zwischenstand.md)

Dieses Dokument ist der Startpunkt der Studie. Es legt die Forschungsfragen, Testfragen,
Messgrößen und Entscheidungsregeln fest, **bevor** gemessen wird. Ergebnisse kommen später als
eigene Dateien in diesen Ordner (`01_…`, `02_…`).

**Ablauf**

1. ~~Zehn Testfragen prüfen und auf fünf eindampfen (§ 4).~~ Erledigt.
2. Voraussetzungen herstellen (§ 5.1), Gold-Datei aus den gewählten Fragen bauen.
3. FF1 auf allen zehn Fragen messen (ohne LLM, Minuten).
4. FF2 und FF3 auf den fünf Fragen messen (mit LLM, Stunden).
5. Je Forschungsfrage anhand der vorab festgelegten Regel entscheiden.

---

## 1. Ausgangslage

| Thema | Befund | Beleg |
|---|---|---|
| Korpus | `data/StrlSch_DE`: StrlSchG + StrlSchV, zusammen knapp 1 MB, **60 Wiki-Seiten** (Herkunft siehe § 6) | `data/StrlSch_DE/raw`, `data/StrlSch_DE/wiki` |
| Index | `data/StrlSch_DE` neu gebaut: 533 Original-Chunks + 404 Wiki-Chunks, BM25 und Vektoren deckungsgleich | `index_health()`, `vectors.json` |
| Retrieval | BM25 (FTS5) + exakter Kosinus über `vectors.npy` (bge-m3, 1024 Dim.), RRF, optional Cross-Encoder | [retrieval.md](../../docs/retrieval.md) |
| Modell | `gemma4:e4b`, `num_ctx` 32768 für alle Aufrufe | `src/ollama_client.py` |
| Letzter GPU-Lauf | 26.10., q1–q7: 517 s, also 74 s je Frage und 6 s je Tool-Aufruf; Gold 10/10 gelesen | [Bench-Log](../../bench/results/deep_chat_2026-10-22.md) |
| Ältere Basis | Dieser Lauf lag vor den Levels. Für den heutigen Code gibt es keine Laufzeit | Rows ohne `cited_by_level` |
| Referenzen | Im Lauf vom 26.10. nur bei q5 und q7 genutzt (je 1 Hop). Nutzen der Levels unbelegt | `deep_chat_2026-10-26_q1-7_gpu_247ddcd.json` |
| Token-Telemetrie | `src/` wertet keine Token-Zahlen aus; Kontextnutzung ist bisher nur geschätzt | `grep` nach `prompt_eval_count` |

### Lücken, die vor jeder Messung zu schließen sind

- **Retrieval-Gold fehlte: behoben** durch `bench/fixture_study_StrlSch_DE.json`. `bench/fixture_KI*.json` stammen aus dem früheren KI-Korpus
  (Attention-Paper usw.): 0 von 11 Chunk-Labels existieren noch. `bench_retrieval.py` und
  `calibrate_abstention.py` messen auf dieser Datenbank nichts Sinnvolles. In `data/StrlSch_DE/index` liegt
  auch keine `calibration.json`, Abstention und das τ-Filtern greifen dort also nicht.
- **Chunker-Fehler bei langen Anlagen-Köpfen: behoben (2026-11-07).** Die Köpfe von Anlage 4
  (357 Zeichen) und Anlage 19 (227) überschritten die Grenze von 200 Zeichen in
  `_ANNEX_HEAD_RE`, Anlage 4 stand deshalb unter „Anlage 3 (Teil N)“. Auf einer Scratch-Kopie haben
  jetzt alle 19 Anlagen einen eigenen Anker, `data/StrlSch_DE` ist damit neu gebaut.

### Vorabmessung auf dem Mac

Nur zur Einschätzung, nicht als Ergebnis: Mac, ohne Reranker, Scratch-Kopie von `StrlSch_DE` mit aktuellem
Chunker (533 Chunks), Gold ungeprüft.

| Messung | Wert |
|---|---|
| Recall@10 über 26 Gold-Sektionen | BM25 13 · Dense 18 · Hybrid 17 |
| Recall@5 | BM25 8 · Dense 15 · Hybrid 14 |
| Brute-Force je Suche (exakt, 1024 Dim.) | 520 Zeilen ≈ 0 ms · 10 000: 2 ms · 100 000: 21 ms · 1 Mio.: 223 ms |
| Zeichen je Token, Gesetzestext (`gemma4:e4b`) | **4,01** (Code nimmt 3 an) |
| Zeichen je Token, Tabelle Anlage 4 | **1,20** |
| `prompt_eval_count` bei Cache-Treffer | bleibt 2995, nur die Dauer fällt von 10,8 s auf 0,04 s |

Der letzte Punkt ist für FF2 wichtig: Die Zahl misst den vollen Prompt, die Dauer zeigt den
Cache-Treffer. Beides lässt sich pro Aufruf aus `ChatOllama`-Metadaten lesen.

### Erkenntnisse aus `local_summarizer`

Quelle: [ToHeinAC/local_summarizer](https://github.com/ToHeinAC/local_summarizer), Stand
2026-11-06, `docs/agent.md` und `docs/models.md`. Gemessen auf einer gepinnten RTX 4090
(`NUM_PARALLEL=1`), allerdings bei **Einzelprompts**, nicht im Agenten-Loop.

| Erkenntnis | Dort gemessen | Folge für Deep Chat |
|---|---|---|
| VRAM ist für E4B kein Limit | 131072 Tokens ≈ 7,2 GB Kartenbelegung | Das 32k-Fenster ist kein Hardware-Zwang (→ H2.3) |
| Das Fenster kostet kaum Prefill | ≈ 8–13k Tokens/s | Voller Prompt-Neuaufbau bei 24k Tokens ≈ 2–3 s, relevant bei 6 s je Aufruf (→ H3.3) |
| Überlänge bricht still | Ollama verwarf den Prompt-Anfang: 128k Tokens kamen als 65k an, ohne Fehler | Überlauf aktiv erkennen. Verhalten im mehrteiligen `/api/chat`-Verlauf ist offen (→ H2.2) |
| Zwei Budgets statt einem | Hartes Limit mit 2,5 Z/T, Qualität mit 3,3 Z/T | Vorlage für Budget-Arm E1. Unsere Tabelle mit 1,2 Z/T unterschreitet selbst 2,5 |
| Die Antwort ist der Engpass | StrlSchV: 2 × 80k Tokens → 49/200 §§ in den Notizen, 6 × 25k → 113/200 | Mehr Eingabe bringt nicht automatisch mehr Inhalt. „Nadel gefunden“ überschätzt die Verdichtung |
| Weniger Aufrufe, größerer Prompt | StrlSchV: ~95 Aufrufe/15 min → 8 Aufrufe/3 min | Vorbild für Direktlauf D4 (→ H3.2) |
| Modell-Fenster sind vermessen | `qwen3.8-27b` 65536 ≈ 21 GB, 131072 spillt 15 % auf CPU | Grenze für einen möglichen späteren Modellarm |
| Sampling und Runaway-Schutz | Temperatur 1,0 ergab Dubletten, dort 0,2 plus `num_predict` 6144 | Der Deep-Chat-Loop läuft mit 1,0 und ohne `num_predict` (→ § 5.3) |

Grenze der Übertragbarkeit: Der Summarizer schickt einen Prompt einmal. Deep Chat schickt einen
wachsenden Verlauf jeden Turn neu, dort zählen Prompt-Cache und dessen Bruch beim Trimmen. Dazu
kommen frühere Notizen: RULER 95,2 bei 32k gegen 86,6 bei 128k, Empfehlung 16–32k für E4B
(`research_notes/Deep chat and research tweaks/gemma4_e4b_ollama.md`). Beides spricht dagegen,
das größte Fenster ungeprüft zu setzen.

---

## 2. Forschungsfragen

Die Schwellen sind **Vorschläge**. Sie werden vor der Messung festgelegt und danach nicht mehr
geändert.

### FF1: Bringt eine echte Vektordatenbank besseres Retrieval?

**Klärung vorab.** Das System durchsucht heute alle Vektoren exakt. Eine Vektordatenbank mit
ANN-Index (HNSW, IVF) nähert dieses Ergebnis nur an. Bei gleichen Embeddings kann sie die Trefferqualität
also nicht verbessern, sondern höchstens Latenz und Betrieb. Besser werden kann die Qualität nur
durch **andere Repräsentationen** (Sparse, Multi-Vektor, Chunking, Header). Diese beiden Effekte
trennt die Studie, sonst wird dem Speicher ein Gewinn zugeschrieben, der aus der Repräsentation
kommt.

| Hypothese | Inhalt |
|---|---|
| H1.1 | Gleiche Vektoren in einer Vektor-DB ergeben keinen höheren Recall (höchstens gleich) |
| H1.2 | Unter rund 100 000 Chunks bringt ANN keinen spürbaren Zeitgewinn. Das wäre etwa das 190-Fache des Korpus, die Suche dauert heute ≈ 21 ms, Reranking und LLM dominieren |
| H1.3 | BM25 und Dense ergänzen sich (F05, F07). Dense allein verliert bei Fragen mit gesetzesnaher Wortwahl |
| H1.4 | Falls ein Qualitätsgewinn existiert, kommt er aus der Repräsentation und wäre auch ohne Vektor-DB erreichbar |

| Arm | Aufbau | Zweck |
|---|---|---|
| R0 | nur BM25 | Beitrag lexikalisch |
| R1 | nur Dense, exakt | Beitrag semantisch |
| R2 | Hybrid (RRF) | Fast-Pfad heute |
| R3 | Hybrid + Reranker | Deep-Pfad heute, **Referenz** |
| R4 | gleiche Vektoren in Vektor-DB, ANN, sonst wie R3 | Reiner Speicher-Effekt |
| R5 | bge-m3 Sparse oder Multi-Vektor in Vektor-DB | Repräsentations-Effekt |

R5 braucht eine Embedding-Laufzeit neben Ollama, denn `/api/embed` liefert nur Dense-Vektoren.

**Messgrößen:** Recall@5/10, MRR und nDCG@10 auf Sektionsebene, ANN-Recall gegenüber exakt,
Latenz p50/p95 bei 532, 10 000 und 100 000 Zeilen (synthetisch aufgefüllt), RAM, Index-Bauzeit,
Plattenbedarf, Betriebsaufwand.

**Entscheidung:** Vektor-DB nur weiterverfolgen, wenn **R4 oder R5** gegenüber R3 auf den zehn
Fragen mindestens 3 von 26 Gold-Sektionen in Recall@10 gewinnt **und** der Gewinn nicht ohne
Vektor-DB erreichbar ist, oder wenn die Suche bei realistisch erwarteter Korpusgröße p95 > 200 ms
braucht. Sonst bleibt es beim jetzigen Stand; eventuelle Gewinne aus R5 werden als eigene
Maßnahme bewertet.

**Regelgrenze:** AGENTS.md §5.3 verbietet externe Vektor-DBs und ANN-Indizes. Das Experiment läuft
außerhalb von `src/` (`uv run --with …`, Scratch-`DATA_ROOT`). Eine Übernahme bräuchte eine
Regeländerung durch dich.

### FF2: Wird das Kontextfenster im Deep Chat optimal genutzt?

**Ziel:** eine RTX 4090 mit 24 GB VRAM, Modell auf einer Karte, wie auf der Remote-Maschine.

**Rechnung heute:** `(32768 − 8192) × 3 = 73 728` Zeichen Budget, nach dem Trimmen 60 %.

| Inhalt | Zeichen je Token | Budget in Tokens | Anteil `num_ctx` | Nach Trim |
|---|---|---|---|---|
| Gesetzestext | 4,01 | ≈ 18 400 | **≈ 56 %** | ≈ 11 000 (34 %) |
| Tabelle | 1,20 | ≈ 61 400 | **≈ 187 %** | ≈ 36 900 (113 %) |

Die Schätzung liegt also in beide Richtungen daneben. Prosa wird früher getrimmt als nötig,
Tabellen können das Fenster sprengen. Ein einzelner `raw_read` mit 16 000 Zeichen Tabelle wären
schon ≈ 13 300 Tokens. Das sind Rechenwerte, im echten Lauf noch nicht beobachtet.

| Hypothese | Inhalt |
|---|---|
| H2.1 | Bei Gesetzestext bleiben im Schnitt mehr als 30 % des Fensters ungenutzt, obwohl Evidenz weggetrimmt wird |
| H2.2 | Tabellenlastige Läufe überschreiten das Fenster. Das bleibt unbemerkt, weil Ollama still kürzt |
| H2.3 | Der Speicher begrenzt nicht (`local_summarizer`: E4B ≈ 7,2 GB bei 128k). Ein größeres Fenster ist auf einer 4090 möglich |
| H2.4 | Mehr Fenster bringt ab einem Punkt keine zusätzlichen Pflichtfakten, weil E4B nicht mehr verdichten kann. Der beste Wert liegt unter dem Maximum |
| H2.5 | Eine token-genaue Budgetierung bringt bei gleichem `num_ctx` mehr als ein größeres Fenster |

| Arm | `num_ctx` | Budget | Zweck |
|---|---|---|---|
| E0 | 32768 | 3 Z/T | **Referenz**, heute |
| E1 | 32768 | gemessene Tokens statt Zeichen | Budget-Effekt ohne Fensteränderung |
| E2 | 16384 | wie E1 | Untergrenze, zeigt Prefill- und Qualitätseffekt |
| E3 | 65536 | wie E1 | Mittlerer Ausbau |
| E4 | 131072 | wie E1 | Obergrenze laut `local_summarizer` |

Alle Aufrufe eines Laufs nutzen denselben `num_ctx`, sonst lädt Ollama das Modell neu. `INGEST_NUM_CTX`
gilt global und wird nur für den Lauf per Umgebung gesetzt. E3 und E4 prüfen zusätzlich den
`GGML_SCHED_MAX_SPLIT_INPUTS`-Absturz, wegen dem die Kappung ursprünglich eingeführt wurde
([gpu.md](../../docs/gpu.md)).

**Messgrößen je LLM-Aufruf:** `prompt_eval_count` (Füllstand), `prompt_eval_duration`
(Cache-Treffer), `eval_count`, `eval_duration`, `done_reason`. **Je Lauf:** Mittel und Spitze des
Füllstands, Anzahl Trims, getrimmte Gold-Abschnitte, erkannte Überläufe, Anteil
System/Tools/Evidenz/Modelltext, VRAM-Spitze (`nvidia-smi`, `ollama ps`), Pflichtfakten, Laufzeit.

**Überlauf-Erkennung:** Erwartete Tokens aus dem Verlauf gegen `prompt_eval_count` stellen, dazu
ein Canary am Anfang des Verlaufs. Zuerst klären, ob `/api/chat` bei mehreren Nachrichten anders
kürzt als der in `local_summarizer` gemessene Einzelprompt.

**Entscheidung:** Empfohlen wird die kleinste Konfiguration, deren Pflichtfakten nicht schlechter
sind als die der besten (Abstand ≤ 1 Fakt je Frage im Mittel), ohne Überlauf, VRAM-Spitze
≤ 22 GB und Laufzeit ≤ 1,2 × E0. Überläufe sind unabhängig vom Sieger als Fehler zu beheben.

### FF3: Wie wird Deep Chat schneller, und hilft die tiefe Recherche?

**Auslegung:** „Ergebnisse besser vorliegen“ verstehe ich als *früher und belastbar*. Die
Zeitmessung zählt daher auch, wann erstmals eine gate-fähige Antwort vorliegt. Bitte korrigieren,
falls etwas anderes gemeint war.

**Tiefe Recherche** umfasst zwei Mechanismen: die Level-Reads in Code (Kernsektion, Begriffe,
anwendende Vorschriften, innere Begriffe) und das Referenz-Folgen des Agenten über
`raw_read`-Footer mit Hop-Bonus. Beide werden getrennt abgeschaltet.

| Hypothese | Inhalt |
|---|---|
| H3.1 | LLM-Turns dominieren die Laufzeit. Rerank (≈ 0,3 s je Suche) und Level-Reads (≈ 0,24 s) sind Nebensache |
| H3.2 | Ein Direktlauf ohne Agenten-Turns spart mindestens die Hälfte der Zeit bei gleichen Pflichtfakten. Vorbild: `local_summarizer` kam von ~95 auf 8 Aufrufe |
| H3.3 | Trims brechen den Prompt-Cache, jeder Bruch kostet 2–3 s Prefill |
| H3.4 | Referenzen helfen genau dort, wo die Suche scheitert (F02 Anlage 8, F06 § 126), und kosten bei Kontrollfragen (F10) nur Zeit |
| H3.5 | Gate-Ablehnungen sind der teuerste vermeidbare Posten (26.10.: 10 von 31 Gate-Ereignissen waren „minimum is 3 searches“) |

| Arm | Levels | Referenz-Folgen | Agenten-Loop | Zweck |
|---|---|---|---|---|
| D0 | 1–3 | an | an | **Referenz**, identisch mit E0 |
| D1 | 1–3 | aus | an | Nutzen des Referenz-Folgens |
| D2 | nur 1 | an | an | Nutzen der Begriffe und anwendenden Vorschriften |
| D3 | aus | aus | an | Untergrenze: nur Suche und Agent |
| D4 | 1–3 | aus | **aus**: Suche, Levels, direkt Ledger-Antwort | Schnellster Pfad |

Die Arme lassen sich über einen Bench-Wrapper schalten (Konstanten wie `REF_MAX_HOPS`, `CORE_MAX`,
`TERMS_MAX`), ohne `src/` zu ändern. Bei D4 ist das noch zu prüfen. **Reihenfolge wichtig:** Erst
läuft FF2, dann FF3 mit dem FF2-Sieger, falls er von E0 abweicht. Sonst müsste D0 mit
wiederholt werden.

**Messgrößen:** Gesamtzeit, Zeit bis zur ersten gate-fähigen Antwort, Zeit je Phase (HyDE und
Suche, Levels, Agenten-Turns, Gate-Wiederholungen, Ledger-Antwort), Anzahl LLM-Aufrufe,
Pflichtfakten, `gold_read`, `cited_unread`, `cited_by_level`, `hops`, Exit-Pfad.

**„Hilfreich“ messbar gemacht.** Ein Tiefenschritt gilt als hilfreich, wenn sein Abschalten
gegenüber D0 auf mindestens 2 von 5 Fragen Pflichtfakten kostet.

| Ergebnis gegenüber D0 | Entscheidung |
|---|---|
| Faktenverlust auf ≥ 2 Fragen | Schritt bleibt |
| Kein Faktenverlust, ≥ 20 % Zeitgewinn | Schritt entfällt oder läuft nur bei Bedarf |
| Kein Faktenverlust, kaum Zeitgewinn | Schritt wird nach Einfachheit entschieden |
| D4 hält die Fakten und halbiert die Zeit | D4 wird neuer Standardpfad, Agent nur als Eskalation |

---

## 3. Die zehn Testfragen

Alle Abschnitte sind im Text von `data/StrlSch_DE/raw` geprüft. **BM25 / Dense / Hybrid** zeigen den Rang
der Gold-Sektion in der Vorabmessung (`–` = nicht in den Top 60, ohne Reranker).

| # | Kurzname | Typ | Gold-Sektionen | Besonderheit |
|---|---|---|---|---|
| F01 | Flugpersonal | Alltagssprache statt Gesetzeswort | 1 | BM25 scheitert |
| F02 | Radon-Arbeitsfelder | Antwort nur über Verweis | 2 | Anlage 8 hängt an § 127 |
| F03 | Cs-137 | Tabellenwert | 1 | 1,2 Zeichen je Token |
| F04 | Mobilfunk | Nicht im Korpus | 0 | Prüft Ehrlichkeit |
| F05 | Schwangerschaft | Szenario über zwei Gesetze | 3 | Dense deutlich schwächer |
| F06 | Radon-Kette | Mehrstufiges Verfahren | 8 | Maximaltest |
| F07 | Freigabe/Entlassung | Vergleich ähnlicher Regime | 3 | Arme ergänzen sich |
| F08 | Altlast | Ein Gesetz, drei Aspekte | 3 | Mittlerer Umfang |
| F09 | Pflichtenverteilung | Breite mit Verweisflut | 4 | Viele Querverweise |
| F10 | Augenlinse | Kontrollfrage | 1 | Tiefe bringt nichts |

### F01: Flugpersonal

- **Frage:** Ab welcher Strahlendosis muss eine Fluggesellschaft den Betrieb ihrer Flugzeuge wegen der Höhenstrahlung bei der Behörde melden?
- **Gold:** StrlSchG § 50. Rang: § 50 `–/1/1`
- **Pflichtfakten:** 1 mSv im Kalenderjahr · Anzeige vier Wochen vor Aufnahme des Betriebs
- **Sinn:** Misst den Wert der semantischen Suche, wenn die Frage keine Gesetzesbegriffe nutzt („Höhenstrahlung“, „Fluggesellschaft“ gegen „kosmische Strahlung“, „Luftfahrzeug“).
- **Vorteile:** Sauberer Test für FF1, schnell, eindeutiges Gold. Prüft, ob `HyDE` Lücken schließt.
- **Nachteile:** Dense löst sie bereits, also kaum Spielraum für R4/R5. Wenig Aussage zu FF2 und FF3.

### F02: Radon-Arbeitsfelder

- **Frage:** An welchen Arbeitsplätzen muss unabhängig vom Standort des Gebäudes die Radonkonzentration gemessen werden?
- **Gold:** StrlSchG § 127, Anlage 8. Rang: § 127 `3/1/1`, Anlage 8 `–/5/21`
- **Pflichtfakten:** Bergwerke, Schächte, Höhlen · Radonheilbäder und -stollen · Wassergewinnung, -aufbereitung, -verteilung
- **Sinn:** Der Fragenkern steht in § 127, die Antwort aber in der Anlage. Direkter Test des Referenz-Folgens.
- **Vorteile:** Kurz, klare Ja/Nein-Wirkung der Referenzen, zeigt zugleich, dass Hybrid einen Dense-Treffer von Rang 5 auf 21 verschlechtert.
- **Nachteile:** Hat die Suche Anlage 8 doch unter den Treffern, verschwindet der Effekt. Nur ein Hop.

### F03: Cs-137

- **Frage:** Wie hoch sind die Freigrenzen für Cs-137?
- **Gold:** StrlSchV Anlage 4 Tabelle 1, Zeile Cs-137+ (`Anlage 4 (Teil 6)`). Rang: `2/2/2`
- **Pflichtfakten:** 1 E+4 Bq (Spalte 2) · 1 E-1 Bq/g (Spalte 3). Spalten von Hand geprüft.
- **Sinn:** Bezeichner statt Wortlaut, flach konvertierte Tabelle, extreme Token-Dichte. Stresstest für Chunking und Budget.
- **Vorteile:** Einzige Frage, die H2.2 (Überlauf) direkt prüft. Numerisch hart bewertbar.
- **Nachteile:** Die Tabelle ist flach konvertiert, ein Wert steht ohne Spaltenkopf im Chunk. Cs-137+ steht auch in Tabelle 2 (`Anlage 4 (Teil 12)`, Tochternuklide), das ist ein Ablenker. Teilweise Chunker-Test statt Retrieval-Test.

### F04: Mobilfunk

- **Frage:** Welche Grenzwerte gelten für elektromagnetische Felder von Mobilfunkanlagen?
- **Gold:** keines. Weder „Mobilfunk“ noch „elektromagnetisch“ kommen im Korpus vor. Erwartet: klare Aussage, dass die Quellen das nicht regeln.
- **Pflichtfakten:** Keine erfundenen Grenzwerte · Korpus deckt das Thema nicht ab
- **Sinn:** Prüft, ob Gates und Tiefe zu Scheinbelegen drängen. Dense liefert fachfremde Treffer mit Score 0,57, ein rohes Score-Limit reicht also nicht.
- **Vorteile:** Einzige Sicherheitsfrage. Zeigt, ob der Lauf früh abbricht, was auch ein Tempothema ist.
- **Nachteile:** Braucht ein neu kalibriertes τ für `StrlSch_DE`. Kein Recall messbar, Bewertung teils manuell.

### F05: Schwangerschaft

- **Frage:** Eine Mitarbeiterin im Kontrollbereich teilt mit, dass sie schwanger ist. Was muss der Betrieb jetzt tun, und welche Dosisgrenze gilt für das ungeborene Kind?
- **Gold:** StrlSchG § 78, StrlSchV § 69, § 55. Rang: § 78 `10/37/12`, § 69 `6/23/8`, § 55 `8/19/6`
- **Pflichtfakten:** 1 mSv ab Mitteilung bis Ende der Schwangerschaft · innere berufliche Exposition ausschließen · arbeitswöchentliche Ermittlung · Zutritt nur mit Gestattung und Dokumentation
- **Sinn:** Praxisnahes Szenario über zwei Gesetze. BM25 schlägt hier Dense, und das Wissen liegt verteilt. Prüft, ob die Levels eine nicht im Kern liegende Vorschrift finden.
- **Vorteile:** Belegt die Ergänzung der Arme, realistische Nutzerfrage, trennt FF1 und FF3 gut.
- **Nachteile:** Alle Gold-Sektionen liegen auf Rang 6–12, das Ergebnis schwankt also stärker. Gold ist fachlich nicht völlig geschlossen (etwa weitere Schutzpflichten).

### F06: Radon-Kette

- **Frage:** Im Erdgeschoss eines Betriebs in einem Radonvorsorgegebiet werden hohe Radonwerte gemessen. Welche Schritte muss der Arbeitgeber nacheinander gehen, und ab wann gilt der berufliche Strahlenschutz?
- **Gold:** StrlSchG §§ 126–131, StrlSchV §§ 157, 158. Rang: § 126 `–/–/–`, § 127 `–/6/14`, § 128 `–/8/15`, § 129 `–/13/20`, § 130 `–/3/3`, § 131 `–/1/1`, § 157 `–/–/–`, § 158 `55/5/13`
- **Pflichtfakten:** 300 Bq/m³ · unverzüglich Maßnahmen · Erfolgsmessung binnen 30 Monaten · Anmeldung · Abschätzung binnen sechs Monaten · ab 6 mSv beruflicher Strahlenschutz
- **Sinn:** Maximaltest. Die Kette folgt expliziten Verweisen, und zwei Gold-Sektionen findet kein Suchweg, darunter der 300-Bq-Wert. BM25 fällt fast ganz aus, vermutlich wegen Komposita („Radonwerte“) und „Arbeitgeber“ statt „für den Arbeitsplatz Verantwortlicher“.
- **Vorteile:** Berührt alle drei Forschungsfragen, füllt das Fenster, deutlich mehr als `CORE_MAX`. Beste Einzelfrage.
- **Nachteile:** Längste Laufzeit, höchste Streuung, ein Lauf allein sagt wenig. Vermischt Retrieval- und Modellfehler.

### F07: Freigabe/Entlassung

- **Frage:** Worin unterscheiden sich die Freigabe radioaktiver Stoffe und die Entlassung von Rückständen aus der Überwachung, und welches Dosiskriterium gilt jeweils?
- **Gold:** StrlSchV § 31, StrlSchG § 62, StrlSchV § 29. Rang: § 31 `20/1/1`, § 62 `2/2/2`, § 29 `1/11/3`
- **Pflichtfakten:** Freigabe: Bereich von 10 µSv im Kalenderjahr · Entlassung: Richtwert 1 mSv im Kalenderjahr
- **Sinn:** Zwei ähnliche Regime müssen getrennt bleiben. Prüft Verwechslung, die bei E4B mit langen Kontexten laut früherer Notiz schwach ist.
- **Vorteile:** Zeigt die Fusion im besten Fall (BM25 und Dense decken je eine Sektion). Knappes, hartes Faktenkriterium.
- **Nachteile:** Überschneidet sich fachlich mit q5–q7. Hybrid löst das Retrieval bereits gut.

### F08: Altlast

- **Frage:** Wann ist etwas eine radioaktive Altlast, wer ist dafür verantwortlich, und wer trägt die Kosten der Sanierung?
- **Gold:** StrlSchG §§ 136, 137, 146. Rang: § 136 `12/4/6`, § 137 `2/1/1`, § 146 `3/17/5`
- **Pflichtfakten:** abgeschlossene menschliche Betätigung, 1 mSv · Verursacher, Rechtsnachfolger, Eigentümer, tatsächliche Gewalt · Kosten tragen die Verpflichteten, Ausgleichsanspruch
- **Sinn:** Mehrere Aspekte innerhalb eines Gesetzes ohne Hop über Dateigrenzen. Prüft den Nutzen von Level 2.
- **Vorteile:** Saubere Fakten, stabile Suche, mittlere Laufzeit.
- **Nachteile:** Lösbar mit drei Suchen, also wenig Stress für FF2 und FF3. Eher Mittelwert als Grenzfall.

### F09: Pflichtenverteilung

- **Frage:** Wie sind die Pflichten zwischen Strahlenschutzverantwortlichem und Strahlenschutzbeauftragtem verteilt, und welche Pflichten dürfen nicht übertragen werden?
- **Gold:** StrlSchG §§ 69, 70, 72, StrlSchV § 43. Rang: § 69 `–/7/13`, § 70 `7/3/3`, § 72 `6/2/2`, § 43 `1/1/1`
- **Pflichtfakten:** Bestellung schriftlich · Aufgaben und Befugnisse schriftlich festgelegt · Nennung der nicht übertragbaren Pflichten nach § 43 Abs. 2
- **Sinn:** Sektionen mit sehr vielen Querverweisen. Prüft, ob Referenz-Folgen das Fenster mit Randthemen füllt.
- **Vorteile:** Gegenpol zu F02: Hier könnten Referenzen schaden. Keine Abhängigkeit vom Chunker-Fehler.
- **Nachteile:** Bewertung der Vollständigkeit ist schwerer. § 43 Abs. 2 ist eine reine Verweisliste, die Modelle ungern ausformulieren.

### F10: Augenlinse

- **Frage:** Wie hoch ist der Grenzwert der Organ-Äquivalentdosis der Augenlinse für beruflich exponierte Erwachsene, und darf die Behörde davon abweichen?
- **Gold:** StrlSchG § 78. Rang: § 78 `1/1/1`
- **Pflichtfakten:** 20 mSv im Kalenderjahr · Einzelfall 50 mSv in einem Jahr · 100 mSv in fünf Jahren
- **Sinn:** Kontrollfrage. Eine Sektion genügt, also ist jede Sekunde darüber hinaus Overhead. Gibt die Tempo-Untergrenze an.
- **Vorteile:** Kürzester Lauf, geringe Streuung, zeigt reine Kosten der Tiefe, Pflichtfakt verlangt das Lesen des ganzen Paragrafen.
- **Nachteile:** Keine Trennschärfe für FF1. Allein ohne Aussage.

---

## 4. Eindampfen auf fünf

**FF1 muss nicht gekürzt werden.** Retrieval läuft ohne LLM in Minuten, daher immer alle zehn Fragen.
Die Kürzung betrifft nur die teuren Deep-Chat-Läufe von FF2 und FF3.

**Abdeckung** (● stark, ○ schwach, – keine)

| # | FF1 Suche | FF2 Kontext | FF3 Tempo | FF3 Referenzen | Laufzeit |
|---|---|---|---|---|---|
| F01 | ● | – | ○ | – | kurz |
| F02 | ○ | ○ | ○ | ● | kurz |
| F03 | ● | ● | ○ | – | mittel |
| F04 | ● | – | ● | – | offen |
| F05 | ● | ○ | ○ | ○ | mittel |
| F06 | ● | ● | ● | ● | lang |
| F07 | ● | ○ | ○ | ○ | mittel |
| F08 | ○ | ○ | ○ | ○ | mittel |
| F09 | ○ | ● | ● | ● | lang |
| F10 | – | – | ● | – | kurz |

**Gewählt am 2026-11-07:** F02, F03, F05, F06, F10.

| Frage | Warum sie bleibt |
|---|---|
| F06 | Einzige Frage, die alles berührt |
| F02 | Nachweis, dass eine Referenz die Antwort erst möglich macht |
| F03 | Prüft das Tabellen-Risiko im Kontextfenster |
| F05 | Realistisches Szenario ohne direkten Verweis zwischen den Gesetzen |
| F10 | Kontrollfrage, ohne sie sind Zeitgewinne nicht interpretierbar |

**Bewusst weggelassen:** F01 (nur Suche, läuft in FF1 ohnehin), F07 und F08 (Mittelfeld ohne
eigenen Grenzfall), F09 (ähnlich wie F06, aber schwerer zu bewerten), F04 (keine direkte
Kontextaussage, siehe Tausch).

Die q1–q7 aus `bench/fixture_deep_chat_KI.json` bleiben als Regressionstest erhalten und zählen
nicht zu den fünf.

---

## 5. Durchführung

### 5.1 Voraussetzungen

1. Scratch-`DATA_ROOT` je Arm, nie `data/` beschreiben. `StrlSch_DE` dorthin kopieren.
2. Neue Gold-Datei aus den gewählten Fragen, zusätzlich Retrieval-Gold mit Sektionsanker statt
   veralteter Chunk-IDs. Prüfung der Labels von Hand, nicht durch ein LLM.
3. τ auf dem neuen Gold kalibrieren.
4. Telemetrie im Bench ergänzen (§ 5.2), einmal auf q1 trocken testen.
5. Auf der Remote-Maschine: gepinnter Daemon, `NUM_PARALLEL=1`, Karte exklusiv. Beim Lauf vom 26.10.
   teilte sich der Bench den Daemon mit der Live-App, das verfälscht Zeiten.

### 5.2 Fehlende Instrumentierung

Alles im Bench oder Wrapper, ohne Verhaltensänderung in `src/`.

| Was | Woher |
|---|---|
| Token je Aufruf | `usage_metadata` und `response_metadata` von `ChatOllama` (`langchain_ollama` liefert sie) |
| Zeit je Phase | Zeitstempel je Graph-Knoten |
| Trims, getrimmte Sektionen | Instrumentierung von `_fit_window` |
| Anzahl Suchen | Fehlt laut Bench-Log noch in den Rows |
| Pflichtfakten | Regex-Liste je Frage, Bewertung in Code, kein LLM-Richter |
| VRAM | `nvidia-smi` im Sekundentakt, `ollama ps` |

### 5.3 Messregeln

- **Wiederholungen:** Der Agent läuft mit Temperatur 1,0, Läufe streuen (q2 las Gold einmal, beim
  nächsten Lauf nicht). Daher drei Wiederholungen je Zelle, berichtet wird Median und Spanne.
  Ein fester `seed` wird als Hilfe geprüft, ersetzt die Wiederholung aber nicht.
- **Reihenfolge:** Arme verschränken, damit Modell-Warmstart und Cache nicht einen Arm begünstigen.
- **Ein Faktor je Arm.** Temperatur und ein `num_predict`-Limit bleiben fest und sind ggf. eine
  spätere eigene Runde.
- **Rohdaten** nach `bench/results/`, mit Commit-Hash im Dateinamen, Auswertung hier im Ordner.

### 5.4 Aufwand

Grobe Untergrenze mit 74 s je Lauf (Stand 26.10., lange Fragen dauern länger). D0 entspricht E0
und wird nur einmal gemessen.

| Teil | Rechnung | Läufe | Zeit |
|---|---|---|---|
| FF1 | 10 Fragen × 6 Arme, ohne LLM | – | Minuten, plus Index-Bau R4/R5 |
| FF2 | 5 Fragen × 5 Arme × 3 | 75 | ≈ 1,5 h |
| FF3 | 5 Fragen × 4 weitere Arme × 3 | 60 | ≈ 1,2 h |
| **Gesamt mit 5 Fragen** | | 135 | **≈ 2,8 h** |
| Zum Vergleich mit 10 Fragen | | 270 | ≈ 5,6 h |

---

## 6. Grenzen der Aussagekraft

- **Kleines, homogenes Korpus.** Zwei Gesetze sagen wenig über Berichte oder Mischbestände.
  AGENTS.md verlangt Prüfung außerhalb des Strahlenschutzes. Ein Gewinner sollte einmal gegen
  `bench/fixture_deep_chat_general.json` laufen, das KrWG und ein englisches Buchkapitel braucht.
- **Wenig statistische Kraft.** Fünf Fragen zeigen große Effekte, keine kleinen. Unterschiede von
  einem Pflichtfakt sind Rauschen, solange sie nicht über Fragen hinweg gleichgerichtet sind.
- **Wiki mit gemischter Herkunft.** Von 25 Stücken schrieb 4 `gemma4:e4b` lokal, 21 (StrlSchG ab
  Stück 5, die ganze StrlSchV) ein Cloud-Modell (Claude Sonnet) anstelle von Ollama. Prompts,
  Routing, Merge und OKF-Stempel waren der echte App-Code, aber die Seiten sind **nicht** das, was
  `gemma4:e4b` geschrieben hätte: Die 21 Stücke zitieren häufiger einzelne §§, und das Limit
  von 32k Tokens griff bei ihnen nicht. Ergebnisse zum Wiki-Weg gelten daher nur eingeschränkt für
  einen rein lokalen Ingest.
- **Wiki-Reichweite der fünf Fragen.** Bei F06 und F10 stehen alle Pflichtfakten schon in den
  Wiki-Top-5, bei F02 stehen sie im Wiki, aber nicht in den Top-5. Bei F05 fehlt die Formulierung zur
  inneren Exposition. Die Cs-137-Werte (F03) stehen nicht im Wiki, Tabellen wurden nicht übertragen.
- **Skalierung ist synthetisch.** Aufgefüllte Vektoren messen Latenz, nicht Qualität.
- **Gold nach Fachurteil.** Die Gold-Sektionen sind geprüfte Fundstellen, aber keine vollständige
  Rechtsauslegung. Pflichtfakten messen Vollständigkeit, keine juristische Korrektheit.
- **Fremde Messwerte.** Die `local_summarizer`-Zahlen stammen aus Einzelprompts und gelten hier
  nur als Hypothesen, bis sie im Agenten-Loop bestätigt sind.

**Bewusst nicht enthalten:** Modellwechsel (`qwen3.8:27b`), Web-Modus, Quick Research, Fast Chat.
Ein Modellarm wäre die sinnvollste Erweiterung, sobald FF2 und FF3 entschieden sind.

---

## 7. Offene Entscheidungen

1. **Datenbank:** Entschieden: die frühere `KI`, jetzt `data/StrlSch_DE`. AGENTS.md §5.5 und der Hook geben
   weiter nur `data/KI` frei. Das bleibt offen, denn auf der GPU-Maschine trägt eine echte Datenbank
   denselben Namen, und eine Freigabe des Namens würde sie mit öffnen.
2. **Wiki-Schicht:** Entschieden und gebaut (§ 6). Bei Bedarf lässt sich ein rein lokaler Ingest als
   Vergleichsarm nachziehen.
3. **Vektor-DB-Kandidat:** Mein Vorschlag ist **ein** eingebetteter Kandidat ohne Dienst, LanceDB, weil
   das am nächsten an „lokal und wartungsarm“ liegt. Einen Server (Qdrant, pgvector) nur testen,
   falls du ihn wirklich betreiben würdest. Lizenz vor dem Test prüfen.
4. **Schwellen:** Die Vorschläge in § 2 bestätigen oder ändern, vor der ersten Messung.
5. **Remote-Lauf:** Wer startet die Läufe auf der 4090, und ist die Karte dafür exklusiv frei?
