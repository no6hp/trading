---
name: trader-dashboard
description: >-
  Alpaca-Dashboard in Claude. Baut eine HTML-Seite mit dem Alpaca-Papierkonto
  (Depotwert, Positionen, Orders, Ausführungen) und Tagescharts mit den
  Scanner-Signalen, MA20, 20-Tage-Hoch, Plan-Linien (Einstieg/Stop/Ziel),
  Käufen/Verkäufen und Volatilität (HV20, ATR14) und veröffentlicht sie als
  neue Version desselben Artefakts. Nutzen bei „Dashboard“, „Dashboard
  aktualisieren“, „zeig mir mein Konto“, „was ist im Depot“, und nach jedem
  Scan, Plan oder Trade. Nur lesend, platziert nie Orders.
argument-hint: "[--top N] [--symbols A,B]"
---

# trader-dashboard

```bash
python3 .claude/skills/trader-dashboard/dashboard.py            # -> trader/dashboard.html
python3 .claude/skills/trader-dashboard/dashboard.py --top 10 --symbols NVDA,AMD
```

Aus dem Repo-Root starten. Keys aus `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`
(Papierkonto, nur GET-Aufrufe). Kurse von Yahoo über den Code von
`trader-scanner`, daher sind die Signal-Dreiecke exakt die Scanner-Regeln,
für jeden der letzten 90 Handelstage nachgerechnet.

Charts: offene Positionen, offene Orders, `trader/plan.json`,
`trader/entry.json`, `--symbols`, dann die ersten `--top` (Standard 8)
Treffer aus `trader/watchlist.json`.

## Aussehen

Dunkles Layout im TradingView-Stil: Kontoleiste oben, großer interaktiver
Chart (TradingView Lightweight Charts 4.2.3 von jsDelivr, Umschalter 1T / 5m)
mit Watchlist rechts zum Durchklicken, darunter Positionen und Orders
(Bracket-Beine eingerückt). 1T: Kerzen, Volumen, MA20, 20-Tage-Hoch,
Signal-Pfeile, Käufe/Verkäufe, Plan- und Order-Linien, HV20-Fenster darunter.
1m: letzte 2 Sitzungen, 5m: letzte 5 Sitzungen, Opening-Range-Hoch/-Tief der letzten Sitzung, Zeiten ET.

## Veröffentlichen

1. Skript laufen lassen. Meldet es `alpaca_error` oder Chart-Fehler, das kurz
   sagen (keine erfundenen Kurse).
2. Slug aus `trader/state/dashboard.json` lesen und mit `publish_files`
   (`as: index.html`, `path: <repo>/trader/dashboard.html`, `slug`,
   `base_version` aus `get_artifact`) als neue Version veröffentlichen. So
   bleibt der Link gleich. Nur wenn kein Slug da ist, neu anlegen und den Slug
   in `trader/state/dashboard.json` speichern.
3. Dem Nutzer den Stand in ET und deutscher Zeit nennen. Die Seite ist eine
   Momentaufnahme, kein Live-Feed.

`trader/dashboard.html` ist in `.gitignore` (Kontodaten, wird jedes Mal neu
gebaut).
