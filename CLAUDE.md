# Trading – Day-Trader-Skills

Dieses Repo nutzt das Day-Trader-Skill-Paket (`.claude/skills/trader-*`, MIT,
github.com/Jakeschincariol/day-trader-skill). **Antworte auf Deutsch, mit "du".**
Keine Finanzberatung – die Skills rechnen nur mit öffentlichen Daten.

## Einstellungen
- `trader/config.json` – Budget 1.000 $, max. 10 $ Verlust/Trade, 30 $/Tag, 3 Trades/Tag,
  Einstieg 09:45–15:30 ET, flat bis 15:55 ET, `"paper": true`. Nur auf Wunsch ändern.
- Alle Skills lesen/schreiben im Ordner `trader/` im Repo-Root (Skripte immer aus
  `/home/user/trading` bzw. dem Repo-Root starten).
- Broker: Alpaca **Papierkonto**. Keys nur als Umgebungs-Secrets
  (`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`), nie im Chat oder im Repo.

## Kompletter Ablauf (ein Trade)
1. `/trader-scanner` – vorbörslich `daily`, ab 10:00 ET `orb` → `trader/watchlist.json`
2. `/trader-news` – Schlagzeilen + 8-Ks zur Watchlist (Earnings diese Woche?)
3. `/trader-entry` – wartet auf Schlusskurs über der Opening Range → `trader/entry.json`
4. `/trader-exit` – Stop + Ziel → `trader/plan.json`
5. `/trader-timemachine` – 10.000 Replays + Historie; bei „Münzwurf" klar sagen
6. `/trader-budget` – Stückzahl → `trader/orders.json`
7. `/trader-risk` – **immer** vor dem Broker; nur PASS geht weiter
8. `/trader-broker` – Ticket zeigen, Order **nur nach ausdrücklichem „ja"** des Nutzers
9. `/trader-alerts` – Stop, Ziel, „flat by close" (`add --from-plan`, dann `check`)

Regelmäßig daneben: `/trader-news` (Watchlist), `/trader-analyst` (Earnings),
`/trader-pelosi` (Kongress-Trades).

## Regeln
- Nie eine Order ohne PASS von `/trader-risk` und ein wörtliches „ja" des Nutzers.
- Keine erfundenen Kurse: Schlägt ein Datenabruf fehl (z. B. 403 vom Proxy), das kurz
  sagen und stoppen.
- Zeiten immer in New Yorker Zeit (ET) **und** deutscher Zeit angeben.
- Zustand in `trader/` (Watchlist, Plan, Orders, Alerts, Log) committen und pushen,
  damit die nächste Sitzung ihn hat – die Cloud-Umgebung ist flüchtig.

## Netzwerk (Cloud-Umgebung)
Diese Hosts müssen in den Umgebungs-Einstellungen unter „Allowed domains" freigegeben sein:
`query1.finance.yahoo.com`, `query2.finance.yahoo.com`, `feeds.finance.yahoo.com`,
`www.nasdaqtrader.com`, `stooq.com`, `www.sec.gov`, `data.sec.gov`,
`disclosures-clerk.house.gov`, `paper-api.alpaca.markets` (+ `api.alpaca.markets` nur für Live).
