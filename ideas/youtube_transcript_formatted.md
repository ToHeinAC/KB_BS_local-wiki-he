# Transcript: Mein Second Brain — 2.000 Notizen als interaktive Karte

Source transcript from https://www.youtube.com/watch?v=mHSOsy_usAg&t=2070s

## Intro

**0:00**

Hallo zusammen, das hier ist mein Second Brain. Fast 2000 Notizen, über 4000 Dateien und ich finde relevante Informationen innerhalb von wenigen Sekunden.

**0:06**

Viele von euch haben unter dem letzten Video gefragt, wie braucht man sowas? Genau das zeige ich euch heute, den kompletten Weg Schritt für Schritt mit allen Referenzen und allen Fehlern, die ich gemacht habe.

**0:17**

Aber eins vorweg, um diese Optik geht es erst später und das ist Absicht, denn die schöne Galaxie oder die anderen strukturierten Ansichten des gesamten bestehenden Systems, das war nämlich der einfachste Teil und gleichzeitig aber auch der Teil, bei dem ich Stunden verloren habe.

**0:29**

Und warum und welchen Fehler ich gemacht habe, das seht ihr dann. Und der Vorteil ist natürlich für euch, dass ihr diesen Fehler einfach nicht machen müsst und euch Stunden an potenzieller Verzweiflung sparen könnt.

**0:42**

Vorher bauen wir aber das, was wirklich zählt, nämlich ein System, dem du vertrauen kannst und fangen wir da an, wo jeder von uns steht. Du sammelst Notizen in Obsidian, in Notion, egal wo und sammeln, das ist total einfach.

**0:48**

Jeder Artikel, jede Idee, jedes Meeting, einfach rein damit. Und das hier ist mein Vault. So heißt in Obsidian der Ordner mit allen Notizen. Und so sieht das nach ein paar Monaten aus.

**1:00**

Sieht ja eigentlich ganz cool und beeindruckend aus, ist es aber nicht, weil es ist halt einfach nur ein Haarball. Und ich zeige dir jetzt, was dieses Bild wirklich bedeutet.

**1:06**

Erstens, ich finde nicht wieder, was ich gesammelt habe. Die Standardsuche arbeitet mit Wörtern und nicht mit Bedeutung. Das heißt, wenn ich nicht mehr weiß, welche Begriffe ich damals verwendet habe, wird die richtige Notiz quasi unsichtbar.

**1:18**

Zweitens, und das ist viel schlimmer, ich kann dem, was ich finde, gar nicht vertrauen. Und ich zeige das an einem Beispiel aus meinem Workflow. In einem Strategiedokument steht ein Ziel für meine Videos. In einer anderen Notiz stehen aber die echten Auswertungen und die sagen etwas völlig anderes. Beide lagen quasi monatelang friedlich nebeneinander und ich habe es nicht gemerkt.

**1:42**

Und jetzt der entscheidende Punkt. In der Standardvariante kann ich das nicht einmal überprüfen. Obsidian gibt mir Links und eine Suche, aber es sagt mir nicht, wo sich meine Notizen widersprechen, was doppelt ist und was vielleicht veraltet ist. Das müsste ich alles selbst im Kopf behalten. Und bei 2000 Notizen ist es einfach unmöglich.

**1:58**

Es gibt aber mittlerweile Lösungen dafür und genau diese erläutere ich auch in diesem Video. Wie viele solcher Konflikte am Ende wirklich in meinem Vault stecken, zeige ich euch später mit den echten Zahlen.

**2:04**

Und Wissen sammeln ist leicht. Wissen wiederfinden und ihm vertrauen können, das ist das eigentliche Problem.

**2:11**

Deshalb stand am Anfang dieses Projekts keine Technikentscheidung, sondern eine Frage, nämlich die hier: Wie wird aus gesammeltem Wissen ein System, dem ich vertrauen kann, statt ein wachsender Müllhaufen?

**2:23**

Und diese Frage hat zwei Hälften. Erstens die Auffindbarkeit. Ich will jede Information wiederfinden, auch wenn ich nur noch ungefähr weiß, worum es ging. Und zweitens, Vertrauen, Duplikate, Widersprüche und veraltete Stände sollen auffallen und nicht stillschweigend herumliegen.

**2:42**

Und jetzt schaut auf diese Frage. Da steht nichts von einem Grafen, nichts von einer schönen Ansicht. Mit der Optik hat das alles erstmal noch gar nichts zu tun.

**2:48**

Und wenn du nur eine Sache aus diesem Video mitnimmst, dann die: Bau zuerst das System, das diese Frage beantwortet. Die Optik ist quasi nur ein Fenster und ein Fenster, das kannst du zum Schluss bauen.

**3:00**

Und wenn die Frage klar ist, kommt der nächste Schritt: aufschreiben, was das System können muss, um sie zu beantworten. Das hier ist die komplette Übersicht, durch die ich Schritt für Schritt durchgehe. Ich erkläre die Herangehensweise, ich erkläre die Funktion dahinter, sodass ihr das ganze System versteht.

**3:19**

Und wenn ihr dieses Video komplett durchschaut und ihr die Informationen, die ich euch mitteile, alle versteht, könnt ihr danach dieses System komplett nachbauen. Ich habe nachher im Video auch noch einen Goodie für alle, die durchhalten. Es wird teilweise sehr technisch und das Video wird sehr lang, aber damit habt ihr alles, was ihr braucht.

## Was das Second Brain können soll — die vier Fähigkeiten

**3:34**

So, jetzt erst einmal, was es eigentlich können soll. An dieser Stelle machen die meisten und ich auch früher den komplett gleichen Fehler. Sie springen direkt zum Werkzeug. Das heißt, welches Tool, welches Plugin, welche App.

**3:45**

Wir haben es andersrum gemacht. Und wenn ich von wir rede, dann meine ich Claude und ich. Bevor auch nur eine einzige Zeile Code entstanden ist, haben wir aufgeschrieben, was das System können muss, um die Frage vom Anfang zu beantworten, was es braucht, damit ich jede Information wiederfinde und damit ich dem Bestand auch vertrauen kann.

**4:04**

Keine Features, keine Tools, sondern Fähigkeiten. Bei mir sind es genau vier und merkt sie euch gut, denn jede dieser vier Fähigkeiten findet später in der Architektur ihr Zuhause.

**4:16**

Erstens: Finden. Relevante Informationen in Sekunden und zwar auch dann, wenn ich das genaue Wort nicht mehr weiß. Ich will fragen können, wie war noch mal unser Untertitelstil und die richtige Notiz bekommen, ohne den Dateinamen zu kennen. Das heißt, die Suche muss Bedeutung verstehen und nicht nur Buchstaben vergleichen.

**4:38**

Zweitens: Lesen. Wenn ich etwas gefunden habe, will ich es direkt öffnen und lesen können. Im selben System ohne Appwechsel. Klingt banal, ist aber ein Unterschied zwischen einem Werkzeug und einem Sprungbrett zurück ins Chaos.

**4:51**

Drittens, und das ist die Antwort auf die Vertrauenshälfte unserer Frage: sauber bleiben. Das System soll selbst erkennen, wo sich mein Wissen widerspricht, wo Duplikate liegen, wo Stände veraltet sind und es soll Wissen verdichten, statt es einfach nur zu stapeln. Und das kann keine Suche der Welt. Dafür braucht es später einen eigenen Mechanismus.

**5:08**

Und viertens: Überblick. Das ganze System auf einen Blick. Ja, und hier an dieser Stelle kommt irgendwann der Graf ins Spiel, aber schaut es einfach genau an. Es steht hier als Fähigkeit auf der Liste als eine von vieren und nicht an erster Stelle.

**5:21**

Dazu kommt eine Randbedingung, die mehrere Technikentscheidungen prägt. Meine Wissensbasis, der Index, der Graf und die Suche liegen und laufen komplett lokal auf meinem Rechner. Es gibt keine zusätzliche Cloud-Datenbank und keine externen Suchdienste. Meine Notizen sind mein Leben, Projekte, Finanzen, Persönliches und so weiter. Nur wenn Claude Inhalte analysiert oder das Wiki pflegt, werden die dafür ausgewählten Ausschnitte an das Modell übertragen.

**5:52**

Und hier kommt der erste Punkt, den du direkt übernehmen kannst. Bevor du irgendein Tool installierst, nimm dir 10 Minuten und schreib deine eigene Liste. Was muss dein System können, damit du ihm vertraust? Drei bis fünf Punkte und jeder so konkret, dass du am Ende prüfen kannst, ob er erfüllt ist. Fähigkeiten zuerst, Werkzeuge später.

**6:10**

Und jetzt haben wir eine Frage und eine Liste von Fähigkeiten. Und jetzt natürlich die Frage, wie kommt man dann von so einer Liste zu einem fertigen System, ohne sich komplett zu verzetteln?

## Der Prozess: sechs Schritte mit Claude Code

**6:22**

Und dafür gibt es einen Prozess. Der Prozess hat sechs Schritte und das hier ist der Prozess, mit dem aus der Frage ein fertiges System wurde. Diese sechs Schritte und ich sag's gleich, die eigentliche Bauarbeit, also das, was man sich unter mit KI ein System bauen vorstellt, ist nur Schritt 5 von sechs. Vier der sechs Schritte passieren, bevor die erste Zeile Code entsteht. Und genau das ist der Grund, warum es auch am Ende funktioniert hat.

**6:45**

Und eine Sache sage ich euch gleich dazu. Diesen Prozess habe ich mir nicht selbst ausgedacht. Die Schritte 2 bis 5 kommen aus einem fertigen Skillpaket für Claude Code. Es heißt Superpowers.

## Superpowers: Brainstorming, Spezifikation, Plan — dann erst bauen

**6:59**

Ein Skill ist dabei nichts anderes als eine Arbeitsanweisung, die man Claude einmal mitgibt und die dann bei jedem Projekt gilt. Im Kern macht Superpowers genau eine Sache. Es zwingt die KI in einen Ingenieursprozess.

**7:07**

Claude darf nicht einfach loslegen und Code schreiben. Es muss erst Fragen stellen, eine nach der anderen. Es muss die Entscheidungen in ein Dokument schreiben. Es muss daraus einen Plan mit kleinen testbaren Aufgaben machen und erst dann wird gebaut. Und an jedem dieser Übergänge sitzt du als Kontrollpunkt. Ohne deine Freigabe geht's einfach nicht weiter.

**7:31**

Wenn du mehr über Skills erfahren willst, wo du sie herbekommst und wie du sie installieren kannst, dann verlinke ich dir ein passendes Video in der Beschreibung.

**7:37**

Warum ist der Prozess so wertvoll? Das größte Risiko bei KI-Projekten ist nicht schlechter Code. Es ist, dass die KI mit voller Geschwindigkeit das Falsche baut, stundenlang überzeugend und komplett am Ziel vorbei. Und genau davor schützt diese Struktur.

**7:49**

Du musst kein Projektmanagement können und kein Software-Team geführt haben. Der Skill bringt diese Disziplin mit und du bringst die Entscheidungen. Ihr werdet in den nächsten Minuten sehen, was ich meine.

**8:02**

Schritt 1 hat mit KI noch gar nichts zu tun und es ist trotzdem der wichtigste: die Datenbasis ordnen. Bevor irgendwas gebaut wurde, habe ich meinen Vault komplett neu aufgestellt. Eine klare Clusterstruktur, Workflow-Ordner für Inbox, Daily Notes und Vorlagen und Themencluster für Content, Business, Community, Persönliches und Wissen. Jede Notiz hat seitdem einen eindeutigen Platz.

**8:21**

Und warum das ganz zuerst? Ganz einfach. Die beste Suche der Welt findet in einem Chaos-Vault auch einfach nur dein Chaos schneller. Und wenn ein Thema an fünf Stellen liegt, kann kein System der Welt daraus Vertrauen bauen. Ordnung in den Daten ist kein Nebenschritt. Es ist das Fundament, auf dem alles andere steht.

**8:41**

Und diesen Schritt kannst du heute auch einfach noch machen. Verwende dazu einfach Claude Code, lass deinen Workspace durchsuchen und ordne alles gemeinsam mit ihm neu. Claude schlägt die Cluster vor. Du entscheidest, was wohin gehört.

**8:53**

Schritt Nummer 2: Brainstorming. Und hier dreht sich die Rollenverteilung um, die die meisten vielleicht von KI erwarten. Ich habe Claude nicht gesagt, bau mir ein Second Brain. Stattdessen stellt Claude mir Fragen, eine nach der anderen. Was ist der Zweck? Was ist die Datenbasis? Was muss es können? Was soll es ausdrücklich nicht können?

## Was das System bewusst nicht kann

**9:11**

Das hier sind beispielsweise die echten Fragen von damals und am Ende schlägt Claude zwei, drei Ansätze vor mit Vor- und Nachteilen und ich entscheide. Die wichtigste Entscheidung damals: Das System arbeitet auf meinem kompletten Workspace, so wie er ist. Keine Migration, kein neues Format, kein erst einmal alles umziehen.

**9:28**

Und wichtig hierbei, in diesem ganzen Schritt entsteht kein Code, kein einziges File.

**9:35**

Schritt 3: Alles, was entschieden wurde, kommt schriftlich in ein Designdokument. Die Spezifikation Abschnitt für Abschnitt von mir freigegeben und das hier ist das Original von damals. Und diese Spezifikation ist quasi der Vertrag. Wenn später beim Bauen eine Streitfrage auftaucht, was gilt dann? Nicht meine Erinnerung, nicht die Interpretation der KI. Es gilt, was in der Spezifikation steht.

**9:54**

Und das klingt vielleicht bürokratisch, spart aber genau die Diskussion, die sonst Stunden kostet. Und damit ihr ein Gefühl für das Tempo bekommt, von der ersten Brainstorming-Frage bis zum Baustart vergingen ungefähr 30 Minuten. Und dieser Prozess ist kein bürokratischer Bremsklotz. Er ist eigentlich der Turbo für dein Projekt, weil alles flüssiger läuft.

**10:13**

Schritt 4: Aus der Spezifikation wird ein Plan. Claude zerlegt das Ganze in kleine Aufgaben. Bei mir waren es insgesamt 14 Kernaufgaben und jede Aufgabe hat zwei Dinge: einen Test und ein ganz klares Fertigkriterium. Nicht mach die Suche, sondern die Suche liefert zu dieser Beispielfrage diese Datei. Vorher ist die Aufgabe nicht fertig.

**10:40**

Schritt 5: bauen und zwar Schritt für Schritt. Für jede Aufgabe wird ein frischer Subagent eingesetzt, eine eigene Claude-Instanz, die genau diese eine Aufgabe und den dafür nötigen Kontext bekommt und sonst nichts. Danach wird das Ergebnis geprüft. Erst dann kommt die nächste Aufgabe.

**10:53**

Und meine Rolle dabei: Ich lese keinen Code. Ich schaue Ergebnisse an, läuft der Test, tut es, was das Kriterium sagt und die KI schreibt jede einzelne Zeile und ich nehme das Ganze ab.

**11:00**

Schritt 6: testen. Was du nicht testest, kannst du dir sehr leicht schön reden und wie der Test aussah und wie er ausging, das kommt in Kapitel 6 mit echten Zahlen.

**11:11**

Und falls ihr das nachbauen wollt, der komplette Ablauf, den ihr gerade gesehen habt, Brainstorming, Spezifikation, Plan, Task für Task, das war Superpowers von Anfang bis Ende. Ein Skillpaket einmal installiert und Claude Code arbeitet so bei jedem Projekt.

**11:30**

Noch einmal, den Link findet ihr in der Beschreibung und selbst wenn ihr ein anderes Werkzeug nutzt, das Muster bleibt übertragbar: erst entscheiden, dann schriftlich festhalten und dann in kleinen Schritten bauen lassen.

## Referenzen: Baustein, Muster, Messlatte

**11:42**

Eine Sache, die ich noch nicht erwähnt habe, woher wusste Claude jetzt eigentlich im Brainstorming, was gut aussieht und was technisch funktioniert? Und die Antwort ist der wichtigste Teil dieses gesamten Videos, nämlich Referenzen.

**11:53**

Und zwar nicht so, wie die meisten sie benutzen. Ich habe dafür drei Rollen vergeben. Referenzen sammeln heißt nicht zwangsläufig Links kopieren und sagen, bau mir das nach. Das wäre einfach nur eine Kopiervorlage und die Ergebnisse davon sind fast immer schlecht, weil fremde Lösungen fremde Probleme lösen und nicht deine eigenen.

**12:10**

Und bei mir hatte jede Referenz eine klar definierte Rolle. Es gibt genau drei davon. Und diese drei Rollen sind das Übertragbarste an dem gesamten Video. Egal was du mit KI baust. Diese drei Fragen kannst du eigentlich immer stellen.

**12:22**

Rolle 1: Der Baustein. Etwas, das fertig existiert und direkt eingebaut werden kann, ohne es neu zu erfinden. Bei mir ist das QMD, eine lokale Hybridsuche von Tobi Lütke, dem Shopify-Gründer. QMD kombiniert die klassische Stichwortsuche mit einer Bedeutungssuche und läuft vollständig auf meinem Rechner.

**12:42**

Erinnert ihr euch an die Fähigkeit Nummer 1, finden ohne das exakte Wort? Genau das liefert QMD als Plugin installiert, eingebunden, einsatzbereit. Und wie diese Suche im Detail arbeitet, das zeige ich euch gleich bei der Architektur. Aber die Lehre dahinter: Bau nichts selbst, was es als gepflegtes, fertiges Teil bereits gibt. Jede Stunde, die du nicht in eine eigene Suche steckst, steckst du in das, was dein System besonders macht.

**13:09**

Rolle 2: Das Muster. Hier übernimmst du keine Software, sondern eine Idee und setzt sie selbst um, passend zu deinem System. Und mein Muster kommt von Andrej Karpathy, einem der bekanntesten KI-Forscher überhaupt und er hat beschrieben, wie eine KI ein eigenes Wissenswiki pflegen kann. Die KI schreibt und aktualisiert Markdown-Seiten, es gibt einen kleinen Index, der zuerst gelesen wird und es gibt Prüfregeln gegen Widersprüche und verwaiste Seiten.

**13:33**

Und das Bemerkenswerte daran, diese Referenz ist kein Programm und kein fertiges Werkzeug. Es ist einfach nur ein kurzer Text, in dem Karpathy beschreibt, wie er arbeitet. Ein paar Absätze, mehr nicht. Aber die Idee darin, die KI pflegt das Wissen selbst nach festen Regeln, ist eins zu eins die Antwort auf unsere Fähigkeit Nummer 3: sauber bleiben.

**13:50**

Die Umsetzung haben wir komplett selbst gebaut, passend zu meinem Vault. Wie das konkret aussieht, seht ihr in Kapitel 6 mit echten Ergebnissen.

**13:56**

Rolle 3, die Messlatte: eine Referenz, aus der du weder Code noch Konzept übernimmst, sondern die festlegt, wie gut das Ergebnis aussehen muss. Und meine Messlatte war kein fremdes Produkt, sondern Bilder, Mockups meiner Zieloptik generiert mit KI. Getrennte Wissenswelten, jede mit eigener Farbe, die sich nicht vermischen. Klare Hierarchie, Übersichtlichkeit. Verbindungen erscheinen erst, wenn man einen Knoten auswählt.

**14:19**

Diese Bilder, nicht vage Worte, bekam Claude Code als visuelles Soll. Nicht im Prompt geschrieben: Mach es schön, sondern so sieht es fertig aus. Und wie es zu diesen Bildern gekommen ist und welcher sehr teure Fehler davor lag, das erzähle ich dir im Optik-Kapitel.

**14:37**

Und nur so viel dazu: Behalte diese Mockups im Hinterkopf. Sie spielen am Ende die Hauptrolle.

**14:44**

Und dann steht da unten noch eine Zeile, die fast wichtiger ist als die drei Karten. Ich habe mir noch zwei weitere Projekte angesehen, nämlich Gbrain und Graphiti. Code habe ich von beiden keinen übernommen, aber ihr Muster, Markdown als einzige Wahrheit, der Graf nur ein abgeleiteter Zwischenstand, hat eine der wichtigsten Architekturentscheidungen abgesichert.

**15:07**

Zu wissen, was du nicht brauchst, gibt dir außerdem die Sicherheit beim eigenen Ansatz zu bleiben, wenn es später schwierig wird. Auch verwerfen ist ein Rechercheergebnis. Also deine drei Fragen für jedes eigene Projekt: Was übernehme ich fertig? Welche Muster adaptiere ich? Und woran messe ich eigentlich, ob das Ergebnis gut genug ist? Baustein, Muster, Messlatte.

**15:24**

Damit habt ihr alle vier Punkte, die in das System hineingeflossen sind: die zentrale Frage, die vier Fähigkeiten, der Prozess, die Referenzen. Jetzt zeige ich euch, was daraus geworden ist und wie das System aufgebaut ist.

## Die Architektur: fünf Bausteine

**15:37**

Und keine Sorge, es sind nur fünf Bausteine und die habe ich eigentlich schon alle erwähnt. So und hier ist die komplette Architektur. Und bevor ihr denkt zu technisch, es sind genau fünf Bausteine und jeder der vier Fähigkeiten von vorhin findet hier sein Zuhause.

**15:55**

Das Wichtigste an diesem Bild sind aber nicht die Kästen, sondern es sind die Farben. Orange heißt deine Daten, grün heißt normaler Code, deterministisch, läuft immer gleich, kostet nichts. Und lila heißt KI. Und jetzt schau dir einmal an, wie wenig lila in diesem Bild ist. Das ist eine der wichtigsten Designentscheidungen im gesamten System. KI wird nur da eingesetzt, wo wirklich Verstehen nötig ist. Alles, was eine Maschine stur und zuverlässig erledigen kann, macht normaler Code. Das spart Geld, ist schneller und es ist nachvollziehbar.

**16:22**

Baustein 1, ganz links, dein Workspace. Das ist der Vault, den wir in Schritt 1 geordnet haben. In meinem Fall fast 2000 Notizen, insgesamt über 4000 Dateien plus die Ordner drumherum. Codeprojekte, die Skills, Claude-Anweisungen, das Memory, das was Claude sich über mich und meine Projekte gemerkt hat und die Connectors, also die Anbindungen an andere Programme.

**16:47**

Und hier seht ihr vielleicht den wichtigsten Satz des gesamten Boards. Markdown ist die einzige Wahrheit. Alles Wissen liegt als einfache Textdatei auf meiner Platte. Keine Datenbank, kein eigenes Format, kein System, das mich irgendwie einsperren kann. Jedes andere Teil der Architektur ist einfach nur eine abgeleitete Sicht auf diese Dateien und kann jederzeit weggeworfen und neu gebaut werden, ohne dass ein einziges Stück Wissen verloren geht. Merkt euch den Ordner 09 Wiki da drin, der spielt gleich noch eine sehr besondere Rolle.

## Der Indexer: Katalog und Landkarte, ohne KI

**17:15**

Baustein Nummer 2, der Indexer. Klingt technisch, ist aber die einfachste Idee im gesamten System. Stellt euch einen Bibliothekar vor, der einmal durch die Regale geht. Er liest die Bücher nicht, er registriert sie nur. Was gibt es? Wo steht es und welche Bücher verweisen aufeinander?

**17:29**

Und genau das macht der Indexer mit meinem Workspace. Ein kleines Programm läuft durch alle Ordner und notiert für jede Datei drei Dinge. Was ist das? Titel, Ort, Größe. Wie hängt es zusammen? Welche Notiz verlinkt auf welche? Welche Tags hat sie? Und zu welchem Wissenscluster gehört sie?

**17:45**

Und daraus schreibt er zwei Dateien. Erstens, eine Landkartendatei. Jeder Punkt, jede Verbindung fertig zum Anzeigen. Die füttert später die Grafansicht. Und zweitens die `index.md`-Datei. Einen Katalog, eine Zeile pro Bereich und wichtiger Datei. Nicht für jede einzelne Notiz, sonst wäre der Katalog selbst wieder ein Buch. Den liest Claude als allererstes, wenn ich etwas frage.

**18:09**

Und das Wichtigste, darin steckt keine KI. Und warum ist das gut? Jeder Lauf ist exakt gleich. Jeder Lauf dauert Sekunden. Jeder Lauf kostet nichts. Hätte eine KI das gemacht, wäre jeder Lauf teurer, langsamer und jedes Mal ein bisschen anders. Deterministischer Code vor dem Modell.

**18:27**

Und wie kommt man jetzt genau zu einem solchen Indexer? Das machst du in drei Schritten und die könnt ihr für euer eigenes System genauso übernehmen.

**18:33**

Schritt 1, das Muster festlegen. Meins stammt aus den beiden Referenzprojekten Gbrain und Graphiti und besteht aus drei Regeln. Regel Nummer 1: Die Markdown-Dateien sind die einzige Wahrheit. Regel Nummer 2: Die Landkartendatei ist nur ein abgeleiteter Zwischenstand, bei jedem Lauf neu erzeugt, nie von Hand gepflegt. Und Regel Nummer 3: Das Auslesen ist strikt getrennt vom Anzeigen.

**19:05**

Schritt 2: Die Spezifikation schreiben. Da stehen genau diese drei Regeln drin und dazu ganz konkret, welche Ordner gescannt werden, welche ignoriert werden und wie die zwei Ausgabedateien aussehen sollen. Das alles stand fest, bevor gebaut wurde.

**19:18**

Und Schritt 3: bauen lassen. Claude Code hat den Indexer aus der Spezifikation in vier kleinen Aufgaben gebaut, jede mit einem Test. Das heißt für euch, ihr müsst der KI nur das Muster sagen. Schreibt mir ein Script ohne KI, das durch alle meine Notizen geht, Titel, Links und Tags einsammelt und daraus eine Landkarte und einen Katalog schreibt. Der Rest ist genau der Prozess aus Kapitel 3.

## QMD: lokale Hybridsuche — Stichwort plus Bedeutung

**19:44**

Baustein Nummer 3, die Suche, unser fertiger Baustein QMD. Und wie versprochen, hier ist das Funktionsprinzip. QMD kombiniert zwei Sucharten, die sich perfekt ergänzen.

**19:55**

Die erste ist die klassische Stichwortsuche. Schnell, exakt, findet jedes Wort, das wirklich im Text steht. Ihre Schwäche kennt ihr natürlich. Wenn du das exakte Wort einfach nicht mehr weißt, dann findest du auch nichts.

**20:07**

Deshalb gibt's die zweite, die Bedeutungssuche. Die erkläre ich euch mit einem Bild. Stellt euch eine riesige Landkarte vor. Nur liegen darauf keine Städte, sondern Bedeutungen. Ein kleines KI-Modell liest jede Notiz und trägt sie auf dieser Karte ein. Der Inhalt bestimmt die Position. Notizen, die vom Gleichen handeln, landen nah beieinander, auch wenn sie völlig verschiedene Wörter benutzen.

**20:27**

Und jetzt die Frage, woher weiß das Modell, was zusammengehört? Es hat beim Training riesige Textmengen gelesen und dabei gelernt, welche Begriffe in denselben Zusammenhängen auftauchen.

**20:39**

Und jetzt kommt der eigentliche Trick. Wenn ich suche, wird meine Frage in genau dieselbe Karte eingetragen. Auch sie bekommt eine Position. Und damit wird aus der schweren Frage, welche Notiz passt zu meiner Frage, eine ganz einfache: Welche Notizen liegen auf der Karte am nächsten an meiner Frage?

**20:50**

Und genau diese nächsten Nachbarn sind die Treffer und dafür muss kein einziges Wort übereinstimmen. Ich frage nach Untertiteln und bekomme die Notiz, in der vielleicht nur Captions steht. Verschiedene Wörter, gleiche Bedeutung, direkt nebeneinander auf der Karte.

**21:09**

Und gebaut wird diese Karte von drei kleinen KI-Modellen, die QMD bei der Einrichtung automatisch heruntergeladen hat und die komplett lokal auf meinem Rechner laufen. Zusammen keine 3 GB. Eins versteht meine Frage und ergänzt verwandte Begriffe. Eins sortiert die Notizen und Fragen auf der Karte ein. Und ein weiteres schaut sich die Treffer zum Schluss noch einmal an und stellt die besten nach vorne.

**21:29**

Und das sind keine Chatgiganten, das sind kleine Spezialisten für eine einzige Aufgabe. Und auf meinem Mac laufen diese Modelle komplett problemlos lokal.

**21:35**

Und hier ein kleines Beispiel. Ich suche etwas absichtlich schwammig und da ist die direkte richtige Datei innerhalb von wenigen Sekunden, ohne dass irgendetwas meinen Rechner verlassen hat.

**21:46**

Und wo kannst du diese Suche im Alltag jetzt nutzen? Das kannst du eigentlich an drei Stellen machen. Erstens, du kannst es direkt im Terminal machen. Zweitens, viel häufiger, gar nicht ich selbst, Claude benutzt sie für mich als eine Stufe seiner Suchleiter und dazu gleich mehr. Und drittens direkt in meiner Graf-Webapp. Wie das zeige ich euch im Optik-Kapitel noch mal im Detail.

## Claude selbst und die Brain-First-Leiter

**22:11**

Baustein Nummer 4, das einzige große Lila im Bild, Claude selbst. Und hier ist der Punkt, den fast jeder unterschätzt. Das Entscheidende ist nicht die KI, es ist ihr Regelwerk. Also die `CLAUDE.md`, eine Textdatei, die Claude bei jedem Start liest und die festlegt, wie es mit meinem Wissen arbeitet.

**22:31**

Das Herzstück darin ist die Suchleiter. Ich nenne dieses Regelwerk Brain First. Wenn ich Claude etwas frage, darf es nicht einfach wild drauflossuchen oder schlimmer noch den halben Vault einlesen. Es muss die Leiter absteigen.

**22:38**

Stufe 1, die `index.md` lesen. Der kleine Katalog, ein paar hundert Zeilen. Stufe Nummer 2, im Wiki nachsehen, ob das Wissen dort überhaupt schon verdichtet liegt. Und Stufe 3 die QMD-Suche. Stufe 4 dann genau eine Datei öffnen, nämlich die beste. Und dann gibt's noch Stufe 5 Antworten.

**23:02**

Das beantwortet übrigens auch eine Frage, die unter dem letzten Video kam. Wie bekommt man den ganzen Vault eigentlich ins Kontextfenster? Und kurz übersetzt, das Kontextfenster ist das Kurzzeitgedächtnis der KI und Token sind die Häppchen, in denen sie Text liest.

**23:15**

Und je mehr Token, desto voller, langsamer und teurer. Und die Antwort auf diese Frage: gar nicht. Die Größe des Vaults bestimmt nicht automatisch, wie viel davon im Kontext landet. Claude lädt pro Frage nur den Katalog und die wenigen relevanten Dateien, ein paar tausend Token vielleicht. Der Trick ist kein größeres Kontextfenster. Der Trick ist ein System, das gar keins braucht.

**23:43**

Und seht ihr hier den Pfeil, der von Claude zurück in den Vault zeigt? Das ist der Rückkanal. Claude liest nicht nur, es schreibt auch, es pflegt dein Wiki-Ordner im Karpathy-Muster. Und wie genau das funktioniert und was dabei herauskam, ist das nächste Kapitel.

## Die Web-App: der Wissens-Graph

**24:02**

Baustein Nummer 5, die Webapp. Und fällt euch irgendwas auf, sie hängt hier in diesem Diagramm ganz am Rand. Das ist kein Zufall, denn sie macht genau drei Dinge.

**24:08**

Erstens, sie liest die Landkartendatei vom Indexer und malt daraus den Grafen. Zweitens, sie öffnet jede Notiz, die ich anklicke, direkt daneben. Damit hat Fähigkeit Nummer 2, das Lesen, hier ihr Zuhause. Und drittens, sie trägt die Suchbox, die dritte Stelle von gerade eben, an der die QMD-Suche arbeitet. Mehr nicht.

**24:26**

Sie schreibt nie, sie entscheidet nie und kein anderes Teil des Systems braucht sie eigentlich. Und das hier ist die wichtigste Erkenntnis für alle, die mitbauen wollen. Baustein 1 bis 4, Vault, Indexer, Suche, Regelwerk, das ist das System.

**24:38**

Und dafür müsst ihr nicht programmieren können. Der Vault ist ordnen, QMD ist installieren. Das Regelwerk ist eine Textdatei und den einzigen echten Code, den Indexer, schreibt euch Claude. Die App ist nur das Fenster und erst muss das System beweisen, dass es das Fenster auch verdient hat.

## Praxistest: Wiki-Ingest live mit versteckten Fehlern

**25:05**

Ein System kann auf dem Papier noch so gut aussehen, aber die Frage ist doch, hält es das im echten Betrieb? Und jetzt schauen wir uns das Ganze mal im Praxistest an. Und dabei kommt eine Zahl ans Licht, bei der ich ganz kurz an meinem eigenen Vault gezweifelt habe.

**25:18**

Mein alter Vault und bis hierhin klingt ja alles erstmal gut, aber klingt gut ist genau der Zustand, in dem die meisten Systeme einfach sterben. Man baut sie, ist stolz und drei Wochen später benutzt man sie nicht mehr, weil sie im Alltag einfach gar nichts bringen. Deshalb musste sich das System von Anfang an in einem Praxisvergleich bewähren.

**25:31**

Schritt sechs im Prozess und zwar zweifach. Erstens ist es wirklich schneller und das klärt ein Messtest und zweitens, das ist mir wichtiger, kann ich dem Wissen darin wirklich vertrauen und das klärt die Wikischicht und fangen wir mit genau dieser an, denn das ist das Herzstück.

**25:51**

Erinnert ihr euch an das Karpathy-Muster von den Referenzen? Die KI pflegt das Wissen selbst. Hier ist es umgesetzt. In meinem Vault gibt es einen Ordner `09 Wiki` und für den gilt eine harte Regel. Ich fasse ihn nicht an. Kein einziger Text darin ist von mir. Er wird ausschließlich von Claude gepflegt.

**26:04**

Und das läuft nach festen Regeln. Die stehen in einer Schema-Datei, einer ganz normalen Textdatei, die im Wiki-Ordner selbst liegt. Sie ist Claudes Arbeitsanweisung fürs Wiki. Vor jeder Wikiarbeit liest Claude genau diese Datei und hält sich an das, was drin steht.

**26:23**

Zum Beispiel welche Seitentypen es gibt, Zusammenfassen von Quellen, Themenseiten, Seiten zu Personen und Projekten und Syntheseseiten, die Wissen aus mehreren Quellen verdichten. Alles ist quervernetzt und der Effekt daraus: Egal welche Claude-Sitzung gerade arbeitet, im Wiki gelten immer genau dieselben Regeln.

**26:43**

Und der wichtigste Vorgang dazu heißt Ingest, einarbeiten. Ich gebe Claude eine neue Quelle, ein Transkript, einen Artikel, eine Notiz. Claude liest dabei die Quelle und ermittelt über das Seitenverzeichnis des Wikis, welche Seiten das Thema bereits berühren. Nur diese werden geöffnet und nicht das ganze Wiki.

**27:02**

Dann wird eingearbeitet, betroffene Seiten werden aktualisiert, fehlende werden neu angelegt, Verweise gesetzt und das Entscheidendste passiert genau dabei, nämlich auf jeder dieser Seiten wird geprüft von Claude, ob diese neue Information dem widerspricht, was bereits schon dort steht.

**27:19**

Und das Wichtigste für alle, die noch volle Konzentration haben, dieses Wiki braucht keine besondere Technik. Es sind ganz normale Markdown-Dateien in meinem Vault. Ein Ordner, eine Regeldatei und die Pflege macht Claude Code. Öffnen kann jeder Texteditor. Ich lese sie zum Beispiel in Obsidian oder direkt in meiner Grafapp. Beide machen aus den Querverweisen klickbare Links und aus den Warnhinweisen farbige Kästen.

**27:43**

Der Texteditor ist quasi das Regal und Claude ist der Bibliothekar. Und diesen Bibliothekar könnt ihr an drei Orten rufen. Im Terminal, in der Claude-Code-App oder direkt auch in Obsidian mit einem Plugin wie Claudian beispielsweise, das Claude Code als Seitenleiste einbettet. Dann passiert alles in einem Fenster.

**28:03**

Nur eines macht der Ingest nie. Er läuft nicht in meiner Webapp. Und warum? Das ist eine bewusste Entscheidung. Die seht ihr im nächsten Kapitel.

**28:09**

Und jetzt vielleicht noch eine Zwischenfrage an euch. Würde es euch denn einen Mehrwert bringen, wenn Claude direkt in der Webapp steckt als Chatfenster, das eure Fragen beantwortet und ihr dabei gleich zur Quelle im Grafen fliegt?

**28:26**

Soweit das Prinzip, aber glauben müsst ihr mir das nicht. Ich habe aber eine Falle vorbereitet und das hier ist eine ganz normale Notiz, wie sie bei mir jeden Tag in der Inbox landen könnte. Ein paar Stichpunkte zum Second-Brain-Setup. Sieht sehr harmlos aus, aber ich habe verschiedene Fehler darin versteckt.

**28:43**

Drei Aussagen, die dem widersprechen, was ihr heute schon mal gelernt habt. Vielleicht habt ihr sie beim Mitlesen bereits entdeckt. Jetzt arbeite ich diese Notiz ganz normal ins Wiki ein. Mal sehen, wie viele Fehler das System fängt.

**28:54**

Und hier ist das Ergebnis. Alle drei gefangen und markiert, manche gleich auf mehreren Seiten, denn ein Widerspruch wird überall dort markiert, wo er auftaucht.

**29:07**

Die Behauptung, die Bedeutungssuche schicke meine Notizen an einen Cloud-Dienst, markiert auf der QMD-Seite mit Verweis auf die dokumentierte lokale Architektur. Die Behauptung, der Messtest hätte nichts gebracht, markiert mit den Zahlen aus meinem Praxisvergleich als Gegenbeleg. Und die Empfehlung, das Wiki von Hand zu pflegen, markiert auf gleich zwei Seiten, weil sie die Grundregel des ganzen Wiki-Musters trifft.

**29:33**

Und ein Detail zeigt, dass das System nicht einfach auf alles anschlägt. In der Notiz steckte auch eine vierte Aussage: mehr Quellenarbeit, völlig harmlos. Die wurde nicht markiert, sondern als Bestätigung eines offenen Punkts in die passende Seite eingearbeitet. Das System unterscheidet also: Was passt, wird eingearbeitet. Was widerspricht, wird markiert.

**29:53**

Und jetzt schaut ganz genau hin, denn das ist die wichtigste Eigenschaft des ganzen Systems. Es hat nichts überschrieben. Es hat nicht einfach entschieden, wer recht hat. Beide Aussagen stehen da, jede mit ihrer Quelle und darunter der Satz quasi: Patrick entscheidet. Die KI findet die Konflikte, aber welcher Stand gilt, das entscheide ich.

**30:17**

Und das war eine präparierte Falle. Aber das Verrückte, als das Wiki meinen echten Bestand eingearbeitet hat, meine Notizen, meine Strategiedokumente, meine Projektdateien, hat es 52 Konfliktstellen markiert, Aussagen, die nicht eindeutig zusammenpassten, 52 in meinem eigenen Wissen, darunter echte Widersprüche, veraltete Stände und Fälle wie dieser hier, bei denen Soll und Ist nicht sauber getrennt waren.

**30:40**

Und ein Beispiel kennt ihr schon, die zwei Dateien vom Anfang des Videos. Genau, die hat das System gefunden. In meiner Kanalstrategie stand ein Ziel: Die Zuschauer sollen im Schnitt mindestens die Hälfte jedes Videos schauen. Das klingt hervorragend, habe ich so irgendwann aufgeschrieben. In einer anderen Notiz lagen aber die echten Auswertungen und die tatsächlichen Werte waren darunter und beide Aussagen existierten quasi wochenlang friedlich nebeneinander in zwei Dateien, die ich nie gleichzeitig offen hatte.

**31:07**

Ich habe es dann auch am Anfang ganz kurz erwähnt, aber nicht erklärt. Das System hat es von selbst markiert und genau das ist der Punkt. Diese Unklarheiten und Konflikte waren die ganze Zeit da. Sichtbar wurden sie erst, als eine Maschine alles gleichzeitig gelesen und verdichtet hat.

**31:25**

Und jetzt die Frage, was mache ich mit so einem Fund? Der Kasten ist kein Endzustand. Er ist eine Aufgabe an mich. In diesem Fall lautet die Entscheidung, das Ziel bleibt. 50 Prozent sind meine Ambition. Die echten Zahlen sagen mir nicht, dass das Ziel falsch ist, sondern in diesem Fall sagen sie mir einfach, dass ich besser werden muss, beziehungsweise ihr müsst länger meine Videos schauen.

**31:41**

Also präzisiere ich die Quelle. Im Strategiedokument steht jetzt ganz klar, das ist der Zielwert und daneben der aktuelle Stand. Wichtig ist dabei die Reihenfolge. Ich repariere die Quelle, nicht den Warnhinweis. Würde ich einfach nur den Kasten löschen, würde der nächste Durchlauf genau denselben Konflikt sofort wiederfinden und die Dateien widersprechen sich ja weiterhin.

**32:00**

Erst wenn die Quelle klar ist, sage ich Claude: entschieden, so gilt es. Das Wiki zieht nach, der Kasten verschwindet, die Entscheidung steht im Protokoll und aus dem versteckten Widerspruch ist ein sichtbarer Arbeitsauftrag geworden.

**32:12**

Dazu kommt, jeder einzelne Durchlauf wird protokolliert. Wann lief der Ingest? Welche Quelle kam rein? Welche Seiten wurden geändert? Das klingt unspektakulär, aber das ist der Unterschied zwischen einem System, dem man glauben muss und einem System, das man überprüfen kann.

## Der Benchmark: 50 Prozent weniger Token

**32:32**

Bleibt der zweite Test, die Geschwindigkeit. Der Test lief zweimal mit denselben fünf echten Fragen aus meinem Arbeitsalltag. Einmal Claude ohne mein System und am nächsten Morgen noch einmal mit Brain. Dazwischen lag nur die Installation der Suche und das Regelwerk. Gemessen wurden Token, Zeit und ob die Antwort stimmt.

**32:55**

Und das Ergebnis in diesem Vergleich: Mit fünf Fragen brauchte die Brain-Variante rund 50 Prozent weniger Token und etwa 40 Prozent weniger Zeit bei fünf von fünf richtigen Antworten in beiden Durchläufen. Und das ist keine wissenschaftliche Studie natürlich, sondern ein Praxisvergleich mit meinen eigenen Arbeitsfragen. Und für meinen Workflow war der Unterschied einfach deutlich.

**33:12**

Und die teuerste Frage zeigt, warum. Ein Einzeiler über einen Fix in meinem Projekt hat ohne Brain über eine halbe Million Token gekostet. Und versteht mich hier richtig, der Tokenverbrauch, der kommt nicht von der Frage, er kommt vom Suchen. Jeder Suchschritt liest den kompletten bisherigen Verlauf neu ein. Ohne System sucht Claude lange und jede Runde wird teurer als die davor. Und mit System war die Suche nach zwei Schritten vorbei und deshalb kostet die Frage nur noch ein Drittel.

**33:43**

Bei einfachen Fragen, Dingen, die sowieso im geladenen Kontext bereits liegen, da gewinnt die normale Session genauso. Da gibt's auch nichts, wo du irgendwie Token sparen kannst. Und das Brain gewinnt da, wo es wirklich relevant ist: bei Wissen, das tief vergraben ist und bei Fragen, deren Antwort in mehreren Dateien steckt.

**34:07**

Und der Test, der am Ende doch wirklich zählt, ist der Alltag. Ich arbeite jeden Tag damit, nicht weil ich es gebaut habe, sondern weil es schneller ist, als selbst zu suchen. Und das ist die Messlatte, an der jedes System hängt. Benutzt du es noch, wenn die Begeisterung weg ist?

## Die Optik: ChatGPT-Mockups und Claude Code

**34:18**

Und damit ist das System komplett. Es findet in Sekunden, es liest, es hält sich sauber und es hat sich in meinem Test und im Alltag bewährt. Jetzt ist die Zeit gekommen für den letzten Schritt, die Optik und für den größten Fehler des ganzen Projekts.

**34:34**

Ich löse das Versprechen aus dem Intro ein. Der Fehler, der uns Stunden gekostet hat. Ich sage euch direkt, was ihr nicht machen solltet, denn genau das habe ich gemacht und das war der Fehler. Ich habe in Text beschrieben, was ich will und die KI bauen lassen.

**34:46**

Mach es dichter, 3D, mehr Tiefe, weniger Glow und Claude hat geliefert, aber irgendwas. Und dann war ich einfach nur so, nein, mach das so und so, wieder irgendwas anderes, bis ich dann irgendwann echt genervt war und nicht weitergekommen bin. Das Problem war natürlich nicht die KI, sondern meine Beschreibungen, die waren einfach nicht gut. Es ist ein Ratespiel für die KI.

**35:12**

Und dann kam die Erkenntnis, die alles gedreht hat. Claude ist nämlich extrem gut darin, mit Referenzen umzugehen, etwas ganz Konkretes nachzubauen, aber es kann halt nicht erraten, wie es in meinem Kopf aussieht. Also brauchte ich etwas ganz Konkretes, nämlich Bilder.

**35:24**

Deshalb der Wechsel. Ich habe ChatGPT geöffnet. Dort gibt's nämlich eine richtig gute Bild-Engine und habe mir dort zuerst den Zielzustand der Optik generieren lassen. Und das zeige ich euch jetzt komplett, den echten Verlauf mit meinen Prompts.

**35:36**

Mein Einstiegsprompt. Ihr seht ihn hier komplett im Bild und der war im Kern: Ich brauche eine Grafenansicht für mein Second Brain. Bis zu zehn Hauptcluster, jedes mit eigener Farbe. Klar getrennt und optisch hochwertiger als der Obsidian-Graph.

**35:49**

ChatGPT lieferte zuerst ein Konzept und daraus habe ich verschiedene Ideen direkt übernommen. Erstens, die Cluster bleiben räumlich getrennt, damit sich die Inhalte nicht vermischen. Zweitens, Verbindungen sind nicht dauerhaft sichtbar, sondern erscheinen erst, wenn man mit der Maus darüber fährt, sonst wird der Graf unruhig. Und genau daher kommt das Hoververhalten aus meiner App. Und je mehr Wissen in meinem Ordner steckt, desto größer die Kugel.

**36:17**

Dann kam das Zielbild Nummer 1, der Globus mit getrennten Wissenswelten. Zielbild Nummer 2, die Clusteransicht. Ein Prompt, direkt ein Ergebnis. Als Ergänzung habe ich noch gesagt, setzt das Code-Maskottchen als zentrales Element in die Mitte. Und ihr seht, die Richtung saß einfach sofort.

**36:34**

Und Zielbild Nummer 3, ich wollte nicht nur meine Notizen sehen, sondern mein komplettes KI-System, die `CLAUDE.md` als zentrales Steuerelement, dazu Memories, aktive Skills, Plugins und Connectors. ChatGPT schlug dafür eine Ringstruktur vor. Innen der Systemkern, darum die Wissens- und Projektstruktur, ganz außen die externen Dienste optisch ganz klar getrennt.

**36:57**

Und aus demselben Vorschlag stammt noch eine Idee, die er aus meiner App kennt, nämlich das Detailfenster, das sich beim Anklicken eines Elements ruhig an der Seite öffnet.

**37:09**

Nach ein, zwei weiteren Runden stand das Ergebnis. Vor ein paar Tagen habe ich dann noch eine weitere Darstellung ergänzt, die Ebenenansicht. Ein einziger Prompt und die Grundidee saß direkt. Diese Bilder wurden zur visuellen Spezifikation für Claude Code und damit entstanden die Ansichten innerhalb von wenigen Minuten.

**37:28**

Und das Verrückte dabei ist, genau diese Ansichten sind das, was die Leute am meisten beeindruckt. Dabei ist es eigentlich der Teil, der am schnellsten geht, wenn man einmal den richtigen Weg kennt.

**37:34**

Und noch ein Tipp am Rande: Wenn ihr visuelle Anregungen sucht, lohnt sich auch ein Blick zu Pinterest. Suchbegriffe wie Wissensgraf oder Big Data Cloud liefern echt coole Referenzbilder.

**37:45**

Erinnert ihr euch noch an das Versprechen aus dem Referenzkapitel? Behalte die Mockups im Hinterkopf. Sie spielen am Ende die Hauptrolle. Genau da ist es jetzt. Die Bilder wurden von der Messlatte zur Bauvorlage.

**37:51**

Ich habe sie Claude Code als Referenz gegeben und gebaut wurde nach einer einzigen Regel. Claude setzt einen Schritt um. Ich schaue im Browser nach, ob das Ergebnis dem Zielbild entspricht und erst nach meiner Abnahme kommt der nächste Schritt.

**38:05**

Und das beste Beispiel ist die Ebenenansicht. Das Bild aus dem ChatGPT-Verlauf als Referenz, ein Umsetzungsschritt, ein Blick in den Browser, Abnahme, fertig. Und hier ist das Ergebnis, mein Wissen als Graf in verschiedenen Versionen. Ich hatte gesagt, das System muss erst beweisen, dass es das Fenster verdient und das hat es. Jetzt darf es auch schön sein.

**38:30**

Und jetzt natürlich die berechtigte Frage, wenn Suche, Wiki und Lesen auch in Obsidian mit Claude Code funktionieren, wozu dann überhaupt eine eigene App? Und dazu habe ich drei Antworten.

**38:36**

Erstens, Obsidian sieht nur meine Notizen. Mein System ist größer. Claude-Projekte, Skills, Memory, Connectors, diese Schichten zeigt kein Obsidian-Vault an. Die App ist das einzige Fenster, das alles zeigt.

**38:49**

Zweitens, der Gesundheitsblick. Welche Cluster wachsen? Was liegt verwaist herum? Das sehe ich hier auf einen Blick, statt im Haarball irgendwo zu raten, wo irgendwas liegt.

**38:55**

Und drittens, ich kann im Grafen lesen und weiterklicken. Jede Datei öffnet sich direkt hier, auch die außerhalb des Vaults. Und das ist der Test, ob eine Visualisierung ein Werkzeug ist oder eigentlich nur ein Poster.

**39:13**

Wenn dir Obsidian dafür reicht, perfekt, spart ihr die App. Sie ist die Kür und sieht eigentlich auch ganz cool aus und man kann sich auch einfach ausprobieren. Und bei solchen Projekten lernt man extrem viel im Umgang mit KI.

**39:19**

Und eine Sache ist neu dazu gekommen, die genau diese Frage noch besser beantwortet. Die Suchbox der App kann jetzt auch Bedeutungssuche. Ich tippe also eine Frage ein: Wie war unser Stil für die Untertitel? Drücke Enter und die App liefert die passende Notiz, obwohl das Wort so nirgendwo drin steht. Ein Klick und der Graf fliegt zu genau dieser Datei und öffnet sie.

**39:43**

Und jetzt der Punkt, den viele überraschen wird, nämlich was das eigentlich für KI und für Token bedeutet. Bei diesem Enter passiert folgendes. Die App reicht die Frage an QMD weiter und zwar an die schnelle Variante der Suche. Der Frageversteher erweitert die Anfrage um verwandte Begriffe. Das Embedding-Modell setzt sie auf die Bedeutungslandkarte und vergleicht zwei der drei lokalen Modelle. Also, das heißt, der Feinsortierer bleibt hier außen vor. Den nutzt nur die vollständige Hybridsuche, mit der Claude Code über die Suchleiter arbeitet.

**40:09**

Das alles läuft komplett auf meinem Mac. Es wird nichts an irgendeinen Anbieter geschickt, kein einziger API-Token verbraucht, nichts von meinem Claude-Kontingent angefasst. Die Kosten sind reine Rechenzeit, etwa 2 Sekunden Prozessorarbeit pro Suche, sonst nichts. Ich kann 100 mal am Tag suchen, ohne dass pro Suche API-Kosten entstehen und es funktioniert auch offline.

**40:34**

Die App nutzt damit lokale KI, aber keine Cloud-KI und sie verursacht keine nutzungsabhängigen API-Kosten. Sie borgt sich für die Suche die lokalen Spezialisten von QMD, bleibt aber eine reine Leseoberfläche. Sie findet und zeigt, aber sie schreibt nie. Token verbrauche ich in diesem ganzen System nur an einer einzigen Stelle, wenn Claude wirklich für mich denkt.

**40:54**

Zum Schluss wechsel ich noch einmal in die Ansicht, die Ebenenansicht. Sie ist der Beweis, dass die Optik austauschbar ist. Das System darunter, Index, Suche, Wiki, Regelwerk, das bleibt exakt dasselbe, egal welches Fenster du davorsetzt. Das Fenster ist einfach nur Geschmackssache. Das Fundament ist Pflicht.

**41:13**

Die Lehre aus diesem Kapitel in einem Satz: Beschreibt der KI nicht in Worten, wie es aussehen soll. Lass dir erst Bilder vom Zielzustand generieren und die gibst du als Referenz rein. Zwei KI ist klare Arbeitsteilung. Zum Beispiel ChatGPT erstellt das Zielbild. Claude Code baut es nach. Seit ich so arbeite, ist schön kein Ratespiel mehr. Es ist einfach ein Auftrag mit Vorlage.

## Sieben Lektionen aus dem Projekt

**41:40**

Und jetzt bleibt die Frage, die wichtigste im ganzen Video eigentlich: Was davon baust du jetzt nach und womit fängst du heute an? Kommen wir zu deinem Einstieg und fassen wir das Ganze noch mal zusammen, was wir jetzt in diesem Projekt gelernt und was das Projekt gelernt hat. Sieben Lektionen und ihr habt jede davon heute in Aktion gesehen.

**41:58**

Eins: Referenzen schlagen Beschreibungen immer, bei der Technik wie bei der Optik.

**42:05**

Zwei: Kleine Schritte mit Abnahme, nie alles auf einmal. Das hat das Fundament gebaut und die Optik gerettet.

**42:10**

Drei: Entscheiden vor bauen. Die Spezifikation ist der Vertrag. Wer erst baut und dann entscheidet, baut zweimal.

**42:17**

Punkt Nummer 4: Deterministisch, wo es geht. KI nur da einsetzen, wo wirklich Verstehen nötig ist. Deshalb kostet mein Indexer nichts und läuft in Sekunden.

**42:24**

Fünf: Markdown bleibt die einzige Wahrheit. Keine Datenbank, kein Formatgefängnis. Alles andere ist nur eine Sicht auf deine Dateien und ist jederzeit ersetzbar.

**42:30**

Sechs: Jede Behauptung braucht einen Prüfpunkt. Ohne den Benchmark wüsste ich bis heute nicht, ob sich das alles überhaupt lohnt. Ich würde es einfach nur glauben.

**42:41**

Und sieben, die wichtigste: Der Mensch entscheidet, die KI liefert. Bei jeder Brainstorming-Frage, bei jedem Widerspruch im Wiki, bei jedem Optikschritt in diesem ganzen Projekt hat die KI nicht eine einzige Entscheidung getroffen. Sie hat sie nur möglich gemacht.

## Dein Einstieg: vier Schritte in einer Stunde

**42:59**

Und jetzt zu dir. Du musst nicht das komplette System nachbauen, um davon zu profitieren. Der Kern, finden und Vertrauen, geht komplett, ohne dass du selbst Code schreiben können musst. Vier Schritte zusammen ungefähr eine Stunde und aus meiner Sicht hast du damit schon den größten Teil des praktischen Nutzens.

**43:13**

Schritt 1: Ordne deine Notizen in Themencluster. Nimm dir Claude Code dazu, lass deinen Bestand durchsuchen und sortiere gemeinsam mit ihm neu. Das ist das Fundament. Es kostet nichts, außer vielleicht der Stunde.

**43:26**

Schritt Nummer 2: Leg eine Indexdatei an, einen Katalog, eine Zeile pro Thema, was es ist, wo es liegt. Auch das tippt Claude Code für dich. Sag ihm, es soll durch deine Ordner gehen und den Katalog schreiben. Es ist die erste Stufe der Leiter.

**43:39**

Schritt 3: Installiere und initialisiere QMD. Nach wenigen Terminalbefehlen hast du eine lokale Hybridsuche über all deine Notizen. Der Link ist in der Beschreibung.

**43:51**

Schritt 4: Schreib die Brain-First-Regeln in deine `CLAUDE.md`. Erst der Katalog, dann die Suche, dann genau eine Datei. Die Regeln zum Kopieren findest du in meinem PDF-Giveaway zum Download in meiner kostenfreien School-Community, wo sich alles um KI dreht und wo viele weitere KI-Interessierte bereits drin sind und sich über verschiedene Themen austauschen.

**44:07**

Das ist alles. Kein Graf, keine App, kein Wiki. Das ist die Kür, die kommt, wenn das Fundament sich bewährt. Und wenn du dir von diesem ganzen Video nur einen Satz merkst, dann den hier unter dem Board. Die KI schreibt den Code: Du kuratierst die Referenzen und du entscheidest und du nimmst jeden Schritt ab.

**44:26**

Weil mir die Oberfläche selbst gehört, kann ich sie später weiter ausbauen und erweitern. Zum Beispiel hier meine eigenen Videobearbeitungen, die ich erstellt habe, automatisches Cutting meiner Langvideos und aus dem fertigen Video in wenigen Sekunden kann ich direkt Shorts exportieren. Alles lokal, kein Abo, keine Kosten. Das ist aber ein eigenes Kapitel.

**44:44**

Für das Second Brain bleibt entscheidend: Das System darunter funktioniert unabhängig von dieser Oberfläche. Alle Links findest du in der Beschreibung. Dort ist auch mein kostenloses Startdokument verlinkt.

## Outro: Was soll ich als Nächstes zeigen?

**44:49**

Und jetzt interessiert mich natürlich eine Frage. Was soll ich als nächstes zeigen?

**44:55**

Claude direkt in der App oder vielleicht eine Cloud-Variante? Schreib mir einfach Chat oder Cloud in die Kommentare oder vielleicht auch irgendwas anderes, was dich interessiert.

**45:07**

Und wenn dir dieser Deep Dive, auch wenn extrem lange gewesen ist und vielleicht sehr technisch gewesen ist, geholfen hat und Mehrwert geliefert hat und dieses Format gut für dich ist, freue ich mich über ein Abo und einen Kommentar.

**45:12**

Und jetzt bau dein Fundament und wir sehen uns im nächsten Video.
