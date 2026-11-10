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
        out["orders"] = alpaca_get("/v2/orders?status=all&limit=30&direction=desc&nested=true")
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


def fetch_intraday(scan, sym, rng="5d", interval="5m"):
    """Intraday bars of the regular session (5m over 5 days, 1m over 2 days)."""
    s = scan.parse_chart(scan.yahoo_get(scan.chart_path(sym, rng, interval)), sym)
    out = []
    for i, ts in enumerate(s["t"]):
        o, h, l, c = (s[k][i] if s[k] else None for k in ("o", "h", "l", "c"))
        if None in (o, h, l, c):
            continue
        t = dt.datetime.fromtimestamp(ts, ET)
        if not (dt.time(9, 30) <= t.time() < dt.time(16, 0)):
            continue
        out.append({"t": ts, "d": t.date().isoformat(), "hm": t.strftime("%H:%M"), "o": o, "h": h, "l": l, "c": c,
                    "v": (s["v"][i] if s["v"] else None) or 0})
    return out


def et_chart_time(ts):
    """Lightweight Charts draws UTC; shift so the axis reads New York time."""
    off = dt.datetime.fromtimestamp(ts, ET).utcoffset().total_seconds()
    return int(ts + off)


def r2(x):
    return None if x is None else round(x, 4)


SIG_COLORS = {"breakout_20d": "#0a84ff", "bull_flag": "#64d2ff", "reclaim_ma20": "#ff9f0a",
              "oversold": "#ff453a", "oversold_bounce": "#bf5af2"}
SIG_SHORT = {"breakout_20d": "Ausbruch", "bull_flag": "Flagge", "reclaim_ma20": "MA20",
             "oversold": "RSI<30", "oversold_bounce": "Rebound"}


def symbol_payload(sym, why, bars, ind, intraday, intraday1, lines, fills, orders, today_done):
    k0 = max(0, len(bars) - 160)
    B = bars[k0:]
    today = dt.datetime.now(ET).date().isoformat()
    daily = {
        "candles": [{"time": b["d"], "open": r2(b["o"]), "high": r2(b["h"]), "low": r2(b["l"]), "close": r2(b["c"])} for b in B],
        "volume": [{"time": b["d"], "value": b["v"], "color": "rgba(48,209,88,.35)" if b["c"] >= b["o"] else "rgba(255,69,58,.35)"} for b in B],
        "ma20": [{"time": b["d"], "value": r2(v)} for b, v in zip(B, ind["ma20"][k0:]) if v is not None],
        "hi20": [{"time": b["d"], "value": r2(v)} for b, v in zip(B, ind["hi20"][k0:]) if v is not None],
        "hv20": [{"time": b["d"], "value": round(v, 2)} for b, v in zip(B, ind["hv20"][k0:]) if v is not None],
        "markers": [],
    }
    for b, tags in zip(B, ind["sig"][k0:]):
        if b["d"] == today and not today_done:
            continue
        for t in sorted(tags, key=SETUP_ORDER.index):
            daily["markers"].append({"time": b["d"], "position": "belowBar", "color": SIG_COLORS[t], "shape": "arrowUp", "text": ""})
    def build(intraday, bar_s):
        if not intraday:
            return None
        last_day = intraday[-1]["d"]
        sess = [b for b in intraday if b["d"] == last_day and b["hm"] < "09:45"]
        orb = sess
        return {
            "candles": [{"time": et_chart_time(b["t"]), "open": r2(b["o"]), "high": r2(b["h"]), "low": r2(b["l"]), "close": r2(b["c"])} for b in intraday],
            "volume": [{"time": et_chart_time(b["t"]), "value": b["v"], "color": "rgba(48,209,88,.35)" if b["c"] >= b["o"] else "rgba(255,69,58,.35)"} for b in intraday],
            "or_high": r2(max(b["h"] for b in orb)) if orb else None,
            "or_low": r2(min(b["l"] for b in orb)) if orb else None,
            "session": last_day, "bar_s": bar_s,
            "markers": [],
        }
    intr = build(intraday, 300)
    m1 = build(intraday1, 60)
    for f in fills:
        txt = ("K " if f["side"] == "buy" else "V ") + str(f["qty"])
        m = {"position": "belowBar" if f["side"] == "buy" else "aboveBar", "color": "#30d158" if f["side"] == "buy" else "#ff453a",
             "shape": "arrowUp" if f["side"] == "buy" else "arrowDown", "text": txt}
        daily["markers"].append(dict(m, time=f["date"]))
        for v in (intr, m1):
            if v:
                ts = int(f["ts"] // v["bar_s"] * v["bar_s"])
                v["markers"].append(dict(m, time=et_chart_time(ts)))
    daily["markers"].sort(key=lambda m: m["time"])
    for v in (intr, m1):
        if v:
            v["markers"].sort(key=lambda m: m["time"])
    last, prev = bars[-1], bars[-2]
    live = intraday1 or intraday
    price = live[-1]["c"] if live else last["c"]
    ref = prev["c"] if last["d"] == (live[-1]["d"] if live else last["d"]) else last["c"]
    sig_now = []
    for b, tags in zip(reversed(bars), reversed(ind["sig"])):
        if b["d"] == today and not today_done:
            continue
        sig_now = tags
        break
    return {
        "sym": sym, "why": why, "price": r2(price), "chg": round((price / ref - 1) * 100, 2),
        "rsi": round(ind["rsi"], 1) if ind["rsi"] is not None else None,
        "atr": r2(ind["atr"][-1]), "atr_pct": round(ind["atr"][-1] / last["c"] * 100, 2),
        "hv": round(ind["hv20"][-1], 1) if ind["hv20"][-1] else None, "ma20": r2(ind["ma20"][-1]),
        "signals": [{"key": t, "label": SETUP_LABELS[t], "color": SIG_COLORS[t]} for t in sig_now],
        "lines": [{"price": v, "title": n, "kind": k} for k, (n, v) in lines.items() if v is not None] + orders,
        "daily": daily, "intraday": intr, "m1": m1,
    }


# ---------------------------------------------------------------- page

CSS = """
:root{--bg:#000;--card:#1c1c1e;--card2:#2c2c2e;--fill:rgba(118,118,128,.24);--fill2:rgba(118,118,128,.12);--sep:rgba(84,84,88,.6);
--ink:#fff;--ink2:rgba(235,235,245,.6);--ink3:rgba(235,235,245,.3);--blue:#0a84ff;--up:#30d158;--dn:#ff453a;--warn:#ff9f0a;--vol:#bf5af2;
--f:-apple-system,BlinkMacSystemFont,"SF Pro Text","SF Pro Display","Helvetica Neue",system-ui,sans-serif;
--ease:cubic-bezier(.32,.72,0,1);--r:14px;color-scheme:dark}
/* layout: iOS dark mode, inset grouped cards; account hero, chart card + watchlist side by side on wide screens, lists below */
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.35 var(--f);-webkit-font-smoothing:antialiased}
.num{font-variant-numeric:tabular-nums}
.up{color:var(--up)}.dn{color:var(--dn)}.mute{color:var(--ink2)}
button{font:inherit;color:inherit;background:none;border:0;padding:0;margin:0;cursor:pointer;text-align:inherit}
button:focus-visible{outline:2px solid var(--blue);outline-offset:2px;border-radius:10px}
.tap{transition:transform .18s var(--ease),background-color .18s,opacity .18s}
.tap:active{transform:scale(.97);opacity:.85}
.nav{position:sticky;top:0;z-index:20;background:rgba(0,0,0,.72);-webkit-backdrop-filter:saturate(180%) blur(20px);backdrop-filter:saturate(180%) blur(20px);border-bottom:.5px solid var(--sep)}
.nav-in{max-width:1180px;margin:0 auto;padding:10px 20px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.nav-title{font-weight:600;font-size:17px}
.nav .pills{margin-left:auto;display:flex;gap:6px;flex-wrap:wrap}
.pill{display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 12px;border-radius:999px;background:var(--fill2);color:var(--ink2);font-size:13px;font-weight:500}
.pill.on::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--up);box-shadow:0 0 0 3px rgba(48,209,88,.2)}
.pill.paper{background:rgba(10,132,255,.18);color:var(--blue)}
.wrap{max-width:1180px;margin:0 auto;padding:8px 20px 40px;display:grid;gap:22px}
.large{font-size:34px;font-weight:700;letter-spacing:.37px;margin:14px 0 0}
.sub{color:var(--ink2);font-size:13px;margin-top:2px}
.card{background:var(--card);border-radius:var(--r);overflow:hidden;min-width:0}
.section{display:grid;gap:8px;min-width:0}
.sec-h{display:flex;align-items:baseline;gap:8px;padding:0 4px}
.sec-h h2{margin:0;font-size:22px;font-weight:700;letter-spacing:.35px}
.sec-h .mute{font-size:13px;margin-left:auto}
.hero{padding:18px 18px 14px;display:grid;gap:14px}
.hero .lbl{color:var(--ink2);font-size:13px;font-weight:500}
.hero .eq{font-size:40px;font-weight:700;letter-spacing:-.5px;line-height:1.1}
.delta{display:inline-flex;align-items:center;gap:6px;font-size:15px;font-weight:600;margin-top:4px}
.spark{width:100%;height:56px;display:block}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px}
.tile{background:var(--card2);border-radius:12px;padding:10px 12px;display:grid;gap:2px}
.tile span{color:var(--ink2);font-size:12px;font-weight:500;display:flex;justify-content:space-between}
.tile span::after{content:"ⓘ";color:var(--ink3);font-size:12px}
.tile b{font-size:17px;font-weight:600}
.main{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:22px;align-items:start}
@media (max-width:920px){.main{grid-template-columns:1fr}}
.ch-head{padding:16px 16px 10px;display:grid;gap:10px}
.ch-top{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap}
.ch-top h1{margin:0;font-size:28px;font-weight:700;letter-spacing:.3px}
.ch-top .px{font-size:22px;font-weight:600}
.chg{display:inline-flex;align-items:center;height:26px;padding:0 9px;border-radius:7px;font-size:14px;font-weight:600;color:#fff}
.chg.up{background:var(--up);color:#000}.chg.dn{background:var(--dn)}
.ch-why{color:var(--ink2);font-size:13px}
.seg{position:relative;display:grid;grid-template-columns:repeat(3,1fr);background:var(--fill);border-radius:9px;padding:2px;min-width:220px;margin-left:auto}
.seg .thumb{position:absolute;top:2px;bottom:2px;left:2px;width:calc((100% - 4px)/3);border-radius:7px;background:#636366;box-shadow:0 3px 8px rgba(0,0,0,.12),0 3px 1px rgba(0,0,0,.04);transform:translateX(calc(var(--i,2)*100%));transition:transform .35s var(--ease)}
.seg button{position:relative;z-index:1;height:28px;font-size:13px;font-weight:500;text-align:center;border-radius:7px;color:var(--ink)}
.seg button[aria-pressed="true"]{font-weight:600}
.seg button:disabled{color:var(--ink3);cursor:default}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 11px;border-radius:999px;background:var(--fill2);font-size:13px;font-weight:500}
.chip i{width:8px;height:8px;border-radius:50%}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:0;border-top:.5px solid var(--sep);border-bottom:.5px solid var(--sep)}
@media (max-width:560px){.stats{grid-template-columns:repeat(2,1fr)}}
.stat{padding:9px 14px;display:grid;gap:1px;border-right:.5px solid var(--sep)}.stat:last-child{border-right:0}
.stat span{font-size:11px;color:var(--ink2);font-weight:500;text-transform:uppercase;letter-spacing:.3px}
.stat b{font-size:15px;font-weight:600}
.chartbox{transition:opacity .25s var(--ease)}.chartbox.fade{opacity:0}
#chart{height:420px}#hv{height:96px}
.hvlabel{padding:8px 16px 0;font-size:11px;color:var(--ink2);font-weight:500;text-transform:uppercase;letter-spacing:.3px;border-top:.5px solid var(--sep)}
.legend{display:flex;flex-wrap:wrap;gap:4px 14px;padding:10px 16px 14px;font-size:12px;color:var(--ink2)}
.legend i{display:inline-block;width:10px;height:2px;margin-right:5px;vertical-align:middle;border-radius:1px}
.list{display:grid}
.row{display:grid;grid-template-columns:minmax(0,1fr) auto auto 14px;align-items:center;gap:10px;padding:11px 14px 11px 16px;position:relative;width:100%}
.row::after{content:"";position:absolute;left:16px;right:0;bottom:0;border-bottom:.5px solid var(--sep)}
.row:last-child::after{display:none}
.row:active,.row[aria-selected="true"]{background:var(--card2)}
.row .t{font-weight:600;font-size:16px;display:flex;align-items:center;gap:6px}
.row .s{display:block;color:var(--ink2);font-size:13px;margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .p{font-size:15px;font-weight:500;text-align:right}
.row .chg{min-width:72px;justify-content:flex-end;font-size:13px;height:26px}
.row .chev{width:8px;height:13px;color:var(--ink3)}
.dots{display:inline-flex;gap:3px}.dots i{width:6px;height:6px;border-radius:50%;display:inline-block}
.row.o{grid-template-columns:minmax(0,1fr) auto 14px}
.badge{font-size:12px;font-weight:600;padding:2px 8px;border-radius:6px;background:var(--fill2);color:var(--ink2)}
.badge.up{background:rgba(48,209,88,.16);color:var(--up)}.badge.dn{background:rgba(255,69,58,.16);color:var(--dn)}.badge.warn{background:rgba(255,159,10,.16);color:var(--warn)}
.empty{color:var(--ink2);padding:18px 16px;text-align:center;font-size:15px}
.acct{display:grid;grid-template-columns:1fr 1fr;gap:22px;align-items:start}@media (max-width:920px){.acct{grid-template-columns:1fr}}
.err{background:rgba(255,69,58,.14);color:var(--ink);padding:12px 16px;border-radius:12px;font-size:14px}
.foot{color:var(--ink3);font-size:12px;line-height:1.5;padding:0 4px;max-width:90ch}.foot a{color:var(--ink2)}
#nolib{display:none;padding:24px 16px;color:var(--ink2);text-align:center}
.sheet{position:fixed;inset:0;z-index:50;display:flex;align-items:flex-end;justify-content:center}
.sheet[hidden]{display:none}
.sheet .bd{position:absolute;inset:0;background:rgba(0,0,0,.5);opacity:0;transition:opacity .3s var(--ease)}
.sheet .pn{position:relative;width:min(560px,100%);max-height:82vh;overflow:auto;background:var(--card);border-radius:14px 14px 0 0;padding:6px 18px 26px;transform:translateY(100%);transition:transform .38s var(--ease)}
@media (min-width:700px){.sheet{align-items:center}.sheet .pn{border-radius:16px;transform:translateY(24px) scale(.96);opacity:0;transition:transform .3s var(--ease),opacity .25s}}
.sheet.open .bd{opacity:1}.sheet.open .pn{transform:none;opacity:1}
.grab{width:36px;height:5px;border-radius:3px;background:var(--fill);margin:4px auto 6px}
.sh-h{display:flex;align-items:center;gap:10px;padding:6px 0 10px}
.sh-h h3{margin:0;font-size:20px;font-weight:700;flex:1}
.done{color:var(--blue);font-weight:600;font-size:17px;padding:6px 2px}
.sh-b{font-size:15px;color:var(--ink);display:grid;gap:12px}
.sh-b p{margin:0;color:var(--ink2);line-height:1.45}
.kvl{background:var(--card2);border-radius:12px;display:grid}
.kvl div{display:flex;justify-content:space-between;gap:12px;padding:11px 14px;position:relative}
.kvl div+div::before{content:"";position:absolute;left:14px;right:0;top:0;border-top:.5px solid var(--sep)}
.kvl span{color:var(--ink2)}.kvl b{font-weight:500;text-align:right}
.btn{display:block;width:100%;text-align:center;background:var(--blue);color:#fff;font-weight:600;font-size:17px;border-radius:12px;padding:13px}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const C = {bg:'#1c1c1e', grid:'rgba(255,255,255,.06)', text:'rgba(235,235,245,.6)', up:'#30d158', dn:'#ff453a', accent:'#0a84ff', vol:'#bf5af2', warn:'#ff9f0a'};
const LINE = {entry:C.accent, stop:C.dn, target:C.up, avg:'#ffffff', order:C.warn, or_high:'#8e8e93', or_low:'#8e8e93'};
const fmt = (x, d=2) => x == null || isNaN(x) ? '–' : x.toLocaleString('de-DE', {minimumFractionDigits:d, maximumFractionDigits:d});
const esc = t => String(t ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const money = (x, sign) => x == null || isNaN(x) ? '–' : (sign ? (x >= 0 ? '+' : '−') : (x < 0 ? '−' : '')) + fmt(Math.abs(x)) + ' $';
const pn = x => x > 0 ? 'up' : x < 0 ? 'dn' : '';
const pct = x => (x >= 0 ? '+' : '−') + fmt(Math.abs(x)) + ' %';
const CHEV = '<svg class="chev" viewBox="0 0 8 13" aria-hidden="true"><path d="M1.5 1.5 6.5 6.5 1.5 11.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const STATUS = {filled:'ausgeführt', new:'offen', accepted:'offen', pending_new:'offen', held:'wartet (Bracket)', partially_filled:'teilweise',
  canceled:'storniert', expired:'verfallen', rejected:'abgelehnt', replaced:'ersetzt', done_for_day:'Tagesende'};
const TYP = {limit:'Limit', market:'Market', stop:'Stop', stop_limit:'Stop-Limit'};
const INFO = {
  equity:['Depotwert', 'Alles zusammen: Bargeld plus der aktuelle Wert deiner offenen Positionen. Das ist dein Papierkonto bei Alpaca, kein echtes Geld.'],
  day:['Heute', 'Wie sich der Depotwert seit gestern Abend (Schlusskurs 16:00 ET) verändert hat, in Dollar und Prozent.'],
  upl:['Unrealisiert', 'Gewinn oder Verlust der Positionen, die noch offen sind. Er wird erst echt, wenn du verkaufst.'],
  cash:['Bargeld', 'Geld, das gerade nicht in Aktien steckt.'],
  bp:['Kaufkraft', 'Wie viel Alpaca dich kaufen ließe, inklusive Hebel. Unser Budget bleibt trotzdem bei 1.000 $ und höchstens 10 $ Verlust pro Trade.'],
  dt:['Day-Trades (5 Tage)', 'Wie viele Day-Trades (am selben Tag gekauft und verkauft) in den letzten fünf Handelstagen gezählt wurden.'],
  rsi:['RSI 14', 'Misst, wie stark die letzten 14 Tage nach oben oder unten liefen. Unter 30 gilt als überverkauft, über 70 als überkauft.'],
  atr:['ATR 14', 'Durchschnittliche Tagesschwankung der letzten 14 Tage. Ein Stop enger als die halbe ATR wird oft vom normalen Rauschen ausgelöst, deshalb gilt das im Qualitätsfilter.'],
  hv:['HV20', 'Historische Volatilität der letzten 20 Tage, aufs Jahr hochgerechnet. Hoch heißt: große Schwankungen, also mehr Risiko pro Aktie.'],
  ma20:['MA20', 'Durchschnitt der letzten 20 Schlusskurse (blaue Linie im Tageschart). Darüber gilt der kurzfristige Trend als intakt.'],
  live:['Snapshot oder Live', 'Die Seite ist eine Momentaufnahme vom angegebenen Stand. Schreib in Claude „Dashboard aktualisieren“, dann baue ich sie neu. Bei jedem geplanten Check passiert das automatisch.'],
  market:['Marktzeiten', 'Die US-Börse ist Montag bis Freitag von 9:30 bis 16:00 Uhr New Yorker Zeit offen, das ist 15:30 bis 22:00 Uhr bei dir. Neue Einstiege nur 9:45 bis 15:30 ET, flat bis 15:55 ET.'],
  paper:['Papierkonto', 'Alle Orders laufen über Alpacas Papierkonto mit Spielgeld. Eine Order gibt es nur nach deinem „ja“ im Chat.'],
};
const SIG = {
  breakout_20d:'Der Schlusskurs liegt auf dem höchsten Stand der letzten 20 Tage. Ausbrüche laufen manchmal weiter, scheitern aber auch oft.',
  bull_flag:'Erst ein kräftiger Anstieg, dann ein paar ruhige, leicht fallende Tage. Das Muster wartet auf einen Ausbruch nach oben.',
  reclaim_ma20:'Der Kurs hat den 20-Tage-Durchschnitt von unten zurückerobert. Kann den Beginn einer Erholung markieren.',
  oversold:'Der RSI liegt unter 30: Die Aktie ist stark gefallen. Das ist ein Warnsignal und kein Kaufsignal, es kann weiter fallen.',
  oversold_bounce:'Nach überverkauftem Stand schließt die Aktie wieder höher. Ein erster Erholungsversuch, mehr nicht.',
};
let cur = 0, tf = 'D', chart, hvChart, cs, vs, lastFocus = null;

// ---------- sheet ----------
function sheet(title, body){
  const s = $('#sheet'); $('#sh-t').textContent = title; $('#sh-b').innerHTML = body;
  lastFocus = document.activeElement; s.hidden = false;
  requestAnimationFrame(() => requestAnimationFrame(() => s.classList.add('open')));
  setTimeout(() => $('#sh-x').focus(), 60);
  $$('#sh-b [data-open]').forEach(b => b.addEventListener('click', () => { closeSheet(); openSym(b.dataset.open); }));
}
function closeSheet(){
  const s = $('#sheet'); if (s.hidden) return; s.classList.remove('open');
  setTimeout(() => { s.hidden = true; }, 320); if (lastFocus) lastFocus.focus();
}
const kvl = rows => '<div class="kvl">' + rows.filter(r => r).map(([k, v, c]) => `<div><span>${esc(k)}</span><b class="${c || ''}">${v}</b></div>`).join('') + '</div>';
const openBtn = sym => D.symbols.some(s => s.sym === sym) ? `<button class="btn tap" data-open="${esc(sym)}">Chart von ${esc(sym)} öffnen</button>` : '';
function info(key, extra){ const [t, p] = INFO[key]; sheet(t, `<p>${esc(p)}</p>` + (extra || '')); }

function openSym(sym){
  const i = D.symbols.findIndex(s => s.sym === sym); if (i < 0) return false;
  cur = i; render(true); $('#chartcard').scrollIntoView({behavior:'smooth', block:'start'}); return true;
}

// ---------- account ----------
function renderAccount(a, P, O){
  if (a && a.equity) {
    const eq = +a.equity, last = +(a.last_equity || a.equity), day = eq - last, upl = P.reduce((t, x) => t + +x.unrealized_pl, 0);
    $('#eq').textContent = money(eq);
    const d = $('#day'); d.className = 'delta ' + pn(day); d.textContent = `${money(day, true)} (${pct(last ? day / last * 100 : 0)}) heute`;
    const T = [['upl', 'Unrealisiert', money(upl, true), pn(upl)], ['cash', 'Bargeld', money(+a.cash), ''], ['bp', 'Kaufkraft', money(+a.buying_power), ''], ['dt', 'Day-Trades 5T', String(a.daytrade_count ?? 0), '']];
    $('#kvs').innerHTML = T.map(([k, l, v, c]) => `<button class="tile tap" data-info="${k}"><span>${l}</span><b class="num ${c}">${v}</b></button>`).join('');
    $$('#kvs [data-info]').forEach(b => b.addEventListener('click', () => info(b.dataset.info)));
  }
  $('#poscount').textContent = P.length ? P.length + (P.length === 1 ? ' offen' : ' offen') : '';
  $('#posbox').innerHTML = P.length ? '<div class="list">' + P.map((x, i) => {
    const pl = +x.unrealized_pl, plp = +x.unrealized_plpc * 100;
    return `<button class="row tap" data-pos="${i}"><span><span class="t">${esc(x.symbol)}</span><span class="s">${esc(x.qty)} Stück · Ø ${fmt(+x.avg_entry_price)} $</span></span>
      <span class="p num">${fmt(+x.current_price)}</span><span class="chg ${pl >= 0 ? 'up' : 'dn'} num">${money(pl, true)}</span>${CHEV}</button>`; }).join('') + '</div>'
    : '<div class="empty">Keine offenen Positionen</div>';
  $$('#posbox [data-pos]').forEach(b => b.addEventListener('click', () => {
    const x = P[+b.dataset.pos], pl = +x.unrealized_pl;
    sheet(x.symbol, kvl([['Stück', esc(x.qty)], ['Ø Einstand', fmt(+x.avg_entry_price) + ' $'], ['Aktueller Kurs', fmt(+x.current_price) + ' $'],
      ['Wert', money(+x.market_value)], ['Gewinn/Verlust', `${money(pl, true)} (${pct(+x.unrealized_plpc * 100)})`, pn(pl)], ['Heute', pct(+x.change_today * 100), pn(+x.change_today)]]) + openBtn(x.symbol));
  }));
  const rows = [];
  for (const o of O) { rows.push(o); for (const l of (o.legs || [])) rows.push(Object.assign({}, l, {_leg:true, _parent:o})); }
  $('#ordbox').innerHTML = rows.length ? '<div class="list">' + rows.map((o, i) => {
    const st = o.status || '', lim = o.limit_price || o.stop_price;
    let typ = TYP[o.type] || o.type || ''; if (o._leg) typ = '↳ ' + (o.type === 'limit' ? 'Ziel' : 'Stop'); else if (o.order_class === 'bracket') typ += ' · Bracket';
    const t = o.submitted_at && !o._leg ? when(o.submitted_at) : '';
    const stc = st === 'filled' ? 'up' : ['canceled','rejected','expired'].includes(st) ? 'dn' : ['new','accepted','held','pending_new','partially_filled'].includes(st) ? 'warn' : '';
    const what = o.filled_avg_price ? `${esc(o.filled_qty)} @ ${fmt(+o.filled_avg_price)}` : (lim ? fmt(+lim) : esc(o.qty || ''));
    return `<button class="row o tap" data-ord="${i}"><span><span class="t"><span class="${o.side === 'buy' ? 'up' : 'dn'}">${o.side === 'buy' ? 'Kauf' : 'Verkauf'}</span> ${esc(o.symbol)}</span>
      <span class="s">${esc(typ)} · ${what}${t ? ' · ' + t : ''}</span></span><span class="badge ${stc}">${esc(STATUS[st] || st)}</span>${CHEV}</button>`; }).join('') + '</div>'
    : '<div class="empty">Noch keine Orders</div>';
  $$('#ordbox [data-ord]').forEach(b => b.addEventListener('click', () => {
    const o = rows[+b.dataset.ord], st = o.status || '';
    let typ = TYP[o.type] || o.type || ''; if (o._leg) typ = o.type === 'limit' ? 'Ziel (Take-Profit)' : 'Stop-Loss'; else if (o.order_class === 'bracket') typ += ' mit Stop und Ziel (Bracket)';
    sheet(`${o.side === 'buy' ? 'Kauf' : 'Verkauf'} ${o.symbol}`, kvl([['Art', esc(typ)], ['Stück', esc(o.qty || o.notional || '')],
      o.limit_price ? ['Limit', fmt(+o.limit_price) + ' $'] : null, o.stop_price ? ['Stop', fmt(+o.stop_price) + ' $'] : null,
      ['Ausgeführt', o.filled_avg_price ? `${esc(o.filled_qty)} @ ${fmt(+o.filled_avg_price)} $` : '–'], ['Status', esc(STATUS[st] || st)],
      (o.submitted_at || (o._parent && o._parent.submitted_at)) ? ['Aufgegeben', when(o.submitted_at || o._parent.submitted_at, true)] : null,
      o.filled_at ? ['Ausgeführt um', when(o.filled_at, true)] : null, ['Gültig', o.time_in_force === 'day' ? 'nur heute' : esc(o.time_in_force || '')]]) + openBtn(o.symbol));
  }));
}
function when(iso, date){
  const ms = Date.parse(iso), o = {hour:'2-digit', minute:'2-digit'};
  const d = date ? new Date(ms).toLocaleDateString('de-DE', {timeZone:'America/New_York', day:'2-digit', month:'2-digit'}) + ' ' : '';
  return `${d}${new Date(ms).toLocaleTimeString('de-DE', Object.assign({timeZone:'America/New_York'}, o))} ET · ${new Date(ms).toLocaleTimeString('de-DE', Object.assign({timeZone:'Europe/Berlin'}, o))} DE`;
}
function spark(){
  const h = D.history, el = $('#spark'); if (!h || !h.length || h.length < 2) { el.style.display = 'none'; return; }
  const W = 600, H = 56, lo = Math.min(...h), hi = Math.max(...h), rng = hi - lo || 1;
  const pts = h.map((v, i) => [i / (h.length - 1) * W, H - 4 - (v - lo) / rng * (H - 8)]);
  const d = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
  const col = h[h.length - 1] >= h[0] ? C.up : C.dn;
  el.innerHTML = `<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${col}" stop-opacity=".3"/><stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>
    <path d="${d} L${W} ${H} L0 ${H} Z" fill="url(#g)"/><path d="${d}" fill="none" stroke="${col}" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>`;
}

// ---------- chart ----------
function base(el, h){
  return LightweightCharts.createChart(el, {height:h, layout:{background:{color:C.bg}, textColor:C.text, fontSize:11, fontFamily:'-apple-system,BlinkMacSystemFont,system-ui,sans-serif'},
    grid:{vertLines:{visible:false}, horzLines:{color:C.grid}}, rightPriceScale:{borderVisible:false}, leftPriceScale:{borderVisible:false},
    timeScale:{borderVisible:false, timeVisible:true, secondsVisible:false, rightOffset:4},
    crosshair:{mode:0, vertLine:{color:'rgba(255,255,255,.25)', labelBackgroundColor:'#3a3a3c'}, horzLine:{color:'rgba(255,255,255,.25)', labelBackgroundColor:'#3a3a3c'}},
    localization:{locale:'de-DE', priceFormatter:p => fmt(p)}});
}
function render(anim){
  const s = D.symbols[cur]; if (!s) return;
  const box = $('.chartbox');
  if (anim) { box.classList.add('fade'); setTimeout(() => { draw(s); box.classList.remove('fade'); }, 140); } else draw(s);
  $('#sym').textContent = s.sym;
  $('#px').textContent = fmt(s.price) + ' $';
  const ch = $('#chg'); ch.textContent = pct(s.chg); ch.className = 'chg num ' + (s.chg >= 0 ? 'up' : 'dn');
  $('#why').textContent = s.why;
  $('#sigs').innerHTML = s.signals.length ? s.signals.map(g => `<button class="chip tap" data-sig="${g.key}"><i style="background:${g.color}"></i>${esc(g.label)}</button>`).join('') : '<span class="mute" style="font-size:13px">Kein Signal am letzten Schlusskurs</span>';
  $$('#sigs [data-sig]').forEach(b => b.addEventListener('click', () => { const g = s.signals.find(x => x.key === b.dataset.sig); sheet(g.label, `<p>${esc(SIG[g.key] || '')}</p><p>Signale sind Regeln des Scanners, keine Kaufempfehlung. Ein Ticket gibt es nur, wenn der Qualitätsfilter passt.</p>`); }));
  const st = [['rsi', 'RSI 14', fmt(s.rsi, 1)], ['atr', 'ATR 14', `${fmt(s.atr)} $`], ['hv', 'HV20', `${fmt(s.hv, 1)} %`], ['ma20', 'MA20', fmt(s.ma20)]];
  $('#st').innerHTML = st.map(([k, l, v]) => `<button class="stat tap" data-info="${k}"><span>${l}</span><b class="num">${v}</b></button>`).join('');
  $$('#st [data-info]').forEach(b => b.addEventListener('click', () => info(b.dataset.info, b.dataset.info === 'atr' ? kvl([['ATR in Prozent', fmt(s.atr_pct, 1) + ' %'], ['Halbe ATR (Mindest-Stop)', fmt(s.atr / 2) + ' $']]) : '')));
  $$('.wl .row').forEach((r, i) => r.setAttribute('aria-selected', i === cur));
  const idx = {M:0, I:1, D:2}[tf]; $('.seg').style.setProperty('--i', idx);
  $$('.seg button').forEach(b => b.setAttribute('aria-pressed', b.dataset.tf === tf));
  $('.seg button[data-tf="I"]').disabled = !s.intraday; $('.seg button[data-tf="M"]').disabled = !s.m1;
  $('#sess').textContent = tf === 'D' ? 'Tageskerzen' : `Sitzung ${(tf === 'M' ? s.m1 : s.intraday).session}, Zeiten in ET`;
}
function draw(s){
  const el = $('#chart'), hv = $('#hv');
  if (chart) chart.remove(); if (hvChart) { hvChart.remove(); hvChart = null; }
  el.innerHTML = ''; hv.innerHTML = '';
  const iv = tf === 'M' ? s.m1 : tf === 'I' ? s.intraday : null, intra = !!iv, src = iv || s.daily;
  chart = base(el, el.clientHeight);
  cs = chart.addCandlestickSeries({upColor:C.up, downColor:C.dn, borderVisible:false, wickUpColor:C.up, wickDownColor:C.dn});
  cs.setData(src.candles);
  vs = chart.addHistogramSeries({priceScaleId:'vol', priceFormat:{type:'volume'}, lastValueVisible:false, priceLineVisible:false});
  chart.priceScale('vol').applyOptions({scaleMargins:{top:0.85, bottom:0}});
  vs.setData(src.volume);
  if (!intra) {
    chart.addLineSeries({color:C.accent, lineWidth:2, lastValueVisible:false, priceLineVisible:false, crosshairMarkerVisible:false}).setData(s.daily.ma20);
    chart.addLineSeries({color:'#8e8e93', lineWidth:1, lineStyle:2, lineType:1, lastValueVisible:false, priceLineVisible:false, crosshairMarkerVisible:false}).setData(s.daily.hi20);
  } else {
    if (iv.or_high) cs.createPriceLine({price:iv.or_high, color:LINE.or_high, lineWidth:1, lineStyle:1, axisLabelVisible:true, title:'OR-Hoch'});
    if (iv.or_low) cs.createPriceLine({price:iv.or_low, color:LINE.or_low, lineWidth:1, lineStyle:1, axisLabelVisible:true, title:'OR-Tief'});
  }
  for (const l of s.lines) cs.createPriceLine({price:l.price, color:LINE[l.kind] || C.text, lineWidth:1, lineStyle:2, axisLabelVisible:true, title:l.title});
  cs.setMarkers(src.markers);
  const n = src.candles.length;
  chart.timeScale().setVisibleLogicalRange({from:Math.max(0, n - (intra ? (tf === 'M' ? 200 : 160) : 110)), to:n + 4});
  if (!intra) {
    hvChart = base(hv, hv.clientHeight);
    hvChart.applyOptions({timeScale:{visible:false}, handleScroll:false, handleScale:false});
    const h = hvChart.addAreaSeries({lineColor:C.vol, topColor:'rgba(191,90,242,.3)', bottomColor:'rgba(191,90,242,0)', lineWidth:2,
      priceFormat:{type:'custom', formatter:v => fmt(v, 0) + ' %'}});
    h.setData(s.daily.hv20);
    const sync = r => { if (r && hvChart) hvChart.timeScale().setVisibleLogicalRange(r); };
    chart.timeScale().subscribeVisibleLogicalRangeChange(sync);
    sync(chart.timeScale().getVisibleLogicalRange());
  }
  $('#hvwrap').hidden = intra;
}

// ---------- wiring ----------
$('#sh-x').addEventListener('click', closeSheet);
$('#sheet .bd').addEventListener('click', closeSheet);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSheet(); });
$$('[data-info]').forEach(b => b.addEventListener('click', () => info(b.dataset.info)));
renderAccount(D.account, D.positions || [], D.orders || []);
spark();
$$('.wl .row').forEach((r, i) => r.addEventListener('click', () => { cur = i; render(true); if (window.innerWidth < 920) $('#chartcard').scrollIntoView({behavior:'smooth', block:'start'}); }));
$$('.seg button').forEach(b => b.addEventListener('click', () => { if (b.disabled) return; tf = b.dataset.tf; render(true); }));
if (!window.LightweightCharts) { $('#nolib').style.display = 'block'; }
else {
  let t; window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(() => render(false), 150); });
  if (D.symbols.length) render(false);
  startLive();
}
"""

LIVE_JS = r"""
// ---------- live mode: Claude desktop app + local Alpaca MCP server (host:alpaca) ----------
const SRV = 'host:alpaca';
const asList = p => Array.isArray(p) ? p : (p && Array.isArray(p.result) ? p.result : (p && Array.isArray(p.orders) ? p.orders : (p && Array.isArray(p.positions) ? p.positions : [])));
let mcp = null, liveOk = false, lastLive = 0;

function etParts(ms){
  const f = new Intl.DateTimeFormat('en-US', {timeZone:'America/New_York', year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23'});
  const o = {}; for (const p of f.formatToParts(new Date(ms))) o[p.type] = p.value;
  return o;
}
function etShift(ms){ const o = etParts(ms); return Math.floor(Date.UTC(+o.year, +o.month - 1, +o.day, +o.hour, +o.minute, +o.second) / 1000); }
function hhmm(ms, tz){ return new Date(ms).toLocaleTimeString('de-DE', {timeZone:tz, hour:'2-digit', minute:'2-digit', second:'2-digit'}); }
function setState(text, kind, title){
  const el = $('#livestate'); el.textContent = text; el.className = 'pill tap' + (kind === 'live' ? ' on' : '');
  el.style.color = kind === 'warn' ? 'var(--warn)' : kind === 'err' ? 'var(--dn)' : '';
  if (title) el.title = title;
}
function handleErr(e){
  const c = e && e.code;
  if (c === 'server_not_connected') setState('Snapshot', '');
  else if (c === 'not_in_manifest' || c === 'approval_required' || c === 'cancelled') setState('Live nicht erlaubt', 'warn');
  else if (c === 'tool_error') setState('Alpaca-Fehler', 'err', (e.message || '').slice(0, 300));
  else setState(liveOk ? 'Live (hakt)' : 'Snapshot', liveOk ? 'warn' : '', (e && e.message) || '');
  return c;
}
async function call(tool, input){ const r = await mcp.callTool(SRV, tool, input, {cache:false}); return r.payload; }
function mergeBars(s, key, bars, toTime){
  const src = key === 'daily' ? s.daily : key === 'm1' ? s.m1 : s.intraday;
  if (!src || !bars || !bars.length) return;
  const visible = D.symbols[cur] === s && ((key === 'daily' && tf === 'D') || (key === 'm1' && tf === 'M') || (key === 'intraday' && tf === 'I'));
  for (const b of bars) {
    const t = toTime(b); if (t == null) continue;
    const c = {time:t, open:b.o, high:b.h, low:b.l, close:b.c};
    const v = {time:t, value:b.v, color: b.c >= b.o ? 'rgba(48,209,88,.35)' : 'rgba(255,69,58,.35)'};
    const arr = src.candles, last = arr[arr.length - 1];
    if (last && last.time === t) { arr[arr.length - 1] = c; src.volume[src.volume.length - 1] = v; }
    else if (!last || t > last.time) { arr.push(c); src.volume.push(v); }
    else continue;
    if (visible && cs) { cs.update(c); vs.update(v); }
  }
}
function inSession(ms){ const o = etParts(ms); const m = +o.hour * 60 + +o.minute; return m >= 570 && m < 960; }
async function pollChart(){
  const s = D.symbols[cur]; if (!s) return;
  if (tf === 'D') {
    const p = await call('get_stock_bars', {symbols:s.sym, timeframe:'1Day', days:5, feed:'iex', limit:10});
    mergeBars(s, 'daily', (p && p.bars && p.bars[s.sym]) || [], b => { const o = etParts(Date.parse(b.t) + 12 * 3600e3); return `${o.year}-${o.month}-${o.day}`; });
  } else {
    const key = tf === 'M' ? 'm1' : 'intraday', tfa = tf === 'M' ? '1Min' : '5Min';
    const p = await call('get_stock_bars', {symbols:s.sym, timeframe:tfa, hours:12, days:0, feed:'iex', limit:1000});
    mergeBars(s, key, ((p && p.bars && p.bars[s.sym]) || []).filter(b => inSession(Date.parse(b.t))), b => etShift(Date.parse(b.t)));
  }
}
async function pollPrices(){
  const p = await call('get_stock_bars', {symbols:D.symbols.map(s => s.sym).join(','), timeframe:'1Min', minutes:20, hours:0, days:0, feed:'iex', limit:1000});
  const all = (p && p.bars) || {}, rows = $$('.wl .row');
  D.symbols.forEach((s, i) => {
    const b = all[s.sym]; if (!b || !b.length) return;
    const px = b[b.length - 1].c, ref = s.price / (1 + s.chg / 100);
    s.price = px; s.chg = (px / ref - 1) * 100;
    const r = rows[i];
    if (r) { r.querySelector('.p').textContent = fmt(px); const c = r.querySelector('.chg'); c.textContent = pct(s.chg); c.className = 'chg num ' + (s.chg >= 0 ? 'up' : 'dn'); }
    if (i === cur) { $('#px').textContent = fmt(px) + ' $'; const ch = $('#chg'); ch.textContent = pct(s.chg); ch.className = 'chg num ' + (s.chg >= 0 ? 'up' : 'dn'); }
  });
}
async function pollAccount(){
  const [a, pos, ords] = await Promise.all([call('get_account_info', {}), call('get_all_positions', {}), call('get_orders', {status:'all', limit:30, nested:true, direction:'desc'})]);
  renderAccount(a, asList(pos), asList(ords));
}
let busy = false, tick = 0, stopped = false, accountOff = false, timer = null;
async function liveTick(){
  if (busy || document.hidden) return; busy = true;
  try {
    const jobs = [pollChart()];
    if (tick % 3 === 0) jobs.push(pollPrices());
    if (tick % 3 === 1 && !accountOff) jobs.push(pollAccount().catch(e => { if (['cancelled','approval_required','not_in_manifest'].includes(e && e.code)) { accountOff = true; return; } throw e; }));
    await Promise.all(jobs);
    liveOk = true; lastLive = Date.now();
    setState('Live', 'live');
    $('#stand').textContent = `Aktualisiert ${hhmm(lastLive, 'America/New_York').slice(0,5)} ET · ${hhmm(lastLive, 'Europe/Berlin').slice(0,5)} DE`;
  } catch (e) {
    const c = handleErr(e);
    if (['server_not_connected','not_in_manifest','approval_required','cancelled','not_granted','capability_disabled','capability_removed'].includes(c) && !liveOk) { stopped = true; if (timer) { clearInterval(timer); timer = null; } }
  } finally { busy = false; tick++; }
}
async function startLive(){
  if (!window.claude || !claude.use) return;
  try { mcp = await claude.use('mcp'); } catch (e) { mcp = null; }
  if (!mcp) return;
  setState('Verbinde …', 'warn');
  await liveTick();
  if (!stopped) timer = setInterval(liveTick, 5000);
  $$('.wl .row, .seg button').forEach(el => el.addEventListener('click', () => setTimeout(() => { if (timer) liveTick(); }, 200)));
}
"""


JS = LIVE_JS + JS

LWC = "https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js"


def fmt(x, nd=2):
    return "–" if x is None else f"{x:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def money(x, sign=False):
    if x is None:
        return "–"
    s = fmt(abs(x)) + " $"
    if sign:
        return ("+" if x >= 0 else "−") + s
    return ("−" if x < 0 else "") + s


def cls(x):
    return "" if not x else ("up" if x > 0 else "dn")


def ts_both(iso_or_dt, date=True):
    t = iso_or_dt if isinstance(iso_or_dt, dt.datetime) else dt.datetime.fromisoformat(iso_or_dt.replace("Z", "+00:00"))
    d = f'{t.astimezone(ET):%d.%m. }' if date else ""
    return f'{d}{t.astimezone(ET):%H:%M} ET · {t.astimezone(DE):%H:%M} DE'


ACCT_KEYS = ("equity", "last_equity", "cash", "buying_power", "daytrade_count")
POS_KEYS = ("symbol", "qty", "avg_entry_price", "current_price", "market_value", "unrealized_pl", "unrealized_plpc", "change_today")
ORD_KEYS = ("symbol", "side", "type", "order_class", "status", "qty", "notional", "limit_price", "stop_price", "filled_qty",
            "filled_avg_price", "submitted_at", "filled_at", "time_in_force")
CHEV = ('<svg class="chev" viewBox="0 0 8 13" aria-hidden="true"><path d="M1.5 1.5 6.5 6.5 1.5 11.5" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def slim_order(o):
    d = {k: o.get(k) for k in ORD_KEYS}
    d["legs"] = [{k: l.get(k) for k in ORD_KEYS} for l in o.get("legs") or []]
    return d


def page(now, acct, symbols, watch, args):
    E = html.escape
    p = ['<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">'
         '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
         f'<title>Alpaca Paper Dashboard</title><style>{CSS}</style></head><body>']
    clock = acct.get("clock") or {}
    a = acct.get("account") or {}
    mk = (f'<button class="pill tap{" on" if clock.get("is_open") else ""}" data-info="market">{"Markt offen" if clock.get("is_open") else "Markt zu"}</button>') if clock else ""
    p.append('<header class="nav"><div class="nav-in"><span class="nav-title">Depot</span><div class="pills">'
             '<button class="pill paper tap" data-info="paper">Papierkonto</button>' + mk +
             '<button class="pill tap" id="livestate" data-info="live">Snapshot</button></div></div></header><main class="wrap">')
    p.append(f'<div><h1 class="large">Übersicht</h1><div class="sub" id="stand">Stand {ts_both(now)}</div></div>')
    if acct.get("error"):
        p.append(f'<div class="err">Kontodaten fehlen: {E(acct["error"])}. Die Charts kommen trotzdem aus aktuellen Kursdaten.</div>')
    eq = float(a["equity"]) if a.get("equity") else None
    p.append('<section class="card hero"><button class="tap" data-info="equity" style="display:grid;gap:2px"><span class="lbl">Depotwert ⓘ</span>'
             f'<span class="eq num" id="eq">{money(eq)}</span><span class="delta" id="day"></span></button>'
             '<svg class="spark" id="spark" viewBox="0 0 600 56" preserveAspectRatio="none" aria-hidden="true"></svg>'
             '<div class="tiles" id="kvs"></div></section>')
    # chart + watchlist
    p.append('<div class="main"><section class="section" id="chartcard"><div class="card">'
             '<div class="ch-head"><div class="ch-top"><h1 id="sym"></h1><span class="px num" id="px"></span><span class="chg num" id="chg"></span>'
             '<div class="seg" role="group" aria-label="Zeiteinheit"><span class="thumb"></span>'
             '<button type="button" data-tf="M">1 Min</button><button type="button" data-tf="I">5 Min</button><button type="button" data-tf="D">1 Tag</button></div></div>'
             '<div class="ch-why"><span id="why"></span> · <span id="sess"></span></div><div class="chips" id="sigs"></div></div>'
             '<div class="stats" id="st"></div>'
             '<div id="nolib">Die Chart-Bibliothek konnte nicht geladen werden. Seite neu laden hilft meistens.</div>'
             '<div class="chartbox"><div id="chart"></div><div id="hvwrap"><div class="hvlabel">Volatilität HV20, annualisiert</div><div id="hv"></div></div></div>'
             '<div class="legend"><span><i style="background:#0a84ff"></i>MA20</span><span><i style="border-top:1px dashed #8e8e93;height:0"></i>20-Tage-Hoch</span>'
             + "".join(f'<span><i style="background:{SIG_COLORS[k]};height:7px;width:7px;border-radius:50%"></i>{v}</span>' for k, v in SETUP_LABELS.items())
             + '<span><i style="background:#30d158;height:7px;width:7px"></i>Kauf</span><span><i style="background:#ff453a;height:7px;width:7px"></i>Verkauf</span></div>'
             '</div></section>')
    wl_note = (f'{"ORB" if watch.get("mode") == "orb" else "Tages"}-Scan · {len(watch.get("hits") or [])} Treffer') if watch else "keine Watchlist"
    p.append(f'<section class="section wl"><div class="sec-h"><h2>Watchlist</h2><span class="mute">{E(wl_note)}</span></div><div class="card list">')
    for s in symbols:
        dots = "".join(f'<i style="background:{g["color"]}" title="{E(g["label"])}"></i>' for g in s["signals"])
        p.append(f'<button class="row tap" aria-selected="false"><span><span class="t">{E(s["sym"])}<span class="dots">{dots}</span></span>'
                 f'<span class="s">{E(s["why"])}</span></span><span class="p num">{fmt(s["price"])}</span>'
                 f'<span class="chg num {"up" if s["chg"] >= 0 else "dn"}">{"+" if s["chg"] >= 0 else "−"}{fmt(abs(s["chg"]))} %</span>{CHEV}</button>')
    if not symbols:
        p.append('<div class="empty">Keine Charts</div>')
    p.append('</div></section></div>')
    p.append('<div class="acct"><section class="section"><div class="sec-h"><h2>Positionen</h2><span class="mute" id="poscount"></span></div>'
             '<div class="card" id="posbox"></div></section>'
             '<section class="section"><div class="sec-h"><h2>Orders</h2><span class="mute">letzte 30</span></div><div class="card" id="ordbox"></div></section></div>')
    p.append('<p class="foot">Alles Antippbare öffnet Details: Kennzahlen, Signale, Positionen und Orders. Die Seite ist eine Momentaufnahme. '
             'Schreib in Claude „Dashboard aktualisieren“, dann baue ich sie neu, bei jedem geplanten Check passiert das automatisch. '
             'Signale sind Regeln des Scanners, keine Kaufempfehlung. Daten: Alpaca Paper API, Yahoo Finance (kann verzögert sein). '
             'Charts: <a href="https://www.tradingview.com/lightweight-charts/">TradingView Lightweight Charts</a>. Die Seite liest nur und kann keine Orders auslösen. Keine Finanzberatung.</p></main>')
    p.append('<div class="sheet" id="sheet" hidden role="dialog" aria-modal="true" aria-labelledby="sh-t"><div class="bd"></div><div class="pn">'
             '<div class="grab"></div><div class="sh-h"><h3 id="sh-t"></h3><button class="done" id="sh-x">Fertig</button></div><div class="sh-b" id="sh-b"></div></div></div>')
    hist = acct.get("history") or {}
    hv = [round(v, 2) for v in (hist.get("equity") or []) if v]
    data = json.dumps({"symbols": symbols, "account": {k: a.get(k) for k in ACCT_KEYS} if a else None,
                       "positions": [{k: x.get(k) for k in POS_KEYS} for x in acct.get("positions") or []],
                       "orders": [slim_order(o) for o in acct.get("orders") or []], "history": hv},
                      separators=(",", ":")).replace("</", "<\\/")
    p.append(f'<script id="data" type="application/json">{data}</script>'
             f'<script src="{LWC}"></script><script>{JS}</script></body></html>')
    return "".join(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=8, help="Watchlist-Treffer mit Chart (Standard 8)")
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
    clock = acct.get("clock") or {}
    now_et = now.astimezone(ET)
    today_done = not clock.get("is_open") and now_et.time() >= dt.time(16, 0) if clock else now_et.time() >= dt.time(16, 0)

    picks = {}
    def add(sym, why):
        if sym and sym.upper() not in picks:
            picks[sym.upper()] = why
    for x in acct.get("positions") or []:
        add(x["symbol"], "Position")
    open_orders = [o for o in acct.get("orders") or [] if o.get("status") in ("new", "accepted", "partially_filled", "held", "pending_new")]
    for o in open_orders:
        add(o["symbol"], "offene Order")
    plan_today = plan.get("date") == now_et.date().isoformat()
    if plan_today:
        add(plan.get("symbol"), "Plan")
    if entry.get("date") == now_et.date().isoformat():
        add(entry.get("symbol"), "Einstieg")
    for s in filter(None, args.symbols.split(",")):
        add(s.strip(), "auf Wunsch")
    for h in (watch.get("hits") or [])[:args.top]:
        add(h["symbol"], "Watchlist " + ("ORB" if watch.get("mode") == "orb" else "Tag"))

    fills_by = {}
    for f in acct.get("fills") or []:
        t = dt.datetime.fromisoformat(f["transaction_time"].replace("Z", "+00:00"))
        fills_by.setdefault(f["symbol"], []).append(
            {"date": t.astimezone(ET).date().isoformat(), "ts": t.timestamp(), "side": f["side"], "qty": f["qty"], "price": float(f["price"])})
    avg = {x["symbol"]: float(x["avg_entry_price"]) for x in acct.get("positions") or []}
    order_lines = {}
    for o in open_orders:
        if o.get("type") == "limit" and o.get("status") != "held":
            order_lines.setdefault(o["symbol"], []).append(
                {"price": float(o["limit_price"]), "title": ("Kauf-Limit " if o["side"] == "buy" else "Verkauf-Limit ") + str(o.get("qty")), "kind": "order"})

    symbols = []
    for sym, why in picks.items():
        try:
            bars, _ = fetch_daily(scan, sym)
            if len(bars) < 40:
                raise RuntimeError("zu wenige Tageskerzen")
            ind = indicators(scan, bars)
            try:
                intr = fetch_intraday(scan, sym)
            except Exception:
                intr = []
            try:
                intr1 = fetch_intraday(scan, sym, "2d", "1m")
            except Exception:
                intr1 = []
            lines = {"avg": ("Ø Einstand", avg.get(sym))}
            if plan_today and plan.get("symbol", "").upper() == sym:
                lines.update(entry=("Einstieg", plan.get("entry")), stop=("Stop", plan.get("stop")), target=("Ziel", plan.get("target")))
            symbols.append(symbol_payload(sym, why, bars, ind, intr, intr1, lines, fills_by.get(sym, []), order_lines.get(sym, []), today_done))
            ok = "ok"
        except Exception as e:
            ok = str(e)
        print(f"  {sym:6} {why:20} {ok}", file=sys.stderr)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        fh.write(page(now, acct, symbols, watch, args))
    print(json.dumps({"out": args.out, "charts": len(symbols), "chart_errors": len(picks) - len(symbols),
                      "alpaca_error": acct.get("error"), "as_of_utc": now.isoformat(timespec="seconds")}))


if __name__ == "__main__":
    main()
