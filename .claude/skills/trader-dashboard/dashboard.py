#!/usr/bin/env python3
"""trader-dashboard: one self-contained HTML page with the Alpaca paper account
(equity, positions, orders, fills) and daily charts of the symbols that matter
right now (positions, open orders, plan, top watchlist hits) with the scanner's
own signals, MA20, 20-day high, plan lines, fills and volatility (HV20, ATR14).

Read-only. It never places, changes or cancels an order.

    python3 .claude/skills/trader-dashboard/dashboard.py              # -> trader/dashboard.html
    python3 .claude/skills/trader-dashboard/dashboard.py --top 8      # more watchlist charts
    python3 .claude/skills/trader-dashboard/dashboard.py --symbols NVDA,AMD
    python3 .claude/skills/trader-dashboard/dashboard.py --no-alpaca  # charts only

Keys come from ALPACA_API_KEY / ALPACA_SECRET_KEY (paper). Prices from Yahoo
via the scanner's own fetch code, so signals match /trader-scanner exactly.
"""
import argparse
import datetime as dt
import html
import importlib.util
import json
import math
import os
import sys
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
SCAN_PY = os.path.join(HERE, "..", "trader-scanner", "scan.py")
PAPER = "https://paper-api.alpaca.markets"
ET = ZoneInfo("America/New_York")
DE = ZoneInfo("Europe/Berlin")
BARS_SHOWN = 90
SETUP_LABELS = {
    "breakout_20d": "Ausbruch 20T-Hoch",
    "bull_flag": "Bull Flag",
    "reclaim_ma20": "MA20 zurückerobert",
    "oversold": "Überverkauft (RSI<30)",
    "oversold_bounce": "Rebound nach überverkauft",
}
SETUP_ORDER = list(SETUP_LABELS)


def load_scanner():
    spec = importlib.util.spec_from_file_location("trader_scan", SCAN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- Alpaca (read only)

def alpaca_get(path):
    key, sec = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")
    if not key or not sec:
        raise RuntimeError("ALPACA_API_KEY / ALPACA_SECRET_KEY fehlen in der Umgebung")
    req = urllib.request.Request(PAPER + path, headers={
        "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def fetch_account():
    out = {"error": None}
    try:
        out["account"] = alpaca_get("/v2/account")
        out["positions"] = alpaca_get("/v2/positions")
        out["orders"] = alpaca_get("/v2/orders?status=all&limit=30&direction=desc&nested=false")
        out["fills"] = alpaca_get("/v2/account/activities/FILL?page_size=50")
        out["clock"] = alpaca_get("/v2/clock")
        try:
            out["history"] = alpaca_get("/v2/account/portfolio/history?period=1M&timeframe=1D")
        except Exception:
            out["history"] = None
    except urllib.error.HTTPError as e:
        out["error"] = "Alpaca antwortete HTTP %d" % e.code
    except Exception as e:  # network, missing keys
        out["error"] = str(getattr(e, "reason", e))
    return out


# ---------------------------------------------------------------- prices + indicators

def fetch_daily(scan, sym):
    s = scan.parse_chart(scan.yahoo_get(scan.chart_path(sym, "1y", "1d")), sym)
    bars = {}
    for i, ts in enumerate(s["t"]):
        o, h, l, c = (s[k][i] if s[k] else None for k in ("o", "h", "l", "c"))
        if None in (o, h, l, c):
            continue
        d = dt.datetime.fromtimestamp(ts, ET).date()
        bars[d] = {"d": d.isoformat(), "o": o, "h": h, "l": l, "c": c,
                   "v": (s["v"][i] if s["v"] else None) or 0}
    return [bars[d] for d in sorted(bars)], s.get("meta") or {}


def indicators(scan, bars):
    c = [b["c"] for b in bars]
    n = len(bars)
    ma20 = [sum(c[i - 19:i + 1]) / 20 if i >= 19 else None for i in range(n)]
    hi20 = [max(c[i - 20:i]) if i >= 20 else None for i in range(n)]
    rets = [math.log(c[i] / c[i - 1]) if i else None for i in range(n)]
    hv20 = []
    for i in range(n):
        if i < 20:
            hv20.append(None)
            continue
        w = rets[i - 19:i + 1]
        m = sum(w) / 20
        hv20.append(math.sqrt(sum((x - m) ** 2 for x in w) / 19) * math.sqrt(252) * 100)
    tr = [bars[0]["h"] - bars[0]["l"]] + [
        max(bars[i]["h"] - bars[i]["l"], abs(bars[i]["h"] - c[i - 1]), abs(bars[i]["l"] - c[i - 1]))
        for i in range(1, n)]
    atr, a = [], None
    for i in range(n):
        if i == 13:
            a = sum(tr[:14]) / 14
        elif i > 13:
            a = (a * 13 + tr[i]) / 14
        atr.append(a)
    sig = [[] for _ in range(n)]
    for i in range(30, n):
        sig[i] = scan.find_setups(c[:i + 1])[0]
    rsi = scan.rsi(c)
    return {"ma20": ma20, "hi20": hi20, "hv20": hv20, "atr": atr, "sig": sig, "rsi": rsi}


# ---------------------------------------------------------------- SVG chart

def fmt(x, nd=2):
    return "–" if x is None else f"{x:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def chart_svg(sym, bars, ind, lines, fills):
    W, H, VH, PADL, PADR, TOP = 760, 300, 80, 8, 62, 12
    k0 = max(0, len(bars) - BARS_SHOWN)
    B = bars[k0:]
    n = len(B)
    lo = min(b["l"] for b in B)
    hi = max(b["h"] for b in B)
    for v in lines.values():
        if v is not None:
            lo, hi = min(lo, v), max(hi, v)
    pad = (hi - lo) * 0.06 or 1
    lo, hi = lo - pad, hi + pad
    pw = W - PADL - PADR
    step = pw / n
    x = lambda i: PADL + step * (i + 0.5)
    y = lambda p: TOP + (hi - p) / (hi - lo) * (H - TOP - 18)
    out = [f'<svg class="chart" viewBox="0 0 {W} {H + VH + 22}" role="img" '
           f'aria-label="Tageschart {html.escape(sym)} der letzten {n} Handelstage">']
    # grid + price labels
    for j in range(5):
        p = lo + (hi - lo) * (j + 0.5) / 5
        yy = y(p)
        out.append(f'<line class="grid" x1="{PADL}" x2="{W - PADR}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        out.append(f'<text class="axis" x="{W - PADR + 6}" y="{yy + 4:.1f}">{fmt(p)}</text>')
    # month ticks
    last_m = None
    for i, b in enumerate(B):
        m = b["d"][:7]
        if m != last_m and i > 2:
            out.append(f'<text class="axis" x="{x(i):.1f}" y="{H + VH + 18}" text-anchor="middle">'
                       f'{["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"][int(m[5:]) - 1]}</text>')
            out.append(f'<line class="grid" x1="{x(i):.1f}" x2="{x(i):.1f}" y1="{TOP}" y2="{H + VH}"/>')
        last_m = m
    # 20d high (step) and MA20
    def poly(vals, cls):
        pts = [f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals) if v is not None]
        return f'<polyline class="{cls}" points="{" ".join(pts)}"/>' if pts else ""
    out.append(poly(ind["hi20"][k0:], "hi20"))
    out.append(poly(ind["ma20"][k0:], "ma20"))
    # candles
    cw = max(1.5, step * 0.62)
    for i, b in enumerate(B):
        up = b["c"] >= b["o"]
        cls = "up" if up else "dn"
        out.append(f'<line class="wick {cls}" x1="{x(i):.1f}" x2="{x(i):.1f}" y1="{y(b["h"]):.1f}" y2="{y(b["l"]):.1f}"/>')
        y1, y2 = y(max(b["o"], b["c"])), y(min(b["o"], b["c"]))
        out.append(f'<rect class="body {cls}" x="{x(i) - cw / 2:.1f}" y="{y1:.1f}" width="{cw:.1f}" height="{max(1, y2 - y1):.1f}"/>')
    # plan lines
    for name, v in lines.items():
        if v is None:
            continue
        out.append(f'<line class="lvl lvl-{name}" x1="{PADL}" x2="{W - PADR}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>')
        out.append(f'<text class="lvl-t lvl-{name}" x="{W - PADR - 4}" y="{y(v) - 4:.1f}" text-anchor="end">'
                   f'{ {"entry": "Einstieg", "stop": "Stop", "target": "Ziel", "avg": "Ø Einstand"}[name]} {fmt(v)}</text>')
    # signal markers (below the low), stacked
    for i, tags in enumerate(ind["sig"][k0:]):
        for s_i, t in enumerate(sorted(tags, key=SETUP_ORDER.index)):
            yy = y(B[i]["l"]) + 7 + s_i * 7
            out.append(f'<path class="sig s-{t}" d="M{x(i):.1f},{yy - 3:.1f} l3.2,5.5 h-6.4 z">'
                       f'<title>{B[i]["d"]}: {SETUP_LABELS[t]}</title></path>')
    # fills
    dates = {b["d"]: i for i, b in enumerate(B)}
    for f in fills:
        i = dates.get(f["date"])
        if i is None:
            continue
        buy = f["side"] == "buy"
        yy = y(f["price"])
        out.append(f'<circle class="fill {"buy" if buy else "sell"}" cx="{x(i):.1f}" cy="{yy:.1f}" r="5">'
                   f'<title>{f["date"]} {"Kauf" if buy else "Verkauf"} {f["qty"]} @ {fmt(f["price"])}</title></circle>')
    # volatility panel: HV20
    hv = ind["hv20"][k0:]
    vals = [v for v in hv if v is not None]
    if vals:
        vlo, vhi = 0, max(vals) * 1.15
        vy = lambda v: H + VH - (v / vhi) * (VH - 10)
        out.append(f'<line class="grid" x1="{PADL}" x2="{W - PADR}" y1="{H + VH}" y2="{H + VH}"/>')
        mid = round(vhi / 2)
        out.append(f'<line class="grid" x1="{PADL}" x2="{W - PADR}" y1="{vy(mid):.1f}" y2="{vy(mid):.1f}"/>')
        out.append(f'<text class="axis" x="{W - PADR + 6}" y="{vy(mid) + 4:.1f}">{mid} %</text>')
        pts = [(x(i), vy(v)) for i, v in enumerate(hv) if v is not None]
        area = f"M{pts[0][0]:.1f},{H + VH} " + " ".join(f"L{a:.1f},{b:.1f}" for a, b in pts) + f" L{pts[-1][0]:.1f},{H + VH} Z"
        out.append(f'<path class="hv-a" d="{area}"/>')
        out.append('<polyline class="hv" points="' + " ".join(f"{a:.1f},{b:.1f}" for a, b in pts) + '"/>')
        out.append(f'<circle class="hv-end" cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="3"/>')
        out.append(f'<text class="axis" x="{PADL + 2}" y="{H + 12}">Volatilität HV20 (annualisiert)</text>')
    # hover strips
    for i, b in enumerate(B):
        tip = (f'{b["d"]}  O {fmt(b["o"])}  H {fmt(b["h"])}  T {fmt(b["l"])}  S {fmt(b["c"])}  '
               f'Vol {b["v"]/1e6:.1f} Mio  HV20 {fmt(hv[i], 1)} %')
        out.append(f'<rect class="hit" x="{PADL + step * i:.1f}" y="{TOP}" width="{step:.1f}" '
                   f'height="{H + VH - TOP}"><title>{tip}</title></rect>')
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- page

CSS = """
:root{--bg:#f4f5f2;--panel:#ffffff;--ink:#1b2320;--mute:#5f6b66;--line:#dfe3df;--accent:#2f5d8a;
--up:#1f8a5b;--dn:#c2453a;--warn:#b7791f;--vol:#7a5aa6;
--f-display:"IBM Plex Sans Condensed","Arial Narrow",sans-serif;--f-body:"IBM Plex Sans",system-ui,sans-serif;--f-mono:"IBM Plex Mono",ui-monospace,monospace;color-scheme:light}
/* layout: summary strip, then account tables, then a grid of charts */
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#121614;--panel:#1a201d;--ink:#e6ebe8;--mute:#93a09a;--line:#2c3430;--accent:#7fb0e0;--up:#3fbf86;--dn:#ef6f63;--warn:#e0a84a;--vol:#b69be0;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#121614;--panel:#1a201d;--ink:#e6ebe8;--mute:#93a09a;--line:#2c3430;--accent:#7fb0e0;--up:#3fbf86;--dn:#ef6f63;--warn:#e0a84a;--vol:#b69be0;color-scheme:dark}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--f-body);font-size:15px;line-height:1.45}
main{max-width:1180px;margin:0 auto;padding:20px 16px 48px;display:grid;gap:20px}
h1,h2{font-family:var(--f-display);font-weight:600;margin:0;text-wrap:balance}h1{font-size:26px}h2{font-size:19px}
.meta{color:var(--mute);font-size:13px}.num{font-variant-numeric:tabular-nums;font-family:var(--f-mono)}
header{display:flex;flex-wrap:wrap;gap:8px 20px;align-items:baseline;justify-content:space-between}
.pill{display:inline-block;padding:2px 9px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid var(--line)}
.pill.open{color:var(--up);border-color:var(--up)}.pill.closed{color:var(--mute)}.pill.paper{color:var(--accent);border-color:var(--accent)}
.err{border-left:4px solid var(--dn);background:var(--panel);padding:10px 14px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px;display:grid;gap:2px}
.tile b{font-size:22px;font-family:var(--f-mono);font-variant-numeric:tabular-nums;font-weight:500}.tile span{color:var(--mute);font-size:13px}
.pos{color:var(--up)}.neg{color:var(--dn)}
section{display:grid;gap:10px}
.tbl{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:7px 12px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--mute);font-weight:500;font-size:12px}td.r,th.r{text-align:right}tr:last-child td{border-bottom:0}
.empty{color:var(--mute);padding:12px 14px}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr));gap:16px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px;display:grid;gap:8px}
.card h3{margin:0;font-family:var(--f-display);font-size:18px;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.why{font-size:12px;color:var(--mute);font-weight:400}
.chips{display:flex;flex-wrap:wrap;gap:6px}.chip{font-size:12px;padding:2px 8px;border-radius:4px;background:var(--bg);border:1px solid var(--line)}
.stats{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:13px;color:var(--mute)}.stats b{color:var(--ink);font-weight:500}
svg.chart{width:100%;height:auto;display:block}
.grid{stroke:var(--line);stroke-width:1}.axis{fill:var(--mute);font:11px var(--f-mono)}
.wick{stroke-width:1}.wick.up{stroke:var(--up)}.wick.dn{stroke:var(--dn)}.body.up{fill:var(--up)}.body.dn{fill:var(--dn)}
.ma20{fill:none;stroke:var(--accent);stroke-width:1.6}.hi20{fill:none;stroke:var(--mute);stroke-width:1;stroke-dasharray:3 3}
.lvl{stroke-width:1.4;stroke-dasharray:6 4}.lvl-t{font:600 11px var(--f-mono)}
.lvl-stop{stroke:var(--dn);fill:var(--dn)}.lvl-target{stroke:var(--up);fill:var(--up)}.lvl-entry,.lvl-avg{stroke:var(--accent);fill:var(--accent)}
.sig{stroke:none}.s-breakout_20d{fill:#2f7fd1}.s-bull_flag{fill:#159e8a}.s-reclaim_ma20{fill:#d08a14}.s-oversold{fill:#c2453a}.s-oversold_bounce{fill:#9a4fc8}
.fill{stroke:var(--panel);stroke-width:2}.fill.buy{fill:var(--up)}.fill.sell{fill:var(--dn)}
.hv{fill:none;stroke:var(--vol);stroke-width:1.5}.hv-a{fill:var(--vol);opacity:.13}.hv-end{fill:var(--vol)}
.hit{fill:transparent}.hit:hover{fill:var(--ink);opacity:.06}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px;color:var(--mute);align-items:center}
.legend i{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.note{font-size:13px;color:var(--mute);max-width:75ch}
"""


def money(x, sign=False):
    if x is None:
        return "–"
    s = fmt(abs(x)) + " $"
    if sign:
        return ("+" if x >= 0 else "−") + s
    return ("−" if x < 0 else "") + s


def cls(x):
    return "" if not x else ("pos" if x > 0 else "neg")


def ts_both(iso_or_dt):
    t = iso_or_dt if isinstance(iso_or_dt, dt.datetime) else dt.datetime.fromisoformat(iso_or_dt.replace("Z", "+00:00"))
    return f'{t.astimezone(ET):%d.%m. %H:%M} ET · {t.astimezone(DE):%H:%M} DE'


def page(now, acct, charts, watch, args):
    E = html.escape
    p = []
    p.append('<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">'
             '<meta name="viewport" content="width=device-width,initial-scale=1">'
             '<title>Alpaca Paper Dashboard</title>'
             '<link rel="preconnect" href="https://fonts.googleapis.com">'
             '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">'
             f'<style>{CSS}</style></head><body><main>')
    clock = acct.get("clock") or {}
    mk = ('<span class="pill open">Markt offen</span>' if clock.get("is_open")
          else '<span class="pill closed">Markt geschlossen</span>' if clock else "")
    p.append(f'<header><div><h1>Alpaca Paper Dashboard</h1>'
             f'<div class="meta">Stand {now.astimezone(ET):%d.%m.%Y %H:%M} ET · {now.astimezone(DE):%H:%M} Uhr DE. '
             f'Momentaufnahme, kein Live-Feed. Zum Auffrischen in Claude „Dashboard aktualisieren“ schreiben.</div></div>'
             f'<div class="chips"><span class="pill paper">Papierkonto</span>{mk}</div></header>')
    if acct.get("error"):
        p.append(f'<div class="err"><b>Kontodaten fehlen:</b> {E(acct["error"])}. Charts unten stammen trotzdem aus aktuellen Kursdaten.</div>')
    a = acct.get("account")
    if a:
        eq, last = float(a["equity"]), float(a.get("last_equity") or a["equity"])
        day = eq - last
        posv = sum(float(x["market_value"]) for x in acct.get("positions") or [])
        upl = sum(float(x["unrealized_pl"]) for x in acct.get("positions") or [])
        nxt = clock.get("next_open") if not clock.get("is_open") else clock.get("next_close")
        nxt_t = (("Nächste Eröffnung " if not clock.get("is_open") else "Schluss ") + ts_both(nxt)) if nxt else ""
        p.append('<div class="tiles">'
                 f'<div class="tile"><span>Depotwert</span><b>{money(eq)}</b><span>{nxt_t}</span></div>'
                 f'<div class="tile"><span>Heute</span><b class="{cls(day)}">{money(day, True)}</b><span>{fmt(day / last * 100 if last else 0)} % ggü. Vortag</span></div>'
                 f'<div class="tile"><span>Bargeld</span><b>{money(float(a["cash"]))}</b><span>Kaufkraft {money(float(a["buying_power"]))}</span></div>'
                 f'<div class="tile"><span>In Positionen</span><b>{money(posv)}</b><span class="{cls(upl)}">unrealisiert {money(upl, True)}</span></div>'
                 f'<div class="tile"><span>Day-Trades (5 Tage)</span><b>{a.get("daytrade_count", 0)}</b><span>Status {E(a.get("status", ""))}</span></div>'
                 '</div>')
        cfg = read_json("trader/config.json") or {}
        if cfg:
            p.append(f'<p class="note">Deine Regeln aus trader/config.json: Budget {money(cfg.get("budget") or cfg.get("account_size"))}, '
                     'Trades nur nach PASS von /trader-risk und deinem „ja“. Das Papierkonto selbst hat mehr Geld als dein Budget; '
                     'maßgeblich sind deine Regeln.</p>')
    # positions
    p.append('<section><h2>Positionen</h2>')
    pos = acct.get("positions") or []
    if pos:
        p.append('<div class="tbl"><table><tr><th>Symbol</th><th class="r">Stück</th><th class="r">Ø Einstand</th>'
                 '<th class="r">Kurs</th><th class="r">Wert</th><th class="r">G/V</th><th class="r">G/V %</th><th class="r">Heute</th></tr>')
        for x in pos:
            pl, plp, dpl = float(x["unrealized_pl"]), float(x["unrealized_plpc"]) * 100, float(x.get("unrealized_intraday_pl") or 0)
            p.append(f'<tr><td><b>{E(x["symbol"])}</b></td><td class="r num">{E(x["qty"])}</td><td class="r num">{fmt(float(x["avg_entry_price"]))}</td>'
                     f'<td class="r num">{fmt(float(x["current_price"]))}</td><td class="r num">{money(float(x["market_value"]))}</td>'
                     f'<td class="r num {cls(pl)}">{money(pl, True)}</td><td class="r num {cls(plp)}">{fmt(plp)} %</td>'
                     f'<td class="r num {cls(dpl)}">{money(dpl, True)}</td></tr>')
        p.append('</table></div>')
    else:
        p.append('<div class="tbl"><div class="empty">Keine offenen Positionen.</div></div>')
    p.append('</section>')
    # orders
    p.append('<section><h2>Orders (letzte 30)</h2>')
    orders = acct.get("orders") or []
    if orders:
        p.append('<div class="tbl"><table><tr><th>Zeit</th><th>Symbol</th><th>Seite</th><th>Typ</th><th class="r">Stück</th>'
                 '<th class="r">Limit/Stop</th><th class="r">Ausgeführt</th><th>Status</th></tr>')
        for o in orders:
            lim = o.get("limit_price") or o.get("stop_price")
            fp = o.get("filled_avg_price")
            st = o.get("status", "")
            stc = "pos" if st == "filled" else "neg" if st in ("canceled", "rejected", "expired") else ""
            p.append(f'<tr><td class="num">{ts_both(o["submitted_at"]) if o.get("submitted_at") else "–"}</td><td><b>{E(o["symbol"])}</b></td>'
                     f'<td>{"Kauf" if o["side"] == "buy" else "Verkauf"}</td><td>{E(o.get("order_class") or "")} {E(o.get("type") or "")}</td>'
                     f'<td class="r num">{E(str(o.get("qty") or o.get("notional") or ""))}</td><td class="r num">{fmt(float(lim)) if lim else "–"}</td>'
                     f'<td class="r num">{(E(o.get("filled_qty") or "0") + " @ " + fmt(float(fp))) if fp else "–"}</td><td class="{stc}">{E(st)}</td></tr>')
        p.append('</table></div>')
    else:
        p.append('<div class="tbl"><div class="empty">Noch keine Orders auf diesem Papierkonto.</div></div>')
    p.append('</section>')
    # charts
    p.append('<section><h2>Charts mit Signalen und Volatilität</h2>')
    wl = (f'Watchlist: {E(str(watch.get("mode")))}-Scan vom {E(str(watch.get("as_of") or watch.get("created_at")))}, '
          f'{len(watch.get("hits") or [])} Treffer. ') if watch else "Keine trader/watchlist.json. "
    p.append(f'<p class="note">{wl}Gezeigt: offene Positionen und Orders, der aktuelle Plan und die ersten {args.top} Watchlist-Treffer. '
             'Dreiecke unter den Kerzen sind die Scanner-Regeln, für jeden Tag der letzten 90 Handelstage nachgerechnet. '
             'Ein Signal ist eine Regel, die zutrifft, keine Kaufempfehlung. Maus über eine Kerze zeigt die Tageswerte.</p>')
    leg = "".join(f'<span><i class="s-{k}" style="background:currentColor"></i>{v}</span>'.replace(
        'style="background:currentColor"', f'style="background:{c}"')
        for (k, v), c in zip(SETUP_LABELS.items(), ["#2f7fd1", "#159e8a", "#d08a14", "#c2453a", "#9a4fc8"]))
    p.append(f'<div class="legend">{leg}<span><i style="background:var(--accent);height:3px"></i>MA20</span>'
             '<span><i style="border-top:1px dashed var(--mute);height:0"></i>20-Tage-Hoch</span>'
             '<span><i style="background:var(--vol);opacity:.5"></i>HV20</span>'
             '<span><i style="background:var(--up);border-radius:50%"></i>Kauf / <i style="background:var(--dn);border-radius:50%"></i>Verkauf</span></div>')
    p.append('<div class="charts">')
    for c in charts:
        if c.get("error"):
            p.append(f'<div class="card"><h3>{E(c["sym"])}</h3><div class="empty">Kein Chart: {E(c["error"])}</div></div>')
            continue
        last = c["bars"][-1]
        prev = c["bars"][-2]["c"]
        chg = (last["c"] / prev - 1) * 100
        ind = c["ind"]
        atr = ind["atr"][-1]
        tags = ind["sig"][-1]
        chips = "".join(f'<span class="chip">{SETUP_LABELS[t]}</span>' for t in tags) or '<span class="chip">kein Signal am letzten Tag</span>'
        p.append(f'<div class="card"><h3>{E(c["sym"])} <span class="num">{fmt(last["c"])} $</span>'
                 f'<span class="num {cls(chg)}" style="font-size:14px">{"+" if chg >= 0 else ""}{fmt(chg)} %</span>'
                 f'<span class="why">{E(c["why"])}</span></h3>'
                 f'<div class="chips">{chips}</div>'
                 f'<div class="stats"><span>Schluss <b>{E(last["d"])}</b></span><span>RSI 14 <b>{fmt(ind["rsi"], 1)}</b></span>'
                 f'<span>ATR 14 <b>{fmt(atr)} $ ({fmt(atr / last["c"] * 100, 1)} %)</b></span>'
                 f'<span>HV20 <b>{fmt(ind["hv20"][-1], 1)} %</b></span><span>MA20 <b>{fmt(ind["ma20"][-1])}</b></span></div>'
                 f'{c["svg"]}</div>')
    p.append('</div></section>')
    p.append('<p class="note">Datenquellen: Alpaca Paper API (Konto, Orders), Yahoo Finance (Tageskerzen, können verzögert sein). '
             'Keine Finanzberatung. Diese Seite liest nur und kann keine Orders auslösen.</p>')
    p.append('</main></body></html>')
    return "".join(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=6, help="Watchlist-Treffer mit Chart (Standard 6)")
    ap.add_argument("--symbols", default="", help="zusätzliche Symbole, Komma-getrennt")
    ap.add_argument("--watchlist", default="trader/watchlist.json")
    ap.add_argument("--out", default="trader/dashboard.html")
    ap.add_argument("--no-alpaca", action="store_true")
    args = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    scan = load_scanner()
    acct = {"error": "übersprungen (--no-alpaca)"} if args.no_alpaca else fetch_account()
    watch = read_json(args.watchlist) or {}
    plan = read_json("trader/plan.json") or {}
    entry = read_json("trader/entry.json") or {}

    picks = {}  # symbol -> reason, ordered by priority
    def add(sym, why):
        if sym and sym.upper() not in picks:
            picks[sym.upper()] = why
    for x in acct.get("positions") or []:
        add(x["symbol"], "Position")
    for o in acct.get("orders") or []:
        if o.get("status") in ("new", "accepted", "partially_filled", "held", "pending_new"):
            add(o["symbol"], "offene Order")
    add(plan.get("symbol"), "Plan (trader/plan.json)")
    add(entry.get("symbol"), "Einstieg (trader/entry.json)")
    for s in filter(None, args.symbols.split(",")):
        add(s.strip(), "auf Wunsch")
    for h in (watch.get("hits") or [])[:args.top]:
        add(h["symbol"], "Watchlist")

    fills_by = {}
    for f in acct.get("fills") or []:
        t = dt.datetime.fromisoformat(f["transaction_time"].replace("Z", "+00:00")).astimezone(ET)
        fills_by.setdefault(f["symbol"], []).append(
            {"date": t.date().isoformat(), "side": f["side"], "qty": f["qty"], "price": float(f["price"])})
    avg = {x["symbol"]: float(x["avg_entry_price"]) for x in acct.get("positions") or []}

    charts = []
    for sym, why in picks.items():
        try:
            bars, _ = fetch_daily(scan, sym)
            if len(bars) < 40:
                raise RuntimeError("zu wenige Tageskerzen")
            ind = indicators(scan, bars)
            lines = {"avg": avg.get(sym)}
            if plan.get("symbol", "").upper() == sym:
                lines.update(entry=plan.get("entry"), stop=plan.get("stop"), target=plan.get("target"))
            svg = chart_svg(sym, bars, ind, lines, fills_by.get(sym, []))
            charts.append({"sym": sym, "why": why, "bars": bars, "ind": ind, "svg": svg})
        except Exception as e:
            charts.append({"sym": sym, "why": why, "error": str(e)})
        print(f"  {sym:6} {why:28} {'ok' if 'svg' in charts[-1] else charts[-1]['error']}", file=sys.stderr)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        fh.write(page(now, acct, charts, watch, args))
    ok = sum(1 for c in charts if "svg" in c)
    print(json.dumps({"out": args.out, "charts": ok, "chart_errors": len(charts) - ok,
                      "alpaca_error": acct.get("error"), "as_of_utc": now.isoformat(timespec="seconds")}))


if __name__ == "__main__":
    main()
