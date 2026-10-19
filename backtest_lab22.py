#!/usr/bin/env python3
"""Strategy lab 22: the ORIGINAL support finder (scanner.analyse, replayed candle by candle on 4H, live-style: last candle = empty forming candle,
signals use only closed candles) with extra filters turned on one at a time: RSI(14), BTC 200-day gate, sharp-drop context, touches, 1D confluence, wick.
Window: entries 1 Oct 2020 - 31 Aug 2025 (cycle 1 / bear year / cycle 2). Cost 0.1% round trip. Same outcome rule as backtest.py (stop first, target = next resistance, 7-day horizon).
Controls: random entries with the same stop/target distances, matched on the same BTC gate state. Writes lab22_summary.txt and lab22_signals.csv."""
import csv, os, random, statistics as st, calendar, time
from bisect import bisect_right
from datetime import datetime, timezone
from multiprocessing import Pool
import scanner, backtest as B

B.COST = float(os.environ.get("LAB_COST", "0.001"))
STEP = int(os.environ.get("LAB22_STEP", "2"))          # evaluate every 2nd 4H candle (8 hours)
NCOINS = int(os.environ.get("LAB22_COINS", "45"))
H = 42; COOL = 6
T0 = calendar.timegm((2020, 10, 1, 0, 0, 0)); T1 = calendar.timegm((2025, 9, 1, 0, 0, 0))
C1 = (T0, calendar.timegm((2021, 11, 10, 0, 0, 0))); BEAR = (C1[1], calendar.timegm((2022, 11, 21, 0, 0, 0))); C2 = (BEAR[1], T1)
SIG = ("BUY SIGNAL", "IN ZONE", "IN ZONE - WAIT")
BTCD = {}

def gate_at(t):
    """BTC daily close above its 200-day average, using only fully closed days."""
    d = BTCD["ts"]; j = bisect_right(d, t - 86400)       # days whose close time <= t
    if j < 200: return None
    cl = BTCD["c"][j-200:j]
    return cl[-1] > sum(cl) / 200

def job(tok):
    try:
        if not BTCD:
            b = B.hist_crypto("BTC", "1d", 2500); BTCD["ts"] = [r[0] for r in b]; BTCD["c"] = [r[4] for r in b]
        m = B.hist_crypto(tok, "4h", 12500); hi = B.hist_crypto(tok, "1d", 2600)
        if len(m) < 1500: return tok, [], [], "short history"
        scanner.candles = B.fake_candles; B.CTX["tm"] = "4h"
        hi_ts = [r[0] for r in hi]; per, hper = 4 * 3600, 86400
        idx = [i for i in range(500, len(m) - H) if T0 <= m[i][0] < T1]
        if not idx: return tok, [], [], "no window"
        sigs, ctrl, last_i = [], [], {}; rnd = random.Random(tok)
        for i in idx[::STEP]:
            j = bisect_right(hi_ts, m[i][0] + per - hper); c = m[i][4]
            B.CTX["main"] = B.D(m[i-499:i+1]) + [dict(o=c, h=c, l=c, c=c, v=0)]
            B.CTX["high"] = B.D(hi[max(0, j - 500):j])
            o = scanner.analyse(tok); z = o["zone"]
            if not z or o["verdict"] not in SIG: continue
            mid = (z["lo"] + z["hi"]) / 2; prev = last_i.get(o["verdict"])
            if prev and i - prev[0] < COOL and abs(mid / prev[1] - 1) < .02: continue
            last_i[o["verdict"]] = (i, mid)
            res = B.outcome(c, z["stop"], o["target"], m[i+1:i+1+H])
            if not res: continue
            dc = B.D(m[i-499:i+1])                       # closed candles incl. the current price
            lc = m[i]; rng = lc[3] - lc[4 - 1] if False else (lc[2] - lc[3]) or 1e-12   # last closed candle: high-low
            lowwick = (min(lc[1], lc[4]) - lc[3]) / rng
            rows = m[i-12:i+1]
            drop48 = c / m[i-12][4] - 1
            rr = scanner.rr_of(o)
            sigs.append(dict(token=tok, epoch=int(m[i][0]), verdict=o["verdict"], gate=gate_at(m[i][0]), rsi=round(scanner.rsi14(dc), 1),
                             drop48=round(drop48, 3), touches=z["t"], htf=int(z["htf"]), fib=int(z["fib"]), score=z["pts"], wick=round(lowwick, 2),
                             rr=round(rr, 2) if rr is not None else "", result=res[0], R=round(res[1], 3)))
            sp = (c - z["stop"]) / c; tp = (o["target"] - c) / c if o["target"] else None
            for _ in range(5):
                k = rnd.choice(idx); e = m[k][4]
                r2 = B.outcome(e, e * (1 - sp), e * (1 + tp) if tp else None, m[k+1:k+1+H])
                if r2: ctrl.append(dict(epoch=int(m[k][0]), gate=gate_at(m[k][0]), R=r2[1]))
        return tok, sigs, ctrl, ""
    except Exception as e:
        return tok, [], [], str(e)[:80]

FILTERS = [
 ("ORIGINAL (no extra filter)", lambda r: True),
 ("RSI < 35", lambda r: r["rsi"] < 35), ("RSI < 30", lambda r: r["rsi"] < 30), ("RSI 35-50", lambda r: 35 <= r["rsi"] < 50), ("RSI >= 50", lambda r: r["rsi"] >= 50),
 ("BTC above 200d avg", lambda r: r["gate"] is True), ("BTC below 200d avg", lambda r: r["gate"] is False),
 ("48h drop >= 12%", lambda r: r["drop48"] <= -.12), ("48h drop >= 8%", lambda r: r["drop48"] <= -.08),
 ("touches >= 3", lambda r: r["touches"] >= 3), ("1D/weekly zone match", lambda r: r["htf"] == 1),
 ("long lower wick (>=50%)", lambda r: r["wick"] >= .5), ("BUY SIGNAL only (reclaim)", lambda r: r["verdict"] == "BUY SIGNAL"),
 ("GATE + RSI < 35", lambda r: r["gate"] is True and r["rsi"] < 35),
 ("GATE + drop >= 8%", lambda r: r["gate"] is True and r["drop48"] <= -.08),
 ("GATE + 1D match", lambda r: r["gate"] is True and r["htf"] == 1),
 ("GATE + RSI<35 + 1D match", lambda r: r["gate"] is True and r["rsi"] < 35 and r["htf"] == 1),
 ("GATE + reclaim + RSI<45", lambda r: r["gate"] is True and r["verdict"] == "BUY SIGNAL" and r["rsi"] < 45),
]
WIN = [("all", (T0, T1)), ("cycle 1", C1), ("bear yr", BEAR), ("cycle 2", C2)]

def cell(S, C, f, w):
    s = [r for r in S if w[0] <= r["epoch"] < w[1] and f(r)]
    n = len(s)
    if n < 5: return f"{n:>4}  --"
    R = [r["R"] for r in s]; a = st.mean(R)
    gs = {r["gate"] for r in s}; days = len({(r["token"], r["epoch"] // 86400) for r in s})
    # matched random: same gate mix as the signals
    cr = [c["R"] for c in C if w[0] <= c["epoch"] < w[1]]
    gates = [r["gate"] for r in s]
    cm = []
    for g in (True, False, None):
        k = gates.count(g)
        pool = [c["R"] for c in C if w[0] <= c["epoch"] < w[1] and c["gate"] is g]
        if k and pool: cm += [st.mean(pool)] * k
    rnd = st.mean(cm) if cm else (st.mean(cr) if cr else 0)
    ci = 1.96 * st.stdev(R) / n ** .5
    return f"{n:>4}/{days:<4}{a:+.2f} edge{a - rnd:+.2f}±{ci:.2f}"

def main():
    toks = scanner.top100()[:NCOINS]
    print(f"Replaying {len(toks)} coins...", flush=True)
    with Pool(2) as p: res = p.map(job, toks, chunksize=1)
    S = [s for _, sg, _, _ in res for s in sg]; C = [c for _, _, cc, _ in res for c in cc]
    errs = [(t, e) for t, _, _, e in res if e]
    L = [f"LAB 22  {datetime.now(timezone.utc):%Y-%m-%d}  original support finder + extra filters. Cost {B.COST:.2%} round trip. Entries 1 Oct 2020 - 31 Aug 2025, every {STEP*4}h, {len(toks)-len(errs)} coins (survivors only).",
         "Cell = signals/distinct coin-days, average R after costs, EDGE = avg R minus random entries (same stop/target distances, same BTC-gate mix), ± 95% margin. Edge bigger than the ± and positive in cycle 1 AND cycle 2 = worth trusting. Many filters tested: expect a couple of lucky ones.", ""]
    L.append(f"{'filter':<30}" + "".join(f"{n:<28}" for n, _ in WIN))
    for name, f in FILTERS: L.append(f"{name:<30}" + "".join(f"{cell(S, C, f, w):<28}" for _, w in WIN))
    if errs: L += ["", "Skipped: " + ", ".join(f"{t} ({e})" for t, e in errs[:10])]
    text = "\n".join(L)
    if S:
        with open(os.path.join(scanner.HERE, "lab22_signals.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, list(S[0].keys())); w.writeheader(); w.writerows(sorted(S, key=lambda r: r["epoch"]))
    open(os.path.join(scanner.HERE, "lab22_summary.txt"), "w").write(text + "\n"); print(text)
    try: scanner.notify("Strategy lab 22 finished", "Support finder + filters done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
