# Ontologien in KI-Wissensmanagement und „Second Brains“

## Kurzantwort

Eine **Ontologie** ist im KI-Wissensmanagement kein Ordnerbaum und normalerweise auch keine Hierarchie von Dokumenten. Sie ist ein explizites Modell davon, **welche Arten von Dingen in einer Wissensdomäne existieren, wie sie benannt werden, welche Eigenschaften sie besitzen, in welchen Beziehungen sie stehen und welche Regeln für diese Aussagen gelten**. In OWL werden die Grundelemente als Klassen, Eigenschaften, Individuen und Axiome modelliert; OWL ist ausdrücklich für maschinenverarbeitbares Wissen und Schlussfolgern über eine Domäne gedacht.[^1][^2]

Eine Dokumentenhierarchie beantwortet etwa: „In welchem Ordner liegt diese PDF?“ Eine Ontologie beantwortet dagegen: „Ist dies eine Richtlinie, von welcher Organisation stammt sie, welche Anforderungen enthält sie, auf welches System und welchen Zeitraum beziehen diese sich, welche Fassung ersetzt sie, welche Entscheidung stützt sich darauf und welche Begriffe sind synonym?“

Der wichtigste Unterschied lautet daher:

- **Dokumentstruktur organisiert Informationsbehälter.**
- **Eine Ontologie strukturiert die Bedeutung der darin vorkommenden Dinge und Aussagen.**
- **Ein Knowledge Graph speichert konkrete Dinge und Aussagen entsprechend diesem Modell.**
- **Embeddings ermöglichen Ähnlichkeitssuche, definieren aber keine belastbare Semantik.**

## Ein präzises Begriffsmodell

### Ontologie

In der Wissensrepräsentation ist eine Ontologie eine formale, explizite Beschreibung einer gemeinsamen Konzeptualisierung einer Domäne. „Explizit“ bedeutet, dass Begriffe und Beziehungen tatsächlich definiert werden; „formal“ bedeutet, dass die Darstellung maschinell interpretierbare Semantik besitzt; „gemeinsam“ bedeutet, dass die verwendeten Begriffe nicht bloß private, implizite Bedeutungen eines einzelnen Nutzers sind.[^3][^4]

Eine Ontologie kann sehr leichtgewichtig sein, beispielsweise eine Liste von Entitätstypen und erlaubten Relationen. Sie kann aber auch als OWL-Ontologie logische Axiome enthalten, aus denen ein Reasoner neue Aussagen ableitet oder Widersprüche erkennt.[^2][^5]

### Knowledge Graph

Ein Knowledge Graph enthält üblicherweise die **konkreten Entitäten und Beziehungen**, zum Beispiel:

```text
Projekt_A  verwendet             Modell_Mistral
Modell_Mistral  istInstanzVon    Sprachmodell
Dokument_17  beschreibt          Projekt_A
Dokument_17  wurdeErstelltVon    Tobias
Anforderung_42  giltFür          Projekt_A
Entscheidung_8  basiertAuf       Anforderung_42
```

Im RDF-Modell wird eine Aussage als Tripel aus **Subjekt, Prädikat und Objekt** repräsentiert; eine Menge solcher Tripel bildet einen RDF-Graphen. Der Graph ist somit die konkrete Wissensbasis, während die Ontologie die Bedeutung und zulässige Verwendung von Typen und Beziehungen beschreibt.[^6]

### TBox und ABox

Eine nützliche technische Trennung ist:

- **TBox – terminologisches Wissen:** Klassen, Relationstypen, Hierarchien und allgemeine Axiome, etwa „Jede technische Richtlinie ist ein Dokument“ oder „`arbeitetAn` verbindet Personen mit Projekten“.
- **ABox – assertionales Wissen:** konkrete Tatsachen, etwa „Tobias arbeitet an Projekt X“ oder „Dokument D ist eine technische Richtlinie“.

Diese Trennung entspricht praktisch **Schema/Begriffsmodell** versus **Instanzdaten/Fakten**. OWL selbst beschreibt Ontologien durch Axiome über Klassen, Eigenschaften, Individuen und Datenwerte.[^7][^2]

## Was keine Ontologie ist

| Konstrukt | Hauptfrage | Typische Struktur | Beispiel | Verhältnis zur Ontologie |
|---|---|---|---|---|
| Ordnerbaum | Wo liegt eine Datei? | Verzeichnis/Unterverzeichnis | `Projekte/AI/RAG/` | Kann separat bestehen; modelliert primär Ablageorte. |
| Dokumenthierarchie | Welches Dokument gehört unter welches? | Baum oder Sammlung | Handbuch → Kapitel → Abschnitt | Kann als Teil-Ganzes-Modell in einer Ontologie beschrieben werden, ist aber nicht deren Kern. |
| Tags/Folksonomy | Welche freien Stichwörter passen? | Unkontrollierte Labels | `#rag`, `#local-ai` | Einfach und flexibel, aber häufig synonym-, mehrdeutigkeits- und qualitätsanfällig. |
| Kontrolliertes Vokabular | Welche standardisierten Wörter dürfen verwendet werden? | Autorisierte Begriffsliste | bevorzugt „Sprachmodell“, Alias „LLM“ | Kann die lexikalische Schicht einer Ontologie bilden. Dublin Core empfiehlt kontrollierte Vokabulare für Themenangaben.[^8] |
| Taxonomie | Was ist allgemeiner oder spezieller? | Ober-/Unterbegriffe | Sprachmodell → lokales Sprachmodell | Ist eine hierarchische Wissensordnung; eine Ontologie geht durch typisierte Relationen und Regeln darüber hinaus.[^9][^10] |
| Thesaurus | Welche Begriffe sind breiter, enger, verwandt oder synonym? | Hierarchie plus Assoziationen | LLM ↔ Sprachmodell; RAG ↔ Information Retrieval | SKOS unterstützt bevorzugte Labels sowie `broader`/`narrower`; noch keine umfassende Domänenlogik.[^11][^12] |
| Datenbankschema | Welche Felder, Tabellen und Datentypen gibt es? | Tabellen/Spalten oder JSON-Schema | `documents(id,title,date)` | Regelt Speicherstruktur und Integrität; die fachliche Semantik kann geringer oder nur anwendungslokal sein. |
| Ontologie | Welche Arten von Dingen und Beziehungen gelten fachlich, und was folgt daraus? | Klassen, Eigenschaften, Axiome, Einschränkungen | Entscheidung `basiertAuf` Evidenz; Richtlinie `ersetzt` ältere Fassung | Bedeutungs- und Schlussfolgerungsmodell. |
| Knowledge Graph | Welche konkreten Dinge und Aussagen kennen wir? | Knoten und typisierte Kanten | Entscheidung 8 `basiertAuf` Quelle 17 | Instanziiert häufig eine Ontologie, muss aber nicht streng ontologiebasiert sein. |
| Embedding-/Vektorraum | Welche Inhalte sind semantisch ähnlich? | Vektoren und Distanzmaße | ähnliche Textabschnitte zu „lokales RAG“ | Statistische Retrieval-Schicht; keine expliziten Identitäts-, Gültigkeits- oder Beziehungsregeln. |

Eine Taxonomie kann also **Teil einer Ontologie** sein, nämlich die Klassenhierarchie. Die Ontologie ergänzt jedoch Relationstypen wie `verursacht`, `widerspricht`, `erfüllt`, `ersetzt`, `istVersionVon`, `giltFür` oder `wurdeAbgeleitetAus` und legt deren Semantik fest.[^13][^1]

## Was eine Ontologie regelt

### Gegenstandsarten und Klassen

Klassen legen fest, welche Arten von Entitäten im Modell vorkommen. Eine Klasse bezeichnet eine Menge von Individuen mit gemeinsamen Eigenschaften; Individuen sind konkrete Mitglieder dieser Klassen.[^14][^1]

Für ein technisches Second Brain könnten Klassen sein:

- `Person`, `Organisation`, `Team`
- `Projekt`, `Arbeitspaket`, `Aufgabe`, `Meilenstein`
- `Dokument`, `Notiz`, `E-Mail`, `Quellcode`, `Datensatz`
- `Thema`, `Methode`, `Technologie`, `Software`, `Hardware`
- `Anforderung`, `Behauptung`, `Evidenz`, `Annahme`
- `Entscheidung`, `Alternative`, `Risiko`, `Maßnahme`
- `Ereignis`, `Meeting`, `Experiment`, `Beobachtung`
- `Norm`, `Gesetz`, `Richtlinie`, `Genehmigung`

Die Auswahl ist eine fachliche Entscheidung: In einem regulatorischen Wissenssystem ist `Anforderung` zentral, in einem Literatur-Second-Brain eher `Publikation`, `Autor`, `These`, `Methode` und `Ergebnis`.

### Instanzen und Identität

Instanzen sind konkrete Dinge: nicht die Klasse `Projekt`, sondern das Projekt „Lokales RAG 2026“; nicht `Person`, sondern eine bestimmte Person. Eine Ontologie kann auch Identitätsaussagen festhalten, etwa dass „IBM“ und „International Business Machines“ dieselbe Organisation bezeichnen; OWL stellt dafür unter anderem `sameAs` und `differentFrom` bereit.[^15]

Diese Schicht regelt:

- Kanonische IDs statt bloßer Namen
- Aliasnamen, Abkürzungen und Schreibvarianten
- Deduplizierung von Entitäten
- Trennung gleichnamiger Personen oder Produkte
- Abgleich mit externen Norm-, Produkt- oder Organisations-IDs

Gerade bei LLM-Extraktion ist dies entscheidend: Ohne Entity Resolution können „Postgres“, „PostgreSQL“ und „PG“ als drei Knoten entstehen. Graph-RAG-Pipelines normalisieren deshalb extrahierte Bezeichnungen auf kanonische Entitäten.[^16]

### Typisierte Beziehungen

Die größte Erweiterung gegenüber einer Hierarchie sind **fachlich benannte Beziehungen**. OWL unterscheidet Beziehungen zwischen Individuen von Eigenschaften, die Individuen mit Datenwerten verbinden.[^2]

Beispiele:

| Beziehung | Quelle → Ziel | Bedeutung |
|---|---|---|
| `arbeitetAn` | Person → Projekt | Beteiligung einer Person an einem Projekt |
| `verwendet` | Projekt → Technologie | Technische Abhängigkeit oder Einsatz |
| `enthältBehauptung` | Dokument → Behauptung | Aussage ist in einer Quelle enthalten |
| `stützt` | Evidenz → Behauptung | Evidenz spricht für eine Behauptung |
| `widerspricht` | Behauptung → Behauptung | Zwei Aussagen sind inhaltlich unvereinbar |
| `entscheidetÜber` | Entscheidung → Fragestellung | Gegenstand einer Entscheidung |
| `bevorzugtAlternative` | Entscheidung → Alternative | ausgewählte Option |
| `erfüllt` | System → Anforderung | nachgewiesene Konformität |
| `ersetzt` | Dokumentversion → Dokumentversion | Nachfolge- oder Ablösebeziehung |
| `wurdeAbgeleitetAus` | Artefakt → Quelle | Provenienz einer Information |
| `giltWährend` | Regel → Zeitraum | zeitliche Gültigkeit |
| `istTeilVon` | Komponente → System | mereologische Teil-Ganzes-Beziehung |

Hierarchische Beziehungen sind nur ein Sonderfall. Außerdem muss zwischen unterschiedlichen „Hierarchien“ unterschieden werden:

- **Unterklasse:** Ein `LLM` ist eine Art `KI-Modell`.
- **Instanz:** `Mistral Small` ist ein konkretes `LLM`, nicht dessen Unterklasse.
- **Teil-Ganzes:** Ein Kapitel ist Teil eines Dokuments, aber keine Unterklasse von Dokument.
- **Themenzuordnung:** Ein Dokument handelt von RAG, ist aber nicht selbst ein RAG-System.
- **Ablagestruktur:** Eine PDF liegt in einem Ordner, was keine fachliche „ist-ein“-Beziehung impliziert.

Viele schlechte Wissensmodelle vermischen genau diese fünf Bedeutungen in einer einzigen Parent-Child-Kante.

### Attribute und Datentypen

Datatype Properties verknüpfen Entitäten mit Literalwerten wie Text, Zahlen, Datumsangaben oder Wahrheitswerten.[^14][^2]

Beispiele:

- `Dokument.hatTitel: String`
- `Dokument.veröffentlichtAm: Date`
- `Behauptung.konfidenz: Decimal`
- `Aufgabe.fälligAm: DateTime`
- `Modell.parameterzahl: Integer`
- `Quelle.sprache: LanguageCode`

Eine Ontologie kann dabei mehr ausdrücken als eine Feldliste: Sie kann bestimmen, **für welchen Entitätstyp** ein Attribut sinnvoll ist, **welcher Wertebereich** gilt und ob das Attribut funktional, optional oder mehrfach vorkommend ist. RDFS stellt hierfür unter anderem `domain`, `range`, `subClassOf` und `subPropertyOf` bereit.[^13]

### Hierarchien und Vererbung

Ontologien können Klassen- und Eigenschaftshierarchien enthalten:

```text
RegulatorischesDokument  UnterklasseVon  Dokument
Genehmigung              UnterklasseVon  RegulatorischesDokument

stützt                    UntereigenschaftVon  beziehtSichAuf
widerlegt                 UntereigenschaftVon  widerspricht
```

Wenn jede Genehmigung ein regulatorisches Dokument und jedes regulatorische Dokument ein Dokument ist, folgt, dass jede Genehmigung ein Dokument ist. RDFS definiert `subClassOf` so, dass alle Instanzen der Unterklasse auch Instanzen der Oberklasse sind.[^17][^13]

Das ist also durchaus hierarchisch, aber es handelt sich primär um eine **Begriffshierarchie**, nicht um einen Dateibaum.

### Definitionsregeln

Eine Klasse kann nicht nur per Name, sondern durch notwendige oder hinreichende Bedingungen beschrieben werden. Beispiel:

```text
KritischeAnforderung := Anforderung,
                        die mindestens ein KritischesSystem betrifft
                        und deren Nichterfüllung ein HohesRisiko erzeugt
```

Ein Reasoner könnte eine konkrete Anforderung automatisch als `KritischeAnforderung` klassifizieren, sobald die erforderlichen Fakten vorhanden sind. OWL unterstützt Klassenbeschreibungen, Eigenschaftseinschränkungen und Axiome für solche Schlussfolgerungen.[^18][^5]

### Kardinalitäten

Kardinalitäten regeln, wie viele Werte eine Beziehung haben darf oder haben muss:

- Jede Entscheidung hat **genau einen** Entscheidungsstatus.
- Eine Anforderung hat **mindestens eine** Quelle.
- Ein Dokument kann **mehrere** Autoren haben.
- Eine freigegebene Fassung hat **höchstens einen** direkten Vorgänger.

OWL kann Mindest-, Höchst- und exakte Kardinalitäten ausdrücken; solche Restriktionen sind Teil der logischen Klassenbeschreibung.[^19][^5]

Wichtig ist die Unterscheidung zwischen **logischer Bedeutung** und **Datenvalidierung**. In einer Open-World-Logik bedeutet eine fehlende Quelle nicht automatisch, dass keine Quelle existiert. Soll das System unvollständige Datensätze als Fehler melden, wird üblicherweise zusätzlich eine Validierungsschicht wie SHACL eingesetzt.

### Domain und Range

Domain und Range beschreiben, welche Arten von Subjekten und Objekten zu einer Relation gehören. Für

```text
arbeitetAn(Person, Projekt)
```

ist `Person` die Domain und `Projekt` die Range. In RDFS sind Domain und Range semantische Inferenzregeln: Wenn `x arbeitetAn y`, kann daraus folgen, dass `x` eine Person und `y` ein Projekt ist.[^13]

Das ist subtil: Domain/Range sind nicht automatisch Formularvalidierungen. Für die Aussage „`arbeitetAn` darf ausschließlich bei Personen verwendet werden und ein fehlendes Projekt ist ein Fehler“ ist SHACL meist das passendere Werkzeug.

### Eigenschaften von Beziehungen

Ontologien können die Semantik einer Relation weiter charakterisieren:

- **Inverse Relation:** `arbeitetAn` ↔ `hatMitarbeiter`
- **Symmetrisch:** Wenn A `istVerwandtMit` B, dann B auch mit A
- **Transitiv:** Wenn A `istTeilVon` B und B `istTeilVon` C, dann unter geeigneter Modellierung A `istTeilVon` C
- **Funktional:** Eine Entität hat über diese Eigenschaft höchstens einen Wert
- **Inverse-funktional:** Ein bestimmter Wert identifiziert höchstens eine Entität
- **Disjunkt:** `AktivesProjekt` und `ArchiviertesProjekt` dürfen sich bei entsprechendem Statusmodell nicht überlappen

OWL stellt unter anderem inverse, transitive, funktionale und inverse-funktionale Eigenschaften bereit. Solche Festlegungen ermöglichen Schlussfolgerungen, können bei falscher Modellierung aber auch unerwartet viele Aussagen erzeugen.[^20][^5]

### Gleichheit, Verschiedenheit und Disjunktheit

Eine Ontologie kann festlegen:

- Zwei Identifikatoren meinen dasselbe Individuum.
- Zwei Individuen sind ausdrücklich verschieden.
- Zwei Klassen sind disjunkt.
- Zwei Klassen oder Eigenschaften sind äquivalent.

Das ist für Deduplizierung und Konsistenz wichtig. `owl:sameAs` ist jedoch eine sehr starke Aussage: Alle Eigenschaften beider Identifikatoren gelten dann für dieselbe Entität; eine bloße Ähnlichkeit oder ungefähre Übereinstimmung sollte daher nicht als Identität modelliert werden.[^21][^15]

### Benennungen und Synonyme

Die lexikalische Ebene regelt, wie Konzepte genannt und gefunden werden:

- Bevorzugtes Label: „Retrieval-Augmented Generation“
- Alternative Labels: „RAG“, „retrievalgestützte Generierung“
- Versteckte Suchformen und häufige Tippfehler
- Sprachvarianten: Deutsch/Englisch
- Definition und Scope Note
- Veraltete Begriffe

SKOS sieht dafür unter anderem `prefLabel`, `altLabel`, `hiddenLabel`, `broader` und `narrower` vor. Diese Ebene ist für ein bilingual genutztes Second Brain besonders wertvoll, weil die Benutzeroberfläche mit verständlichen Bezeichnungen arbeiten kann, während die interne Entität eine stabile ID behält.[^11][^12]

### Kontext und Geltungsbereich

Eine nackte Aussage wie „Modell X ist geeignet“ ist meist zu grob. Ein belastbares Wissenssystem muss den Kontext repräsentieren:

- geeignet **für welchen Use Case**,
- unter **welchen Hardwarebedingungen**,
- gemessen mit **welcher Methode**,
- zu **welchem Zeitpunkt**,
- laut **welcher Quelle**,
- mit **welcher Konfidenz**,
- für **welche Organisation oder Jurisdiktion**.

Dafür kann eine Aussage als eigene Entität `Claim` modelliert werden. Sie erhält Relationen zu Quelle, Autor, Bewertungsmethode, Zeitintervall, Geltungsbereich und Gegenbehauptungen. Das vermeidet, dass kontextabhängige Aussagen als universelle Eigenschaften direkt an einer Entität hängen.

### Zeit und Versionen

Zeit ist mehr als ein `created_at`-Feld. Ein Modell kann unterscheiden:

- Veröffentlichungszeit einer Quelle
- Zeitpunkt eines Ereignisses
- Zeitraum, in dem eine Regel gilt
- Erfassungszeit im Second Brain
- Versionierungszeit einer Datei
- Zeitpunkt, auf den sich eine Aussage bezieht

OWL-Time unterscheidet Zeitpunkte und Intervalle und stellt Beziehungen zu Beginn, Ende, Dauer und zeitlicher Position bereit. Für Dokumente und Entscheidungen sind außerdem Relationen wie `istVersionVon`, `ersetzt`, `wurdeUngültigDurch` und `giltAb` wichtig.[^22]

### Provenienz und Verantwortlichkeit

Provenienz beantwortet „Woher kommt diese Aussage, wer hat sie erzeugt und wodurch wurde sie verändert?“ PROV-O modelliert dafür insbesondere `Entity`, `Activity` und `Agent`; Aktivitäten können Entitäten verwenden und erzeugen, während Agenten Verantwortung für Aktivitäten oder Entitäten tragen.[^23][^24]

Für ein KI-Second-Brain sollte mindestens gespeichert werden:

- Quelldokument und genaue Fundstelle
- Import- oder Extraktionsprozess
- verwendetes Modell und Prompt-/Pipeline-Version
- Extraktionsdatum
- menschliche Prüfung und Prüfer
- abgeleitete beziehungsweise zusammengefasste Vorgänger
- Konfidenz und Validierungsstatus

So lässt sich unterscheiden, ob eine Aussage direkt aus einem Primärdokument stammt, durch ein LLM extrahiert, von einem Menschen bestätigt oder aus mehreren Aussagen synthetisiert wurde.

### Datenqualität und Validierung

Eine Ontologie beschreibt Semantik; eine **Shape-/Constraint-Schicht** prüft, ob konkrete Daten die erwartete Struktur erfüllen. SHACL ist eine W3C-Sprache zur Validierung von RDF-Graphen gegen Bedingungen, die in Shapes formuliert werden.[^25]

Beispiele für SHACL-Regeln:

- Jede `Behauptung` braucht mindestens eine `Quelle`.
- `veröffentlichtAm` muss ein Datum sein.
- Eine `Entscheidung` braucht einen Status aus einer kontrollierten Werteliste.
- Eine freigegebene Anforderung muss einen Verantwortlichen besitzen.
- Der Gegenstand von `ersetzt` muss ein Dokument oder eine Dokumentfassung sein.

Die Kombination ist praxisnah:

- **OWL/RDFS:** Was bedeutet das Wissen und was lässt sich daraus folgern?
- **SHACL:** Welche Angaben müssen in dieser Anwendung tatsächlich vorhanden und formal korrekt sein?

### Regeln und Ableitungen

Regeln können neues Wissen erzeugen, beispielsweise:

```text
Wenn eine Anforderung für System S gilt
und Komponente K Teil von S ist,
dann ist zu prüfen, ob die Anforderung auch K betrifft.
```

Nicht jede Regel gehört direkt in OWL. Je nach Zweck kommen OWL-Axiome, regelbasierte Systeme, SPARQL-Konstruktionen, SHACL Rules oder Anwendungslogik infrage. Entscheidend ist, zwischen folgenden Kategorien zu unterscheiden:

- **Definition:** Was ist eine kritische Anforderung?
- **Inferenz:** Welche neue Aussage folgt logisch?
- **Validierung:** Welche fehlende oder falsche Angabe ist ein Datenfehler?
- **Workflow-Regel:** Welche Aktion soll die Software ausführen?
- **Zugriffsregel:** Wer darf die Information lesen oder verändern?

Diese Kategorien werden in Marketingtexten oft sämtlich als „Ontology Rules“ bezeichnet, obwohl sie technisch unterschiedliche Semantiken besitzen.

### Rechte und Nutzungspolitik

Ein Wissensmodell kann auch Rechte ausdrücken: Wer darf ein Asset lesen, verändern, weitergeben oder für Modelltraining verwenden? ODRL modelliert Policies mit Permissions, Prohibitions und Duties für Aktionen auf Assets.[^26][^27]

Für ein Second Brain oder Enterprise-KM betrifft dies etwa:

- Persönlich, Team-intern, vertraulich oder öffentlich
- Darf in externe LLM-APIs übertragen werden?
- Darf als Trainingsmaterial dienen?
- Muss vor Nutzung anonymisiert werden?
- Welche Aufbewahrungs- oder Löschpflicht gilt?

Das ist nicht zwingend Teil der fachlichen Kernontologie, kann aber als angebundene Policy-Ontologie modelliert werden.

### Dokument- und Ressourcenmetadaten

Dokumente verschwinden nicht aus dem Modell. Sie werden lediglich **eine Entitätsart unter mehreren**. Dublin Core bietet allgemeine Metadaten wie Titel, Urheber, Thema, Datum, Format, Identifier, Relation und Rechte.[^28][^29]

Eine robuste Dokumentebene unterscheidet idealerweise:

- abstraktes Werk beziehungsweise intellektueller Inhalt,
- konkrete Edition oder Version,
- physische oder digitale Datei,
- extrahierter Text,
- Chunk oder Abschnitt,
- in diesem Abschnitt vorkommende Behauptungen und Entitäten.

Damit kann dieselbe Publikation als PDF, HTML und OCR-Text existieren, ohne dreimal als inhaltlich unabhängiges Werk behandelt zu werden.

## Die wichtigsten Achsen

Eine nützliche Ontologie für ein Second Brain regelt typischerweise mehrere voneinander unabhängige Achsen:

| Achse | Leitfrage | Typische Konstrukte |
|---|---|---|
| Fachliche Typen | Was für ein Ding ist es? | Person, Projekt, Anforderung, Technologie |
| Begriffsordnung | Was ist allgemeiner oder spezieller? | Unterklasse, Oberbegriff, Taxonomie |
| Mereologie | Woraus besteht etwas? | Teil-von, enthält, Komponente |
| Themenbezug | Wovon handelt etwas? | Thema, erwähnt, beschreibt |
| Semantische Relation | Wie hängen Dinge fachlich zusammen? | nutzt, verursacht, erfüllt, widerspricht |
| Identität | Sind zwei Bezeichnungen dasselbe Ding? | kanonische ID, Alias, same-as |
| Dokumentstruktur | Wo steht die Information? | Dokument, Abschnitt, Chunk, Seitenanker |
| Provenienz | Woher stammt sie? | Quelle, Agent, Aktivität, Ableitung |
| Evidenz | Wie ist sie begründet? | Claim, Evidence, supports, refutes |
| Zeit | Wann geschah oder galt etwas? | Zeitpunkt, Intervall, gültig-ab/bis |
| Version | Was wurde geändert oder ersetzt? | Version, Revision, Nachfolger |
| Qualität | Wie sicher und vollständig ist es? | Konfidenz, Reviewstatus, Validierungsregel |
| Normativität | Muss, darf oder soll etwas geschehen? | Anforderung, Verbot, Erlaubnis, Pflicht |
| Zugriff | Wer darf was tun? | Rolle, Berechtigung, Policy |
| Workflow | Was folgt als Handlung? | Aufgabe, Entscheidung, Freigabe, Status |

Die Ontologie ist somit eher ein **mehrdimensionales semantisches Koordinatensystem** als ein Baum.

## Beispiel für ein Second Brain

Angenommen, eine PDF enthält den Satz:

> Für produktive lokale RAG-Systeme muss der verwendete Embedding-Dienst versioniert und seine Modellkennung dokumentiert werden.

Ein dokumentzentriertes System speichert vielleicht nur:

```text
/AI/RAG/Architektur/leitlinie.pdf
Tags: RAG, Embeddings, Produktion
```

Ein ontologiebasiertes System könnte daraus erzeugen:

```text
Dokument_17       rdf:type             TechnischeRichtlinie
Dokument_17       hatVersion           "2.1"
Dokument_17       enthält              Anforderung_42
Anforderung_42    rdf:type             Dokumentationsanforderung
Anforderung_42    betrifft             EmbeddingDienst
Anforderung_42    verlangtDokumentationVon Modellkennung
Anforderung_42    verlangtDokumentationVon Modellversion
Anforderung_42    giltFür              ProduktivesRAGSystem
Anforderung_42    hatModalität         Muss
Anforderung_42    belegtDurch          Textstelle_17_4
Textstelle_17_4   istTeilVon           Dokument_17
Extraktion_901    verwendeteEntität    Textstelle_17_4
Extraktion_901    warAssoziiertMit     LLM_Pipeline_v3
Anforderung_42    reviewStatus         MenschlichBestätigt
```

Darauf lassen sich Fragen beantworten, die über Volltextsuche und Ordner hinausgehen:

- Welche Muss-Anforderungen betreffen Embeddings in produktiven Systemen?
- Welche Anforderungen haben noch keinen Nachweis?
- Welche Entscheidungen basieren auf inzwischen ersetzten Richtlinien?
- Welche Aussagen wurden nur automatisch extrahiert und noch nicht bestätigt?
- Welche Projekte nutzen Komponenten, für die neue regulatorische Anforderungen gelten?

## Ontologie, Graph und RAG

### Klassisches Vektor-RAG

Klassisches RAG zerlegt Dokumente in Chunks, erzeugt Embeddings und sucht zur Nutzerfrage semantisch ähnliche Passagen. Das ist stark bei sprachlicher Ähnlichkeit, Varianten in der Formulierung und offenen Fragen, aber schwächer bei exakten mehrstufigen Beziehungen, Identitätsauflösung, Negation, Versionen und globalen Überblicksfragen.

### Ontologiegestütztes RAG

Eine Ontologie kann RAG an mehreren Stellen verbessern:

- **Ingestion:** erwartete Entitätstypen und Relationen leiten die Extraktion.
- **Entity Linking:** Erwähnungen werden auf kanonische Entitäten abgebildet.
- **Chunk-Anreicherung:** Chunks erhalten fachliche Typen, Themen, Quellen und Gültigkeitskontext.
- **Query Understanding:** Die Nutzerfrage wird in Entitäten, Relationstypen und Filter zerlegt.
- **Graph Retrieval:** Das System verfolgt relevante Kanten und mehrstufige Pfade.
- **Hybrid Retrieval:** Vektorsuche, Volltext, Metadatenfilter und Graphtraversierung werden kombiniert.
- **Grounding:** Antworten werden mit konkreten Quellen, Behauptungen und Provenienz verbunden.
- **Validierung:** Extrahierte Daten werden gegen Shapes oder fachliche Regeln geprüft.

Microsoft beschreibt GraphRAG als Kombination aus Textextraktion, Netzwerk-/Graphanalyse, hierarchischen Communities und Zusammenfassungen; beim Indexieren werden Entitäten, Beziehungen und zentrale Claims aus Textsegmenten extrahiert. Das zeigt zugleich eine wichtige Abgrenzung: Ein automatisch extrahierter Knowledge Graph ist nicht automatisch eine sauber kuratierte OWL-Ontologie. GraphRAG kann Graphstrukturen verwenden, ohne eine starke formallogische Domänenontologie vorauszusetzen.[^30][^31]

### Komplementäre Retrieval-Signale

Eine praxisnahe Architektur verwendet nicht „Graph statt Vektor“, sondern mehrere Signale:

1. **Lexikalisch:** exakte Begriffe, Kennzeichen, Paragraphen und Modellnamen.
2. **Semantisch:** ähnliche Bedeutung über Embeddings.
3. **Strukturell:** Nachbarschaften und Pfade im Knowledge Graph.
4. **Metadatenbasiert:** Datum, Quelle, Autor, Dokumenttyp und Sicherheitsklasse.
5. **Logisch:** abgeleitete Klassen und Relationen.
6. **Provenienzbasiert:** nur bestätigte oder primäre Quellen.

Graph-augmented RAG kombiniert entsprechend Vektorsuche und Graphtraversierung, um neben semantischer Ähnlichkeit auch Beziehungen, Zitationsketten und mehrstufige Pfade zu berücksichtigen.[^16]

## Modellierungsfallen

### Dokumente mit Wissen verwechseln

Ein Dokument ist eine Quelle oder ein Informationsträger, nicht automatisch das Wissen selbst. Zwei Dokumente können dieselbe Behauptung enthalten; ein Dokument kann sich selbst widersprechen; eine Behauptung kann in einer neueren Fassung widerrufen werden.

**Besser:** `Dokument → enthält → Claim → beziehtSichAuf → Entität` und `Claim → belegtDurch → Textstelle`.

### Themen mit Dingen verwechseln

„RAG“ kann je nach Kontext ein Thema, eine Technologieklasse, ein konkretes System oder eine Projektkomponente meinen.

**Besser:** getrennte Typen und Relationen verwenden, beispielsweise `Dokument handeltVon RAG` versus `System implementiert RAGArchitektur`.

### Alles in eine Taxonomie pressen

`Projekt → Dokument → Entscheidung → Person` ist keine sinnvolle Klassenhierarchie. Diese Dinge stehen in unterschiedlichen Relationen und sollten nicht über eine generische Parent-Child-Struktur verbunden werden.

**Besser:** `Person arbeitetAn Projekt`, `Dokument dokumentiert Projekt`, `Entscheidung betrifft Projekt`.

### Zu frühe Vollformalisierung

Eine umfassende OWL-Ontologie vor echten Anwendungsfragen zu entwickeln, führt häufig zu hohem Pflegeaufwand und geringer Nutzung.

**Besser:** mit Kompetenzfragen beginnen. Kompetenzfragen sind Anforderungen in Frageform, die eine Ontologie beantworten können soll, und dienen der Abgrenzung sowie Validierung des Modells.[^32][^33]

### Open-World-Semantik übersehen

In semantischen Websprachen bedeutet „nicht bekannt“ typischerweise nicht automatisch „falsch“. Fehlende Daten sind daher nicht ohne Weiteres Regelverletzungen.

**Besser:** OWL für Semantik und Inferenz, SHACL beziehungsweise Applikationsregeln für Vollständigkeits- und Eingabeprüfungen verwenden.[^34][^25]

### `sameAs` zu großzügig verwenden

Ähnliche Namen, ähnliche Produkte oder verschiedene Versionen sind nicht zwingend identisch. Eine falsche Identitätsaussage verschmilzt alle Eigenschaften der Entitäten.[^15][^21]

**Besser:** schwächere Relationen wie `wahrscheinlichIdentischMit`, `entsprichtUngefähr`, `istVersionVon` oder kuratierte Mapping-Entitäten mit Konfidenz verwenden.

### LLM-Extraktionen als Fakten behandeln

Ein LLM kann Entitäten, Relationen oder Claims falsch extrahieren. Das Ergebnis sollte deshalb einen Status wie `vorgeschlagen`, `automatischExtrahiert`, `menschlichBestätigt` oder `verworfen` sowie Provenienz tragen.

**Besser:** Aussagen reifizieren oder als Claim-Entitäten modellieren, Konfidenz speichern, Validierungsregeln anwenden und die Textstelle beibehalten.

### Semantik und Workflow vermischen

„Eine Entscheidung hat einen Autor“ ist ein fachliches Modell. „Nach dem Speichern sende eine E-Mail“ ist Prozesslogik. „Nur Teamleiter dürfen freigeben“ ist Autorisierung.

**Besser:** Ontologie, Datenvalidierung, Workflow-Engine und Access Control als getrennte, aber verbundene Schichten behandeln.

## Empfohlenes Schichtenmodell

Für eine moderne KI-Wissensmanagement-Lösung ist folgende Trennung robust:

| Schicht | Aufgabe | Mögliche Technik |
|---|---|---|
| Rohquellen | Originale unverändert aufbewahren | Dateispeicher, Git, DMS, Object Store |
| Dokumentmodell | Werk, Version, Datei, Abschnitt, Chunk | Dublin Core, eigenes Schema, DCAT bei Datensätzen |
| Lexikon | Labels, Synonyme, Sprachen, Definitionen | SKOS oder eigenes kontrolliertes Vokabular |
| Kernontologie | Klassen, Relationen, Axiome | RDFS/OWL oder Property-Graph-Schema |
| Wissensgraph | konkrete Entitäten, Claims und Beziehungen | RDF Triple Store oder Property Graph |
| Provenienz | Quelle, Extraktion, Agent, Verarbeitung | PROV-O plus Pipeline-Metadaten |
| Validierung | Pflichtfelder und strukturelle Qualität | SHACL, JSON Schema, Pydantic |
| Suchindizes | Volltext- und Ähnlichkeitssuche | BM25, Vektorindex, Hybrid Search |
| Retrieval | Auswahl und Fusion des Kontexts | GraphRAG, Reranker, Query Planner |
| Anwendung | UI, Agenten, Workflows, Rechte | App-Logik, Policy Engine, ACL/RBAC |

RDF ist ein standardisiertes Graphmodell; SPARQL dient zur Abfrage von RDF-Graphen und kann Graphmuster, optionale Muster, Aggregation und Subqueries ausdrücken. Ein Property Graph mit Neo4j/Cypher kann für eine Anwendung ebenso sinnvoll sein; entscheidend ist, dass die Semantik explizit und konsistent bleibt, nicht dass zwingend OWL verwendet wird.[^35][^6]

## Ein pragmatisches Startmodell

Für ein persönliches oder kleines technisches Second Brain genügt zunächst ein **leichtgewichtiges semantisches Schema**.

### Kernklassen

- `Entity`: gemeinsame Oberklasse für identifizierbare Dinge
- `Person`, `Organization`
- `Project`, `Task`, `Decision`
- `Concept`, `Technology`, `Product`
- `Document`, `DocumentVersion`, `Section`, `Chunk`
- `Claim`, `Evidence`, `Requirement`
- `Event`, `TimeInterval`

### Kernrelationen

- `isA` nur für echte Typ-/Unterklassenbeziehungen
- `partOf` für Teil-Ganzes
- `about` für Themenbezug
- `mentions` für bloße Erwähnung
- `createdBy`, `ownedBy`, `responsibleFor`
- `worksOn`, `uses`, `dependsOn`
- `containsClaim`, `supports`, `contradicts`
- `derivedFrom`, `extractedFrom`
- `versionOf`, `supersedes`
- `validDuring`, `occurredAt`
- `requires`, `satisfies`

### Kernmetadaten

- stabile ID
- bevorzugtes Label und Aliase
- Beschreibung/Definition
- Erstellungs-, Änderungs- und Gültigkeitszeit
- Quelle und genaue Fundstelle
- Erzeuger beziehungsweise Bearbeiter
- Reviewstatus
- Konfidenz
- Sicherheits-/Zugriffsklasse

### Minimale Constraints

- Jeder Claim besitzt eine Quelle oder ist explizit als persönliche Annahme markiert.
- Jede automatisch extrahierte Relation besitzt Provenienz.
- Jede Entität hat eine stabile ID und mindestens ein Label.
- Jede Dokumentversion verweist auf ein Werk beziehungsweise eine Versionsfamilie.
- `partOf`, `isA`, `about` und `mentions` dürfen nicht als austauschbare Parent-Child-Beziehung verwendet werden.
- Freigegebene Anforderungen brauchen Verantwortlichkeit und Gültigkeitskontext.

## Vorgehen zur Entwicklung

### Kompetenzfragen formulieren

Nicht mit Klassen beginnen, sondern mit Fragen, die das Second Brain zuverlässig beantworten soll. Kompetenzfragen definieren den benötigten Umfang und können später als Akzeptanztests dienen.[^36][^32]

Beispiele:

- Welche Entscheidungen zu Projekt X beruhen auf Quelle Y?
- Welche Aussagen zu Modell Z widersprechen einander?
- Welche Anforderungen sind für System A gültig, aber noch nicht nachgewiesen?
- Welche Dokumente wurden nach einer Entscheidung aktualisiert?
- Welche Erkenntnisse wurden nur von einem LLM extrahiert und nie geprüft?
- Welche Komponenten hängen indirekt von einer abgekündigten Bibliothek ab?

### Begriffe und Entitäten trennen

Für jeden Kandidaten prüfen:

- Ist es eine Klasse, ein konkretes Individuum oder nur ein Label?
- Ist es ein Ding, ein Ereignis, eine Aussage, eine Rolle oder ein Dokument?
- Hat es eine eigene Identität und einen Lebenszyklus?
- Kann es mehrere Versionen geben?
- Ist es kontextabhängig?

### Relationen benennen

Generische Kanten wie `relatedTo` nur als Notlösung verwenden. Jede wichtige Beziehung sollte einen klaren Satz ergeben:

```text
Subjekt — Prädikat — Objekt
Entscheidung_8 — basiertAuf — Evidenz_12
System_A — erfüllt — Anforderung_42
Dokument_17 — ersetzt — Dokument_9
```

Für jede Relation festhalten:

- Definition
- erlaubte Quell- und Zieltypen
- inverse Relation
- zeitliche Gültigkeit
- Transitivität oder Symmetrie, falls wirklich fachlich korrekt
- Provenienzanforderung

### Bestehende Vokabulare wiederverwenden

Allgemeine Konzepte sollten möglichst nicht neu erfunden werden:

- **Dublin Core:** Dokument- und Ressourcenmetadaten[^28]
- **SKOS:** Begriffssysteme, Labels und Ober-/Unterbegriffe[^11]
- **PROV-O:** Provenienz, Aktivitäten und verantwortliche Agenten[^23]
- **OWL-Time:** Zeitpunkte, Intervalle und Dauer[^22]
- **DCAT:** Kataloge, Datensätze und Distributionen[^37]
- **ODRL:** Erlaubnisse, Verbote und Pflichten für Assets[^26]

Die Domänenontologie ergänzt nur das, was für den eigenen Wissensbereich spezifisch ist.

### Kleinen Vertical Slice bauen

Zunächst 20 bis 100 repräsentative Dokumente und wenige Kompetenzfragen verwenden. Daraus Entitäten, Relationen und Claims extrahieren, manuell prüfen und die häufigsten Modellierungsfehler korrigieren.

Ein sinnvoller Vertical Slice umfasst:

- Dokumentimport mit Versions- und Quellenmetadaten
- Chunking mit stabilen Ankern
- Entitäts- und Claim-Extraktion
- Entity Resolution
- Graphspeicherung
- Hybrid Retrieval
- Antwort mit belegten Fundstellen
- SHACL- oder Schemaprüfung
- Reviewoberfläche für unsichere Extraktionen

### Ontologie versionieren

Auch das Schema selbst braucht Versionierung:

- Änderungsgrund
- verantwortlicher Maintainer
- Migration bestehender Instanzen
- veraltete Klassen und Relationen
- Kompatibilitätsregeln
- Tests gegen Kompetenzfragen

Eine Ontologie ist kein einmaliges Diagramm, sondern ein gepflegtes Software- und Wissensartefakt.

## Entscheidungshilfe zur Formalität

| Bedarf | Sinnvolle Ausbaustufe |
|---|---|
| Persönliche Notizen besser filtern | kontrollierte Tags, feste Entitätstypen, wenige Relationstypen |
| Synonyme und mehrsprachige Begriffe | SKOS-artiges Konzeptsystem mit stabilen IDs |
| Dokumente, Projekte und Personen vernetzen | leichtgewichtiger Property Graph oder RDF-Schema |
| Claims, Evidenz, Widersprüche und Provenienz | explizites Claim-/Provenienzmodell, Named Graphs oder reifizierte Aussagen |
| Strenge Datenqualität | SHACL oder vergleichbare Constraints |
| Automatische Klassifikation und logische Ableitung | RDFS/OWL und Reasoner |
| Austausch zwischen Organisationen/Systemen | standardisierte RDF-Vokabulare, URIs und Mapping-Regeln |
| Nur bessere semantische Suche | Vektor-RAG kann genügen; keine Vollontologie nötig |
| Multi-Hop-Fragen und Abhängigkeitsanalyse | Knowledge Graph plus Graph-Retrieval |

Nicht jedes Second Brain braucht OWL-DL oder einen Triple Store. Eine Ontologie beginnt bereits dort, wo Begriffe, Typen und Beziehungen bewusst und konsistent definiert werden; die formale Ausbaustufe sollte sich nach Kompetenzfragen, Interoperabilität und Inferenzbedarf richten.

## Praktische Kernaussage

Das Gefühl, dass mit „Ontologie“ **nicht einfach eine Dokumenthierarchie** gemeint ist, ist korrekt. Eine Ontologie beschreibt primär die **semantische Welt hinter den Dokumenten**: Dinge, Typen, Aussagen, Beziehungen, Identitäten, Gültigkeiten, Herkunft und Regeln.

Für ein hochwertiges KI-Second-Brain sollten mindestens vier Strukturen nebeneinander existieren:

1. **Dokumentstruktur:** Quelle, Version, Abschnitt und Chunk.
2. **Begriffsstruktur:** kontrollierte Begriffe, Synonyme und Taxonomie.
3. **Wissensstruktur:** Entitäten, Claims und typisierte Beziehungen.
4. **Vertrauensstruktur:** Provenienz, Evidenz, Zeit, Konfidenz und Reviewstatus.

Erst zusammen ermöglichen sie nicht nur „ähnliche Texte finden“, sondern Fragen wie: **Was ist bekannt, worauf beruht es, wann galt es, was widerspricht ihm, wer ist verantwortlich und welche Konsequenzen folgen daraus?**

---

## References

1. [OWL Web Ontology Language Overview - W3C](https://www.w3.org/TR/owl-features/)

2. [OWL 2 Web Ontology Language Primer (Second Edition)](https://www.w3.org/TR/owl2-primer/)

3. [The Web Ontology Language OWL2 - cgi.di.uoa.gr](https://cgi.di.uoa.gr/~pms509/lectures/OWL2.pdf)

4. [[PDF] Semantic Web Engineering - IFI UZH - Universität Zürich](https://www.ifi.uzh.ch/dam/jcr:ffffffff-8c04-b998-0000-00006402e42d/04_OWL.pdf)

5. [Web Ontology Language (OWL) Abstract Syntax and Semantics](https://www.w3.org/TR/2002/WD-owl-semantics-20021108/semantics-all.html)

6. [RDF 1.1 Concepts and Abstract Syntax](https://www.w3.org/TR/rdf11-concepts/)

7. [[PDF] Semantic Web OWL - LIRMM](https://www.lirmm.fr/~baget/publications/support-cours-owl.pdf)

8. [DCMI Metadata Terms](https://www.dublincore.org/documents/dcmi-terms/) - This document is an up-to-date specification of all metadata terms maintained by the Dublin Core Met...

9. [Taxonomies: What you need to know to start a taxonomy from scratch](http://www.hedden-information.com/wp-content/uploads/2019/07/Intro_to_Taxonomies__Thesauri.pdf)

10. [FDSN2023_WGII_ControlloedVoc_Strollo-Haslinger](http://www.fdsn.org/media/wg/II/2023/WG2-2023-Controlled-Vocabularies-Strollo.pdf)

11. [SKOS Simple Knowledge Organization System Primer](https://www.w3.org/TR/skos-primer/)

12. [SKOS Simple Knowledge Organization System Primer - W3C](https://www.w3.org/TR/2008/WD-skos-primer-20080221/)

13. [RDF Schema 1.1 - W3C](https://www.w3.org/TR/rdf-schema/)

14. [OWL Web Ontology Language Guide](https://www.w3.org/TR/owl-guide/)

15. [OWL Web Ontology Language Reference - W3C](https://www.w3.org/2001/sw/WebOnt/TR/STAGE-owl-ref/)

16. [Graph-Augmented RAG Patterns in Azure HorizonDB - Microsoft Learn](https://learn.microsoft.com/en-us/azure/horizondb/ai/graph-rag) - Learn how to combine knowledge graphs, vector search, and LLM reasoning in Azure HorizonDB to build ...

17. [Resource Description Framework (RDF) Schema Specification 1.0](https://www.w3.org/2001/sw/RDFCore/Schema/20010913/)

18. [Properties](https://www.w3.org/TR/owl-ref/)

19. [Web Ontology Language (OWL) Abstract Syntax and ...](https://www.w3.org/TR/2002/WD-owl-semantics-20021108/syntax.html) - Individual-valued properties can also be specified to be symmetric as well as functional, inverse fu...

20. [OWL Lite RDF Schema Features](https://www.w3.org/People/Sandro/OWL-Overview)

21. [Same Difference: Identity and Diversity in Linked Open Cultural Data | International Journal of Humanities and Arts Computing](https://www.euppublishing.com/doi/10.3366/ijhac.2022.0273) - Linked Open Data (LOD) was designed to respect heterogeneity in source datasets. However, the fundam...

22. [Time Ontology in OWL - W3C](https://www.w3.org/TR/owl-time/) - OWL-Time is an OWL-2 DL ontology of temporal concepts, for describing the temporal properties of res...

23. [PROV-O: The PROV Ontology - W3C](https://www.w3.org/TR/prov-o/)

24. [PROV Model Primer - W3C](https://www.w3.org/TR/prov-primer/)

25. [Shapes Constraint Language (SHACL) - W3C](https://www.w3.org/TR/shacl/)

26. [ODRL Information Model 2.2](https://www.w3.org/TR/odrl-model/) - The ODRL Information Model represents Policies that express Permissions, Prohibitions and Duties rel...

27. [ODRL Vocabulary & Expression 2.2 - W3C](https://www.w3.org/TR/odrl-vocab/) - The Open Digital Rights Language (ODRL) is a policy expression language that provides a flexible and...

28. [Dublin Core Metadata Element Set](https://msi.dublincore.org/standards/dublin-core-elements/) - Fifteen core properties for describing any resource, from title and creator to date and format.

29. [DCMI: Metadata Basics](https://www.dublincore.org/resources/metadata-basics/) - A brief introduction to DCMI by Tom Baker as presented at the DCMI Virtual 2021 conference, 4 Octobe...

30. [Project GraphRAG - Microsoft Research](https://www.microsoft.com/en-us/research/project/graphrag/) - GraphRAG is a structured, hierarchical RAG system that builds a knowledge graph from unstructured te...

31. [Welcome - GraphRAG](https://microsoft.github.io/graphrag/)

32. [A Method to Develop Description Logic Ontologies ...](https://ceur-ws.org/Vol-1041/ontobras-2013_paper45.pdf)

33. [Use of Competency Questions in Ontology Engineering](https://www.inf.ufes.br/~monalessa/wp-content/papercite-data/pdf/use_of_competency_questions_in_ontology_engineering__a_survey_2023.pdf) - von GKQ Monfardini · Zitiert von: 56 — To assist ontology engineers in the ontology development proc...

34. [SHACL Use Cases and Requirements - W3C](https://www.w3.org/TR/shacl-ucr/)

35. [SPARQL 1.2 Query Language](https://www.w3.org/TR/sparql12-query/) - RDF is a directed, labeled graph data model for representing information in the Web. This specificat...

36. [A Review and Comparison of Competency Question ...](https://livrepository.liverpool.ac.uk/3184940/1/EKAW2024-2.pdf)

37. [Data Catalog Vocabulary (DCAT) - W3C](https://www.w3.org/TR/vocab-dcat-1/) - A vocabulary for describing the contents of a data catalog
