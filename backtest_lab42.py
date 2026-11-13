#!/usr/bin/env python3
"""Lab 42: DOES THE 'MIDTERM / POST-PEAK YEAR' STORY HOLD UP, AND ARE WEEKLY-AVERAGE GATES ANY BETTER?
Prompted by a YouTube analyst's thesis (13 Nov 2026): midterm years are bear years, Q4 drops after a September rate hike, weekly averages are the support, lows form below the realized price.
HONEST LIMITS: midterm years (2014, 2018, 2022) are the SAME three years as the post-peak years of the halving cycle, so the two cannot be separated, and 3 observations cannot prove anything. Parts 1-2 are descriptive. Only Part 3 can produce a rule, and it faces a placebo test and a best-of-N warning.
Data: BTC/USD daily closes from Bitstamp (2011+) via lab 40's loader (which reuses lab 32's loaders). Cost 0.1% per switch; a decision at close i-1 earns day i.
 PART 1  SEASONALITY. Return by quarter for every year; Q4 of post-peak years (2014, 2018, 2022) against all other Q4s; where each post-peak Q4 ranks among ALL rolling 92-day returns (overlapping windows, so ranks are rough). 2026 is shown to date and excluded from the stats.
 PART 2  THE LIVE GATE (200-day and 50-day) BY YEAR AND BY QUARTER: buy&hold vs gate, worst drawdown, share of days IN. Post-peak years vs other years.
 PART 3  GATE VARIANTS with the analyst's tools: 20-week SMA (140d), 21-week EMA (147d), 50-week SMA (350d) and a slow x fast grid up to 400 days. Same start day for all, full history and each half, a 1-day execution delay, and a circular time-shift placebo (300 shifts; p = share of shifts with a Calmar at least as good). 14+ variants are tried, so the best one is selected from many: only a variant that beats the live gate in BOTH halves and the placebo deserves a paper test.
 PART 4  REALIZED PRICE (Coin Metrics community data, if reachable): episodes with BTC below realized price, the lowest ratio, and the 365-day return after the first day below. About 4 to 5 episodes: descriptive only.
Nothing here changes the frozen gate paper bot. Not financial advice. Writes lab42_summary.txt."""
import os, json, time, random, statistics as S
import scanner
import backtest_lab36 as L36
import backtest_lab39 as L39
import backtest_lab40 as L40

OUT = scanner.HERE; CT = L36.CT; fd = L36.fd; sma = L36.sma
POST = {2014, 2018, 2022, 2026}          # years after a halving-cycle peak = midterm years
yr = lambda d: time.gmtime(d * 86400).tm_year
mon = lambda d: time.gmtime(d * 86400).tm_mon

def ema(c, n):
    out = [None] * len(c); k = 2.0 / (n + 1)
    if len(c) < n: return out
    e = sum(c[:n]) / n; out[n - 1] = e
    for i in range(n, len(c)): e = c[i] * k + e * (1 - k); out[i] = e
    return out

def gate_from(closes, parts):
    """parts: list of ('sma'|'ema', n); IN when the close is above ALL of them."""
    ms = [(sma(closes, n) if k == "sma" else ema(closes, n)) for k, n in parts]
    return [all(m[i] is not None and closes[i] > m[i] for m in ms) for i in range(len(closes))]

def daily(closes, gate, cost=CT, delay=0):
    """Gated daily return series: day i earns the gate decided at close i-1-delay."""
    g = [0.0] * len(closes); prev = 0.0
    for i in range(1, len(closes)):
        j = i - 1 - delay; w = 1.0 if j >= 0 and gate[j] else 0.0
        g[i] = w * (closes[i] / closes[i - 1] - 1) - cost * abs(w - prev); prev = w
    return g

def perf(r, a, b):
    """Compound daily returns r[a:b]; returns (final multiple, worst drawdown %, cagr, calmar)."""
    eq = 1.0; pk = 1.0; dd = 0.0
    for x in r[a:b]:
        eq *= 1 + x; pk = max(pk, eq); dd = min(dd, eq / pk - 1)
    yrs = max(1, b - a) / 365.0; cagr = eq ** (1 / yrs) - 1 if eq > 0 else -1.0
    return eq, dd * 100, cagr, (cagr * 100 / abs(dd * 100)) if dd < 0 else float("inf")

def bh(closes): return [0.0] + [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]

def realized(days):
    """Realized price = realized cap / supply from the Coin Metrics community API; {day: price} or None."""
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=CapRealUSD,SplyCur&frequency=1d&start_time=2011-01-01&page_size=10000"
    out = {}
    try:
        for _ in range(6):
            j = json.loads(scanner.http(url))
            for r in j.get("data", []):
                try: out[int(time.mktime(time.strptime(r["time"][:10], "%Y-%m-%d")) // 86400) + 0] = float(r["CapRealUSD"]) / float(r["SplyCur"])
                except Exception: pass
            url = j.get("next_page_url")
            if not url: break
    except Exception as e:
        print("realized price unavailable:", str(e)[:100]); return None
    return out or None

def main(days=None, closes=None, src="synthetic", rp=False):
    if days is None: days, closes, src = L40.load()
    n = len(days); yrs = [yr(d) for d in days]; mns = [mon(d) for d in days]
    last_year = yrs[-1]
    out = [f"LAB 42: MIDTERM / POST-PEAK YEAR AND WEEKLY-GATE TEST  source {src}; {fd(days[0])} to {fd(days[-1])} ({n} days)", ""]
    # ---------- PART 1
    def span(y, m0, m1):   # index range [a, b) of days in year y with month in [m0, m1]
        idx = [i for i in range(n) if yrs[i] == y and m0 <= mns[i] <= m1]
        return (idx[0], idx[-1] + 1) if idx else None
    def ret(sp): return closes[sp[1] - 1] / closes[max(0, sp[0] - 1)] - 1 if sp else None
    out.append("PART 1: BTC RETURN BY QUARTER (%), close to close; * = post-peak (midterm) year; 2026 is to date")
    out.append(f"{'year':<7}{'Q1':>8}{'Q2':>8}{'Q3':>8}{'Q4':>8}{'year':>9}{'Oct':>8}{'Nov':>8}{'Dec':>8}")
    q4 = {}; mret = {m: {True: [], False: []} for m in range(1, 13)}
    for y in sorted(set(yrs)):
        row = [ret(span(y, a, b)) for a, b in ((1, 3), (4, 6), (7, 9), (10, 12))]
        full = ret((span(y, 1, 12)))
        mo = [ret(span(y, m, m)) for m in (10, 11, 12)]
        f = lambda v: f"{v * 100:>8.0f}" if v is not None else f"{'-':>8}"
        out.append(f"{str(y) + ('*' if y in POST else ''):<7}" + "".join(f(v) for v in row) + f"{full * 100:>9.0f}" + "".join(f(v) for v in mo))
        if row[3] is not None and y != last_year: q4[y] = row[3]
        if y != last_year:
            for m in range(1, 13):
                v = ret(span(y, m, m))
                if v is not None: mret[m][y in POST].append(v)
    out.append("")
    for lab, ks in (("Q4 of post-peak years (complete)", [y for y in q4 if y in POST]), ("Q4 of all other years", [y for y in q4 if y not in POST])):
        v = [q4[y] * 100 for y in ks]
        out.append(f"{lab}: n={len(v)}  mean {S.mean(v):.0f}%  median {S.median(v):.0f}%  worst {min(v):.0f}%  best {max(v):.0f}%" if v else lab + ": none")
    roll = sorted(closes[i] / closes[i - 92] - 1 for i in range(92, n))
    for y in sorted(q4):
        if y in POST:
            r = q4[y]; pct = 100 * sum(x <= r for x in roll) / len(roll)
            out.append(f"  Q4 {y}: {r * 100:.0f}% = {pct:.0f}th percentile of all rolling 92-day returns (overlapping windows)")
    if span(last_year, 10, 12): out.append(f"  Q4 {last_year} to date: {ret(span(last_year, 10, 12)) * 100:.0f}%")
    out.append("Midterm years are the same years as the post-peak years of the halving cycle, so this cannot separate the two and n is 3. Descriptive only.")
    # ---------- PART 2
    gate = L39.gate_series(closes, 200, 50); g = daily(closes, gate); b = bh(closes)
    first = next(i for i in range(n) if i >= 200)
    out += ["", f"PART 2: LIVE GATE (200d and 50d) BY YEAR, from {fd(days[first])}  (B&H = buy and hold)", f"{'year':<7}{'B&H %':>8}{'gate %':>8}{'B&H DD%':>9}{'gate DD%':>10}{'IN days%':>10}"]
    agg = {True: [], False: []}
    for y in sorted(set(yrs)):
        a, e = max(first, next(i for i in range(n) if yrs[i] == y)), max(i for i in range(n) if yrs[i] == y) + 1
        if e - a < 200 or y == last_year and False: continue
        pb = perf(b, a, e); pg = perf(g, a, e); inn = 100 * sum(gate[a - 1:e - 1]) / (e - a)
        out.append(f"{str(y) + ('*' if y in POST else ''):<7}{(pb[0] - 1) * 100:>8.0f}{(pg[0] - 1) * 100:>8.0f}{pb[1]:>9.0f}{pg[1]:>10.0f}{inn:>10.0f}")
        if y != last_year: agg[y in POST].append((pb[0] - 1, pg[0] - 1, pb[1], pg[1]))
    for k, nm in ((True, "post-peak years"), (False, "other years")):
        v = agg[k]
        if v: out.append(f"{nm}: n={len(v)}  avg B&H {100 * S.mean(x[0] for x in v):.0f}%  avg gate {100 * S.mean(x[1] for x in v):.0f}%  avg B&H DD {S.mean(x[2] for x in v):.0f}%  avg gate DD {S.mean(x[3] for x in v):.0f}%")
    out.append("Q4 only (gate vs buy&hold, %):")
    for y in sorted(set(yrs)):
        sp = span(y, 10, 12)
        if not sp or sp[0] < first or sp[1] - sp[0] < 80: continue
        out.append(f"  Q4 {y}{'*' if y in POST else ' '}: B&H {(perf(b, *sp)[0] - 1) * 100:>6.0f}   gate {(perf(g, *sp)[0] - 1) * 100:>6.0f}")
    # ---------- PART 3
    i0 = 400; half = i0 + (n - i0) // 2
    V = {"LIVE 200d & 50d": [("sma", 200), ("sma", 50)], "20-week SMA (140d)": [("sma", 140)], "21-week EMA (147d)": [("ema", 147)],
         "50-week SMA (350d)": [("sma", 350)], "21w EMA & 50w SMA": [("ema", 147), ("sma", 350)], "200d only": [("sma", 200)]}
    for s in (100, 150, 250, 300, 400):
        for f_ in (0, 50):
            nm = f"{s}d & 50d" if f_ else f"{s}d only"
            if nm not in V: V[nm] = [("sma", s)] + ([("sma", 50)] if f_ else [])
    rnd = random.Random(42); shifts = rnd.sample(range(90, n - 90), 300)
    out += ["", f"PART 3: GATE VARIANTS, same start {fd(days[i0])} for all ({n - i0} days); halves split at {fd(days[half])}",
            f"{'variant':<22}{'final x':>8}{'DD%':>6}{'Calmar':>8}{'1st half':>9}{'2nd half':>9}{'delay1':>8}{'switch':>7}{'placebo p':>10}"]
    bp = perf(b, i0, n); bh1 = perf(b, i0, half)[3]; bh2 = perf(b, half, n)[3]
    out.append(f"{'buy & hold BTC':<22}{bp[0]:>8.1f}{bp[1]:>6.0f}{bp[3]:>8.2f}{bh1:>9.2f}{bh2:>9.2f}")
    res = {}
    for nm, parts in V.items():
        gt = gate_from(closes, parts); r = daily(closes, gt); p = perf(r, i0, n)
        h1 = perf(r, i0, half)[3]; h2 = perf(r, half, n)[3]; d1 = perf(daily(closes, gt, delay=1), i0, n)[3]
        sw = sum(gt[i] != gt[i - 1] for i in range(i0, n))
        better = sum(perf(daily(closes, gt[s:] + gt[:s]), i0, n)[3] >= p[3] for s in shifts)
        res[nm] = (p[3], h1, h2)
        out.append(f"{nm:<22}{p[0]:>8.1f}{p[1]:>6.0f}{p[3]:>8.2f}{h1:>9.2f}{h2:>9.2f}{d1:>8.2f}{sw:>7}{better / len(shifts):>10.2f}")
    live = res["LIVE 200d & 50d"]
    win = [k for k, v in res.items() if k != "LIVE 200d & 50d" and v[1] > live[1] and v[2] > live[2] and v[0] > live[0]]
    out.append(f"Variants beating the live gate on Calmar in BOTH halves AND overall: {', '.join(win) if win else 'none'}.")
    out.append("Calmar = annual return / worst drawdown; placebo p = share of 300 circular time-shifts of the same gate with a Calmar at least as good (small = unlikely luck). Best-of-" + str(len(V)) + " selection: treat a lone winner with suspicion.")
    # ---------- PART 4
    out += ["", "PART 4: REALIZED PRICE"]
    rpd = realized(days) if rp else None
    if rpd:
        idx = {d: i for i, d in enumerate(days)}; ratio = {d: closes[idx[d]] / rpd[d] for d in rpd if d in idx}
        ds = sorted(ratio); eps = []; cur = None
        for d in ds:
            if ratio[d] < 1:
                cur = cur or [d, d, ratio[d]]; cur[1] = d; cur[2] = min(cur[2], ratio[d])
            elif cur: eps.append(cur); cur = None
        if cur: eps.append(cur)
        out.append(f"Realized price data to {fd(ds[-1])}; latest BTC / realized = {ratio[ds[-1]]:.2f}")
        out.append(f"{'first day below':<17}{'last day':<12}{'days':>6}{'lowest ratio':>14}{'365d later %':>14}")
        for a_, b_, lo in eps:
            if b_ - a_ < 5: continue
            fwd = closes[idx[a_] + 365] / closes[idx[a_]] - 1 if idx[a_] + 365 < n else None
            out.append(f"{fd(a_):<17}{fd(b_):<12}{b_ - a_ + 1:>6}{lo:>14.2f}{(f'{fwd * 100:.0f}' if fwd is not None else 'n/a'):>14}")
        out.append("About 4 to 5 episodes that overlap the big bear markets: descriptive, not a statistical test.")
    else:
        out.append("Realized-price data was not reachable from here, so this part is skipped.")
    text = "\n".join(out); open(os.path.join(OUT, "lab42_summary.txt"), "w").write(text + "\n"); print(text)

if __name__ == "__main__":
    main(rp=True)
