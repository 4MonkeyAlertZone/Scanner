#!/usr/bin/env python3
"""Lab 35: TEST THE CHART-ANALYST CLAIMS. Three claims from two Wyckoff write-ups (28 Oct), turned into rules BEFORE running:
 S1  'Four consecutive red weekly candles, a bounce is due': event = the close of the 4th red week in a row (weeks Monday-Sunday UTC, red = weekly close below weekly open).
 S2  '50-week EMA is key support, buy there': event = the first daily close within 2% of the 50-week EMA (or below it) after at least 10 closes more than 2% above it (EMA of weekly closes, span 50, daily value updated with the current close).
 S3  'Break below the 50-week EMA then add aggressively (spring)': event = the first daily close below the 50-week EMA after at least 10 closes above it. Also shows the worst dip in the next 30 days (what adding costs if the sweep does not reverse).
 S4  'Hidden bullish divergence': event = a confirmed daily swing low (lowest of +-5 days) that is HIGHER than the previous swing low while RSI14 at it is LOWER than RSI14 at the previous swing low; counted on the day it is confirmed (5 days later, no peeking).
Each event is judged by the forward return after 14/30/60/90 days (from that day's close, round-trip cost 0.2%), win rate, and the worst fall within the next 30 days. Events closer than 14 days to the previous one of the same type are dropped (overlap).
Comparison: (a) all days; (b) the same number of random days, 5000 draws, shown as the percentile where the event average falls (95+ = unusual, 50 = nothing); (c) same events split by whether BTC/ETH was above or below its own 200-day average (our regime idea); (d) halves.
BTC and ETH on their own charts. Few events (often 5-15) means wide uncertainty; independent market phases are far fewer than events. Writes lab35_summary.txt."""
import os, time, random, statistics as S
import scanner, backtest as B
OUT = scanner.HERE; fd = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))
COST = 0.002; HZ = (14, 30, 60, 90)

def sma(x, k):
    out = [None] * len(x); s = 0.0
    for i, v in enumerate(x):
        s += v
        if i >= k: s -= x[i - k]
        if i >= k - 1: out[i] = s / k
    return out
def rsi(c, n=14):
    out = [None] * len(c)
    if len(c) <= n: return out
    g = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]; l = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
    ag = sum(g[:n]) / n; al = sum(l[:n]) / n; out[n] = 100 - 100 / (1 + ag / al) if al else 100
    for i in range(n, len(g)):
        ag = (ag * (n - 1) + g[i]) / n; al = (al * (n - 1) + l[i]) / n; out[i + 1] = 100 - 100 / (1 + ag / al) if al else 100
    return out

def weekly(days, O, C):
    """list of (week_id, first_i, last_i) for complete Monday-Sunday weeks; week id from Monday-based index."""
    wk = {}
    for i, d in enumerate(days): wk.setdefault((d + 3) // 7, []).append(i)
    out = []
    for w in sorted(wk):
        ix = wk[w]
        if len(ix) == 7: out.append((w, ix[0], ix[-1]))
    return out

def ema50w(days, C):
    """daily series: 50-week EMA with the current close standing in for the unfinished week; None until 50 weeks exist."""
    n = len(days); out = [None] * n; k = 2 / 51
    wk = {}
    for i, d in enumerate(days): wk.setdefault((d + 3) // 7, []).append(i)
    ws = sorted(wk); lastclose = []   # completed weekly closes
    ema = None; cnt = 0; seq = []
    for w in ws:
        ix = wk[w]
        for i in ix:
            # EMA through completed weeks, then update with today's close as the provisional weekly close
            if ema is None: val = None
            else: val = ema + k * (C[i] - ema)
            out[i] = val if cnt >= 50 else None
        if len(ix) == 7:
            c = C[ix[-1]]; cnt += 1
            ema = c if ema is None else ema + k * (c - ema)
    return out

def events(name, days, O, H, Lo, C, E, R, ma200):
    n = len(C); ev = {"S1 four red weeks": [], "S2 touch 50w EMA": [], "S3 break below 50w EMA": [], "S4 hidden bull divergence": []}
    W = weekly(days, O, C); run = 0
    for w, a, b in W:
        red = C[b] < O[a]; run = run + 1 if red else 0
        if run == 4: ev["S1 four red weeks"].append(b)       # decided at the Sunday close
    above = 0; armed2 = armed3 = False
    for i in range(n):
        e = E[i]
        if e is None: continue
        if C[i] > 1.02 * e: above += 1
        else:
            if above >= 10 and C[i] <= 1.02 * e: ev["S2 touch 50w EMA"].append(i)
            if above >= 10 and C[i] < e: ev["S3 break below 50w EMA"].append(i)
            if C[i] <= 1.02 * e: above = 0 if C[i] < e or above >= 10 else above
    # S3 needs closes above (not only >2% above): recompute simply
    ev["S3 break below 50w EMA"] = []; ab = 0
    for i in range(n):
        e = E[i]
        if e is None: continue
        if C[i] > e: ab += 1
        else:
            if ab >= 10: ev["S3 break below 50w EMA"].append(i)
            ab = 0
    k = 5; sl = [i for i in range(k, n - k) if Lo[i] == min(Lo[i - k:i + k + 1])]
    for a, b in zip(sl, sl[1:]):
        if R[a] is not None and R[b] is not None and Lo[b] > Lo[a] and R[b] < R[a] and b - a >= 10: ev["S4 hidden bull divergence"].append(b + k)
    for key in ev:
        keep = []; last = -999
        for i in sorted(set(ev[key])):
            if i - last >= 14: keep.append(i); last = i
        ev[key] = [i for i in keep if i < n]
    return ev

def fwd(C, Lo, i, h):
    n = len(C)
    if i + h >= n: return None
    return C[i + h] / C[i] - 1 - COST
def worst30(C, Lo, i):
    n = len(C)
    if i + 30 >= n: return None
    return min(Lo[i + 1:i + 31]) / C[i] - 1

def stats(idx, C, Lo, h, split):
    r = [fwd(C, Lo, i, h) for i in idx]; r = [x for x in r if x is not None]
    return r

def main(daily=None):
    daily = daily or {s: B.hist_crypto(s, "1d", 2700) for s in ("BTC", "ETH")}
    L = ["LAB 35: CHART-ANALYST CLAIMS, tested", ""]
    random.seed(35)
    for sym in ("BTC", "ETH"):
        rows = daily[sym]; days = [int(r[0] // 86400) for r in rows]; O = [r[1] for r in rows]; Hh = [r[2] for r in rows]; Lo = [r[3] for r in rows]; C = [r[4] for r in rows]
        n = len(C); E = ema50w(days, C); R = rsi(C); ma200 = sma(C, 200); split = n // 2
        ev = events(sym, days, O, Hh, Lo, C, E, R, ma200)
        L += [f"===== {sym}  data {fd(days[0])} to {fd(days[-1])} ({n} days); first signals possible after 50 weeks of data =====", ""]
        valid = [i for i in range(n) if E[i] is not None]
        allr = {h: [x for x in (fwd(C, Lo, i, h) for i in valid) if x is not None] for h in HZ}
        L.append(f"{'':<30}" + "".join(f"{'avg ' + str(h) + 'd':>9}{'win%':>6}" for h in HZ) + f"{'worst30d':>10}")
        L.append(f"{'ALL DAYS (reference)':<30}" + "".join(f"{S.mean(allr[h]) * 100:>8.1f}%{100 * sum(x > 0 for x in allr[h]) / len(allr[h]):>6.0f}" for h in HZ) + f"{S.mean([w for w in (worst30(C, Lo, i) for i in valid) if w is not None]) * 100:>9.1f}%")
        L.append("")
        for key, idx in ev.items():
            idx = [i for i in idx if E[i] is not None]
            L.append(f"{key}: {len(idx)} events" + (": " + ", ".join(fd(days[i]) for i in idx[-8:]) if idx else ""))
            if not idx: L.append(""); continue
            line = f"{'  all events':<30}"; pct = []
            for h in HZ:
                r = [x for x in (fwd(C, Lo, i, h) for i in idx) if x is not None]
                if len(r) < 2: line += f"{'n/a':>9}{'':>6}"; pct.append("n/a"); continue
                pool = [i for i in valid if fwd(C, Lo, i, h) is not None]
                m = S.mean(r); draws = [S.mean([fwd(C, Lo, j, h) for j in random.sample(pool, len(r))]) for _ in range(2000)]
                pct.append(f"{h}d:{100 * sum(d < m for d in draws) / len(draws):.0f}")
                line += f"{m * 100:>8.1f}%{100 * sum(x > 0 for x in r) / len(r):>6.0f}"
            w = [x for x in (worst30(C, Lo, i) for i in idx) if x is not None]
            line += f"{(S.mean(w) * 100 if w else float('nan')):>9.1f}%"
            L.append(line); L.append(f"{'  percentile vs random days':<30}" + "  ".join(pct) + "   (95+ unusually good, ~50 nothing, 5- unusually bad)")
            for nm, sel in (("above 200d", [i for i in idx if ma200[i] is not None and C[i] > ma200[i]]), ("below 200d", [i for i in idx if ma200[i] is not None and C[i] <= ma200[i]]), ("first half", [i for i in idx if i < split]), ("second half", [i for i in idx if i >= split])):
                ln = f"{'  ' + nm + ' (' + str(len(sel)) + ')':<30}"
                for h in HZ:
                    r = [x for x in (fwd(C, Lo, i, h) for i in sel) if x is not None]
                    ln += f"{(S.mean(r) * 100 if r else float('nan')):>8.1f}%{(100 * sum(x > 0 for x in r) / len(r) if r else float('nan')):>6.0f}"
                w = [x for x in (worst30(C, Lo, i) for i in sel) if x is not None]
                ln += f"{(S.mean(w) * 100 if w else float('nan')):>9.1f}%"; L.append(ln)
            L.append("")
    L += ["Read: a claim is supported only if (1) the percentile vs random days is high (90+) at several horizons, (2) it holds in BOTH halves and in BOTH coins, (3) it is not just 'above 200d' doing the work (compare above/below rows), and (4) the worst 30-day dip is tolerable. S3 is judged mainly by that last number: it is the cost of adding on a break. Few events, hindsight, ~3 market phases, avg returns include cost 0.2%."]
    text = "\n".join(L); open(os.path.join(OUT, "lab35_summary.txt"), "w").write(text + "\n"); print(text)

if __name__ == "__main__":
    main()
