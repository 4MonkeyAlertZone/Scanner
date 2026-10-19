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
PIVOT = 5          # a swing point must be the highest/lowest of this many candles on each side
NEAR_PCT = 3       # "near a zone" = price within this % above it
COOLDOWN_H = 6     # don't repeat the same alert within this many hours
HOLDINGS = os.environ.get("HOLDINGS", "")   # your open positions for SELL alerts, e.g. "NEAR@4.80/4.55/5.20,SOL@100/95,stock:AAPL@180/170"
# ntfy can't colour text, so each alert type gets a coloured circle emoji (ntfy "tags") and a priority (1-5)
COLORS = {"BUY SIGNAL": ("green_circle", 4), "IN ZONE": ("yellow_circle", 3), "IN ZONE - WAIT": ("orange_circle", 3),
          "STOP HIT": ("red_circle", 5), "TAKE PROFIT": ("blue_circle", 4), "REJECTED": ("blue_circle", 4),
          "SHORT SIGNAL": ("purple_circle", 4), "AT TOP - WAIT": ("brown_circle", 3)}
MUTED_PHONE = {"IN ZONE - WAIT"}   # verdicts that are still checked, logged and recorded, but send no phone alert (remove a name to get its alerts back)
SHORT_TOKENS = [t.strip().upper() for t in os.environ.get("SHORT_TOKENS", "BTC,ETH").split(",") if t.strip()]   # coins to watch for a local top
SHORTS = []        # filled by check_shorts(); tracker.py reads it for the paper-trading ledger
# -------------------------------------------------------

# tuner.py may change MIN_SCORE / MIN_RR here after its weekly self-review (config.json beats the values above)
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")) as _f: _c = json.load(_f)
    MIN_SCORE, MIN_RR = int(_c.get("MIN_SCORE", MIN_SCORE)), float(_c.get("MIN_RR", MIN_RR))
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))   # state files live next to this script
STATE = os.path.join(HERE, "alerts.json")
LISTS = os.path.join(HERE, "lists.json")

def load(path):
    try:
        with open(path) as f: return json.load(f)
    except Exception: return {}

def save(path, obj):
    try:
        with open(path, "w") as f: json.dump(obj, f)
    except Exception: pass

API = "https://api.mexc.com/api/v3/klines?symbol={}USDT&interval={}&limit=500"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{}?interval={}&range={}"
alerted = load(STATE)

def http(url, data=None, headers=None, tries=3):
    h = {"User-Agent": "support-scanner"}
    h.update(headers or {})
    for i in range(tries):
        try: return urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=20).read()
        except Exception:
            if i == tries - 1 or data is not None: raise   # only retry reads, never re-send an alert
            time.sleep(1.5 * (i + 1))

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
    n, K, last = len(d), PIVOT, d[-1]["c"]
    tr = [max(r["h"] - r["l"], abs(r["h"] - d[i-1]["c"]), abs(r["l"] - d[i-1]["c"])) if i else r["h"] - r["l"]
          for i, r in enumerate(d)]
    atr = sum(tr[-14:]) / 14
    tol = max(atr * .6, last * .004)
    av = sum(r["v"] for r in d) / n or 1
    piv = []
    for i in range(K, n - K):
        w = d[i-K:i+K+1]
        wl, wh = [r["l"] for r in w], [r["h"] for r in w]
        if d[i]["l"] == min(wl) and wl.index(d[i]["l"]) == K: piv.append((d[i]["l"], i, d[i]["v"]))   # first of equal lows only
        if d[i]["h"] == max(wh) and wh.index(d[i]["h"]) == K: piv.append((d[i]["h"], i, d[i]["v"]))
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
        if r["v"] < 1.5 * av or r["c"] <= r["o"]: continue   # heavy buying candles only
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
    if ll > 0 and hh / ll < 1.04:   # moved less than 4% in the last ~20 days: a pegged stablecoin (USDF, USDGO...), not a tradable setup
        return dict(tok=tok.replace("STOCK:", ""), last=last, verdict="WAIT", zone=None, target=None, note="Price barely moves (stablecoin?)")
    fibs = [hh - r * (hh - ll) for r in (.236, .382, .5, .618, .786)]
    sup = sorted([z for z in lv if z["lo"] < last], key=lambda z: -z["p"])[:5]
    res = sorted([z for z in lv if z["lo"] >= last], key=lambda z: z["p"])
    for z in sup: z["dist"] = max(0, (last - z["hi"]) / last * 100)
    lv1 = []
    if any(z["dist"] <= NEAR_PCT for z in sup):   # only fetch the higher timeframe when price is near a zone
        lv1 = zones(candles(tok, th))[0]
    for z in sup:
        z["htf"] = any(abs(y["p"] - z["p"]) <= tol for y in lv1)
        z["fib"] = any(abs(f - z["p"]) <= tol for f in fibs)
        z["base"] = (2 if z["s"] >= .66 else 1 if z["s"] >= .4 else 0) + z["htf"] + z["fib"]   # quality, max 4
        z["pts"] = z["base"] + (z["dist"] <= NEAR_PCT)                                          # + closeness, max 5
        z["stop"] = z["lo"] - atr * .5
        z["entry"] = min(last, z["hi"])   # realistic entry: current price, or the top of the zone if price is above it
    target = res[0]["p"] if res else None
    out = dict(tok=tok.replace("STOCK:", ""), last=last, verdict="WAIT", zone=None, target=target, note="")
    near = [z for z in sup if z["dist"] <= NEAR_PCT]
    if not near:
        out["zone"] = sup[0] if sup else None
        out["note"] = f"No strong support within {NEAR_PCT}% of price"
        return out
    z = max(near, key=lambda z: (z["pts"], -z["dist"]))
    out["zone"] = z
    if z["base"] < 2:
        out["note"] = "Nearby support is weak"
        return out
    dc = d4[:-1]   # closed candles only: the last row is still forming
    sw, risk = sweep(dc, z, atr), liq_below(dc, z, atr)
    if sw and sw[1] and sw[0] <= 3:
        out.update(verdict="BUY SIGNAL", note=f"Price dipped to {fmt(sw[2])}, then closed back above the zone")
    elif z["dist"] <= 1:
        out.update(verdict="IN ZONE - WAIT" if risk else "IN ZONE",
                   note="Possible liquidation cluster (estimate) just below: wait for a candle to close back above the zone" if risk
                   else "At support. Scale in with 2-3 smaller orders")
    else:
        out.update(verdict="WATCH", note=f"{z['dist']:.1f}% above the zone")
    return out

def rr_of(o):
    z = o["zone"]
    if not z or not o["target"] or z["entry"] <= z["stop"]: return None
    return (o["target"] - z["entry"]) / (z["entry"] - z["stop"])

def show(o):
    z = o["zone"]
    print(f'{o["tok"]:<6}{fmt(o["last"]):>11}   {o["verdict"]}')
    if z:
        r = rr_of(o)
        rr = f'  target {fmt(o["target"])}  risk/reward {r:.1f}' if r is not None else ""
        print(f'        zone {fmt(z["lo"])}-{fmt(z["hi"])}  entry ~{fmt(z["entry"])}  stop {fmt(z["stop"])}{rr}  score {z["pts"]}/5')
    if o["note"]: print(f'        {o["note"]}')

def notify(title, msg, topic, tag, prio=3):
    if not topic: return
    try: http("https://ntfy.sh/" + topic, msg.encode(), {"Title": title, "Tags": tag, "Priority": str(prio)})
    except Exception as e: print("        (phone alert failed:", e, ")")

SKIP = set("USDT USDC DAI USDE FDUSD TUSD USDD PYUSD USDS BUSD USD1 USDY USDG BUIDL STETH WSTETH WBTC WETH WEETH WBETH CBBTC CBETH RETH WEETH SUSDE SUSDS".split())
BIG_STOCKS = "AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO BRK-B JPM LLY V XOM UNH MA COST HD PG JNJ NFLX WMT BAC ABBV CRM ORCL KO CVX AMD MRK PEP TMO CSCO ADBE MCD".split()

UA = {"User-Agent": "Mozilla/5.0"}

def cached(name, fn):
    """Reuse a coin/stock list for a day (10 minutes if it came from a backup source) so we don't hammer free APIs."""
    c = load(LISTS)
    e = c.get(name)
    if e and time.time() - e["t"] < e["ttl"]: return e["v"], e["src"]
    v, good, src = fn()
    c[name] = {"t": time.time(), "ttl": 86400 if good else 600, "v": v, "src": src}
    save(LISTS, c)
    return v, src

def _top100():
    """Top 100 coins by market cap that trade as USDT pairs on MEXC. Backup: MEXC's busiest pairs."""
    price = json.loads(http("https://api.mexc.com/api/v3/ticker/price"))
    mexc = {x["symbol"][:-4] for x in price if x["symbol"].endswith("USDT") and x["symbol"].isascii()}
    for src, url in (("CoinGecko", "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=200&page=1"),
                     ("CoinPaprika", "https://api.coinpaprika.com/v1/tickers?limit=200")):
        try:
            syms = [c["symbol"].upper() for c in json.loads(http(url, headers=UA))]
            out = list(dict.fromkeys(x for x in syms if x in mexc and x not in SKIP))[:100]
            if len(out) >= 30: return out, True, src
        except Exception: pass
    t = json.loads(http("https://api.mexc.com/api/v3/ticker/24hr"))
    t = [x for x in t if x["symbol"].endswith("USDT") and x["symbol"].isascii() and x["symbol"][:-4] not in SKIP
         and not x["symbol"][:-4].endswith(("3L", "3S", "5L", "5S"))]
    t.sort(key=lambda x: -float(x.get("quoteVolume") or 0))
    return [x["symbol"][:-4] for x in t[:100]], False, "MEXC busiest pairs (market-cap lists unavailable)"

def top100():
    v, src = cached("top100", _top100)
    print(f"(crypto list: {src})")
    return v

def _sp500():
    try:
        rows = csv.reader(http("https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv").decode().splitlines())
        next(rows)
        out = ["STOCK:" + r[0].strip().replace(".", "-") for r in rows if r]
        if len(out) > 100: return out, True, "S&P 500 list"
    except Exception: pass
    return ["STOCK:" + x for x in BIG_STOCKS], False, "short list of big stocks (S&P 500 list unavailable)"

def sp500():
    v, src = cached("sp500", _sp500)
    print(f"(stock list: {src})")
    return v

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

def fresh(key, p):
    """False if we already alerted this token + verdict recently for roughly the same zone."""
    e = alerted.get(key)
    return not (isinstance(e, dict) and time.time() - e["t"] < COOLDOWN_H * 3600 and abs(p / e["p"] - 1) < .02)

def check(t):
    try: return t, analyse(t), None
    except Exception as e: return t, None, e

def exit_check(tok, entry, stop, target):
    """Sell-side check for a position you hold. Returns (name, verdict, level, message) or None for HOLD."""
    d = candles(tok, "1d" if tok.startswith("STOCK:") else "4h")
    dc = d[:-1]                                  # closed candles only
    lv, last, atr, tol = zones(d)
    res = sorted([z for z in lv if z["lo"] >= last], key=lambda z: z["p"])
    name = tok.replace("STOCK:", "")
    pl = f" ({(last / entry - 1) * 100:+.1f}% vs your entry {fmt(entry)})" if entry else ""
    if stop is not None and last <= stop:
        return name, "STOP HIT", stop, f"Price {fmt(last)} is at or below your stop {fmt(stop)}{pl}. Consider exiting."
    if target is not None and last >= target:
        return name, "TAKE PROFIT", target, f"Price {fmt(last)} reached your target {fmt(target)}{pl}. Consider taking profit."
    r = res[0] if res else None
    if r and target is None:
        if any(c["h"] > r["hi"] for c in dc[-3:]) and last < r["lo"]:
            return name, "REJECTED", r["p"], f"Price pushed above resistance {fmt(r['lo'])}-{fmt(r['hi'])} then fell back{pl}. Possible top: consider taking profit."
        if last >= r["lo"] * 0.99:
            return name, "TAKE PROFIT", r["p"], f"Price {fmt(last)} is at resistance {fmt(r['lo'])}-{fmt(r['hi'])}{pl}. Consider taking profit."
    return None

def parse_holdings():
    out = []
    for h in HOLDINGS.split(","):
        if not h.strip(): continue
        name, _, rest = h.strip().partition("@")
        try: nums = [float(x) if x.strip() else None for x in rest.split("/")] if rest else []
        except ValueError: print("(could not read holding:", h, ")"); continue
        out.append((name.strip().upper(), *(nums + [None] * 3)[:3]))
    return out

def rsi14(d):
    c = [r["c"] for r in d]
    if len(c) < 30: return 50.0
    g = l = 0.0
    for i in range(1, 15):
        x = c[i] - c[i-1]; g += max(x, 0); l += max(-x, 0)
    g, l = g / 14, l / 14
    for i in range(15, len(c)):
        x = c[i] - c[i-1]; g = (g * 13 + max(x, 0)) / 14; l = (l * 13 + max(-x, 0)) / 14
    return 100 - 100 / (1 + g / l) if l else 100.0

def short_check(tok):
    """Mirror image of the buy logic: a strong resistance zone just above price, ideally after a failed breakout above it."""
    tm, th = ("1d", "1wk") if tok.startswith("STOCK:") else ("4h", "1d")     # stocks: daily + weekly, crypto: 4H + daily
    d = candles(tok, tm); dc = d[:-1]          # closed candles only for the rejection test
    lv, last, atr, tol = zones(d)
    ups = sorted([z for z in lv if z["hi"] >= last], key=lambda z: z["p"])
    downs = sorted([z for z in lv if z["hi"] < last], key=lambda z: -z["p"])
    out = dict(tok=tok.replace("STOCK:", ""), key=tok, verdict="WAIT", last=last, pts=0, rr=None, note="")
    if not ups: out["note"] = "No resistance above price"; return out
    r = ups[0]
    dist = max(0, (r["lo"] - last) / last * 100)
    if dist > NEAR_PCT: out["note"] = f"No major resistance within {NEAR_PCT}% above price"; return out
    seg = d[-120:]; hh, ll = max(x["h"] for x in seg), min(x["l"] for x in seg)
    fibs = [hh - f * (hh - ll) for f in (.236, .382, .5, .618, .786)]
    htf = any(abs(y["p"] - r["p"]) <= tol for y in zones(candles(tok, th))[0])
    fib = any(abs(f - r["p"]) <= tol for f in fibs)
    hot = rsi14(dc) >= 65
    out["pts"] = (2 if r["s"] >= .66 else 1 if r["s"] >= .4 else 0) + htf + fib + hot     # quality of the top, max 5
    wick = [k for k in range(max(0, len(dc) - 3), len(dc)) if dc[k]["h"] > r["hi"] + atr * .05]
    rejected = bool(wick) and last <= r["hi"] and any(c["c"] <= r["hi"] for c in dc[wick[0]:wick[0] + 4])
    top = max([dc[k]["h"] for k in wick] + [r["hi"]])
    stop = top + atr * .5
    target = downs[0]["hi"] if downs else None
    out.update(zone=(r["lo"], r["hi"]), level=r["p"], stop=stop, target=target, htf=htf, fib=fib, hot=hot,
               rr=(last - target) / (stop - last) if target and stop > last else None)
    if out["pts"] < 2: out["note"] = "Nearby resistance is weak"; return out
    if rejected: out.update(verdict="SHORT SIGNAL", note="Price spiked above the resistance zone, then closed back below it")
    elif dist <= 1: out.update(verdict="AT TOP - WAIT", note="At resistance: wait for a rejection (a spike above the zone that closes back below) before shorting")
    else: out.update(verdict="WATCH", note=f"{dist:.1f}% below the resistance zone")
    return out

def check_shorts():
    SHORTS.clear()
    for tok in SHORT_TOKENS:
        stock = tok.startswith("STOCK:"); name = tok.replace("STOCK:", "")
        if stock and not (os.environ.get("STOCKS_ANYTIME") or us_open()): continue       # stock prices only move in US market hours
        try: o = short_check(tok)
        except Exception as e: print(f"{name} top check: could not check ({str(e)[:50]})"); continue
        v = o["verdict"]
        print(f"{name} top check: {v}" + (f", score {o['pts']}/5" if o["pts"] else "") + (f" - {o['note']}" if o["note"] else ""))
        if v not in ("SHORT SIGNAL", "AT TOP - WAIT"): continue
        o["passed"] = o["pts"] >= MIN_SCORE and (o["rr"] is None or o["rr"] >= MIN_RR)
        SHORTS.append(o)
        if not o["passed"]: print(f"        (no phone alert: below your filters, score {MIN_SCORE}/5 and risk/reward {MIN_RR})"); continue
        key = f"SHORT:{tok}|{v}"
        if fresh(key, o["level"]):
            alerted[key] = {"t": time.time(), "p": o["level"]}
            save(STATE, alerted)
            lo, hi = o["zone"]
            msg = f"Possible local top. Price {fmt(o['last'])}, resistance {fmt(lo)}-{fmt(hi)}. {o['note']}."
            if v == "SHORT SIGNAL":
                msg += f" Short idea: stop {fmt(o['stop'])}" + (f", target {fmt(o['target'])}" if o["target"] else "") + (f", risk/reward {o['rr']:.1f}" if o["rr"] else "")
                msg += (". Stocks tend to drift up over time and shorting needs a broker that allows it (or puts or an inverse ETF), so keep size small." if stock
                        else f". Alts often fall harder than {name} when it turns, but shorts can lose more than a long, so keep size small.")
            notify(f"{name}: {v}", msg, (NTFY_TOPIC_STOCKS or NTFY_TOPIC) if stock else NTFY_TOPIC,
                   COLORS[v][0] + "," + ("chart_with_downwards_trend" if stock else "coin"), COLORS[v][1])

def check_holdings():
    for tok, entry, stop, target in parse_holdings():
        stock = tok.startswith("STOCK:")
        if stock and not (os.environ.get("STOCKS_ANYTIME") or us_open()): continue
        try: r = exit_check(tok, entry, stop, target)
        except Exception as e: print(f"{tok} holding: could not check ({str(e)[:50]})"); continue
        if not r: print(f"{tok.replace('STOCK:', '')} holding: HOLD"); continue
        name, v, lvl, msg = r
        print(f"{name} holding: {v} - {msg}")
        key = f"HOLD:{tok}|{v}"
        if fresh(key, lvl):
            alerted[key] = {"t": time.time(), "p": lvl}
            save(STATE, alerted)
            notify(f"SELL {name}: {v}", msg, (NTFY_TOPIC_STOCKS or NTFY_TOPIC) if stock else NTFY_TOPIC,
                   COLORS[v][0] + "," + ("chart_with_upwards_trend" if stock else "coin"), COLORS[v][1])

def run(tokens):
    tokens = expand(tokens)
    note = ""
    if not (os.environ.get("STOCKS_ANYTIME") or us_open()):
        n0 = len(tokens); tokens = [t for t in tokens if not t.startswith("STOCK:")]
        if len(tokens) < n0: note = f" (skipped {n0 - len(tokens)} stocks: US market closed)"
    print("\n" + datetime.now().strftime("%d %b %H:%M"), f"- checking {len(tokens)} symbols{note}", "-" * 20)
    with ThreadPoolExecutor(6) as ex: res = list(ex.map(check, tokens))
    waiting, hidden, errs, bulk = 0, 0, [], len(tokens) > 15
    for t, o, e in res:
        if e: errs.append((t, e)); continue
        v, z = o["verdict"], o["zone"]
        alertable = bool(z) and v in ("BUY SIGNAL", "IN ZONE", "IN ZONE - WAIT")
        rr = rr_of(o) if alertable else None
        passes = alertable and z["pts"] >= MIN_SCORE and (rr is None or rr >= MIN_RR)
        if bulk and (v == "WAIT" or (alertable and not passes)):
            if v == "WAIT": waiting += 1
            else: hidden += 1
            continue
        show(o)
        if not alertable: continue
        if not passes:
            print(f"        (no phone alert: below your filters, score {MIN_SCORE}/5 and risk/reward {MIN_RR})"); continue
        key = f"{t}|{v}"
        if fresh(key, z["p"]):
            alerted[key] = {"t": time.time(), "p": z["p"]}
            for k in [k for k, e in alerted.items() if not isinstance(e, dict) or time.time() - e["t"] > 86400]: del alerted[k]
            save(STATE, alerted)
            stock = t.startswith("STOCK:")
            (print if v in MUTED_PHONE else notify)(f'{o["tok"]}: {v}', f'Price {fmt(o["last"])}. Zone {fmt(z["lo"])}-{fmt(z["hi"])}, stop {fmt(z["stop"])}' + (f', risk/reward {rr:.1f}' if rr else '') + f'. {o["note"]}',
                   (NTFY_TOPIC_STOCKS or NTFY_TOPIC) if stock else NTFY_TOPIC, COLORS[v][0] + "," + ("chart_with_upwards_trend" if stock else "coin"), COLORS[v][1])
    if waiting or hidden: print(f"\n{waiting} others: nothing near support. {hidden} weaker setups hidden (below your filters).")
    if errs: print(f"could not check {len(errs)}: " + ", ".join(f"{t} ({str(e)[:40]})" for t, e in errs[:3]) + (" ..." if len(errs) > 3 else ""))
    check_holdings()
    check_shorts()

if __name__ == "__main__":
    toks = [a.upper() for a in sys.argv[1:]] or TOKENS
    try:
        while True:
            run(toks)
            if not CHECK_EVERY_MINUTES: break
            time.sleep(CHECK_EVERY_MINUTES * 60)
    except KeyboardInterrupt:
        print("\nStopped.")
