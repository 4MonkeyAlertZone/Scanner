#!/usr/bin/env python3
"""Lab 43: THE LIVE REGIME ALERT'S OPEN-INTEREST (OI) FILTER, TESTED LIKE-FOR-LIKE AGAINST THE PLAIN GATE.
The live regime alert is IN only when BTC closes above its 200-day AND 50-day average AND there has been no OI warning C in the last 14 days (C = BTC futures OI at a new 180-day high AND up 15%+ in 30 days). That OI part was chosen after seeing the data and was never given its own number. This lab gives it one, using the SAME code as the live alert (basket_paper.warnings, 14-day cool-off) on the SAME price history as lab 42.
Data: BTC/USD daily closes from Bitstamp (via lab 40's loader); BTC futures open interest from btc_metrics_daily.csv (Binance public futures files, from 2021-01-01, written by lab 26) plus basketgate_oi.csv (the live cache); the two files agree on every overlapping day. Binance US is not used for OI.
Window: starts 130 days after the first OI day, because the 180-day-high test needs history. That is about 5.5 years: three market phases, ONE bear market. Cost 0.1% per switch; a decision at close i-1 earns day i.
 PART 1  RULES side by side over the window: final x, CAGR, worst drawdown, Calmar, share of days IN, switches, 1-day-delay Calmar, each half, circular time-shift placebo (300 shifts inside the window), and the multiple in each market phase (to the 2021 peak, the 2022 bear, the 2022-25 rally, since the 2025 top).
 PART 2  THE OI WARNINGS THEMSELVES: every warning episode with the BTC move over the next 14 and 30 days and the worst dip within 30 days, against the same numbers for ALL days.
 NOW  current state from the latest data in the file (nothing typed from memory).
CAUTION: few warning episodes and one bear market, so a difference between the rules is anecdote, not proof. The OI rule was fitted to this same data. Nothing here changes the frozen gate paper bot or the live alert. Not financial advice. Writes lab43_summary.txt."""
import os, csv, calendar, random, statistics as S
import scanner
import backtest_lab36 as L36
import backtest_lab40 as L40
import backtest_lab42 as L42
import basket_paper as BP

OUT = scanner.HERE; fd = L36.fd; COOL = 14
PHASES = [("to 2021 peak", None, (2021, 11, 10)), ("2022 bear", (2021, 11, 10), (2022, 11, 21)), ("2022-25 rally", (2022, 11, 21), (2025, 10, 6)), ("since 2025 top", (2025, 10, 6), None)]
day_of = lambda y, m, d: calendar.timegm((y, m, d, 0, 0, 0)) // 86400

def load_oi():
    oi = {}
    for fn, key, col in (("btc_metrics_daily.csv", "date", "open_interest_btc"), ("basketgate_oi.csv", "day", "oi")):
        p = os.path.join(OUT, fn)
        if not os.path.exists(p): continue
        for r in csv.DictReader(open(p)):
            try:
                v = float(r[col]); d = int(r[key]) if key == "day" else day_of(*map(int, r["date"].split("-")))
            except Exception: continue
            if v > 0: oi[d] = v
    return oi

def main(days=None, closes=None, src="synthetic", oi=None):
    if days is None: days, closes, src = L40.load()
    if oi is None: oi = load_oi()
    assert oi, "no open-interest data found"
    n = len(days); idx = {d: i for i, d in enumerate(days)}
    a, b = BP.warnings(days, oi); cw = [x and y for x, y in zip(a, b)]
    cool = [any(cw[max(0, i - COOL + 1):i + 1]) for i in range(n)]
    first_oi = min(oi); s0 = next(i for i, d in enumerate(days) if d >= first_oi + 130)
    nm_ = lambda k: fd(days[k])
    out = [f"LAB 43: OPEN-INTEREST FILTER VS PLAIN GATE  price source {src}; {nm_(0)} to {nm_(n - 1)}; OI {fd(first_oi)} to {fd(max(oi))} ({len(oi)} days); window {nm_(s0)} to {nm_(n - 1)} ({n - s0} days)", ""]
    g200 = L42.gate_from(closes, [("sma", 200)]); g50 = L42.gate_from(closes, [("sma", 50)])
    ema147 = L42.gate_from(closes, [("ema", 147)])
    R = {"buy & hold BTC": None,
         "200d only": g200,
         "200d & 50d (paper bot)": [x and y for x, y in zip(g200, g50)],
         "200d + OI (majors report)": [x and not c for x, c in zip(g200, cool)],
         "200d & 50d + OI (LIVE ALERT)": [x and y and not c for x, y, c in zip(g200, g50, cool)],
         "21-week EMA only": ema147,
         "21-week EMA + OI": [x and not c for x, c in zip(ema147, cool)],
         "buy & hold except OI cool-off": [not c for c in cool]}
    half = s0 + (n - s0) // 2; rnd = random.Random(43); L = n - s0
    shifts = rnd.sample(range(30, L - 30), 300)
    bh = L42.bh(closes)
    def phase_mult(r, d0, d1):
        a_ = s0 if d0 is None else idx[day_of(*d0)]; b_ = n - 1 if d1 is None else idx[day_of(*d1)]
        a_ = max(a_, s0)
        eq = 1.0
        for x in r[a_ + 1:b_ + 1]: eq *= 1 + x
        return eq
    out.append(f"PART 1: RULES OVER {nm_(s0)} TO {nm_(n - 1)}  (cost {L36.CT * 100:.1f}% per switch)")
    out.append(f"{'rule':<32}{'final x':>8}{'CAGR%':>7}{'DD%':>6}{'Calmar':>8}{'1st half':>9}{'2nd half':>9}{'delay1':>8}{'IN%':>5}{'sw':>5}{'plac p':>8}")
    res = {}; pm = {}
    for nm, g in R.items():
        r = bh if g is None else L42.daily(closes, g)
        p = L42.perf(r, s0, n); h1 = L42.perf(r, s0, half)[3]; h2 = L42.perf(r, half, n)[3]
        d1 = p[3] if g is None else L42.perf(L42.daily(closes, g, delay=1), s0, n)[3]
        if g is None: inn, sw, pp = 100.0, 0, None
        else:
            inn = 100 * sum(g[s0 - 1:n - 1]) / (n - s0); sw = sum(g[i] != g[i - 1] for i in range(s0, n))
            better = 0
            for s in shifts:
                gw = g[s0:]; g2 = g[:s0] + gw[s:] + gw[:s]
                better += L42.perf(L42.daily(closes, g2), s0, n)[3] >= p[3]
            pp = better / len(shifts)
        res[nm] = (p[3], h1, h2); pm[nm] = [phase_mult(r, x, y) for _, x, y in PHASES]
        out.append(f"{nm:<32}{p[0]:>8.2f}{p[2] * 100:>7.0f}{p[1]:>6.0f}{p[3]:>8.2f}{h1:>9.2f}{h2:>9.2f}{d1:>8.2f}{inn:>5.0f}{sw:>5}{(f'{pp:.2f}' if pp is not None else '-'):>8}")
    out += ["", "Multiple in each market phase (x; 1.00 = flat):", f"{'rule':<32}" + "".join(f"{lab:>16}" for lab, _, _ in PHASES)]
    for nm in R: out.append(f"{nm:<32}" + "".join(f"{v:>16.2f}" for v in pm[nm]))
    plain = res["200d & 50d (paper bot)"]; live = res["200d & 50d + OI (LIVE ALERT)"]
    out.append("")
    out.append(f"Live alert vs plain 200d & 50d: Calmar {live[0]:.2f} vs {plain[0]:.2f}; first half {live[1]:.2f} vs {plain[1]:.2f}; second half {live[2]:.2f} vs {plain[2]:.2f}. "
               + ("The OI filter helps in both halves and overall." if all(x > y for x, y in zip(live, plain)) else "The OI filter does NOT beat the plain gate in both halves and overall."))
    # ---------- PART 2
    eps = []; k = None
    for i in range(s0, n):
        if cw[i]:
            if k and i - k[1] <= COOL: k[1] = i
            else: k = [i, i]; eps.append(k)
    def fwd(i, h): return closes[i + h] / closes[i] - 1 if i + h < n else None
    def dip(i, h=30): return min(closes[j] / closes[i] - 1 for j in range(i + 1, min(n, i + h + 1))) if i + 1 < n else None
    out += ["", f"PART 2: OI WARNING EPISODES (warning days {sum(cw[s0:])}; episodes {len(eps)}; episodes start on the first warning day)", f"{'first day':<12}{'last day':<12}{'BTC':>9}{'next 14d %':>12}{'next 30d %':>12}{'worst dip 30d %':>17}"]
    rows = []
    for a_, b_ in eps:
        f14, f30, dp = fwd(a_, 14), fwd(a_, 30), dip(a_)
        rows.append((f14, f30, dp))
        fm = lambda v: f"{v * 100:>12.0f}" if v is not None else f"{'n/a':>12}"
        out.append(f"{nm_(a_):<12}{nm_(b_):<12}{closes[a_]:>9,.0f}{fm(f14)}{fm(f30)}{(f'{dp * 100:>17.0f}' if dp is not None else f"{'n/a':>17}")}")
    allf = [fwd(i, 30) for i in range(s0, n - 30)]; alld = [dip(i) for i in range(s0, n - 30)]
    ef = [r[1] for r in rows if r[1] is not None]; ed = [r[2] for r in rows if r[2] is not None]
    out.append(f"All days: next-30d median {S.median(allf) * 100:.0f}%, mean {S.mean(allf) * 100:.0f}%; share with a 10%+ dip inside 30 days {100 * sum(x <= -0.10 for x in alld) / len(alld):.0f}%.")
    if ef: out.append(f"Warning-episode starts (n={len(ef)}): next-30d median {S.median(ef) * 100:.0f}%, mean {S.mean(ef) * 100:.0f}%; share with a 10%+ dip inside 30 days {100 * sum(x <= -0.10 for x in ed) / len(ed):.0f}%.")
    out.append("A handful of episodes in one bear market: read as anecdote, and overlapping windows are not independent.")
    # ---------- NOW
    i = n - 1; ma = lambda k_: sum(closes[-k_:]) / k_
    lastw = max((j for j in range(n) if cw[j]), default=None)
    out += ["", f"NOW (latest daily close in the data: {nm_(i)}): BTC {closes[i]:,.0f}   200-day {ma(200):,.0f} ({(closes[i] / ma(200) - 1) * 100:+.1f}%)   50-day {ma(50):,.0f} ({(closes[i] / ma(50) - 1) * 100:+.1f}%)",
            f"Last OI warning day: {nm_(lastw) if lastw is not None else 'none'}; cool-off active now: {'YES' if cool[i] else 'no'}.",
            "Rule states now: " + "; ".join(f"{nm}: {'IN' if g[i] else 'OUT'}" for nm, g in R.items() if g is not None and nm in ("200d & 50d (paper bot)", "200d & 50d + OI (LIVE ALERT)"))]
    text = "\n".join(out); open(os.path.join(OUT, "lab43_summary.txt"), "w").write(text + "\n"); print(text)

if __name__ == "__main__":
    main()
