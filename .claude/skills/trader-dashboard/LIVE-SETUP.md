# Alpaca-Dashboard live in der Claude-Desktop-App

Das Dashboard holt Kurse, Konto und Orders live, wenn es in der **Claude-Desktop-App** geöffnet ist
und dort ein lokaler Alpaca-Server mit dem Namen `alpaca` läuft. Im Browser oder auf dem Handy
bleibt es eine Momentaufnahme.

## 1. uv installieren (einmalig)
Mac, im Terminal:
```
brew install uv
```
(ohne Homebrew: `curl -LsSf https://astral.sh/uv/install.sh | sh`)

Danach `which uvx` eingeben und den Pfad merken, z. B. `/opt/homebrew/bin/uvx`.

## 2. Server in Claude eintragen
Claude-Desktop-App → **Einstellungen → Entwickler → Konfiguration bearbeiten**.
Das öffnet `claude_desktop_config.json`. Diesen Block einfügen (gibt es schon `mcpServers`,
nur den Eintrag `"alpaca"` ergänzen):

```json
{
  "mcpServers": {
    "alpaca": {
      "command": "/opt/homebrew/bin/uvx",
      "args": ["alpaca-mcp-server"],
      "env": {
        "ALPACA_API_KEY": "DEIN_PAPER_KEY",
        "ALPACA_SECRET_KEY": "DEIN_PAPER_SECRET",
        "ALPACA_PAPER_TRADE": "true",
        "ALPACA_TOOLSETS": "account,trading,stock-data"
      }
    }
  }
}
```
- `command`: der Pfad aus Schritt 1.
- Die Keys sind die **Papier**-Keys aus dem Alpaca-Dashboard (Paper Trading → API Keys).
  Nur in diese Datei tippen, nie in einen Chat.

## 3. Claude neu starten und Seite öffnen
Claude komplett beenden (Cmd+Q) und neu öffnen. Unter Einstellungen → Entwickler sollte `alpaca`
als „running“ stehen. Dann das Dashboard in der Desktop-App öffnen. Beim ersten Mal fragt Claude,
ob die Seite deinen lokalen Alpaca-Server nutzen darf: erlauben.

Oben rechts steht dann **Live** statt **Snapshot**.

## Was die Seite darf
Nur lesen: `get_stock_bars`, `get_account_info`, `get_all_positions`, `get_orders`.
Die Seite kann keine Orders senden. Kurse kommen vom kostenlosen IEX-Feed von Alpaca.
Sie aktualisiert den Chart alle 5 Sekunden, Watchlist und Konto alle 15 Sekunden, solange
der Tab sichtbar ist.

## Fehlerbilder
- **Snapshot** bleibt stehen: Server läuft nicht (Pfad in `command` falsch, Claude nicht neu gestartet)
  oder die Seite ist nicht in der Desktop-App offen.
- **Live nicht erlaubt**: Zugriff abgelehnt. Seite neu laden und erlauben.
- **Alpaca-Fehler**: meist falscher Key. Maus über das Feld zeigt die Meldung.
