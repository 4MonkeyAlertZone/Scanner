#!/usr/bin/env python3
"""Backtest: replays scanner.py over past candles (never peeking at the future) and measures what its signals did.
Writes backtest_signals.csv and backtest_summary.txt. Needs scanner.py in the same folder.  Run: python backtest.py"""
import csv, json, os, random, statistics as st, sys, time
from bisect import bisect_right
from datetime import datetime, timezone
from multiprocessing import Pool
import scanner

# ---------------- SETTINGS ----------------
N_CRYPTO = int(os.environ.get("BT_CRYPTO", "30"))            # test the top N coins by market cap
USE_STOCKS = os.environ.get("BT_STOCKS", "1") == "1"         # also test ~30 big US stocks
MONTHS = int(os.environ.get("BT_MONTHS", "12"))              # months of crypto history to replay
STOCK_YEARS = int(os.environ.get("BT_STOCK_YEARS", "3"))
HORIZON = {"crypto": 42, "stock": 10}   # candles to wait for target/stop: 7 days of 4H, 10 trading days
COOL = {"crypto": 6, "stock": 3}        # ignore repeat signals on the same zone for this many candles
COST = 0.002                            # round-trip fees + slippage, as a fraction of price
CONTROLS = 5                            # random entries per signal, used as the "no skill" comparison
SIGNALS = ("BUY SIGNAL", "IN ZONE", "IN ZONE - WAIT")
OUT = scanner.HERE
# ------------------------------------------

def _rows(k, ms=True):
    return [(x[0] / 1000, float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])) for x in k]

def _binance_us(sym, interval, need):
    """Binance.US: 1000 candles per request, pages back with endTime (verified to work from GitHub, MEXC's paging does not)."""
    out, end = [], int(time.time() * 1000)
    while len(out) < need:
        k = json.loads(scanner.http(f"https://api.binance.us/api/v3/klines?symbol={sym}USDT&interval={interval}&endTime={end}&limit=1000"))
        if not k: break
        out = _rows(k) + out
        end = int(k[0][0]) - 1
        if len(k) < 1000: break
    return out

def _okx(sym, interval, need):
    """OKX: 100 candles per request, pages back with 'after'. Used when Binance.US does not list the coin or has too little history."""
    bar = {"4h": "4H", "1d": "1D"}[interval]; out, after = [], ""
    while len(out) < need:
        k = json.loads(scanner.http(f"https://www.okx.com/api/v5/market/history-candles?instId={sym}-USDT&bar={bar}&limit=100" + (f"&after={after}" if after else "")))["data"]
        if not k: break
        rows = [(int(x[0]) / 1000, float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])) for x in k]
        out += rows; after = str(int(min(r[0] for r in rows) * 1000))
        if len(k) < 100: break
        time.sleep(0.45)            # OKX allows about 20 history requests per 2 seconds per address
    return out

def clean(rows):
    """Oldest first, one row per timestamp, prices valid. Guards against the duplicated-history bug that spoiled the first crypto backtests."""
    seen, out = set(), []
    for r in sorted(rows):
        if r[0] in seen or min(r[1:5]) <= 0: continue
        seen.add(r[0]); out.append(r)
    return out

def hist_crypto(sym, interval, need):
    best = []
    for fn in (_binance_us, _okx):
        try: rows = clean(fn(sym, interval, need))
        except Exception: rows = []
        if len(rows) > len(best): best = rows
        if len(best) >= need * .9: break
    return best[:-1]   # drop the candle that is still forming

def coverage(rows):
    """One line saying what dates the signals really cover, so a data problem is visible in every report."""
    f = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
    out = []
    for mk in ("crypto", "stock"):
        e = [int(r["epoch"]) for r in rows if r.get("market") == mk]
        if e: out.append(f"{mk}: {f(min(e))} to {f(max(e))} ({(max(e) - min(e)) / 86400 / 30.4:.0f} months, {len(e)} signals)")
    return "DATA COVERED  " + "; ".join(out) if out else ""

def hist_stock(sym, interval):
    j = json.loads(scanner.http(scanner.YAHOO.format(sym, interval, "10y"), headers=scanner.UA))["chart"]["result"][0]
    q = j["indicators"]["quote"][0]
    rows = [(t, o, h, l, c, v or 0) for t, o, h, l, c, v in zip(j["timestamp"], q["open"], q["high"], q["low"], q["close"], q["volume"])
            if None not in (o, h, l, c)]
    return rows[:-1]

def D(rows): return [dict(o=o, h=h, l=l, c=c, v=v) for _, o, h, l, c, v in rows]

def outcome(entry, stop, target, fut):
    """('target'|'stop'|'neither', result in R after costs). If one candle touches both, the stop counts first."""
    risk = entry - stop
    if risk <= 0 or not fut: return None
    cost = COST * entry / risk
    for _, o, h, l, c, v in fut:
        if l <= stop: return "stop", -1 - cost
        if target and h >= target: return "target", (target - entry) / risk - cost
    return "neither", (fut[-1][4] - entry) / risk - cost

CTX = {}
def fake_candles(tok, tf): return CTX["main"] if tf == CTX["tm"] else CTX["high"]

def backtest_token(a):
    tok, market = a
    try:
        name = tok if market == "crypto" else "STOCK:" + tok
        if market == "crypto":
            m, hi = hist_crypto(tok, "4h", MONTHS * 180 + 520), hist_crypto(tok, "1d", MONTHS * 30 + 520)
            per, hper, tm, ntest = 4 * 3600, 86400, "4h", MONTHS * 180
        else:
            m, hi = hist_stock(tok, "1d"), hist_stock(tok, "1wk")
            per, hper, tm, ntest = 86400, 7 * 86400, "1d", STOCK_YEARS * 252
        H = HORIZON[market]
        if len(m) < 560: return tok, [], [], "not enough history"
        scanner.candles = fake_candles
        CTX["tm"] = tm
        hi_ts = [r[0] for r in hi]
        first = max(500, len(m) - H - ntest)
        sigs, ctrl, last_i = [], [], {}
        rnd = random.Random(tok)
        for i in range(first, len(m) - H):
            j = bisect_right(hi_ts, m[i][0] + per - hper)       # higher-timeframe candles fully closed by now
            c = m[i][4]
            CTX["main"] = D(m[i-499:i+1]) + [dict(o=c, h=c, l=c, c=c, v=0)]   # + an empty "forming" candle, like live
            CTX["high"] = D(hi[max(0, j - 500):j])
            o = scanner.analyse(name)
            z = o["zone"]
            if not z or o["verdict"] not in SIGNALS: continue
            mid = (z["lo"] + z["hi"]) / 2
            prev = last_i.get(o["verdict"])
            if prev and i - prev[0] < COOL[market] and abs(mid / prev[1] - 1) < .02: continue
            last_i[o["verdict"]] = (i, mid)
            res = outcome(c, z["stop"], o["target"], m[i+1:i+1+H])
            if not res: continue
            rr = scanner.rr_of(o)
            sigs.append(dict(token=tok, market=market, time=datetime.fromtimestamp(m[i][0], timezone.utc).strftime("%Y-%m-%d %H:%M"),
                             epoch=int(m[i][0]), verdict=o["verdict"], passed=int(z["pts"] >= scanner.MIN_SCORE and (rr is None or rr >= scanner.MIN_RR)),
                             score=z["pts"], quality=z["base"], htf=int(z["htf"]), fib=int(z["fib"]), strength=round(z["s"], 2),
                             touches=z["t"], dist_pct=round(z["dist"], 2), rr=round(rr, 2) if rr is not None else "",
                             price=c, stop=z["stop"], target=o["target"] or "", result=res[0], R=round(res[1], 3)))
            sp = (c - z["stop"]) / c
            tp = (o["target"] - c) / c if o["target"] else None
            for _ in range(CONTROLS):                            # random entries with the same stop/target distances
                k = rnd.randrange(first, len(m) - H); e = m[k][4]
                r2 = outcome(e, e * (1 - sp), e * (1 + tp) if tp else None, m[k+1:k+1+H])
                if r2: ctrl.append(dict(market=market, result=r2[0], R=r2[1]))
        return tok, sigs, ctrl, ""
    except Exception as e:
        return tok, [], [], str(e)[:80]

def line(label, rs):
    n = len(rs)
    if not n: return f"{label:<34}{0:>5}"
    R = [r["R"] for r in rs]
    tg, sp = sum(r["result"] == "target" for r in rs), sum(r["result"] == "stop" for r in rs)
    ci = 1.96 * st.stdev(R) / n ** .5 if n > 1 else 0
    return f"{label:<34}{n:>5}  target {tg/n:4.0%}  stop {sp/n:4.0%}  neither {1-(tg+sp)/n:4.0%}  avg R {st.mean(R):+.2f} (+/-{ci:.2f})"

def summary(S, C, errs):
    S.sort(key=lambda r: r["epoch"]); mid = S[len(S) // 2]["epoch"] if S else 0
    g = lambda f: [r for r in S if f(r)]
    L = [f"BACKTEST  {datetime.now(timezone.utc):%Y-%m-%d}  (R = profit in units of the risk to the stop; costs of {COST:.1%} included)",
         "Avg R above 0 means profitable. The +/- is a 95% margin of error: if it is bigger than the average, it is mostly noise.", "",
         line("ALL SIGNALS", S), line("random entries, same stop/target", C), "",
         "-- Did the filters help? --", line(f"passed filters (score>={scanner.MIN_SCORE}, R/R>={scanner.MIN_RR})", g(lambda r: r["passed"])),
         line("blocked by filters", g(lambda r: not r["passed"])), "", "-- By verdict --"]
    L += [line(v, g(lambda r, v=v: r["verdict"] == v)) for v in SIGNALS]
    L += ["", "-- By score --"] + [line(f"score {s}/5", g(lambda r, s=s: r["score"] == s)) for s in range(2, 6)]
    L += ["", "-- Other factors --", line("1D/weekly zone matched", g(lambda r: r["htf"])), line("no higher-timeframe match", g(lambda r: not r["htf"])),
          line("fib level matched", g(lambda r: r["fib"])), line("no fib match", g(lambda r: not r["fib"])),
          line("risk/reward < 1.2", g(lambda r: r["rr"] != "" and r["rr"] < 1.2)), line("risk/reward 1.2 - 2", g(lambda r: r["rr"] != "" and 1.2 <= r["rr"] < 2)),
          line("risk/reward >= 2", g(lambda r: r["rr"] != "" and r["rr"] >= 2)), "", "-- By market and time (is it stable?) --",
          line("crypto", g(lambda r: r["market"] == "crypto")), line("stocks", g(lambda r: r["market"] == "stock")),
          line("first half of the period", g(lambda r: r["epoch"] < mid)), line("second half of the period", g(lambda r: r["epoch"] >= mid))]
    if errs: L += ["", f"Could not test {len(errs)}: " + ", ".join(f"{t} ({e})" for t, e in errs[:5])]
    return "\n".join(L)

if __name__ == "__main__":
    jobs = [(t, "crypto") for t in scanner.top100()[:N_CRYPTO]]
    if USE_STOCKS: jobs += [(s, "stock") for s in scanner.BIG_STOCKS[:30]]
    print(f"Replaying {len(jobs)} symbols...", flush=True)
    with Pool(max(1, os.cpu_count() or 1)) as p: res = p.map(backtest_token, jobs)
    S = [s for _, sg, _, _ in res for s in sg]; C = [c for _, _, cc, _ in res for c in cc]
    errs = [(t, e) for t, _, _, e in res if e]
    if S:
        with open(os.path.join(OUT, "backtest_signals.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, list(S[0].keys())); w.writeheader(); w.writerows(sorted(S, key=lambda r: r["epoch"]))
    text = (coverage(S) + "\n" + summary(S, C, errs)) if S else "No signals found. " + str(errs[:3])
    open(os.path.join(OUT, "backtest_summary.txt"), "w").write(text + "\n")
    print("\n" + text)
    try:   # send the headline numbers and the full summary to your phone
        import paper
        scanner.notify("Backtest finished", text.split("-- By score")[0][:1800], scanner.NTFY_TOPIC, "bar_chart")
        paper.attach(os.path.join(OUT, "backtest_summary.txt"))
    except Exception as e: print("(phone send failed:", e, ")")
