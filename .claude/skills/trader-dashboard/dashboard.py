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


SIG_COLORS = {"breakout_20d": "#2962ff", "bull_flag": "#00bcd4", "reclaim_ma20": "#ff9800",
              "oversold": "#f23645", "oversold_bounce": "#ab47bc"}
SIG_SHORT = {"breakout_20d": "Ausbruch", "bull_flag": "Flagge", "reclaim_ma20": "MA20",
             "oversold": "RSI<30", "oversold_bounce": "Rebound"}


def symbol_payload(sym, why, bars, ind, intraday, intraday1, lines, fills, orders, today_done):
    k0 = max(0, len(bars) - 160)
    B = bars[k0:]
    today = dt.datetime.now(ET).date().isoformat()
    daily = {
        "candles": [{"time": b["d"], "open": r2(b["o"]), "high": r2(b["h"]), "low": r2(b["l"]), "close": r2(b["c"])} for b in B],
        "volume": [{"time": b["d"], "value": b["v"], "color": "rgba(8,153,129,.35)" if b["c"] >= b["o"] else "rgba(242,54,69,.35)"} for b in B],
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
            "volume": [{"time": et_chart_time(b["t"]), "value": b["v"], "color": "rgba(8,153,129,.35)" if b["c"] >= b["o"] else "rgba(242,54,69,.35)"} for b in intraday],
            "or_high": r2(max(b["h"] for b in orb)) if orb else None,
            "or_low": r2(min(b["l"] for b in orb)) if orb else None,
            "session": last_day, "bar_s": bar_s,
            "markers": [],
        }
    intr = build(intraday, 300)
    m1 = build(intraday1, 60)
    for f in fills:
        txt = ("K " if f["side"] == "buy" else "V ") + str(f["qty"])
        m = {"position": "belowBar" if f["side"] == "buy" else "aboveBar", "color": "#089981" if f["side"] == "buy" else "#f23645",
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
:root{--bg:#131722;--panel:#1e222d;--panel2:#171b26;--line:#2a2e39;--ink:#d1d4dc;--mute:#787b86;--accent:#2962ff;
--up:#089981;--dn:#f23645;--warn:#ff9800;--vol:#ab47bc;
--f-body:-apple-system,BlinkMacSystemFont,"Trebuchet MS",Roboto,Ubuntu,sans-serif;--f-mono:"SF Mono",Menlo,Consolas,ui-monospace,monospace;color-scheme:dark}
/* layout: one dark terminal in the TradingView manner: account strip, chart + watchlist side by side, account tables below */
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.4 var(--f-body)}
.app{max-width:1400px;margin:0 auto;padding:12px 16px 32px;display:grid;gap:8px}
.num{font-variant-numeric:tabular-nums;font-family:var(--f-mono)}
.up{color:var(--up)}.dn{color:var(--dn)}.mute{color:var(--mute)}
.bar{display:flex;flex-wrap:wrap;align-items:center;gap:6px 22px;background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:8px 14px}
.bar .brand{font-weight:600;font-size:14px;display:flex;gap:8px;align-items:center}
.kv{display:grid;gap:0}.kv span{color:var(--mute);font-size:11px}.kv b{font:500 14px var(--f-mono);font-variant-numeric:tabular-nums}
.bar .right{margin-left:auto;display:flex;gap:8px;align-items:center;color:var(--mute);font-size:12px}
.tag{display:inline-flex;align-items:center;gap:5px;padding:2px 8px;border-radius:3px;font-size:11px;font-weight:600;background:var(--panel2);border:1px solid var(--line);color:var(--mute)}
.tag.live::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--up)}
.tag.paper{color:#fff;background:var(--accent);border-color:var(--accent)}
.main{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:8px}
@media (max-width:900px){.main{grid-template-columns:1fr}}
.pane{background:var(--panel);border:1px solid var(--line);border-radius:4px;min-width:0}
.head{display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;padding:8px 12px;border-bottom:1px solid var(--line)}
.head h1{margin:0;font-size:16px;font-weight:600}.head .px{font:600 16px var(--f-mono)}
.tf{display:flex;gap:2px;margin-left:auto}
.tf button{background:transparent;border:0;color:var(--mute);font:600 12px var(--f-body);padding:4px 8px;border-radius:3px;cursor:pointer}
.tf button:hover{background:var(--line);color:var(--ink)}.tf button[aria-pressed="true"]{color:var(--accent);background:rgba(41,98,255,.12)}
button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.stats{display:flex;flex-wrap:wrap;gap:4px 16px;padding:6px 12px;color:var(--mute);font-size:12px;border-bottom:1px solid var(--line)}
.stats b{color:var(--ink);font-weight:500;font-family:var(--f-mono)}
.legend{display:flex;flex-wrap:wrap;gap:4px 12px;padding:6px 12px 0;font-size:11px;color:var(--mute)}
.legend i{display:inline-block;width:10px;height:2px;margin-right:4px;vertical-align:middle}
.chips{display:flex;gap:4px;flex-wrap:wrap}
.chip{font-size:11px;padding:1px 6px;border-radius:3px;border:1px solid currentColor}
#chart{height:430px}#hv{height:110px;border-top:1px solid var(--line)}
.hvlabel{padding:4px 12px 0;font-size:11px;color:var(--mute)}
.wl table{width:100%;border-collapse:collapse}
.wl th{font-size:11px;color:var(--mute);font-weight:500;text-align:left;padding:6px 10px;border-bottom:1px solid var(--line)}
.wl td{padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
.wl tr.row{cursor:pointer}.wl tr.row:hover{background:var(--panel2)}.wl tr.row[aria-selected="true"]{background:rgba(41,98,255,.14)}
.wl .sym{font-weight:600}.wl .why{display:block;font-size:11px;color:var(--mute)}
.dots{display:inline-flex;gap:3px;margin-left:4px}.dots i{width:6px;height:6px;border-radius:50%;display:inline-block}
.r{text-align:right}
.acct{display:grid;grid-template-columns:1fr 1fr;gap:8px}@media (max-width:900px){.acct{grid-template-columns:1fr}}
.acct h2{margin:0;font-size:13px;font-weight:600;padding:8px 12px;border-bottom:1px solid var(--line)}
.tbl{overflow-x:auto}.tbl table{border-collapse:collapse;width:100%}
.tbl th{font-size:11px;color:var(--mute);font-weight:500;text-align:left;padding:6px 12px;border-bottom:1px solid var(--line);white-space:nowrap}
.tbl td{padding:6px 12px;border-bottom:1px solid var(--line);white-space:nowrap}.tbl tr:last-child td{border-bottom:0}
.empty{color:var(--mute);padding:12px}
.err{border:1px solid var(--dn);color:var(--ink);background:rgba(242,54,69,.08);padding:8px 12px;border-radius:4px}
.foot{color:var(--mute);font-size:11px;max-width:90ch}
.foot a{color:var(--mute)}
#nolib{display:none;padding:16px;color:var(--mute)}
"""

JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const C = {bg:'#1e222d', grid:'#2a2e39', text:'#787b86', up:'#089981', dn:'#f23645', accent:'#2962ff', vol:'#ab47bc'};
const LINE = {entry:C.accent, stop:C.dn, target:C.up, avg:'#d1d4dc', order:C.warn || '#ff9800', or_high:'#787b86', or_low:'#787b86'};
const fmt = (x, d=2) => x == null ? '–' : x.toLocaleString('de-DE', {minimumFractionDigits:d, maximumFractionDigits:d});
let cur = 0, tf = 'D', chart, hvChart;

function base(el, h){
  return LightweightCharts.createChart(el, {height:h, layout:{background:{color:C.bg}, textColor:C.text, fontSize:11},
    grid:{vertLines:{color:C.grid}, horzLines:{color:C.grid}}, rightPriceScale:{borderColor:C.grid},
    timeScale:{borderColor:C.grid, timeVisible:true, secondsVisible:false, rightOffset:4},
    crosshair:{mode:0}, localization:{locale:'de-DE', priceFormatter:p => fmt(p)}});
}

function render(){
  const s = D.symbols[cur];
  const el = document.getElementById('chart'), hv = document.getElementById('hv');
  if (chart) chart.remove(); if (hvChart) { hvChart.remove(); hvChart = null; }
  el.innerHTML = ''; hv.innerHTML = '';
  const iv = tf === 'M' ? s.m1 : tf === 'I' ? s.intraday : null;
  const intra = !!iv;
  const src = iv || s.daily;
  chart = base(el, el.clientHeight);
  const cs = chart.addCandlestickSeries({upColor:C.up, downColor:C.dn, borderVisible:false, wickUpColor:C.up, wickDownColor:C.dn});
  cs.setData(src.candles);
  const vs = chart.addHistogramSeries({priceScaleId:'vol', priceFormat:{type:'volume'}, lastValueVisible:false, priceLineVisible:false});
  chart.priceScale('vol').applyOptions({scaleMargins:{top:0.85, bottom:0}});
  vs.setData(src.volume);
  if (!intra) {
    chart.addLineSeries({color:C.accent, lineWidth:1.5, lastValueVisible:false, priceLineVisible:false, crosshairMarkerVisible:false}).setData(s.daily.ma20);
    chart.addLineSeries({color:'#787b86', lineWidth:1, lineStyle:2, lineType:1, lastValueVisible:false, priceLineVisible:false, crosshairMarkerVisible:false}).setData(s.daily.hi20);
  } else {
    if (iv.or_high) cs.createPriceLine({price:iv.or_high, color:LINE.or_high, lineWidth:1, lineStyle:1, axisLabelVisible:true, title:'OR-Hoch'});
    if (iv.or_low) cs.createPriceLine({price:iv.or_low, color:LINE.or_low, lineWidth:1, lineStyle:1, axisLabelVisible:true, title:'OR-Tief'});
  }
  for (const l of s.lines) cs.createPriceLine({price:l.price, color:LINE[l.kind] || C.text, lineWidth:1, lineStyle:2, axisLabelVisible:true, title:l.title});
  cs.setMarkers(src.markers);
  if (intra) {
    const n = src.candles.length; chart.timeScale().setVisibleLogicalRange({from:Math.max(0, n - (tf === 'M' ? 200 : 160)), to:n + 4});
  } else {
    const n = src.candles.length; chart.timeScale().setVisibleLogicalRange({from:Math.max(0, n - 110), to:n + 4});
    hvChart = base(hv, hv.clientHeight);
    hvChart.applyOptions({layout:{attributionLogo:false}, timeScale:{visible:false}, handleScroll:false, handleScale:false});
    const h = hvChart.addAreaSeries({lineColor:C.vol, topColor:'rgba(171,71,188,.28)', bottomColor:'rgba(171,71,188,.02)', lineWidth:1.5,
      priceFormat:{type:'custom', formatter:v => fmt(v, 0) + ' %'}});
    h.setData(s.daily.hv20);
    const sync = r => { if (r && hvChart) hvChart.timeScale().setVisibleLogicalRange(r); };
    chart.timeScale().subscribeVisibleLogicalRangeChange(sync);
    sync(chart.timeScale().getVisibleLogicalRange());
  }
  document.getElementById('hvwrap').hidden = !!intra;
  // header
  document.getElementById('sym').textContent = s.sym;
  document.getElementById('px').textContent = fmt(s.price) + ' $';
  const ch = document.getElementById('chg'); ch.textContent = (s.chg >= 0 ? '+' : '') + fmt(s.chg) + ' %'; ch.className = 'num ' + (s.chg >= 0 ? 'up' : 'dn');
  document.getElementById('why').textContent = s.why;
  document.getElementById('sigs').innerHTML = s.signals.length ? s.signals.map(g => `<span class="chip" style="color:${g.color}">${g.label}</span>`).join('') : '<span class="mute">kein Signal am letzten Schlusskurs</span>';
  document.getElementById('st').innerHTML = `<span>RSI 14 <b>${fmt(s.rsi,1)}</b></span><span>ATR 14 <b>${fmt(s.atr)} $ (${fmt(s.atr_pct,1)} %)</b></span><span>HV20 <b>${fmt(s.hv,1)} %</b></span><span>MA20 <b>${fmt(s.ma20)}</b></span>` + (intra ? `<span>Sitzung <b>${iv.session}</b>, Zeiten in ET</span>` : '');
  document.querySelectorAll('.wl tr.row').forEach((r, i) => r.setAttribute('aria-selected', i === cur));
  document.querySelectorAll('.tf button').forEach(b => b.setAttribute('aria-pressed', b.dataset.tf === tf));
  document.querySelector('.tf button[data-tf="I"]').disabled = !s.intraday;
  document.querySelector('.tf button[data-tf="M"]').disabled = !s.m1;
}

if (!window.LightweightCharts) { document.getElementById('nolib').style.display = 'block'; }
else {
  document.querySelectorAll('.wl tr.row').forEach((r, i) => {
    r.addEventListener('click', () => { cur = i; render(); });
    r.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); cur = i; render(); } });
  });
  document.querySelectorAll('.tf button').forEach(b => b.addEventListener('click', () => { tf = b.dataset.tf; render(); }));
  let t; window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(render, 150); });
  if (D.symbols.length) render();
}
"""

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


STATUS_DE = {"filled": "ausgeführt", "new": "offen", "accepted": "offen", "pending_new": "offen", "held": "wartet (Bracket)",
             "partially_filled": "teilweise", "canceled": "storniert", "expired": "verfallen", "rejected": "abgelehnt",
             "replaced": "ersetzt", "done_for_day": "Tagesende"}


def page(now, acct, symbols, watch, args):
    E = html.escape
    p = ['<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">'
         '<meta name="viewport" content="width=device-width,initial-scale=1">'
         f'<title>Alpaca Paper Dashboard</title><style>{CSS}</style></head><body><div class="app">']
    clock = acct.get("clock") or {}
    a = acct.get("account")
    items = []
    if a:
        eq, last = float(a["equity"]), float(a.get("last_equity") or a["equity"])
        day = eq - last
        pos = acct.get("positions") or []
        upl = sum(float(x["unrealized_pl"]) for x in pos)
        items = [("Depotwert", money(eq), ""), ("Heute", f'{money(day, True)} ({fmt(day / last * 100 if last else 0)} %)', cls(day)),
                 ("Unrealisiert", money(upl, True), cls(upl)), ("Bargeld", money(float(a["cash"])), ""),
                 ("Kaufkraft", money(float(a["buying_power"])), ""), ("Day-Trades 5T", str(a.get("daytrade_count", 0)), "")]
    mk = ('<span class="tag live">Markt offen</span>' if clock.get("is_open") else '<span class="tag">Markt geschlossen</span>') if clock else ""
    p.append('<div class="bar"><div class="brand">Alpaca <span class="tag paper">PAPIER</span></div>'
             + "".join(f'<div class="kv"><span>{k}</span><b class="{c}">{v}</b></div>' for k, v, c in items)
             + f'<div class="right">{mk}<span>Stand {ts_both(now)}</span></div></div>')
    if acct.get("error"):
        p.append(f'<div class="err">Kontodaten fehlen: {E(acct["error"])}. Die Charts kommen trotzdem aus aktuellen Kursdaten.</div>')
    # main: chart + watchlist
    p.append('<div class="main"><div class="pane">'
             '<div class="head"><h1 id="sym"></h1><span class="px num" id="px"></span><span id="chg"></span>'
             '<span class="mute" id="why"></span><div class="chips" id="sigs"></div>'
             '<div class="tf" role="group" aria-label="Zeiteinheit"><button type="button" data-tf="M">1m</button><button type="button" data-tf="I">5m</button><button type="button" data-tf="D">1T</button></div></div>'
             '<div class="stats" id="st"></div>'
             '<div class="legend"><span><i style="background:#2962ff"></i>MA20</span><span><i style="border-top:1px dashed #787b86;height:0"></i>20-Tage-Hoch</span>'
             + "".join(f'<span><i style="background:{SIG_COLORS[k]};height:6px;width:6px;border-radius:50%"></i>{v}</span>' for k, v in SETUP_LABELS.items())
             + '<span><i style="background:#089981;height:6px;width:6px"></i>Kauf</span><span><i style="background:#f23645;height:6px;width:6px"></i>Verkauf</span></div>'
             '<div id="nolib">Die Chart-Bibliothek konnte nicht geladen werden. Seite neu laden hilft meistens.</div>'
             '<div id="chart"></div><div id="hvwrap"><div class="hvlabel">Volatilität HV20, annualisiert</div><div id="hv"></div></div></div>')
    wl_note = (f'{E(str(watch.get("mode")))}-Scan {E(str(watch.get("as_of") or ""))} · {len(watch.get("hits") or [])} Treffer') if watch else "keine Watchlist"
    p.append(f'<div class="pane wl"><div class="head"><b>Watchlist</b><span class="mute" style="font-size:11px">{wl_note}</span></div>'
             '<table><thead><tr><th>Symbol</th><th class="r">Kurs</th><th class="r">%</th></tr></thead><tbody>')
    for s in symbols:
        dots = "".join(f'<i style="background:{g["color"]}" title="{E(g["label"])}"></i>' for g in s["signals"])
        p.append(f'<tr class="row" tabindex="0" role="button" aria-selected="false"><td><span class="sym">{E(s["sym"])}</span><span class="dots">{dots}</span>'
                 f'<span class="why">{E(s["why"])}</span></td><td class="r num">{fmt(s["price"])}</td>'
                 f'<td class="r num {cls(s["chg"])}">{"+" if s["chg"] >= 0 else ""}{fmt(s["chg"])}</td></tr>')
    p.append('</tbody></table></div></div>')
    # account tables
    p.append('<div class="acct"><div class="pane"><h2>Positionen</h2>')
    pos = acct.get("positions") or []
    if pos:
        p.append('<div class="tbl"><table><tr><th>Symbol</th><th class="r">Stück</th><th class="r">Ø Einstand</th><th class="r">Kurs</th>'
                 '<th class="r">Wert</th><th class="r">G/V</th><th class="r">G/V %</th></tr>')
        for x in pos:
            pl, plp = float(x["unrealized_pl"]), float(x["unrealized_plpc"]) * 100
            p.append(f'<tr><td><b>{E(x["symbol"])}</b></td><td class="r num">{E(x["qty"])}</td><td class="r num">{fmt(float(x["avg_entry_price"]))}</td>'
                     f'<td class="r num">{fmt(float(x["current_price"]))}</td><td class="r num">{money(float(x["market_value"]))}</td>'
                     f'<td class="r num {cls(pl)}">{money(pl, True)}</td><td class="r num {cls(plp)}">{fmt(plp)} %</td></tr>')
        p.append('</table></div>')
    else:
        p.append('<div class="empty">Keine offenen Positionen.</div>')
    p.append('</div><div class="pane"><h2>Orders</h2>')
    orders = acct.get("orders") or []
    if orders:
        p.append('<div class="tbl"><table><tr><th>Zeit</th><th>Symbol</th><th>Seite</th><th>Typ</th><th class="r">Stück</th>'
                 '<th class="r">Limit / Stop</th><th class="r">Ausgeführt</th><th>Status</th></tr>')
        rows = []
        for o in orders:
            rows.append(o)
            rows.extend(dict(l, _leg=True) for l in o.get("legs") or [])
        for o in rows:
            lim = o.get("limit_price") or o.get("stop_price")
            fp = o.get("filled_avg_price")
            st = o.get("status", "")
            stc = "up" if st == "filled" else "dn" if st in ("canceled", "rejected", "expired") else ""
            typ = {"limit": "Limit", "market": "Market", "stop": "Stop", "stop_limit": "Stop-Limit"}.get(o.get("type"), o.get("type") or "")
            if o.get("_leg"):
                typ = "↳ " + ("Ziel" if o.get("type") == "limit" else "Stop")
            elif o.get("order_class") == "bracket":
                typ += " · Bracket"
            p.append(f'<tr><td class="num mute">{ts_both(o["submitted_at"]) if o.get("submitted_at") and not o.get("_leg") else ""}</td><td><b>{E(o["symbol"])}</b></td>'
                     f'<td class="{"up" if o["side"] == "buy" else "dn"}">{"Kauf" if o["side"] == "buy" else "Verkauf"}</td><td>{E(typ)}</td>'
                     f'<td class="r num">{E(str(o.get("qty") or o.get("notional") or ""))}</td><td class="r num">{fmt(float(lim)) if lim else "–"}</td>'
                     f'<td class="r num">{(E(o.get("filled_qty") or "0") + " @ " + fmt(float(fp))) if fp else "–"}</td><td class="{stc}">{E(STATUS_DE.get(st, st))}</td></tr>')
        p.append('</table></div>')
    else:
        p.append('<div class="empty">Noch keine Orders.</div>')
    p.append('</div></div>')
    p.append('<p class="foot">Momentaufnahme, kein Live-Feed. Zum Auffrischen in Claude „Dashboard aktualisieren“ schreiben. '
             'Signale sind die Regeln von /trader-scanner, für jeden Tag nachgerechnet: eine Regel, die zutrifft, keine Kaufempfehlung. '
             'Daten: Alpaca Paper API, Yahoo Finance (kann verzögert sein). Charts: <a href="https://www.tradingview.com/lightweight-charts/">TradingView Lightweight Charts</a>. '
             'Diese Seite liest nur und kann keine Orders auslösen. Keine Finanzberatung.</p>')
    data = json.dumps({"symbols": symbols}, separators=(",", ":")).replace("</", "<\\/")
    p.append(f'</div><script id="data" type="application/json">{data}</script>'
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
