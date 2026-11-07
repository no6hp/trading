# Eigenes Claude-Trading-Projekt einrichten

Diese Anleitung baut das komplette Setup aus diesem Repo in **deinem eigenen** claude.ai-Account
nach: Day-Trader-Skills, Alpaca-**Papierkonto** (Spielgeld), feste Termine Mo–Fr und auf Wunsch
ein Dashboard direkt in Claude. Dauer: ca. 15 Minuten.

> **Keine Finanzberatung.** Die Skills rechnen nur mit öffentlichen Daten. Alles läuft auf einem
> Papierkonto, und keine Order geht ohne dein wörtliches „ja“ raus.

---

## 1. Repo forken

1. Auf GitHub `github.com/no6hp/trading` öffnen → **Fork**.
2. In deinem Fork alte Zustandsdateien des Originals löschen, damit Claude bei dir sauber startet:
   - den Ordner `trader/state/` (vor allem `trader/state/dashboard.json`, dort steht der Link
     zu Noahs Dashboard, nicht zu deinem)
   - optional `trader/watchlist.json`, `trader/plan.json`, `trader/entry.json`,
     `trader/orders.json`, `trader/timemachine.json` (werden beim ersten Lauf neu geschrieben)

   Alternativ kannst du Claude später einfach sagen: „Lösche den alten Zustand in `trader/state/`
   und committe das.“

Das Repo enthält schon alles Nötige:
- `.claude/skills/trader-*` – die Skills (Scanner, Entry, Exit, Timemachine, Budget, Risk, Broker …)
- `trader/config.json` – Budget 1.000 $, max. 10 $ Verlust pro Trade, 30 $ pro Tag, 3 Trades pro Tag,
  Einstieg 09:45–15:30 ET, flat bis 15:55 ET, `"paper": true`
- `.mcp.json` + `.claude/settings.json` – Alpaca-MCP-Server (Lesen erlaubt, Orders fragen immer nach)
- `CLAUDE.md` – Ablauf und Regeln, die Claude in jeder Sitzung liest

> **Wichtig:** Ist dein Fork öffentlich, landen dort **nie** API-Keys. Die Keys kommen nur in die
> Umgebungs-Einstellungen (Schritt 3).

## 2. Alpaca-Papierkonto anlegen

1. Auf [alpaca.markets](https://alpaca.markets) ein eigenes Konto anlegen (kostenlos).
2. Oben links auf **Paper Trading** umschalten.
3. Rechts **API Keys → Generate New Keys**. Key-ID und Secret notieren. Das Secret wird nur
   einmal angezeigt.

Nimm **eigene** Keys. Keys von jemand anderem nie verwenden oder in einen Chat kopieren.

## 3. Projekt auf claude.ai/code anlegen

1. Auf [claude.ai/code](https://claude.ai/code) ein neues **Projekt** erstellen (z. B. „Trading“)
   und deinen Fork als Repository hinzufügen (GitHub verbinden, falls gefragt).
2. **Cloud-Umgebung** des Projekts bearbeiten:
   - **Umgebungsvariablen / Secrets:**
     ```
     ALPACA_API_KEY=<deine Paper-Key-ID>
     ALPACA_SECRET_KEY=<dein Paper-Secret>
     ```
   - **Netzwerkzugriff → Allowed domains** (alle eintragen):
     ```
     paper-api.alpaca.markets
     data.alpaca.markets
     query1.finance.yahoo.com
     query2.finance.yahoo.com
     feeds.finance.yahoo.com
     www.nasdaqtrader.com
     stooq.com
     www.sec.gov
     data.sec.gov
     disclosures-clerk.house.gov
     ```
     (`api.alpaca.markets` nur, falls du jemals live handeln willst. Für dieses Setup nicht nötig.)

### Hinweis zu den Alpaca-Tools

In Projekt-Threads lädt Claude die `mcp__alpaca__*`-Tools aus `.mcp.json` oft **nicht**. Das ist
kein Problem: Claude spricht die Alpaca-REST-API dann direkt per `curl` an, mit den Keys aus der
Umgebung (Header `APCA-API-KEY-ID` / `APCA-API-SECRET-KEY`, Basis-URL
`https://paper-api.alpaca.markets`). Das steht auch in den Projektanweisungen unten.

**Test:** Schreib im Projekt „Prüf mein Alpaca-Papierkonto“. Claude sollte Kontostatus `ACTIVE`
und 100.000 $ Spielgeld melden.

## 4. Projektanweisungen einfügen

In den **Projekteinstellungen → Anweisungen** diesen Text einfügen (Zeiten an deine Zeitzone
anpassen, falls du nicht in Deutschland bist):

```text
Trading-Projekt mit den Day-Trader-Skills aus dem Repo (.claude/skills/trader-*). Antworte auf Deutsch, mit „du“. Keine Finanzberatung.

Broker: Alpaca-PAPIERKONTO. Keys nur aus den Umgebungsvariablen ALPACA_API_KEY / ALPACA_SECRET_KEY, nie im Chat oder im Repo (das Repo ist öffentlich). Wenn die mcp__alpaca__*-Tools nicht geladen sind, die Alpaca-REST-API direkt per curl nutzen (Header APCA-API-KEY-ID / APCA-API-SECRET-KEY, https://paper-api.alpaca.markets, Kurse über https://data.alpaca.markets).

Limits: max. 10 $ Risiko pro Trade, max. 3 Trades pro Tag, max. 30 $ Tagesverlust. Einstieg nur 09:45–15:30 ET, alles flat bis 15:55 ET.

Ablauf pro Trade: /trader-scanner → /trader-news → /trader-entry → /trader-exit → /trader-timemachine → /trader-budget → /trader-risk (nur PASS geht weiter) → Ticket zeigen → Order NUR nach meinem wörtlichen „ja“, als Bracket (Stop + Ziel) → /trader-alerts.

QUALITÄTSFILTER für Tickets – nur wenn ALLE gelten:
(a) Trigger höchstens 15 Min alt und Kurs höchstens 0,5 % über dem Trigger (nicht hinterherlaufen);
(b) Timemachine Average R mindestens +0,10 und nicht „strongly toward the stop“;
(c) History-Teil der Timemachine mit Average R > 0;
(d) Stop nicht enger als 0,5 × Tages-ATR.
Sonst kein Ticket. Lieber kein Trade als ein Münzwurf. Statistik im Ticket immer ehrlich nennen.

Ist der Kurs bis zu meinem „ja“ so gelaufen, dass der Max-Verlust über 10 $ ginge: Limit zum Plan-Einstieg statt Market und das sagen.

Keine erfundenen Kurse: Schlägt ein Datenabruf fehl, kurz sagen und stoppen. Zeiten immer in New Yorker Zeit (ET) und deutscher Zeit. Zustand in trader/ nach jeder Aktion committen und pushen, die Cloud-Umgebung ist flüchtig.
```

## 5. Feste Termine (Routinen) einrichten

Am einfachsten: Starte im Projekt einen Thread (z. B. „Tägliches Trading“) und schreib:

> Richte bitte diese vier Routinen in diesem Thread ein, Mo–Fr, Zeitzone America/New_York,
> mit genau diesen Prompts: (dann die vier Blöcke unten einfügen)

Claude legt sie dann selbst an. Alle Zeiten sind New Yorker Zeit. In Deutschland ist das meist
6 Stunden später. Weil die USA und Europa an verschiedenen Tagen auf Sommerzeit umstellen,
verschiebt sich das im März und Oktober/November kurz um eine Stunde.

| Zeit (ET) | Deutsch | Routine | Cron |
|---|---|---|---|
| 08:47 | 14:47 | Vorbörsen-Scan | `CRON_TZ=America/New_York 47 8 * * 1-5` |
| 10:04 | 16:04 | Opening-Range-Check mit Ticket | `CRON_TZ=America/New_York 4 10 * * 1-5` |
| 11:04–15:04 stündlich | 17:04–21:04 | Intraday-Check (meldet sich nur bei Neuigkeiten) | `CRON_TZ=America/New_York 4 11-15 * * 1-5` |
| 15:45 | 21:45 | Tagesabschluss / Glattstellen | `CRON_TZ=America/New_York 45 15 * * 1-5` |

Die Dashboard-Schritte in den Prompts kannst du weglassen, wenn du kein Dashboard willst
(siehe Schritt 6).

### 5a. Vorbörsen-Scan (08:47 ET)

```text
Geplanter Termin: Vorbörsen-Scan. Prüfe zuerst per Alpaca /v2/clock bzw. /v2/calendar, ob heute ein Handelstag ist; wenn nicht, ohne Nachricht beenden. Sonst im Repo-Root (vorher git pull): /trader-scanner daily, dann /trader-news für die Top-Treffer (Earnings diese Woche?), dann /trader-dashboard und als neue Version desselben Artefakts veröffentlichen (Slug in trader/state/dashboard.json). Zustand committen und pushen. Mich in diesem Thread kurz melden (Deutsch, du): 3–5 interessanteste Charts mit Grund, Stand in ET und deutscher Zeit, Hinweis auf den ORB-Check um 10:04 ET. Keine Orders. Schlägt ein Datenabruf fehl, das kurz sagen und stoppen.
```

### 5b. Opening-Range-Check (10:04 ET)

```text
Geplanter Termin: Opening-Range-Check. Nur an Handelstagen (Alpaca /v2/clock is_open), sonst still beenden. Im Repo-Root (vorher git pull): Daily-Watchlist nach trader/state/watchlist-daily.json sichern, dann /trader-scanner orb. Bis zu 5 Kandidaten (Daily-Setup bevorzugt) mit /trader-entry, /trader-exit, /trader-timemachine, /trader-budget, /trader-risk prüfen.
QUALITÄTSFILTER: Ticket nur, wenn ALLE gelten: (a) Trigger höchstens 15 Min alt und Kurs höchstens 0,5 % über dem Trigger; (b) Timemachine Average R mindestens +0,10 und nicht „strongly toward the stop“; (c) History-Teil Average R > 0; (d) Stop nicht enger als 0,5 × Tages-ATR. Erfüllt keiner alles: mich kurz melden „heute kein Ticket, weil …“ und keinen Trade vorschlagen.
Bei PASS + Filter: mir das Ticket zeigen (Symbol, Stück, Einstieg, Stop, Ziel, Risiko in $, Statistik ehrlich) und auf mein wörtliches „ja“ warten. NIE ohne „ja“ eine Order; mit „ja“ als Bracket; ist der Kurs bis dahin so gelaufen, dass der Max-Verlust über 10 $ ginge, Limit zum Plan-Einstieg und das sagen. Danach /trader-dashboard neu veröffentlichen (gleicher Slug), Zustand committen/pushen. Zeiten in ET und deutscher Zeit, Deutsch, du.
```

### 5c. Stündlicher Check (11:04–15:04 ET)

```text
Geplanter Termin: stündlicher Intraday-Check. Nur wenn Alpaca /v2/clock is_open, sonst still beenden. Im Repo-Root (vorher git pull):
1. Alpaca: Status offener Orders, Positionen, Fills seit dem letzten Check. Ausgeführt, Stop oder Ziel getroffen → mich melden (Symbol, Preis, G/V, Zeit ET + DE) und in trader/state/trades.json eintragen.
2. Neue Signale: Bei offener Position oder offener Einstiegs-Order keinen zweiten Trade vorschlagen; nur Status. Sonst, wenn vor 15:30 ET und Tageslimits frei (3 Trades, 30 $): /trader-scanner orb (Watchlist vorher nach trader/state/ sichern), Kandidaten mit /trader-entry, /trader-exit (Einstieg = aktueller Kurs), /trader-timemachine, /trader-budget, /trader-risk prüfen.
   QUALITÄTSFILTER: Ticket nur, wenn ALLE gelten: (a) Trigger höchstens 15 Min alt und Kurs höchstens 0,5 % über dem Trigger; (b) Timemachine Average R mindestens +0,10 UND nicht „strongly toward the stop“; (c) History-Teil Average R > 0; (d) Stop nicht enger als 0,5 × Tages-ATR (sonst atr:-Stop testen). Bis zu 5 Kandidaten prüfen; erfüllt keiner alles, KEIN Ticket. Lieber kein Trade als ein Münzwurf.
   Bei PASS + Filter: Ticket an mich mit ehrlicher Statistik, Order nur nach meinem wörtlichen „ja“, als Bracket; bewegt sich der Kurs bis zum „ja“ so, dass der Max-Verlust über 10 $ ginge, Limit zum Plan-Einstieg setzen und das sagen.
3. /trader-dashboard neu bauen und unter demselben Slug veröffentlichen, Zustand committen/pushen.
Nur eine Nachricht an mich, wenn es etwas Neues gibt (Fill, Stop/Ziel, neues Ticket, Fehler); sonst still. Deutsch, du, Zeiten ET + deutsche Zeit.
```

### 5d. Tagesabschluss (15:45 ET)

```text
Geplanter Termin: Tagesabschluss vor Börsenschluss (flat bis 15:55 ET). Nur an Handelstagen. Prüfe per Alpaca offene Positionen und offene Orders.
- Offene Position: mich sofort melden (Symbol, Stück, G/V) und fragen, ob du glattstellen sollst; Verkauf nur nach meinem wörtlichen „ja“ (offene Stop/Ziel-Orders dabei vorher stornieren).
- Immer: kurzer Tagesabschluss – Trades des Tages mit G/V (trader/state/trades.json + Alpaca-Fills), Depotwert, warum ggf. kein Ticket kam, nächster Termin (08:47 ET Vorbörsen-Scan, nächster Handelstag). Unter 80 Wörtern.
Danach /trader-dashboard neu veröffentlichen (gleicher Slug), Zustand committen/pushen. Zeiten in ET und deutscher Zeit, Deutsch, du.
```

## 6. Dashboard in Claude (optional)

Der Skill `trader-dashboard` baut eine Seite im TradingView-Stil (dunkel, Kerzenchart mit
Scanner-Signalen, MA20, 20-Tage-Hoch, Einstieg/Stop/Ziel, Volatilität HV20/ATR, darunter Konto,
Positionen und Orders) und veröffentlicht sie als privates Artefakt in deinem Account.

- **Erstes Mal:** Schreib „Dashboard aktualisieren“. Claude führt
  `python3 .claude/skills/trader-dashboard/dashboard.py` aus, legt ein neues Artefakt an und
  speichert dessen Slug in `trader/state/dashboard.json`.
- **Danach:** Bei jedem „Dashboard aktualisieren“ (und nach jedem Scan, Plan oder Trade) wird die
  Seite neu gebaut und als neue Version **desselben** Artefakts veröffentlicht. Der Link bleibt gleich.
- Die Seite ist eine **Momentaufnahme**, kein Live-Feed, und kann keine Orders senden.

Falls der Ordner `.claude/skills/trader-dashboard/` in deinem Fork fehlt, ist er im Original noch
nicht gemergt. Dann einfach die Dashboard-Schritte aus den Prompts streichen oder Noah fragen.

## 7. So läuft ein Handelstag

1. **14:47 Uhr (08:47 ET):** Claude scannt, liest News und schickt dir 3–5 Charts.
2. **16:04 Uhr (10:04 ET):** Opening-Range-Check. Besteht ein Kandidat Risiko-Check **und**
   Qualitätsfilter, bekommst du ein Ticket. Du antwortest „ja“ oder „nein“.
3. **Stündlich bis 21:04 Uhr:** Claude meldet Fills, Stop oder Ziel, sonst ist es still.
4. **21:45 Uhr (15:45 ET):** Tagesabschluss. Bei offener Position fragt Claude, ob glattgestellt
   werden soll.

Claude läuft nicht dauerhaft im Hintergrund. Es arbeitet nur zu diesen Terminen oder wenn du
schreibst. An US-Börsenfeiertagen fällt alles aus.
