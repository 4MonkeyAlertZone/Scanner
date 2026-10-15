#!/usr/bin/env python3
"""Backtest of the SHORT signals (crypto and stocks). Replays scanner.short_check() candle by candle over past data (never
peeking at the future), shorts each signal at the close of its candle, and checks whether the stop (above) or the target (below)
came first. Compares with random shorts that have the same stop/target distances, separately for crypto and stocks.
Needs scanner.py and backtest.py in the same folder. Writes backtest_short_signals.csv and backtest_short_summary.txt.
Run: python backtest_short.py"""
import csv, os, random, statistics as st
from bisect import bisect_right
from datetime import datetime, timezone
from multiprocessing import Pool
import scanner, backtest as B

MONTHS = int(os.environ.get("BT_SHORT_MONTHS", "36"))              # crypto: months of 4H candles to replay
STOCK_YEARS = int(os.environ.get("BT_SHORT_STOCK_YEARS", "5"))     # stocks: years of daily candles to replay
DEFAULT = "BTC,ETH,STOCK:SPY,STOCK:QQQ,STOCK:AAPL,STOCK:MSFT,STOCK:NVDA,STOCK:GOOGL,STOCK:AMZN,STOCK:META,STOCK:TSLA"
SYMS = [c.strip().upper() for c in os.environ.get("SHORT_TOKENS", DEFAULT).split(",") if c.strip()]
HORIZON = {"crypto": 42, "stock": 10}   # candles to wait for the stop/target: 7 days of 4H, 10 trading days
COOLDOWN = {"crypto": 6, "stock": 3}    # ignore repeat signals on the same zone for this many candles
CONTROLS = 5                            # random shorts per signal for the "no skill" comparison
VERDICTS = ("SHORT SIGNAL", "AT TOP - WAIT")
INDEX, MAG7 = {"SPY", "QQQ"}, {"AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"}

def short_outcome(entry, stop, target, fut):
    """('target'|'stop'|'neither', result in R after costs). If one candle touches both, the stop counts first."""
    risk = stop - entry
    if risk <= 0 or not fut: return None
    cost = B.COST * entry / risk
    for _, o, h, l, c, v in fut:
        if h >= stop: return "stop", -1 - cost
        if target and l <= target: return "target", (entry - target) / risk - cost
    return "neither", (entry - fut[-1][4]) / risk - cost

def run_symbol(name):
    stock = name.startswith("STOCK:"); sym = name.replace("STOCK:", ""); mk = "stock" if stock else "crypto"
    H, COOL = HORIZON[mk], COOLDOWN[mk]
    try:
        if stock:
            m, hi = B.hist_stock(sym, "1d"), B.hist_stock(sym, "1wk")
            per, hper, ntest, B.CTX["tm"] = 86400, 7 * 86400, STOCK_YEARS * 252, "1d"
        else:
            m, hi = B.hist_crypto(sym, "4h", MONTHS * 180 + 520), B.hist_crypto(sym, "1d", MONTHS * 30 + 520)
            per, hper, ntest, B.CTX["tm"] = 4 * 3600, 86400, MONTHS * 180, "4h"
        if len(m) < 560: return sym, mk, [], [], None, "not enough history"
        scanner.candles = B.fake_candles
        hi_ts = [r[0] for r in hi]
        first = max(500, len(m) - H - ntest)
        sigs, ctrl, last_i, rnd = [], [], {}, random.Random(sym)
        for i in range(first, len(m) - H):
            j = bisect_right(hi_ts, m[i][0] + per - hper)          # higher-timeframe candles fully closed by now
            c = m[i][4]
            B.CTX["main"] = B.D(m[i-499:i+1]) + [dict(o=c, h=c, l=c, c=c, v=0)]   # + an empty "forming" candle, like live
            B.CTX["high"] = B.D(hi[max(0, j - 500):j])
            o = scanner.short_check(name)
            if o["verdict"] not in VERDICTS or o.get("stop") is None: continue
            mid = o["level"]; prev = last_i.get(o["verdict"])
            if prev and i - prev[0] < COOL and abs(mid / prev[1] - 1) < .02: continue
            last_i[o["verdict"]] = (i, mid)
            res = short_outcome(c, o["stop"], o["target"], m[i+1:i+1+H])
            if not res: continue
            sigs.append(dict(symbol=sym, market=mk, time=datetime.fromtimestamp(m[i][0], timezone.utc).strftime("%Y-%m-%d %H:%M"), epoch=int(m[i][0]),
                             verdict=o["verdict"], score=o["pts"], htf=int(o["htf"]), fib=int(o["fib"]), rsi_hot=int(o["hot"]),
                             rr=round(o["rr"], 2) if o["rr"] is not None else "",
                             passed=int(o["pts"] >= scanner.MIN_SCORE and (o["rr"] is None or o["rr"] >= scanner.MIN_RR)),
                             entry=c, stop=o["stop"], target=o["target"] or "", result=res[0], R=round(res[1], 3)))
            sp = (o["stop"] - c) / c; tp = (c - o["target"]) / c if o["target"] else None
            for _ in range(CONTROLS):                                # random shorts with the same stop/target distances
                k = rnd.randrange(first, len(m) - H); e = m[k][4]
                r2 = short_outcome(e, e * (1 + sp), e * (1 - tp) if tp else None, m[k+1:k+1+H])
                if r2: ctrl.append(dict(market=mk, result=r2[0], R=r2[1]))
        move = (m[len(m) - H - 1][4] / m[first][4] - 1) * 100
        return sym, mk, sigs, ctrl, move, ""
    except Exception as e:
        return sym, mk, [], [], None, str(e)[:80]

def verdict(label, sh, ctl):
    n = len(sh)
    if n < 30: return f"{label}: only {n} SHORT SIGNALs, too few to judge."
    R = [r["R"] for r in sh]; avg = st.mean(R); ci = 1.96 * st.stdev(R) / n ** .5
    c = st.mean([x["R"] for x in ctl]) if ctl else 0
    if avg - ci > max(0, c): return f"{label}: beat both zero and random shorts by more than the margin of error. Encouraging, but the past does not guarantee the future."
    if avg > 0 and avg > c: return f"{label}: slightly positive but within the margin of error. No clear edge yet."
    return f"{label}: NO EDGE. It did not beat random shorts. Do not act on it as it stands."

def summary(S, C, moves, errs):
    S.sort(key=lambda r: r["epoch"]); mid = S[len(S) // 2]["epoch"] if S else 0
    g = lambda f: [r for r in S if f(r)]
    sh = g(lambda r: r["verdict"] == "SHORT SIGNAL")
    cr, sk = [r for r in sh if r["market"] == "crypto"], [r for r in sh if r["market"] == "stock"]
    cc, cs = [c for c in C if c["market"] == "crypto"], [c for c in C if c["market"] == "stock"]
    L = [f"SHORT-SIGNAL BACKTEST  {datetime.now(timezone.utc):%Y-%m-%d}  (crypto: {MONTHS} months of 4H; stocks: {STOCK_YEARS} years of daily)",
         f"R = profit in units of the risk to the stop; costs of {B.COST:.1%} included. Avg R above 0 means profitable. The +/- is a 95% margin of error.",
         "Stocks: no borrow fees or dividends are included, and stocks tend to drift up, which is a headwind for shorts.", ""]
    L += [f"Price change of {s} over the tested period: {mv:+.0f}%" for s, mv in moves.items()]
    L += ["", "-- Crypto --", B.line("SHORT SIGNAL (alerts)", cr), B.line("AT TOP - WAIT (watch only)", g(lambda r: r["verdict"] == "AT TOP - WAIT" and r["market"] == "crypto")),
          B.line("random crypto shorts", cc), "", "-- Stocks --", B.line("SHORT SIGNAL (alerts)", sk),
          B.line("AT TOP - WAIT (watch only)", g(lambda r: r["verdict"] == "AT TOP - WAIT" and r["market"] == "stock")), B.line("random stock shorts", cs), "",
          "-- SHORT SIGNAL by symbol --"] + [B.line(s, [r for r in sh if r["symbol"] == s]) for s in [x.replace("STOCK:", "") for x in SYMS]]
    L += ["", B.line("S&P 500 / Nasdaq ETFs (SPY, QQQ)", [r for r in sk if r["symbol"] in INDEX]), B.line("Magnificent 7 stocks", [r for r in sk if r["symbol"] in MAG7]), "",
          "-- SHORT SIGNAL: did the filters help? --", B.line(f"passed (score>={scanner.MIN_SCORE}, R/R>={scanner.MIN_RR})", [r for r in sh if r["passed"]]),
          B.line("blocked by filters", [r for r in sh if not r["passed"]]), "", "-- SHORT SIGNAL by score --"]
    L += [B.line(f"score {s}/5", [r for r in sh if r["score"] == s]) for s in range(2, 6)]
    L += ["", "-- SHORT SIGNAL: other factors --", B.line("higher-timeframe zone matched", [r for r in sh if r["htf"]]), B.line("no match", [r for r in sh if not r["htf"]]),
          B.line("RSI >= 65 (overbought)", [r for r in sh if r["rsi_hot"]]), B.line("RSI < 65", [r for r in sh if not r["rsi_hot"]]),
          B.line("first half of the period", [r for r in sh if r["epoch"] < mid]), B.line("second half of the period", [r for r in sh if r["epoch"] >= mid]), "",
          "VERDICTS", verdict("Crypto (BTC, ETH)", cr, cc), verdict("Stocks (all)", sk, cs),
          verdict("  S&P 500 / Nasdaq ETFs", [r for r in sk if r["symbol"] in INDEX], cs), verdict("  Magnificent 7", [r for r in sk if r["symbol"] in MAG7], cs)]
    if errs: L += ["", "Problems: " + "; ".join(f"{s}: {e}" for s, e in errs)]
    return "\n".join(L)

if __name__ == "__main__":
    print(f"Replaying {len(SYMS)} symbols...", flush=True)
    with Pool(max(1, min(len(SYMS), os.cpu_count() or 1))) as p: res = p.map(run_symbol, SYMS)
    S = [s for _, _, sg, _, _, _ in res for s in sg]; C = [c for _, _, _, cc, _, _ in res for c in cc]
    moves = {s: mv for s, _, _, _, mv, _ in res if mv is not None}; errs = [(s, e) for s, _, _, _, _, e in res if e]
    if S:
        with open(os.path.join(scanner.HERE, "backtest_short_signals.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, list(S[0].keys())); w.writeheader(); w.writerows(sorted(S, key=lambda r: r["epoch"]))
    text = summary(S, C, moves, errs) if S else "No short signals found. " + str(errs[:3])
    with open(os.path.join(scanner.HERE, "backtest_short_summary.txt"), "w") as f: f.write(text + "\n")
    print("\n" + text)
    try:
        import paper
        scanner.notify("Short-signal backtest", "VERDICTS" + text.split("VERDICTS")[-1], scanner.NTFY_TOPIC, "bar_chart")
        paper.attach(os.path.join(scanner.HERE, "backtest_short_summary.txt"))
    except Exception as e: print("(phone send failed:", e, ")")
