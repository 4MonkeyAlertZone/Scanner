#!/usr/bin/env python3
"""REGIME VARIANTS PAPER TEST (silent, no phone notes). Runs daily after the candle closes, rebuilt from daily candles each run.
Compares the live rule (BASE: BTC > 200d and > 50d avg, no OI warning in 14d) with three variants from lab 33, all with the same OI warning:
  BAND1: 50-day line needs a 1% band (in when close > 50d x1.01, out when close < 50d x0.99; 200d plain)
  S100F50: 100-day and 50-day averages instead of 200 and 50
  VOTE3: BTC above at least 3 of the 50/100/150/200/250-day averages
Paper account per variant and per coin (BTC, ETH): in the market on IN days, cash otherwise, 0.1% cost per change, signal at close earns next day's move.
Start date is stored in variants_start.txt. Writes variants_report.txt and variants_log.csv. Review on 5 Nov 2026."""
import os, csv, time
import scanner, backtest as B, basket_paper as BP
P = BP.P; fd = BP.fd; COST = 0.001

def sma(C, k):
    return [None if i < k - 1 else sum(C[i - k + 1:i + 1]) / k for i in range(len(C))]

def oi_warn(S, lb=180, rise=.15, cool=14):
    n = len(S); W = [False] * n
    for i in range(n):
        prev = [x for x in S[max(0, i - lb):i] if x]
        if S[i] and len(prev) > 0.55 * lb and S[i] >= max(prev) and i >= 30 and S[i - 30] and S[i] / S[i - 30] - 1 >= rise: W[i] = True
    out = [False] * n; left = 0
    for i in range(n):
        if W[i]: left = cool
        out[i] = left > 0
        if left > 0: left -= 1
    return out

def hyst(C, ma, h):
    out = [False] * len(C); st = False
    for i in range(len(C)):
        if ma[i] is None: continue
        if st and C[i] < ma[i] * (1 - h): st = False
        elif not st and C[i] > ma[i] * (1 + h): st = True
        out[i] = st
    return out

def closes(tok, today):
    m = B.hist_crypto(tok, "1d", 420)
    d = {int(r[0] // 86400): r[4] for r in m}
    return {k: v for k, v in d.items() if k < today}

def main():
    today = int(time.time() // 86400)
    cb = closes("BTC", today); ce = closes("ETH", today)
    days = [d for d in sorted(cb) if d in ce]; n = len(days)
    CB = [cb[d] for d in days]; CE = [ce[d] for d in days]
    try:
        oi = BP.get_oi(days); s = []; last = None
        for d in days:
            if d in oi: last = oi[d]
            s.append(last)
        ow = oi_warn(s)
    except Exception as e:
        print("OI unavailable:", e); ow = [False] * n
    ma = {k: sma(CB, k) for k in (50, 100, 150, 200, 250)}
    ab = {k: [ma[k][i] is not None and CB[i] > ma[k][i] for i in range(n)] for k in ma}
    hm = hyst(CB, ma[50], .01)
    V = {"BASE 200/50": [ab[200][i] and ab[50][i] and not ow[i] for i in range(n)],
         "BAND1 (50d +-1%)": [ab[200][i] and hm[i] and not ow[i] for i in range(n)],
         "S100F50": [ab[100][i] and ab[50][i] and not ow[i] for i in range(n)],
         "VOTE3 of 5 avgs": [sum(ab[k][i] for k in ma) >= 3 and not ow[i] for i in range(n)]}
    sp = P("variants_start.txt")
    if not os.path.exists(sp): open(sp, "w").write(str(days[-1]))
    start = int(open(sp).read().strip()); i0 = next((i for i, d in enumerate(days) if d >= start), n - 1)
    def acct(pos, C):
        eq = 1.0; prev = 0.0; flips = 0; inm = 0
        for i in range(i0, n - 1):
            p = 1.0 if pos[i] else 0.0
            if p != prev: eq *= 1 - COST; flips += 1
            eq *= 1 + p * (C[i + 1] / C[i] - 1); prev = p; inm += p
        return eq, flips, inm
    L = [f"REGIME VARIANTS PAPER TEST  data to {fd(days[-1])}  started {fd(days[i0])}  ({n - 1 - i0} days of live record so far)", "",
         f"{'variant':<20}{'state now':<11}{'BTC acct':>10}{'ETH acct':>10}{'flips':>7}{'days in':>9}"]
    for k, pos in V.items():
        b, f, im = acct(pos, CB); e, _, _ = acct(pos, CE)
        L.append(f"{k:<20}{'IN' if pos[-1] else 'OUT':<11}{(b - 1) * 100:>+9.1f}%{(e - 1) * 100:>+9.1f}%{f:>7}{int(im):>9}")
    bh = (CB[-1] / CB[i0] - 1) * 100; eh = (CE[-1] / CE[i0] - 1) * 100
    L.append(f"{'buy and hold':<20}{'':<11}{bh:>+9.1f}%{eh:>+9.1f}%")
    L += ["", "Accounts start at 0 (percent change since start), 0.1% cost per IN/OUT change, signal at the daily close earning the next day.",
          "Early weeks are not evidence: a few days of difference means nothing. Lab 33 history suggested these variants are close to BASE; this is a live check for the 5 Nov review."]
    open(P("variants_report.txt"), "w").write("\n".join(L) + "\n"); print("\n".join(L))
    lp = P("variants_log.csv"); new = not os.path.exists(lp)
    rows = {}
    if not new:
        for r in csv.reader(open(lp)):
            if r and r[0] != "date": rows[r[0]] = r
    rows[fd(days[-1])] = [fd(days[-1])] + ["IN" if pos[-1] else "OUT" for pos in V.values()]
    with open(lp, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date"] + list(V)); [w.writerow(rows[k]) for k in sorted(rows)]

if __name__ == "__main__":
    main()
