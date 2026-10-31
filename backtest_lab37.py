#!/usr/bin/env python3
"""Lab 37: CONTROLS AND CONFIDENCE INTERVALS for the lab 36 swing scanner. Lab 36 showed big numbers; this lab asks whether they survive honest controls.
Same universe, data loader, costs and signal timing as lab 36 (signal at close i earns i+1, cost 0.1% per unit of turnover, round trip 0.2% for events).
 PART A, is the value in the BTC gate or in the coin-level rules? (all rows start when 20+ coins have a 200-day average; H1/H2 = halves of history)
  A1  trend coins (above 200d and 50d), BTC IN only            (lab 36 row)
  C1  BTC alone, held only while BTC IN                         (the gate on its own, no altcoins)
  C2  ETH alone, held only while BTC IN
  C3  EVERY coin equal weight, BTC IN only, no coin trend filter (gate + plain altcoin beta)
  C4  trend coins, BTC IN only, but ALL coins above their own 200d only (looser coin filter)
  BASE equal-weight buy&hold all coins, BTC buy&hold
  If A1 is not clearly better than C1 and C3 in BOTH halves, the coin-level rules add nothing and the gate does the work.
 PART B, the LIVE scanner trigger and confidence intervals (event = close crosses above the 50-day while above the 200-day, same coin not re-fired within 14 days)
  B2   cross + volume >= 1.5x 20-day average            (no gate)
  B2g  B2 + BTC IN                                       (what swing_scan.py alerts on; NOT tested in lab 36)
  B4   B2 + beats BTC over 90 days + BTC IN             (lab 36 best row, for reference)
  For each: events, distinct dates, 30-day forward return (after 0.2% cost), median, win rate, and a BOOTSTRAP over distinct dates (events on the same date are resampled together, 5000 draws):
  95% interval for the average 30-day return, and the share of draws at or below the average of random coin-days (a rough one-sided p-value).
  Also the same numbers for H1 and H2 separately, and the average with the best 3 dates removed (does a handful of dates carry the result?).
 SELECTION WARNING: 36 earlier labs were run on this same data. A p-value near 0.05 after that many looks is weak evidence; treat anything above ~0.01 as unproven.
Writes lab37_summary.txt."""
import os, random, statistics as S
import scanner, backtest as B
import backtest_lab36 as L36

OUT = scanner.HERE
CT = L36.CT; CR = L36.CR
sma = L36.sma; metrics = L36.metrics; fd = L36.fd

def prep(data):
    days = sorted(data["BTC"]); n = len(days)
    coins = [s for s in data if s != "BTC"]
    C = {}; V = {}; M50 = {}; M200 = {}; VM = {}; R90 = {}
    for s in data:
        cl = []; vo = []; last = None
        for d in days:
            x = data[s].get(d)
            if x is not None: last = x
            cl.append(last[0] if last else None); vo.append(last[1] if last else None)
        C[s] = cl; V[s] = vo
        ok0 = next((i for i, x in enumerate(cl) if x is not None), None)
        if ok0 is None: continue
        M50[s] = [None] * ok0 + sma(cl[ok0:], 50); M200[s] = [None] * ok0 + sma(cl[ok0:], 200); VM[s] = [None] * ok0 + sma(vo[ok0:], 20)
        R90[s] = [None] * (ok0 + 90) + [cl[i] / cl[i - 90] - 1 for i in range(ok0 + 90, n)]
    return days, n, coins, C, V, M50, M200, VM, R90

def boot(vals_by_date, ref, draws=5000, rng=None):
    """vals_by_date: list of lists (one list of 30-day returns per distinct date). Resample dates with replacement; each date's events move together."""
    rng = rng or random.Random(37)
    k = len(vals_by_date); means = []
    for _ in range(draws):
        pick = [vals_by_date[rng.randrange(k)] for _ in range(k)]
        flat = [x for g in pick for x in g]
        means.append(S.mean(flat))
    means.sort()
    lo = means[int(0.025 * draws)]; hi = means[int(0.975 * draws) - 1]
    p = sum(m <= ref for m in means) / draws
    return lo, hi, p

def main(data=None):
    if data is None:
        syms = [s for s in scanner.top100() if s != "BTC"]; data = L36.load(["BTC"] + syms)
    assert "BTC" in data, "BTC history missing"
    days, n, coins, C, V, M50, M200, VM, R90 = prep(data)
    bt = C["BTC"]
    btin = [M200["BTC"][i] is not None and bt[i] > M200["BTC"][i] and bt[i] > M50["BTC"][i] for i in range(n)]
    isin = lambda s, i: M200[s][i] is not None and C[s][i] is not None and C[s][i] > M200[s][i] and C[s][i] > M50[s][i]
    above200 = lambda s, i: M200[s][i] is not None and C[s][i] is not None and C[s][i] > M200[s][i]
    rs_ok = lambda s, i: R90[s][i] is not None and R90["BTC"][i] is not None and R90[s][i] > R90["BTC"][i]
    RET = {s: [None] + [(C[s][i] / C[s][i - 1] - 1) if C[s][i] and C[s][i - 1] else None for i in range(1, n)] for s in data}
    ncov = [sum(1 for s in coins if M200[s][i] is not None) for i in range(n)]
    i0 = next(i for i in range(n) if ncov[i] >= 20); split = (i0 + n) // 2
    out = [f"LAB 37: CONTROLS AND CONFIDENCE  data {fd(days[0])} to {fd(days[-1])}; {len(coins)} coins; tests start {fd(days[i0])}, halves split at {fd(days[split])}",
           "SURVIVORSHIP: universe is today's top 100 (dead coins missing). SELECTION: 36 earlier labs used this same data.", ""]

    def sim(sel):
        eq = 1.0; curve = [1.0]; prev = {}; h1 = h2 = 1.0; inm = 0; held = 0
        for i in range(i0, n - 1):
            w = [s for s in sel(i) if s in RET]; cnt = len(w); r = 0.0; nw = {}
            for s in w:
                r += (RET[s][i + 1] or 0.0) / cnt; nw[s] = 1.0 / cnt
            turn = sum(abs(nw.get(s, 0) - prev.get(s, 0)) for s in set(nw) | set(prev))
            r -= CT * turn; eq *= 1 + r; curve.append(eq); prev = nw; inm += cnt > 0; held += cnt
            if i + 1 < split: h1 *= 1 + r
            else: h2 *= 1 + r
        return eq, metrics(curve), h1, h2, held / (n - 1 - i0), 100 * inm / (n - 1 - i0)
    gate = lambda f: (lambda i: f(i) if btin[i] else [])
    rows = {"A1 trend coins, BTC IN only": gate(lambda i: [s for s in coins if isin(s, i)]),
            "C1 BTC only, BTC IN only": gate(lambda i: ["BTC"]),
            "C2 ETH only, BTC IN only": gate(lambda i: ["ETH"] if "ETH" in RET else []),
            "C3 ALL coins equal wt, BTC IN only": gate(lambda i: [s for s in coins if C[s][i] and C[s][i - 1]]),
            "C4 coins above own 200d, BTC IN only": gate(lambda i: [s for s in coins if above200(s, i)]),
            "BASE equal-weight buy&hold all coins": lambda i: [s for s in coins if C[s][i] and C[s][i - 1]],
            "BASE BTC buy&hold": lambda i: ["BTC"]}
    out.append("PART A: IS THE VALUE IN THE BTC GATE OR IN THE COIN RULES?")
    out.append(f"{'row':<40}{'final x':>9}{'worst DD%':>11}{'H1 x':>8}{'H2 x':>8}{'avg held':>10}{'in-mkt%':>9}")
    for nm, f in rows.items():
        e, d, h1, h2, ah, im = sim(f); out.append(f"{nm:<40}{e:>9.2f}{d:>11.0f}{h1:>8.2f}{h2:>8.2f}{ah:>10.1f}{im:>9.0f}")
    out.append("Read: if A1 does not beat C1 and C3 in BOTH H1 and H2, the coin-level 200/50 rule adds nothing; the BTC gate is doing the work.")

    # ---------- Part B
    def events(cond):
        ev = []
        for s in coins:
            last = -99
            for i in range(max(1, i0 - 100), n - 1):
                if M200[s][i] is None or M50[s][i] is None or M50[s][i - 1] is None or C[s][i] is None or C[s][i - 1] is None: continue
                if not (C[s][i] > M50[s][i] and C[s][i - 1] <= M50[s][i - 1] and C[s][i] > M200[s][i]): continue
                if i - last < 14 or not cond(s, i): continue
                last = i; ev.append((s, i))
        return ev
    f30 = lambda s, i: C[s][i + 30] / C[s][i] - 1 - CR if i + 30 < n and C[s][i + 30] and C[s][i] else None
    allf = [f30(s, i) for s in coins for i in range(i0, n - 31) if M200[s][i] is not None and C[s][i] and C[s][i + 30]]
    ref = S.mean(allf)
    volok = lambda s, i: VM[s][i] and V[s][i] and V[s][i] >= 1.5 * VM[s][i]
    cond = {"B2  cross + volume>=1.5x": lambda s, i: volok(s, i),
            "B2g B2 + BTC IN (LIVE scanner)": lambda s, i: btin[i] and volok(s, i),
            "B4  B2 + beats BTC 90d + BTC IN": lambda s, i: btin[i] and volok(s, i) and rs_ok(s, i)}
    out += ["", f"PART B: LIVE TRIGGER WITH BOOTSTRAP (resampled by distinct date, 5000 draws). Random coin-day 30d average = {ref * 100:.1f}% (n={len(allf)})",
            f"{'trigger':<34}{'events':>7}{'dates':>6}{'30d avg%':>9}{'median%':>9}{'win%':>6}{'95% low':>9}{'95% high':>9}{'p(<=rand)':>10}{'no top3 dates':>14}{'H1 avg%':>9}{'H2 avg%':>9}"]
    for nm, cf in cond.items():
        ev = events(cf); bd = {}
        for s, i in ev:
            x = f30(s, i)
            if x is not None: bd.setdefault(i, []).append(x)
        flat = [x for g in bd.values() for x in g]
        if len(bd) < 8: out.append(f"{nm:<34}{len(ev):>7}{len(bd):>6}  too few dates"); continue
        lo, hi, p = boot(list(bd.values()), ref)
        top = sorted(bd, key=lambda d: -S.mean(bd[d]))[:3]
        rest = [x for d, g in bd.items() if d not in top for x in g]
        h1 = [x for d, g in bd.items() if d < split for x in g]; h2 = [x for d, g in bd.items() if d >= split for x in g]
        out.append(f"{nm:<34}{len(ev):>7}{len(bd):>6}{S.mean(flat) * 100:>9.1f}{S.median(flat) * 100:>9.1f}{100 * sum(x > 0 for x in flat) / len(flat):>6.0f}{lo * 100:>9.1f}{hi * 100:>9.1f}{p:>10.3f}{S.mean(rest) * 100:>14.1f}{(S.mean(h1) * 100 if h1 else float('nan')):>9.1f}{(S.mean(h2) * 100 if h2 else float('nan')):>9.1f}")
    out += ["", "Read: 'no top3 dates' removes the 3 best dates; if the average collapses, a few dates carry the result. 'p(<=rand)' = share of bootstrap averages at or below the random-day average (small = unlikely to be chance), but 36 earlier labs mean this is optimistic.",
            "A trigger is worth trusting only if: the 95% low is above the random average, H1 and H2 both beat random, and the average survives removing the top 3 dates. Not financial advice."]
    text = "\n".join(out); open(os.path.join(OUT, "lab37_summary.txt"), "w").write(text + "\n"); print(text)

if __name__ == "__main__":
    main()
