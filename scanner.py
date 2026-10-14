#!/usr/bin/env python3
"""Support Scanner: checks MEXC tokens on 4H + 1D and tells you when price is at a good buy zone.
No installs needed (Python 3.8+). Run:  python scanner.py        or:  python scanner.py NEAR SOL
Analysis of past price only. Not financial advice."""
import csv, json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# ---------------- SETTINGS (edit these) ----------------
TOKENS = [t.strip().upper() for t in os.environ.get("TOKENS", "NEAR,SOL,ETH").split(",") if t.strip()]
CHECK_EVERY_MINUTES = int(os.environ.get("CHECK_EVERY_MINUTES", "15"))   # 0 = check once and stop
MIN_SCORE = int(os.environ.get("MIN_SCORE", "3"))       # phone alert only if zone score is at least this (out of 5)
MIN_RR = float(os.environ.get("MIN_RR", "1.2"))         # ...and risk/reward is at least this
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_TOPIC_STOCKS = os.environ.get("NTFY_TOPIC_STOCKS", "")   # separate phone channel for stocks (optional)
# -------------------------------------------------------

API = "https://api.mexc.com/api/v3/klines?symbol={}USDT&interval={}&limit=500"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{}?interval={}&range={}"
STATE = "alerts.json"
try: alerted = json.load(open(STATE))
except Exception: alerted = {}

def http(url, data=None, headers=None):
    h = {"User-Agent": "support-scanner"}
    h.update(headers or {})
    return urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=20).read()

def candles(tok, tf):
    if tok.startswith("STOCK:"):   # stocks via Yahoo Finance (daily + weekly)
        j = json.loads(http(YAHOO.format(tok[6:], tf, "2y" if tf == "1d" else "10y"), headers={"User-Agent": "Mozilla/5.0"}))
        q = j["chart"]["result"][0]["indicators"]["quote"][0]
        return [dict(o=o, h=h, l=l, c=c, v=v or 0) for o, h, l, c, v in zip(q["open"], q["high"], q["low"], q["close"], q["volume"])
                if None not in (o, h, l, c)]
    return [dict(o=float(r[1]), h=float(r[2]), l=float(r[3]), c=float(r[4]), v=float(r[5]))
            for r in json.loads(http(API.format(tok, tf)))]

def fmt(p):
    return f"{p:.{2 if p >= 1000 else 3 if p >= 10 else 4 if p >= 1 else 5 if p >= .01 else 8}f}"

def zones(d):
    n, K, last = len(d), 5, d[-1]["c"]
    tr = [max(r["h"] - r["l"], abs(r["h"] - d[i-1]["c"]), abs(r["l"] - d[i-1]["c"])) if i else r["h"] - r["l"]
          for i, r in enumerate(d)]
    atr = sum(tr[-14:]) / 14
    tol = max(atr * .6, last * .004)
    av = sum(r["v"] for r in d) / n or 1
    piv = []
    for i in range(K, n - K):
        w = d[i-K:i+K+1]
        if d[i]["l"] <= min(r["l"] for r in w): piv.append((d[i]["l"], i, d[i]["v"]))
        if d[i]["h"] >= max(r["h"] for r in w): piv.append((d[i]["h"], i, d[i]["v"]))
    piv.sort()
    groups = []
    for p, i, v in piv:
        if groups and p - groups[-1]["m"] <= tol:
            g = groups[-1]; g["q"].append((p, i, v)); g["m"] = sum(x[0] for x in g["q"]) / len(g["q"])
        else:
            groups.append({"q": [(p, i, v)], "m": p})
    lv = []
    for g in groups:
        q, m = g["q"], g["m"]
        lv.append(dict(p=m, lo=min(min(x[0] for x in q), m - atr * .15), hi=max(max(x[0] for x in q), m + atr * .15),
                       t=len(q), sc=len(q) * 2 + sum(x[1] / n for x in q) * 2 + sum(x[2] / av for x in q) * .5))
    strong = [x for x in lv if x["t"] >= 2]
    if len(strong) >= 3: lv = strong
    mx = max([x["sc"] for x in lv] or [1])
    for x in lv: x["s"] = x["sc"] / mx
    return lv, last, atr, tol

def sweep(d, z, atr):
    """Most recent wick below the zone in the last 12 candles -> (candles ago, reclaimed?, wick low)."""
    n, last = len(d), d[-1]["c"]
    for k in range(n - 1, max(0, n - 13), -1):
        if d[k]["l"] < z["lo"] - atr * .05:
            return n - 1 - k, last >= z["lo"] and any(c["c"] >= z["lo"] for c in d[k:k+4]), d[k]["l"]
    return None

def liq_below(d, z, atr):
    """Estimated unswept long-liquidation cluster just under the zone (5x/10x/25x leverage)."""
    av = sum(r["v"] for r in d) / len(d) or 1
    for i, r in enumerate(d[:-1]):
        if r["v"] < 1.5 * av: continue
        after = min(x["l"] for x in d[i+1:])
        for L in (5, 10, 25):
            lp = r["c"] * (1 - .95 / L)
            if after > lp and z["lo"] - 2.5 * atr < lp < z["lo"]: return True
    return False

def analyse(tok):
    tm, th = ("1d", "1wk") if tok.startswith("STOCK:") else ("4h", "1d")
    d4 = candles(tok, tm)
    lv, last, atr, tol = zones(d4)
    seg = d4[-120:]
    hh, ll = max(r["h"] for r in seg), min(r["l"] for r in seg)
    fibs = [hh - r * (hh - ll) for r in (.236, .382, .5, .618, .786)]
    sup = sorted([z for z in lv if z["lo"] < last], key=lambda z: -z["p"])[:5]
    res = sorted([z for z in lv if z["lo"] >= last], key=lambda z: z["p"])
    for z in sup: z["dist"] = max(0, (last - z["hi"]) / last * 100)
    lv1, tol1 = [], 0
    if any(z["dist"] <= 3 for z in sup):   # only fetch the higher timeframe when price is near a zone
        lv1, _, _, tol1 = zones(candles(tok, th))
    for z in sup:
        z["htf"] = any(abs(y["p"] - z["p"]) <= max(tol, tol1) for y in lv1)
        z["fib"] = any(abs(f - z["p"]) <= tol for f in fibs)
        z["pts"] = (2 if z["s"] >= .66 else 1 if z["s"] >= .4 else 0) + z["htf"] + z["fib"] + (z["dist"] <= 3)
        z["stop"] = z["lo"] - atr * .5
    target = res[0]["p"] if res else None
    out = dict(tok=tok.replace("STOCK:", ""), last=last, verdict="WAIT", zone=None, target=target, note="")
    near = [z for z in sup if z["dist"] <= 3]
    if not near:
        out["zone"] = sup[0] if sup else None
        out["note"] = "No strong support within 3% of price"
        return out
    z = max(near, key=lambda z: (z["pts"], -z["dist"]))
    out["zone"] = z
    if z["pts"] < 2:
        out["note"] = "Nearby support is weak"
        return out
    sw, risk = sweep(d4, z, atr), liq_below(d4, z, atr)
    if sw and sw[1] and sw[0] <= 3:
        out.update(verdict="BUY SIGNAL", note=f"Price dipped to {fmt(sw[2])}, then closed back above the zone")
    elif z["dist"] <= 1:
        out.update(verdict="IN ZONE - WAIT" if risk else "IN ZONE",
                   note="Liquidations likely just below: wait for a candle to close back above the zone" if risk
                   else "At support. Scale in with 2-3 smaller orders")
    else:
        out.update(verdict="WATCH", note=f"{z['dist']:.1f}% above the zone")
    return out

def show(o):
    z = o["zone"]
    print(f'{o["tok"]:<6}{fmt(o["last"]):>11}   {o["verdict"]}')
    if z:
        rr = ""
        if o["target"] and z["p"] > z["stop"]:
            rr = f'  target {fmt(o["target"])}  risk/reward {(o["target"] - z["p"]) / (z["p"] - z["stop"]):.1f}'
        print(f'        zone {fmt(z["lo"])}-{fmt(z["hi"])}  stop {fmt(z["stop"])}{rr}  score {z["pts"]}/5')
    if o["note"]: print(f'        {o["note"]}')

def notify(title, msg, topic, tag):
    if not topic: return
    try: http("https://ntfy.sh/" + topic, msg.encode(), {"Title": title, "Tags": tag})
    except Exception as e: print("        (phone alert failed:", e, ")")

SKIP = set("USDT USDC DAI USDE FDUSD TUSD USDD PYUSD USDS BUSD USD1 USDY USDG BUIDL STETH WSTETH WBTC WETH WEETH WBETH CBBTC CBETH RETH WEETH SUSDE SUSDS".split())
BIG_STOCKS = "AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO BRK-B JPM LLY V XOM UNH MA COST HD PG JNJ NFLX WMT BAC ABBV CRM ORCL KO CVX AMD MRK PEP TMO CSCO ADBE MCD".split()

def top100():
    """Top 100 coins by market cap (CoinGecko) that trade as USDT pairs on MEXC. Falls back to MEXC's busiest pairs."""
    try:
        mexc = {x["symbol"][:-4] for x in json.loads(http("https://api.mexc.com/api/v3/ticker/price")) if x["symbol"].endswith("USDT")}
        cg = json.loads(http("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=200&page=1"))
        out = [c["symbol"].upper() for c in cg if c["symbol"].upper() in mexc and c["symbol"].upper() not in SKIP]
        out = list(dict.fromkeys(out))[:100]
        if len(out) >= 30: return out
    except Exception as e:
        print("(market-cap list unavailable, using MEXC's busiest pairs instead:", e, ")")
    t = json.loads(http("https://api.mexc.com/api/v3/ticker/24hr"))
    t = [x for x in t if x["symbol"].endswith("USDT") and x["symbol"][:-4] not in SKIP and not x["symbol"][:-4].endswith(("3L", "3S", "5L", "5S"))]
    t.sort(key=lambda x: -float(x.get("quoteVolume") or 0))
    return [x["symbol"][:-4] for x in t[:100]]

def sp500():
    try:
        rows = csv.reader(http("https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv").decode().splitlines())
        next(rows)
        out = ["STOCK:" + r[0].strip().replace(".", "-") for r in rows if r]
        if len(out) > 100: return out
    except Exception as e:
        print("(S&P 500 list unavailable, using a short list of big stocks:", e, ")")
    return ["STOCK:" + x for x in BIG_STOCKS]

def expand(tokens):
    out = []
    for t in tokens:
        out += top100() if t == "TOP100" else sp500() if t == "SP500" else [t]
    return list(dict.fromkeys(out))

def us_open():
    try:
        from zoneinfo import ZoneInfo
        n = datetime.now(ZoneInfo("America/New_York"))
    except Exception: return True
    return n.weekday() < 5 and (9, 30) <= (n.hour, n.minute) < (16, 0)

def check(t):
    try: return t, analyse(t), None
    except Exception as e: return t, None, e

def run(tokens):
    tokens = expand(tokens)
    note = ""
    if not (os.environ.get("STOCKS_ANYTIME") or us_open()):
        n0 = len(tokens); tokens = [t for t in tokens if not t.startswith("STOCK:")]
        if len(tokens) < n0: note = f" (skipped {n0 - len(tokens)} stocks: US market closed)"
    print("\n" + datetime.now().strftime("%d %b %H:%M"), f"- checking {len(tokens)} symbols{note}", "-" * 20)
    with ThreadPoolExecutor(6) as ex: res = list(ex.map(check, tokens))
    waiting, errs = 0, []
    for t, o, e in res:
        if e: errs.append((t, e)); continue
        if o["verdict"] == "WAIT" and len(tokens) > 15: waiting += 1; continue
        show(o)
        z = o["zone"]
        if not (z and o["verdict"] in ("BUY SIGNAL", "IN ZONE", "IN ZONE - WAIT")): continue
        rr = (o["target"] - z["p"]) / (z["p"] - z["stop"]) if o["target"] and z["p"] > z["stop"] else None
        if z["pts"] < MIN_SCORE or (rr is not None and rr < MIN_RR):
            print(f"        (no phone alert: below your filters, score {MIN_SCORE}/5 and risk/reward {MIN_RR})"); continue
        key = f'{t}|{round(z["p"], 4)}|{o["verdict"]}'
        if time.time() - alerted.get(key, 0) > 6 * 3600:
            alerted[key] = time.time()
            try: json.dump(alerted, open(STATE, "w"))
            except Exception: pass
            stock = t.startswith("STOCK:")
            notify(f'{o["tok"]}: {o["verdict"]}', f'Price {fmt(o["last"])}. Zone {fmt(z["lo"])}-{fmt(z["hi"])}, stop {fmt(z["stop"])}. {o["note"]}',
                   (NTFY_TOPIC_STOCKS or NTFY_TOPIC) if stock else NTFY_TOPIC, "chart_with_upwards_trend" if stock else "coin")
    if waiting: print(f"\n{waiting} others: nothing near support")
    if errs: print(f"could not check {len(errs)}: " + ", ".join(f"{t} ({str(e)[:40]})" for t, e in errs[:3]) + (" ..." if len(errs) > 3 else ""))

if __name__ == "__main__":
    toks = [a.upper() for a in sys.argv[1:]] or TOKENS
    while True:
        run(toks)
        if not CHECK_EVERY_MINUTES: break
        time.sleep(CHECK_EVERY_MINUTES * 60)
