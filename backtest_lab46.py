#!/usr/bin/env python3
"""Lab 46: IS THE VOLATILITY-SIZED GATE A REAL EDGE OR A LUCKY SETTING?  (follow-up to lab 45, declared BEFORE running, 16 Nov 2026)
Lab 45 found that sizing the BTC gate by recent volatility looked best (target 50% volatility, update weekly, cap 2x: CAGR 101% vs 91%, worst drawdown -41% vs -73%) but missed the pass bar on a tie, and it was ONE setting. A real effect should hold across neighbouring settings.
Rule under test: when the 200/50 gate is IN, exposure = min(cap, target / BTC's 90-day annualised volatility), recomputed every U days and at each flip; OUT = cash; idle cash earns the T-bill rate; borrowing above 1x costs 8% a year; 0.1% cost per unit traded; a decision at close i-1 earns day i.
GRID (27 variants, all declared here): target volatility 35%, 50%, 65%  x  update every 7, 14, 30 days  x  cap 1.0, 1.5, 2.0.
BASELINE: the live 200/50 gate with T-bill cash (lab 45's Y1). Windows: LONG = 2012-10-17 to now, split into halves; B = 11 May 2021 to now.
A variant BEATS the baseline only if ALL hold: CAGR higher in BOTH halves of LONG and overall in B; Calmar no lower than the baseline minus 0.05 in LONG and in B; worst drawdown no more than 10 points worse than the baseline in LONG and in B.
PLATEAU TEST (the point of this lab): among the 18 variants with cap above 1x, at least 14 (75%) must beat the baseline, AND the same count must still hold under two stresses: costs doubled to 0.2%, and borrowing at 12% a year. If fewer do, the lab-45 result was a lucky setting and the idea is dropped. Cap 1.0 variants cannot borrow, so they are judged as RISK CUTS only: Calmar higher than the baseline in LONG and in B, and worst drawdown smaller in both.
Also shown: the worst single day (leverage makes tail days worse; daily closes cannot show intraday liquidation risk, which is a real extra danger above 1x). A pass earns a separate paper account only; nothing changes the live gate or paper bot. Not financial advice. Writes lab46_summary.txt."""
import os, statistics as S
import scanner
import backtest_lab36 as L36
import backtest_lab40 as L40
import backtest_lab42 as L42
import backtest_lab44 as L44
import backtest_lab45 as L45

OUT = scanner.HERE; fd = L36.fd; sma = L36.sma; CT = L36.CT
TARGETS = (0.35, 0.50, 0.65); UPDS = (7, 14, 30); CAPS = (1.0, 1.5, 2.0)

def evaluate(P, w, rf, fin, cost, wins):
    r = L45.daily_x(P, w, rf, fin, cost); n = len(P); o = {}
    for wn, (s0, half) in wins.items():
        p = L42.perf(r, s0, n); o[wn] = dict(cagr=p[2], calmar=p[3], dd=p[1], c1=L42.perf(r, s0, half)[2], c2=L42.perf(r, half, n)[2])
    o["worst"] = min(r[wins["LONG"][0]:]) * 100
    return o

def beats(v, b):
    return (v["LONG"]["c1"] > b["LONG"]["c1"] and v["LONG"]["c2"] > b["LONG"]["c2"] and v["B"]["cagr"] > b["B"]["cagr"]
            and v["LONG"]["calmar"] >= b["LONG"]["calmar"] - 0.05 and v["B"]["calmar"] >= b["B"]["calmar"] - 0.05
            and v["LONG"]["dd"] >= b["LONG"]["dd"] - 10 and v["B"]["dd"] >= b["B"]["dd"] - 10)

def risk_cut(v, b):
    return v["LONG"]["calmar"] > b["LONG"]["calmar"] and v["B"]["calmar"] > b["B"]["calmar"] and v["LONG"]["dd"] > b["LONG"]["dd"] and v["B"]["dd"] > b["B"]["dd"]

def main(days=None, closes=None, src="synthetic", irx=None):
    if days is None: days, closes, src = L40.load()
    n = len(days); c = closes
    if irx is None:
        try:
            import backtest_stocks2b as B2
            irx = B2.fetch("^IRX", adj=False)
        except Exception as e: print("T-bill data unavailable:", str(e)[:100]); irx = {}
    rf = L45.ffill(days, irx, days) if irx else [0.0] * n
    m200 = sma(c, 200); m50 = sma(c, 50)
    g0 = [m200[i] is not None and m50[i] is not None and c[i] > m200[i] and c[i] > m50[i] for i in range(n)]
    iB = next(i for i, d in enumerate(days) if d >= L44.day_of(2021, 5, 11))
    wins = {"LONG": (400, 400 + (n - 400) // 2), "B": (iB, iB + (n - iB) // 2)}
    stress = {"normal": (CT, 8.0), "costs x2": (2 * CT, 8.0), "borrow 12%": (CT, 12.0)}
    base_w = [1.0 if x else 0.0 for x in g0]
    base = {k: evaluate(c, base_w, rf, [f] * n, co, wins) for k, (co, f) in stress.items()}
    res = {}
    for t in TARGETS:
        for u in UPDS:
            for cap in CAPS:
                w = L45.vol_sized(c, g0, cap, t, 365, u)
                res[(t, u, cap)] = dict(w=w, ev={k: evaluate(c, w, rf, [f] * n, co, wins) for k, (co, f) in stress.items()}, exp=sum(w[wins['LONG'][0] - 1:n - 1]) / (n - wins['LONG'][0]))
    out = [f"LAB 46: ROBUSTNESS OF VOLATILITY-SIZED EXPOSURE  BTC source {src}; {fd(days[0])} to {fd(days[-1])}; T-bill {'latest ' + format(rf[-1], '.2f') + '% a year' if irx else 'NOT available (cash 0%)'}", "",
           f"LONG = {fd(days[wins['LONG'][0]])} to {fd(days[-1])} (halves split at {fd(days[wins['LONG'][1]])}); B = {fd(days[wins['B'][0]])} to {fd(days[-1])}.  'beats' = passes the declared rule against the baseline.",
           f"{'target':>6}{'upd':>5}{'cap':>5} | {'CAGR%':>6}{'Calmar':>7}{'DD%':>5}{'1st':>5}{'2nd':>5} | {'B CAGR%':>8}{'Calmar':>7}{'DD%':>5} | {'worst day%':>10}{'avg exp':>8}{'  beats':>8}{' risk-cut':>9}"]
    b = base["normal"]
    out.append(f"{'BASE':>6}{'-':>5}{'1.0':>5} | {b['LONG']['cagr'] * 100:>6.0f}{b['LONG']['calmar']:>7.2f}{b['LONG']['dd']:>5.0f}{b['LONG']['c1'] * 100:>5.0f}{b['LONG']['c2'] * 100:>5.0f} | {b['B']['cagr'] * 100:>8.0f}{b['B']['calmar']:>7.2f}{b['B']['dd']:>5.0f} | {b['worst']:>10.1f}{sum(base_w) / n:>8.2f}")
    cnt = {k: 0 for k in stress}; tot = 0; rc = 0; rc_tot = 0; deltas = []; by = {"target": {}, "upd": {}, "cap": {}}
    for (t, u, cap), r in res.items():
        v = r["ev"]["normal"]; bt = beats(v, b); rck = risk_cut(v, b)
        out.append(f"{t * 100:>5.0f}%{u:>5}{cap:>5.1f} | {v['LONG']['cagr'] * 100:>6.0f}{v['LONG']['calmar']:>7.2f}{v['LONG']['dd']:>5.0f}{v['LONG']['c1'] * 100:>5.0f}{v['LONG']['c2'] * 100:>5.0f} | {v['B']['cagr'] * 100:>8.0f}{v['B']['calmar']:>7.2f}{v['B']['dd']:>5.0f} | {v['worst']:>10.1f}{r['exp']:>8.2f}{('YES' if bt else 'no'):>8}{('YES' if rck else 'no'):>9}")
        if cap > 1.0:
            tot += 1; deltas.append(v["LONG"]["cagr"] - b["LONG"]["cagr"])
            for k in stress: cnt[k] += beats(r["ev"][k], base[k])
            for dim, key in (("target", t), ("upd", u), ("cap", cap)):
                by[dim].setdefault(key, [0, 0]); by[dim][key][1] += 1; by[dim][key][0] += bt
        else:
            rc_tot += 1; rc += rck
    need = int(0.75 * tot + 0.999)
    out += ["", f"PLATEAU TEST (cap above 1x: {tot} variants; need {need} to beat the baseline in each row below):"]
    for k in stress: out.append(f"  {k:<12}{cnt[k]:>3} of {tot} beat the baseline   {'OK' if cnt[k] >= need else 'FAIL'}")
    out.append(f"  median CAGR change vs baseline over LONG (cap above 1x): {S.median(deltas) * 100:+.0f} points")
    for dim, d in by.items(): out.append(f"  by {dim}: " + "; ".join(f"{(k * 100 if dim == 'target' else k):g}{'%' if dim == 'target' else ''}: {a}/{t_}" for k, (a, t_) in sorted(d.items())))
    out.append(f"RISK-CUT TEST (cap 1.0, {rc_tot} variants): {rc} of {rc_tot} lift Calmar and shrink the worst drawdown in both windows.")
    ok = all(cnt[k] >= need for k in stress)
    out.append("VERDICT: " + ("the volatility-sizing result holds across the grid and both stresses: it earns a separate paper account (not a change to the live gate)." if ok else "the lab-45 result did NOT hold up across settings and stresses: drop the 'more gain' claim." ) + (" The risk-cut (cap 1.0) result is judged on its own line above." ))
    i = n - 1; sd = S.pstdev([c[k] / c[k - 1] - 1 for k in range(i - 89, i + 1)]) * (365 ** 0.5)
    out += ["", f"NOW (latest close in the data: {fd(days[i])}): BTC {c[i]:,.0f}; 90-day volatility {sd * 100:.0f}% a year; gate {'IN' if g0[i] else 'OUT'}; T-bill {rf[i]:.2f}%",
            "   sizing if IN today (cap 2x): " + "; ".join(f"target {t * 100:.0f}% -> {min(2.0, t / sd) * 100:.0f}%" for t in TARGETS)]
    text = "\n".join(out); open(os.path.join(OUT, "lab46_summary.txt"), "w").write(text + "\n"); print(text)

if __name__ == "__main__":
    main()
