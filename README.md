# FK04: Dein WebUntis-Stundenplan automatisch im Apple Kalender

**Status: Vorlage vorbereitet, Live-Abruf der FK04 noch nicht verifiziert.**
Ein GitHub-Workflow holt regelmäßig den Stundenplan der Klasse 12ME, entfernt
nicht belegte Fächer und veröffentlicht `stundenplan.ics` über GitHub Pages.
Der letzte funktionierende Kalender bleibt online, wenn ein neuer Abruf scheitert.

## Was voreingestellt ist

- Server: `fk04-munchen.webuntis.com` (aus dem Screenshot)
- Schulname: `FK04` (Hochschule München)
- Klasse: `12ME`, UI-ID: `1706` (aus der Browseradresse im Screenshot)
- Zeitraum: **01.10.2026–14.03.2027** (gesamtes Wintersemester)
- Unterricht: offiziell **01.10.2026–22.01.2027**, Prüfungszeit **23.01.–06.02.2027**;
  Termine erscheinen nur, wenn sie tatsächlich in WebUntis hinterlegt sind.
- Fächer: Batterien und Brennstoffzellen; Ringvorlesung Elektromobilität;
  N. Energiesysteme; Elektroak. u. Audiotechnik; Felder und Wellen; Seminar Systeme.
- Abruf alle drei Stunden (nicht sekundengenau).

## 1. GitHub-Repository anlegen

1. [github.com/new](https://github.com/new) öffnen, z. B. Repositoryname
   `fk04-kalender`. Für **GitHub Pages auf GitHub Free** ist ein öffentliches Repository
   der einfache Weg. **Die generierte Kalenderdatei ist dann öffentlich lesbar.**
2. Dieses ZIP herunterladen und **entpacken**. Die Dateien einschließlich des
   versteckten Verzeichnisses `.github/workflows/` ins Repository hochladen.
   In GitHub: `Add file → Upload files → Commit changes`. Ein direktes ZIP im Repo
   funktioniert nicht: die Dateien müssen entpackt vorliegen.
3. Unter `Settings → Pages → Build and deployment → Source` **GitHub Actions** auswählen.
4. Unter `Settings → Actions → General` sicherstellen, dass Actions zugelassen sind.

## 2. Erster Funktionstest

1. `Actions → FK04 Kalender aktualisieren → Run workflow` starten.
2. Das Protokoll des Schritts **WebUntis abrufen und iCal erstellen** öffnen.
3. Wenn öffentlich abrufbar, funktioniert es ohne Zugangsdaten.
   Wenn nicht, Secrets konfigurieren wie im folgenden Schritt.
4. Auch wenn der Abruf klappt, können Namen anders lauten. Daher nach dem Lauf
   unter `Summary → Artifacts → fachnamen-diagnose` die Textdatei
   `subjects.txt` herunterladen und mit `config.json` abgleichen.

**Was wurde wirklich getestet?** Für den FK04-Server war eine Live-Abfrage aus
unserer Arbeitsumgebung technisch nicht möglich. Die Scriptlogik wurde lokal mit
Testfällen geprüft. Erst **dieser Actions-Lauf** ist der Live-Test des Servers.

## 3. Wenn die öffentliche WebUntis-API deaktiviert ist

Auf GitHub im Repository unter
`Settings → Secrets and variables → Actions → New repository secret`
**zwei** Secrets anlegen:

| Name | Wert |
| --- | --- |
| `UNTIS_USERNAME` | der Klassenbenutzer für 12ME (FK04 dokumentiert ihn offiziell) |
| `UNTIS_PASSWORD` | das zugehörige Klassenpasswort aus der FK04-Anleitung |

Die Klasse ist in der offiziellen Tabelle auf
https://ee.hm.edu/studierende/vorlesungsplaene_/vorlesungsplaene.de.html
als `ELM1/2 → 12ME` aufgeführt. Kopiere das Passwort von dort und trage
es **nicht** in `config.json`, Code oder GitHub-Issues ein.

Sobald Secrets eingerichtet sind, wieder **Run workflow** starten.
Wenn der API-Zugang der FK04 auch für den offiziellen Klassenbenutzer gesperrt ist,
kann diese Lösung keinen Live-Abruf durchführen. Dann ist eine Freigabe durch die FK04
oder ein anderer erlaubter Datenweg erforderlich.

## 4. Apple Kalender abonnieren

Sobald der Actions-Lauf erfolgreich und Pages aktiviert ist, lautet die Adresse:

`https://DEIN-GITHUB-NAME.github.io/fk04-kalender/stundenplan.ics`

`DEIN-GITHUB-NAME` und ggf. `fk04-kalender` durch deinen tatsächlichen
GitHub-Namen / Repositorynamen ersetzen. **Die URL ist ein Abonnement,
kein einmaliger Dateiexport.**

Auf dem iPhone: `Kalender → Kalender → Hinzufügen → Kalenderabonnement hinzufügen`
und die vollständige HTTPS-Adresse einfügen, dann iCloud als Account auswählen.
Auf dem Mac: `Kalender → Ablage → Neues Kalenderabonnement`.

Die Aktualisierung erfolgt erst bei Abruf durch GitHub Actions **und** anschließend
beim nächsten Abruf des Apple-Kalenderabonnements. Apple bestimmt dabei den Rhythmus
auf dem iPhone selbst. Änderungen erscheinen deshalb nicht sofort.

## 5. Weitere Fächer erkennen und Kursfilter anpassen

Die sechs Module stehen mit Synonymen in `config.json` unter `courses`.
Das Skript vergleicht diese mit den **vollständigen Bezeichnungen**, die die API
zurückliefert (nicht mit den visuell gekürzten Namen der Webseite). Die Aliase sind
**Vorschläge, keine verifizierten exakten Fachnamen der FK04**.

Wenn in `subjects.txt` ein fehlender Kurs z. B. als `Ringvorl. Elektromob.`
erscheint, erweitere die Aliasliste in `config.json` entsprechend.

Das Skript beendet sich absichtlich mit Fehler, wenn es keinen einzigen passenden
Termin findet, statt einen leeren Kalender zu veröffentlichen. Wenn nur einzelne
Fächer nicht erkannt werden, erscheint eine Warnung im Bericht, und die erkannten
Fächer erscheinen bereits im Kalender. Prüfe beim ersten Lauf unbedingt, dass **alle
sechs Module** in der Diagnoseliste Treffer haben, sofern Termine geplant sind.

## 6. Lokal prüfen

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python main.py --probe  # liest nur die Woche ab 12.10.2026; schreibt keine ICS
python main.py          # gesamtes Semester und docs/stundenplan.ics
```

`--probe` versucht ebenfalls den Login-Fallback, wenn die beiden Variablen
`UNTIS_USERNAME` und `UNTIS_PASSWORD` in der Umgebung gesetzt sind.

## Grenzen und Datenschutz

- Das Repo und die veröffentlichte `.ics`-Datei können öffentlich sein. Persönliche
  Lehrveranstaltungen und Räume sind dann für jeden mit der URL lesbar; nichts
  Privates in Beschreibungen oder Modulnamen eintragen.
- **Keine Garantie**, dass der neue WebUntis-Server die bisherige öffentliche
  API/JSON-RPC-Schnittstelle akzeptiert. Die FK04 dokumentiert offiziell nur
  Browser und Untis Mobile.
- Änderungen bei der FK04 können API-Zugriff, Felder oder Klassennamen ändern.
- Bei einer Ausfallmarkierung aus der API entfernt der Generator den Eintrag.
  Ob FK04 die Ausfallinformationen vollständig via API publiziert, bleibt zu testen.
- Ein leeres oder teilweise noch nicht veröffentlichtes Semester kann zu
  unvollständigen Terminen führen. Der Feed wird bei erfolgreichen Läufen komplett
  neu erzeugt und ergänzt später veröffentlichte Termine automatisch.
- Wiederholt fehlschlagende Abfragen lassen **den zuletzt erfolgreich
  veröffentlichten Kalender unverändert**. Prüfe bei wichtigen Terminen zusätzlich
  den Originalplan in WebUntis.
- GitHub kann regelmäßige Actions-Läufe verzögern oder automatische Workflows in
  lange inaktiven Repositories deaktivieren. In diesem Fall GitHub Actions erneut
  aktivieren beziehungsweise manuell starten.

## Technische Details

- Quellen: `webuntis-public` (zuerst, ohne Anmeldung); als Fallback `webuntis`
  mit Klassenbenutzer aus verschlüsselten GitHub Actions-Secrets.
- Wöchentliche API-Abfragen über das gesamte Semester; lesender Zugriff.
- Separate VEVENT-Einträge statt RRULE, damit sporadische Stunden, Raumwechsel,
  Ausfälle und Feiertage übernommen werden.
- Datum/Uhrzeit werden aus `Europe/Berlin` korrekt nach UTC umgerechnet, auch
  beim Wechsel von Sommer- auf Winterzeit. RFC-5545-Zeilen werden UTF-8-sicher gefaltet.
- Kalender-UID aus Fach, Datum, Unterrichtskennung und Auftretensindex. Identischer
  Termin am selben Tag behält beim Raumwechsel dieselbe UID. Bei Verschiebungen
  zwischen Tagen ersetzt der Feed den alten Termin durch einen neuen.