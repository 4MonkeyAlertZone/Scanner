#!/usr/bin/env python3
"""Lab 44: CAN THE BTC 200/50 GATE BE IMPROVED? FIVE PRE-DECLARED IDEAS, EACH TESTED ALONE.
Base = the live plain gate: IN while BTC's daily close is above its 200-day AND 50-day average. Every idea changes that gate in one way and is judged against it on the same days. Declared BEFORE running (13 Nov 2026), nothing added afterwards:
 C1a  2-close confirmation: a flip (either way) only counts after 2 closes in a row showing the new state.   [targets whipsaws: half of episodes last <= 5 days]
 C1b  2% band: enter only above BOTH averages x1.02; exit only below EITHER average x0.98.                   [same target]
 C2   graded exposure: 100% above both averages, 50% above the 200-day only, 0% below the 200-day.           [softens the on/off switch]
 C3a  fast exit: also OUT while the close is 15% or more below its 60-day high.                              [the gate lags quick crashes]
 C3b  same with 20%.
 C4   rising 200-day: also require the 200-day average to be higher than 30 days ago.                        [filters weak bounces]
 C5   S&P 500 above its own 200-day average as well (carried over weekends).                                 [BTC falls with equities in risk-off]
Data: BTC/USD daily closes from Bitstamp via lab 40's loader; S&P 500 (^GSPC) from Yahoo via lab stocks2b's fetch. Cost 0.1% per unit of exposure traded; a decision at close i-1 earns day i.
WINDOW A: 2012-10-17 to now (same start as lab 42, so the live gate reads Calmar 1.23 there); two halves. WINDOW B: 11 May 2021 to now (lab 43's window), two halves. Price-only ideas can be judged on A, which holds several full cycles; B checks the recent regime.
PASS needs ALL of: Calmar above the live gate in BOTH halves of A and overall in A; Calmar above the live gate in B overall; no more than 20% more switches than the live gate (A); time-shift placebo p <= 0.05 (A, 300 circular shifts). With 7 variants tried, one narrow pass is weak evidence; a pass only earns a SEPARATE paper account, never a change to the live gate or the paper bot. Combinations are NOT tested here.
Not financial advice. Writes lab44_summary.txt."""
import os, time, calendar, random
import scanner
import backtest_lab36 as L36
import backtest_lab40 as L40
import backtest_lab42 as L42

OUT = scanner.HERE; fd = L36.fd; sma = L36.sma; CT = L36.CT
day_of = lambda y, m, d: calendar.timegm((y, m, d, 0, 0, 0)) // 86400

def daily_w(closes, w, cost=CT, delay=0):
    """Daily returns for a fractional exposure series: day i earns the weight decided at close i-1-delay."""
    g = [0.0] * len(closes); prev = 0.0
    for i in range(1, len(closes)):
        j = i - 1 - delay; x = float(w[j]) if j >= 0 else 0.0
        g[i] = x * (closes[i] / closes[i - 1] - 1) - cost * abs(x - prev); prev = x
    return g

def confirm(raw, k):
    st = False; pend = 0; out = []
    for x in raw:
        if x == st: pend = 0
        else:
            pend += 1
            if pend >= k: st = x; pend = 0
        out.append(st)
    return out

def band(c, m200, m50, up=1.02, dn=0.98):
    st = False; out = []
    for i in range(len(c)):
        if m200[i] is None or m50[i] is None: out.append(False); continue
        if st and (c[i] < dn * m200[i] or c[i] < dn * m50[i]): st = False
        elif not st and c[i] > up * m200[i] and c[i] > up * m50[i]: st = True
        out.append(st)
    return out

def spx_flags(days, spx):
    ds = sorted(spx); cl = [spx[d] for d in ds]; m = sma(cl, 200)
    ok = {d: (m[i] is not None and cl[i] > m[i]) for i, d in enumerate(ds)}
    res = []; j = -1
    for d in days:
        while j + 1 < len(ds) and ds[j + 1] <= d: j += 1
        res.append(ok[ds[j]] if j >= 0 and m[j] is not None else False)
    return res

def main(days=None, closes=None, src="synthetic", spx=None):
    if days is None: days, closes, src = L40.load()
    n = len(days); c = closes
    if spx is None:
        try:
            import backtest_stocks2b as B2
            spx = B2.fetch("^GSPC", adj=False)
        except Exception as e:
            print("S&P 500 data unavailable:", str(e)[:100]); spx = None
    m200 = sma(c, 200); m50 = sma(c, 50)
    g0 = [m200[i] is not None and m50[i] is not None and c[i] > m200[i] and c[i] > m50[i] for i in range(n)]
    hi60 = [max(c[max(0, i - 59):i + 1]) for i in range(n)]
    V = {"LIVE 200d & 50d": [1.0 if x else 0.0 for x in g0],
         "C1a 2-close confirmation": [1.0 if x else 0.0 for x in confirm(g0, 2)],
         "C1b 2% band": [1.0 if x else 0.0 for x in band(c, m200, m50)],
         "C2 graded 100/50/0": [(1.0 if (m50[i] is not None and c[i] > m50[i]) else 0.5) if (m200[i] is not None and c[i] > m200[i]) else 0.0 for i in range(n)],
         "C3a out if 15% below 60d high": [1.0 if g0[i] and c[i] >= 0.85 * hi60[i] else 0.0 for i in range(n)],
         "C3b out if 20% below 60d high": [1.0 if g0[i] and c[i] >= 0.80 * hi60[i] else 0.0 for i in range(n)],
         "C4 200d rising (30d)": [1.0 if g0[i] and i >= 30 and m200[i - 30] is not None and m200[i] > m200[i - 30] else 0.0 for i in range(n)]}
    if spx:
        sf = spx_flags(days, spx); V["C5 S&P 500 above its 200d"] = [1.0 if g0[i] and sf[i] else 0.0 for i in range(n)]
    else:
        sf = None
    iA = 400; iB = next(i for i, d in enumerate(days) if d >= day_of(2021, 5, 11))
    W = {"A": (iA, iA + (n - iA) // 2), "B": (iB, iB + (n - iB) // 2)}
    bh = L42.bh(c); rnd = random.Random(44)
    out = [f"LAB 44: FIVE PRE-DECLARED GATE IMPROVEMENTS  BTC source {src}; {fd(days[0])} to {fd(days[-1])} ({n} days); S&P 500 {'loaded (' + str(len(spx)) + ' days)' if spx else 'NOT available (C5 skipped)'}", ""]
    table = {}
    for wn, (s0, half) in W.items():
        shifts = rnd.sample(range(30, n - s0 - 30), 300)
        yrs = (n - s0) / 365.0
        out.append(f"WINDOW {wn}: {fd(days[s0])} to {fd(days[-1])} ({n - s0} days, {yrs:.1f} years); halves split at {fd(days[half])}   cost {CT * 100:.1f}% per unit traded")
        out.append(f"{'variant':<32}{'final x':>9}{'DD%':>6}{'Calmar':>8}{'1st half':>9}{'2nd half':>9}{'delay1':>8}{'sw/yr':>7}{'avg exp%':>9}{'plac p':>8}")
        p = L42.perf(bh, s0, n); h1 = L42.perf(bh, s0, half)[3]; h2 = L42.perf(bh, half, n)[3]
        out.append(f"{'buy & hold BTC':<32}{p[0]:>9.1f}{p[1]:>6.0f}{p[3]:>8.2f}{h1:>9.2f}{h2:>9.2f}")
        for nm, w in V.items():
            r = daily_w(c, w); p = L42.perf(r, s0, n); h1 = L42.perf(r, s0, half)[3]; h2 = L42.perf(r, half, n)[3]
            d1 = L42.perf(daily_w(c, w, delay=1), s0, n)[3]
            sw = sum(w[i] != w[i - 1] for i in range(s0, n)); exp = 100 * sum(w[s0 - 1:n - 1]) / (n - s0)
            better = 0
            for s in shifts:
                ww = w[s0:]; w2 = w[:s0] + ww[s:] + ww[:s]
                better += L42.perf(daily_w(c, w2), s0, n)[3] >= p[3]
            pp = better / len(shifts); table[(wn, nm)] = dict(calmar=p[3], h1=h1, h2=h2, sw=sw, p=pp, dd=p[1], final=p[0])
            out.append(f"{nm:<32}{p[0]:>9.1f}{p[1]:>6.0f}{p[3]:>8.2f}{h1:>9.2f}{h2:>9.2f}{d1:>8.2f}{sw / yrs:>7.1f}{exp:>9.0f}{pp:>8.2f}")
        out.append("")
    L = "LIVE 200d & 50d"; la = table[("A", L)]; lb = table[("B", L)]
    out.append("VERDICT (rule declared in the header):")
    passed = []
    for nm in V:
        if nm == L: continue
        a = table[("A", nm)]; b = table[("B", nm)]
        checks = [("A overall", a["calmar"] > la["calmar"]), ("A 1st half", a["h1"] > la["h1"]), ("A 2nd half", a["h2"] > la["h2"]), ("B overall", b["calmar"] > lb["calmar"]),
                  ("switches <= 120%", a["sw"] <= 1.2 * la["sw"]), ("placebo p<=0.05", a["p"] <= 0.05)]
        ok = all(v for _, v in checks); passed.append(nm) if ok else None
        out.append(f"  {nm:<32}{'PASS' if ok else 'fail'}   " + ("" if ok else "failed: " + ", ".join(k for k, v in checks if not v)))
    out.append(f"Passing: {', '.join(passed) if passed else 'none'}. A pass earns a separate paper account only.")
    i = n - 1
    out += ["", f"NOW (latest daily close in the data: {fd(days[i])}): BTC {c[i]:,.0f}  200-day {m200[i]:,.0f} ({(c[i] / m200[i] - 1) * 100:+.1f}%)  50-day {m50[i]:,.0f} ({(c[i] / m50[i] - 1) * 100:+.1f}%)  60-day high {hi60[i]:,.0f} ({(c[i] / hi60[i] - 1) * 100:+.1f}%)",
            "Exposure now: " + "; ".join(f"{nm.split(' ')[0]} {V[nm][i] * 100:.0f}%" for nm in V)]
    if sf: out.append(f"S&P 500 above its 200-day on the latest day: {'yes' if sf[i] else 'no'}")
    text = "\n".join(out); open(os.path.join(OUT, "lab44_summary.txt"), "w").write(text + "\n"); print(text)

if __name__ == "__main__":
    main()
