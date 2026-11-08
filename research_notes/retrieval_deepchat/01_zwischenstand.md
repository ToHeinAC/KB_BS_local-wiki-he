# Zwischenstand der Messungen

Stand 2026-11-08. Rahmen: [00_framework.md](00_framework.md). **FF1 ist gemessen und entschieden, FF2
und FF3 warten auf die RTX 4090.**

## FF1: Retrieval

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

## Erster Deep-Chat-Lauf

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

## Plan für die RTX 4090

Der Mac schafft die 135 Läufe nicht (mindestens 48 h). Auf der 4090 rechne ich grob mit 5–7 h,
hochgerechnet aus 164 Tokens/s laut [gpu.md](../../docs/gpu.md).

**Achtung:** Auf der GPU-Maschine existiert laut Bench-Log vom 26.10. eine echte Datenbank `StrlSch_DE`.
Die Studienkopie darf nie nach `data/` dort. Sie gehört in einen eigenen Scratch-Ordner.

```bash
# 1. Auf dem Mac: die Studienkopie auf die Maschine, außerhalb von data/
rsync -a data/StrlSch_DE/ <host>:~/study_root/StrlSch_DE/

# 2. Auf der Maschine: Code holen, τ nur in der Kopie kalibrieren
git pull
export DATA_ROOT=~/study_root
uv run python scripts/calibrate_abstention.py --db StrlSch_DE --scope raw --write

# 3. Karte exklusiv: gepinnter Daemon, NUM_PARALLEL=1, Live-App auf dieser Karte aus

# 4. FF2 mit dem heutigen Fenster, dazu die FF3-Arme
uv run python scripts/bench_study_deep.py --arm E0 --arm E1 --arm D1 --arm D2 --arm D3 --arm D4 \
    --reps 3 --out runs.jsonl

# 5. Die Fenster-Arme, je Lauf eigener Wert
INGEST_NUM_CTX=16384  uv run python scripts/bench_study_deep.py --arm E2 --reps 3 --out runs.jsonl
INGEST_NUM_CTX=65536  uv run python scripts/bench_study_deep.py --arm E3 --reps 3 --out runs.jsonl
INGEST_NUM_CTX=131072 uv run python scripts/bench_study_deep.py --arm E4 --reps 3 --out runs.jsonl
```

Das Framework sieht vor, FF3 erst mit dem FF2-Sieger zu fahren. Der Befehl unter 4 mischt beides mit
dem heutigen Fenster. Weicht der FF2-Sieger von E0 ab, werden D1 bis D4 mit diesem Sieger wiederholt.
Die VRAM-Spitze während der Läufe getrennt mitschreiben, etwa mit `nvidia-smi -l 1` in eine Datei.
Ein Abbruch ist unkritisch, ein neuer Start überspringt die Zeilen, die in `runs.jsonl` stehen.
