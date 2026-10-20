#!/usr/bin/env python3
"""Lab 32: COST-BASIS CROSSOVER PROXY (the 'Realized Price by Age' idea, rebuilt from price and volume only).
Real Realized Price by Age is on-chain data (Glassnode) and is NOT available here. Proxy: PINK = volume-weighted average price (VWAP) of BTC over the window 180 to 90 days ago (about the price paid by coins that last moved 3-6 months ago);
BLUE = VWAP over 730 to 365 days ago (coins last moved 1-2 years ago). Daily close x daily volume; exchange volume stands in for on-chain movement, so the lines will differ from Glassnode's, but the crossover logic is the same.
Data: Bitstamp daily BTC/USD from 2011 (fallback Yahoo BTC-USD from 2014, then the scanner's Binance.US/OKX source from 2019). Everything uses only past data at each day.
Questions: (1) list EVERY pink-below-blue crossover, not only the ones in the post, with the drawdown at the time and how much further BTC fell afterwards; (2) how far from each major bear-market bottom they land (before or after); (3) forward 90/180/365-day returns after a crossover and while the state 'pink below blue' holds, against all days and against a random-timing null (circular shifts of the same state);
(4) today's reading. Writes lab32_summary.txt and lab32_events.csv. Past prices only; BTC only; few bear markets, so every statistic is a handful of events."""
import os, csv, json, time, random, calendar, statistics as S
import scanner, backtest as B

OUT = scanner.HERE; fd = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))

def bitstamp():
    out = {}; start = calendar.timegm((2011, 9, 13, 0, 0, 0))
    while start < time.time():
        j = json.loads(scanner.http(f"https://www.bitstamp.net/api/v2/ohlc/btcusd/?step=86400&limit=1000&start={start}"))["data"]["ohlc"]
        if not j: break
        for r in j: out[int(r["timestamp"]) // 86400] = (float(r["close"]), float(r["volume"]))
        nxt = int(j[-1]["timestamp"]) + 86400
        if len(j) < 1000 or nxt <= start: break
        start = nxt
    return out

def yahoo():
    j = json.loads(scanner.http(scanner.YAHOO.format("BTC-USD", "1d", "max"), headers=scanner.UA))["chart"]["result"][0]
    q = j["indicators"]["quote"][0]; out = {}
    for t, c, v in zip(j["timestamp"], q["close"], q["volume"]):
        if c: out[int(t) // 86400] = (float(c), float(v or 0))
    return out

def load():
    for nm, fn in (("Bitstamp", bitstamp), ("Yahoo BTC-USD", yahoo)):
        try:
            d = fn()
            if len(d) > 1500: return d, nm
        except Exception as e: print(nm, "failed:", str(e)[:80])
    rows = B.hist_crypto("BTC", "1d", 2700)
    return {int(r[0] // 86400): (r[4], r[5]) for r in rows}, "scanner source (Binance.US/OKX)"

def main(data=None, src="test"):
    if data is None: data, src = load()
    ds = sorted(data); d0, d1 = ds[0], ds[-1]; days = list(range(d0, d1 + 1)); n = len(days)
    C = [None] * n; V = [0.0] * n
    for d, (c, v) in data.items(): C[d - d0] = c; V[d - d0] = v
    for i in range(n):
        if C[i] is None: C[i] = C[i - 1] if i else None
    cpv = [0.0] * (n + 1); cv = [0.0] * (n + 1)
    for i in range(n): cpv[i + 1] = cpv[i] + C[i] * V[i]; cv[i + 1] = cv[i] + V[i]
    def vwap(i, a, b):                       # window [i-b, i-a]
        lo, hi = i - b, i - a
        if lo < 0: return None
        v = cv[hi + 1] - cv[lo]
        return (cpv[hi + 1] - cpv[lo]) / v if v > 0 else None
    pink = [vwap(i, 90, 180) for i in range(n)]; blue = [vwap(i, 365, 730) for i in range(n)]
    ok = [i for i in range(n) if pink[i] and blue[i]]
    first = ok[0]
    ath = [0] * n; m = 0
    for i in range(n):
        if C[i] >= C[m]: m = i
        ath[i] = m
    def fwd(i, h): return C[i + h] / C[i] - 1 if i + h < n else None
    def fmin(i, h=365):
        w = C[i + 1:i + 1 + h]; return min(w) / C[i] - 1 if w else None
    # bear markets: ATH peak -> trough before next ATH, drop >= 40%, >= 120 days
    peaks = [i for i in range(n) if ath[i] == i]; bears = []
    for k, p in enumerate(peaks):
        nxt = peaks[k + 1] if k + 1 < len(peaks) else n
        # collapse consecutive peaks: only use peaks that are followed by a real decline
        seg = C[p:nxt]; t = min(range(len(seg)), key=lambda x: seg[x]) + p
        if C[t] / C[p] - 1 <= -0.40 and t - p >= 60 and (not bears or p > bears[-1][1]): bears.append((p, t, nxt >= n))
    L = [f"LAB 32: COST-BASIS CROSSOVER PROXY  data: {src}, {fd(d0)} to {fd(d1)} ({n} days)  lines usable from {fd(days[first])}", "",
         "PINK = VWAP of days 180-90 ago; BLUE = VWAP of days 730-365 ago (proxy for Glassnode's Realized Price by Age 3m-6m and 1y-2y). Crossover = PINK falls below BLUE.", ""]
    # ---- crossovers
    cd = [i for i in ok if i > first and pink[i - 1] >= blue[i - 1] and pink[i] < blue[i]]
    cu = [i for i in ok if i > first and pink[i - 1] < blue[i - 1] and pink[i] >= blue[i]]
    ev = []
    L += [f"== 1. EVERY pink-below-blue crossover ({len(cd)} raw crossovers, {len(cu)} back-up crossovers) ==",
          f"{'date':<12}{'price':>10}{'from ATH':>10}{'days since ATH':>16}{'further low in next 365d':>26}{'ret 90d':>9}{'ret 180d':>10}{'ret 365d':>10}  context"]
    for i in cd:
        dd = C[i] / C[ath[i]] - 1; fm = fmin(i); ctx = ""
        for p, t, openb in bears:
            if p <= i <= t + 400 and dd <= -0.2: ctx = f"in bear {fd(days[p] if False else d0 + p)} -> {fd(d0 + t)}{' (not over)' if openb else ''}; {('%d d before' % (t - i)) if t >= i else ('%d d after' % (i - t))} the low"
        pc = lambda x: "n/a" if x is None else f"{x * 100:+.0f}%"
        L.append(f"{fd(d0 + i):<12}{C[i]:>10,.0f}{dd * 100:>9.0f}%{i - ath[i]:>16}{pc(fm):>26}{pc(fwd(i, 90)):>9}{pc(fwd(i, 180)):>10}{pc(fwd(i, 365)):>10}  {ctx}")
        ev.append([fd(d0 + i), round(C[i], 2), round(dd * 100, 1), i - ath[i], None if fm is None else round(fm * 100, 1), ctx])
    L.append("")
    # ---- bear bottoms
    L += ["== 2. Major bear markets (peak to trough, 40%+ fall, 60+ days) and the first crossover inside each ==",
          f"{'peak':<12}{'trough':<12}{'fall':>7}   {'first crossover after peak':<28}{'vs the low':<26}{'price at crossover':>20}{'still to fall':>15}"]
    for p, t, openb in bears:
        cross = [i for i in cd if p <= i <= (n if openb else t + 400)]
        fall = C[t] / C[p] - 1
        if cross:
            i = cross[0]; rel = (f"{t - i} d BEFORE the low" if t >= i else f"{i - t} d AFTER the low")
            L.append(f"{fd(d0 + p):<12}{fd(d0 + t) + ('*' if openb else ''):<12}{fall * 100:>6.0f}%   {fd(d0 + i):<28}{rel:<26}{C[i]:>20,.0f}{(C[t] / C[i] - 1) * 100:>14.0f}%")
        else: L.append(f"{fd(d0 + p):<12}{fd(d0 + t):<12}{fall * 100:>6.0f}%   no crossover in this bear")
    L += ["(* = bear market not over, the low shown is the lowest so far; 'still to fall' is the move from the crossover price to the low, negative = further loss.)", ""]
    # ---- state stats and null
    st = [None] * n
    for i in ok: st[i] = pink[i] < blue[i]
    st2 = [None] * n
    for i in ok: st2[i] = pink[i] < blue[i] and C[i] < min(pink[i], blue[i])
    L += ["== 3. Forward returns while the state holds (all days, overlapping windows) vs all days vs random timing =="]
    L.append(f"{'state':<42}{'days':>6}{'mean 180d':>11}{'median 180d':>13}{'% up 180d':>11}{'mean 365d':>11}{'% up 365d':>11}{'null p (180d)':>15}")
    base = [i for i in ok if fwd(i, 180) is not None]
    def stat(sel, h):
        r = [fwd(i, h) for i in sel if fwd(i, h) is not None]
        return (len(r), sum(r) / len(r) if r else float("nan"), S.median(r) if r else float("nan"), sum(1 for x in r if x > 0) / len(r) * 100 if r else float("nan"))
    rng = random.Random(7)
    def nullp(arr):
        idx = [i for i in ok if fwd(i, 180) is not None]; obs = [i for i in idx if arr[i]]
        if len(obs) < 20: return float("nan")
        m0 = sum(fwd(i, 180) for i in obs) / len(obs); cnt = 0; N = 1500; span = len(ok)
        pos = {i: k for k, i in enumerate(ok)}
        for _ in range(N):
            sh = rng.randrange(365, max(366, span - 365)); sel = [i for i in idx if arr[ok[(pos[i] + sh) % span]]]
            if sel and sum(fwd(i, 180) for i in sel) / len(sel) >= m0: cnt += 1
        return cnt / N
    rows = [("all days", [True] * n), ("pink below blue", st), ("pink below blue AND price below both", st2), ("pink ABOVE blue", [None if x is None else (not x) for x in st])]
    for nm, arr in rows:
        sel = [i for i in ok if arr[i]]; a = stat(sel, 180); b = stat(sel, 365)
        pv = nullp(arr) if nm not in ("all days",) else float("nan")
        L.append(f"{nm:<42}{len(sel):>6}{a[1] * 100:>10.0f}%{a[2] * 100:>12.0f}%{a[3]:>10.0f}%{b[1] * 100:>10.0f}%{b[3]:>10.0f}%{('%.2f' % pv) if pv == pv else '':>15}")
    L += ["(null p = share of 1,500 random circular shifts of the same state series whose average 180-day return was at least as good; small p = the state beat random timing. Overlapping windows, few independent episodes.)", ""]
    # episodes of the state: first day of each run
    L += ["== 4. Each episode of 'pink below blue' (first day), forward returns from that day =="]
    runs = []
    for i in ok:
        if st[i] and (i == first or not st[i - 1]): runs.append(i)
    L.append(f"{'first day':<12}{'price':>10}{'90d':>8}{'180d':>8}{'365d':>8}{'worst dip next 365d':>22}")
    pc = lambda x: "n/a" if x is None else f"{x * 100:+.0f}%"
    for i in runs: L.append(f"{fd(d0 + i):<12}{C[i]:>10,.0f}{pc(fwd(i, 90)):>8}{pc(fwd(i, 180)):>8}{pc(fwd(i, 365)):>8}{pc(fmin(i)):>22}")
    # ---- today
    i = n - 1
    L += ["", "== 5. Latest reading ==", f"{fd(d0 + i)}: BTC {C[i]:,.0f}; PINK {pink[i]:,.0f}; BLUE {blue[i]:,.0f}; pink {'BELOW' if pink[i] < blue[i] else 'ABOVE'} blue; price {'below' if C[i] < min(pink[i], blue[i]) else ('above' if C[i] > max(pink[i], blue[i]) else 'between')} both."]
    last = [j for j in cd if j <= i]
    if last: L.append(f"Latest pink-below-blue crossover in this proxy: {fd(d0 + last[-1])} (BTC {C[last[-1]]:,.0f}).")
    L += ["", "Caveats: a proxy, not Glassnode data; exchange volume is not on-chain movement; the crossover in a smooth VWAP is by construction a slow trend measure; the post picked this pair of cohorts after seeing the bottoms (forking paths); each bear market is one event, so all numbers are a few observations."]
    text = "\n".join(L); open(os.path.join(OUT, "lab32_summary.txt"), "w").write(text + "\n"); print(text)
    with open(os.path.join(OUT, "lab32_events.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "price", "pct_from_ath", "days_since_ath", "further_low_next_365d_pct", "context"]); w.writerows(ev)

if __name__ == "__main__":
    main()
