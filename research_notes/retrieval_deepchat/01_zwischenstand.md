# Zwischenstand der Messungen

Stand 2026-11-09. Rahmen: [00_framework.md](00_framework.md). **FF1, FF2 und FF3 sind gemessen und
entschieden:** keine Vektordatenbank, das 32k-Fenster mit dem heutigen Budget bleibt, alle
Tiefenschritte bleiben, D4 wird kein Standardpfad. Drei Wiederholungen sind dünn, siehe
[Streuung](#streuung).

## FF1 auf dem Mac: zwei Gesetze

Mac, Scratch-Kopie von `StrlSch_DE`, Suche über die Originale, Ränge auf Sektionsebene, Reranker
aktiv. Rohdaten: `bench/results/study_ff1_arms_adbf8c6.json`, `study_ff1_lancedb_adbf8c6.json`,
`study_ff1_m3_adbf8c6.json`.

| Arm | Recall@5 | Recall@10 (von 26) | MRR | nDCG@10 |
|---|---|---|---|---|
| R0 BM25 | 9 | 11 | 0,55 | 0,46 |
| R1 Dense | 15 | 19 | 0,84 | 0,74 |
| R2 Hybrid | 13 | 16 | 0,85 | 0,71 |
| R3 Hybrid + Reranker (heute) | 16 | 20 | 0,87 | 0,78 |
| R4 gleiche Vektoren in LanceDB | 16 | 20 | 0,87 | 0,78 |
| R5 nur Sparse | 12 | 15 | 0,64 | 0,51 |
| R5 nur Multi-Vektor | 17 | 21 | 0,87 | 0,78 |
| R5 Dense + Sparse + Multi-Vektor, ohne BM25 und Reranker | 18 | 20 | 0,94 | 0,81 |
| R5 dasselbe als Dense-Arm in Fusion und Reranker | 16 | 20 | 0,93 | 0,79 |

**Entscheidung nach der Regel aus § 2: keine Vektordatenbank.** R4 ändert nichts. R5 gewinnt in
Recall@10 höchstens 1 von 26 Sektionen statt der geforderten 3, und auch dieser Gewinn braucht keine
Vektordatenbank, nur die Repräsentation. Die Latenzschwelle reißt nur die heutige Ladeweise bei
rund 190-facher Korpusgröße (p95 275 ms), im Speicher sind es 13 ms.

**Skalierung** (1024 Dimensionen, mit Zufallsvektoren aufgefüllt, misst nur Latenz, p50):

| Zeilen | Heute (lädt je Suche neu) | NumPy im Speicher | LanceDB ANN | ANN-Recall@10 | Platz npy / Lance |
|---|---|---|---|---|---|
| 533 | 0,7 ms | 0,02 ms | 1,3 ms | 0,97 | 1,1 / 2,8 MB |
| 10 000 | 24 ms | 1,1 ms | 1,4 ms | 0,98 | 20 / 53 MB |
| 100 000 | 257 ms | 12 ms | 1,8 ms | 1,00 | 205 / 532 MB |

**Beobachtungen**

- H1.1 bestätigt: Gleiche Vektoren in LanceDB liefern dieselben Summenwerte wie R3.
- H1.2: Bei 100 000 Zeilen dauert die Suche im Speicher 12 ms. Die 257 ms kommen fast nur vom Neuladen
  von `vectors.json` und `vectors.npy` je Suche, das ließe sich ohne Datenbank beheben.
- R5 zeigt einen eigenen, kleineren Kandidaten: Die Kombination verbessert die vorderen Ränge (MRR 0,94 gegen 0,87,
  Recall@5 18 gegen 16) ohne Reranker. Das ist dünn: Der MRR-Gewinn kommt allein von F05 (bester Rang 1 statt 3), § 126 und § 157 findet auch R5 nicht. Es bräuchte
  eine Embedding-Laufzeit neben Ollama und ist eine eigene Entscheidung, keine Datenbankfrage.
- Im Verhältnis dazu ist das Reranking teuer: rund 6 s je Suche auf dem Mac (laut Doku 0,3 s auf der GPU).
- Unerwartet: Hybrid (16) liegt bei Recall@10 unter Dense allein (19), MRR etwas höher. Die Fusion zieht
  Dense-Treffer nach unten, etwa F02 Anlage 8 von Rang 5 auf 21 (mit Reranker 9).
- Zwei Sektionen findet kein Arm in den Top-60: § 126 StrlSchG und § 157 StrlSchV (beide F06). Sie sind
  nur über Verweise oder die Levels erreichbar.
- BM25 fällt bei F06 ganz aus, vermutlich wegen Komposita („Radonwerte“) und der Wortwahl „Arbeitgeber“.

**τ:** Nur über die Originale kalibriert −0,06, AUC 1,0, beantwortbar ab +1,56, nicht beantwortbar bis
−0,74 (9 und 14 Fragen). Geschrieben nur in die Scratch-Kopie.
## FF1 auf der RTX 4090: ganze Datenbank

Scratch-Kopie der `StrlSch_DE` der GPU-Maschine: StrlSchG, StrlSchV und neun weitere Quellen,
1492 Chunks der Originale (auf dem Mac nur die zwei Gesetze). Die Kopie hatte zunächst keine Vektoren
und wurde vor dem Lauf nachgerüstet; seither bettet jeder Ingest ein (Changelog 2026-11-09). Gold
`bench/fixture_study_StrlSch_DE_full.json`, gleiche Fragen, F03 auf `Anlage 4 (Teil 13)`, weil die
Tabelle hier anders geteilt ist. Rohdaten: `bench/results/study_ff1_{arms,lancedb,m3}_4090_91bba8c.json`.

| Arm | Recall@5 | Recall@10 (von 26) | MRR | nDCG@10 | p50 |
|---|---|---|---|---|---|
| R0 BM25 | 8 | 11 | 0,56 | 0,48 | 19 ms |
| R1 Dense | 14 | 18 | 0,89 | 0,76 | 98 ms |
| R2 Hybrid | 12 | 16 | 0,91 | 0,74 | 89 ms |
| R3 Hybrid + Reranker (heute) | 15 | 18 | 0,93 | 0,77 | 404 ms |
| R4 gleiche Vektoren in LanceDB | 15 | 18 | 0,93 | 0,77 | 380 ms |
| R5 nur Sparse | 14 | 16 | 0,75 | 0,62 | 358 ms |
| R5 nur Multi-Vektor | 16 | 20 | 0,94 | 0,81 | 337 ms |
| R5 Dense + Sparse + Multi-Vektor | 16 | 19 | 1,00 | 0,81 | 321 ms |
| R5 dasselbe in Fusion und Reranker | 15 | 18 | 1,00 | 0,80 | 712 ms |

| Zeilen | Heute (lädt je Suche neu) | NumPy im Speicher | LanceDB ANN | ANN-Recall@10 |
|---|---|---|---|---|
| 533 | 6 ms | 3 ms | 1,8 ms | 0,96 |
| 10 000 | 54 ms | 4,9 ms | 1,8 ms | 0,98 |
| 100 000 | 417 ms | 15 ms | 1,9 ms | 0,92 |

**Die Entscheidung bleibt: keine Vektordatenbank.** R4 liefert dieselben Werte wie R3. R5 gewinnt in
Recall@10 höchstens 2 von 26 Sektionen. Das Bild ist dasselbe wie auf dem Mac, trotz der neun
zusätzlichen Quellen. Die Latenz bei 100 000 Zeilen kommt wieder vom Neuladen je Suche, nicht von der
Suche selbst. Ohne Vektoren (vor dem Nachrüsten) fand Hybrid 11 statt 16 Sektionen in den Top 10, nur
über BM25.

## FF2 und FF3 auf der RTX 4090

Gemma `gemma4:e4b` im gepinnten Daemon auf GPU 1, fünf Fragen, drei Wiederholungen, also 15 Läufe
je Arm und 54 Pflichtfakten. Rohdaten ohne Antworttexte (sie zitieren lizenzierte Quellen der
Datenbank): `bench/results/study_deep_4090_2026-11-09.jsonl`.

Der erste Durchgang von E1 bis E4 ist verworfen. Das Bench-Skript startete jeden Lauf ohne Messwert
und ein Budget von 0 Zeichen, und es koppelte den Verlauf an den falschen LLM-Aufruf (Changelog
2026-11-09). E1 lief danach ein zweites Mal, weil die Karte während des ersten korrigierten Laufs
nur 66 statt rund 155 Tokens/s erzeugte.

| Arm | `num_ctx` | Fakten | Zeit Mittel | × E0 | Füllstand Mittel / Spitze (Median) | Trims | Abgeschnitten |
|---|---|---|---|---|---|---|---|
| E0 | 32768 | 33 | 90 s | 1,00 | 0,36 / 0,58 | 33 | 0 |
| E1 | 32768 | 24 | 77 s | 0,86 | 0,32 / 0,52 | 8 | 0 |
| E2 | 16384 | 29 | 81 s | 0,91 | 0,39 / 0,56 (max 0,98) | 153 | 1 |
| E3 | 65536 | 31 | 76 s | 0,85 | 0,17 / 0,28 | 0 | 0 |
| E4 | 131072 | 28 | 90 s | 1,01 | 0,10 / 0,15 | 0 | 0 |
| D1 ohne Referenzen | 32768 | 31 | 76 s | 0,84 | 0,32 / 0,54 | 21 | 0 |
| D2 nur Level 1 | 32768 | 23 | 65 s | 0,73 | 0,33 / 0,54 | 0 | 0 |
| D3 ohne Levels und Referenzen | 32768 | 24 | 72 s | 0,80 | 0,35 / 0,57 | 8 | 0 |
| D4 ohne Agent | 32768 | 8 | 26 s | 0,29 | 0,03 / 0,06 | 0 | 0 |

Fakten je Frage (Summe über drei Läufe):

| Arm | F02 (9) | F03 (6) | F05 (12) | F06 (18) | F10 (9) |
|---|---|---|---|---|---|
| E0 | 9 | 0 | 7 | 11 | 6 |
| E1 | 7 | 0 | 6 | 8 | 3 |
| E2 | 7 | 2 | 5 | 13 | 2 |
| E3 | 8 | 0 | 6 | 14 | 3 |
| E4 | 5 | 1 | 6 | 9 | 7 |
| D1 | 5 | 1 | 6 | 13 | 6 |
| D2 | 0 | 0 | 7 | 12 | 4 |
| D3 | 4 | 0 | 6 | 10 | 4 |
| D4 | 0 | 0 | 3 | 2 | 3 |

**VRAM** (nach den Läufen gemessen, Modell allein auf GPU 1 geladen): 5,0 GB bei 16k, 5,3 GB bei
32k, 5,7 GB bei 64k, 6,7 GB bei 128k. Kein Absturz bei 64k und 128k.

**FF2-Entscheidung: E0 bleibt.** Alle Arme liegen im Abstand von höchstens 0,6 Fakten je Frage und
Lauf hinter E0 (33), alle unter 1,2 × E0 und weit unter 22 GB. Der kleinste Kandidat E2 (16k)
scheidet aus: Ein Lauf füllte das Fenster zu 98 % und die Antwort wurde abgeschnitten
(`done_reason = length`), und F10 fiel von 6 auf 2 Fakten. Unter den 32k-Armen hat E0 die meisten
Fakten. FF3 musste deshalb nicht wiederholt werden.

| Hypothese | Ergebnis |
|---|---|
| H2.1 Fenster ungenutzt trotz Trims | Bestätigt: E0 trimmt in 3 von 15 Läufen, deren Spitze nur 68–76 % des Fensters erreicht |
| H2.2 Tabellen sprengen das Fenster | Nicht beobachtet: kein Prompt am Fensterrand, F03 höchstens 76 % |
| H2.3 Speicher begrenzt nicht | Bestätigt: 6,7 GB bei 128k |
| H2.4 Mehr Fenster bringt keine Fakten | Bestätigt: E3 31, E4 28 gegen 33 |
| H2.5 Token-Budget schlägt größeres Fenster | Nicht bestätigt: E1 hatte 24 und im verworfenen langsamen Lauf 30 Fakten |

**FF3-Entscheidung nach der Regel aus § 2:** Jeder Tiefenschritt kostet beim Abschalten Fakten auf
mindestens zwei Fragen und bleibt (D1: F02, F05; D2: F02, F10; D3: F02, F05, F06, F10). D4 halbiert
die Zeit, verliert aber 25 von 33 Fakten und wird kein Standardpfad.

| Hypothese | Ergebnis |
|---|---|
| H3.1 LLM-Turns dominieren | Bestätigt: 90–94 % der Zeit ist Textgenerierung, 2 % Prefill |
| H3.2 Direktlauf spart die Hälfte bei gleichen Fakten | Halb: 71 % Zeitgewinn, aber 8 statt 33 Fakten |
| H3.3 Trims brechen den Cache | Nicht messbar: Prefill ist mit 2 % der Zeit Nebensache |
| H3.4 Referenzen helfen bei F02 | Gestützt: F02 9 von 9 mit allen Schritten, 5 ohne Referenzen, 0 nur mit Level 1 |
| H3.5 Gate-Ablehnungen | Nicht getrennt ausgewertet |

**Der größte Hebel ist die Textmenge:** Ein E0-Lauf erzeugt in rund acht LLM-Aufrufen im Mittel 12 000 Tokens für eine Antwort
von etwa 680 Wörtern. Weniger oder kürzere Zwischenantworten sparen mehr Zeit als jede Fenster- oder
Tiefeneinstellung.

### Streuung

Zwei Läufe von E1 mit gleichem Code und gleicher Konfiguration fanden 30 und 24 Fakten. Unterschiede
von bis zu etwa sechs Fakten zwischen Armen sind also Rauschen. Belastbar sind nur die großen Abstände:
D4 gegen alle anderen und F02 unter D2 (0 von 9 in allen drei Läufen gegen 9 von 9 bei E0). Die Regel
„Abstand ≤ 1 Fakt je Frage“ ist bei 1,6 bis 2,2 Fakten je Frage und Lauf zu weit, um Fensterarme zu
trennen. Für eine schärfere Aussage bräuchte es mehr Wiederholungen oder mehr Fragen.

## Erster Deep-Chat-Lauf (Mac)

F10, Arm E0, Mac, ein einziger Lauf, also nur Hinweise. Rohdaten:
`bench/results/study_deep_smoke_mac_adbf8c6.jsonl`.

| Messgröße | Wert |
|---|---|
| Laufzeit, erste verwertbare Antwort | 1278 s, 880 s |
| Textgenerierung, Prompt-Aufbau | 1165 s (91 %), 72 s |
| Erzeugte Tokens bei 601 Wörtern Antwort | 19 838 |
| Füllstand des Fensters | Mittel 39 %, Maximum 67 %, kein Trim, kein Überlauf |
| Cache-Treffer | 7 von 10 Aufrufen |
| Pflichtfakten | 2 von 3 |

Offen ist, wohin die rund 20-fache Tokenmenge geht. Das ist der erste Prüfpunkt für FF3. Exit 134 am
Prozessende ist ein Absturz von `ggml-metal` beim Beenden, die Daten waren da schon geschrieben.
