#!/usr/bin/env python3
"""Lab 45: CAN ANYTHING RAISE GAIN WITHOUT SIMPLY ADDING RISK? Ideas from the research scan (13 Nov 2026), declared BEFORE running, tested on BTC AND on US stocks (SPY, dividends reinvested), then combined.
Base = the plain 200/50 gate (IN while the close is above its 200-day AND 50-day average) on each asset. Earlier crypto labs let cash earn 0% while OUT; the stocks labs already used T-bill cash.
 Y1   T-BILL ON CASH: the same gate, but money not invested earns the 13-week T-bill rate (^IRX, carried over weekends). No added risk. Compared with the gate at 0% cash.
 Y2a  VOLATILITY-SIZED, no leverage: when IN, exposure = min(1, target / 90-day annualised volatility), recomputed weekly and at each flip. Target 50% for BTC, 15% for stocks. Idle cash earns T-bills.
 Y2b  same with exposure capped at 2x. Borrowed money costs 8% a year for BTC (about the long-run crypto funding rate, arXiv 2510.14435) and T-bill + 1.5% for stocks.
 Y3   DONCHIAN ENSEMBLE (my reading of Zarattini, Pagani and Barbon 2025, not their code): for lookbacks of 5, 10, 20, 30, 60, 90, 150, 250 and 360 days, long when the close beats the highest close of the previous L days, until it falls below the midpoint of that range. Exposure = share of the 9 models long. Replaces the 200/50 gate. Idle cash earns T-bills.
 REF  fixed 1.5x when the gate is IN, same financing; shows what 'more gain by leverage' costs in drawdown.
 BOTH 50/50 of the BTC leg and the stock leg (each Y1: its own gate, T-bill cash), rebalanced daily, against 50/50 buy-and-hold.
Signals use each asset's own trading days; money is tracked on calendar days (weekends carry the last price). Cost 0.1% per unit of exposure traded; a decision at close i-1 earns day i.
WINDOWS: BTC long = 2012-10-17 to now; stocks long = 2000-01-03 to now; both also 2012-10-17 to now (A) and 11 May 2021 to now (B). Each split into halves.
PASS per asset (all required), against the Y1 baseline (Y1 itself against 0% cash): CAGR higher in BOTH halves of the long window and overall in B; Calmar no lower than the baseline minus 0.05 in the long window and in B; worst drawdown no more than 10 points worse than the baseline in both. A pass only earns a separate paper account; nothing changes the live gate or paper bot. More return with a much bigger drawdown is leverage, not an improvement, and fails.
Not financial advice. Writes lab45_summary.txt."""
import os, random, statistics as S
import scanner
import backtest_lab36 as L36
import backtest_lab40 as L40
import backtest_lab42 as L42
import backtest_lab44 as L44

OUT = scanner.HERE; fd = L36.fd; sma = L36.sma; CT = L36.CT
LOOKS = (5, 10, 20, 30, 60, 90, 150, 250, 360)
day_of = L44.day_of

def ffill(nd, d, grid):
    ds = sorted(d); out = []; j = -1; last = 0.0
    for x in grid:
        while j + 1 < len(ds) and ds[j + 1] <= x: j += 1; last = d[ds[j]]
        out.append(last)
    return out

def mapto(nd, vals, grid):
    out = []; j = -1
    for x in grid:
        while j + 1 < len(nd) and nd[j + 1] <= x: j += 1
        out.append(vals[j] if j >= 0 else 0.0)
    return out

def daily_x(P, w, rf, fin, cost=CT):
    """Calendar-day returns: weight decided at close i-1 earns day i; idle cash earns rf (annual %), borrowing above 1x costs fin (annual %)."""
    g = [0.0] * len(P); prev = 0.0
    for i in range(1, len(P)):
        x = float(w[i - 1])
        r = x * (P[i] / P[i - 1] - 1) + max(0.0, 1 - x) * rf[i - 1] / 36500.0 - max(0.0, x - 1) * fin[i - 1] / 36500.0 - cost * abs(x - prev)
        g[i] = r; prev = x
    return g

def vol_sized(c, g0, cap, target, ppy, upd):
    n = len(c); w = [0.0] * n; cur = 0.0; last = -10 ** 9
    rets = [0.0] + [c[i] / c[i - 1] - 1 for i in range(1, n)]
    for i in range(n):
        if not g0[i]: cur = 0.0; last = -10 ** 9
        elif cur == 0.0 or i - last >= upd:
            if i >= 90:
                sd = S.pstdev(rets[i - 89:i + 1]) * (ppy ** 0.5); cur = min(cap, target / sd) if sd > 0 else cap
            else: cur = 0.0
            last = i
        w[i] = cur
    return w

def donchian(c):
    n = len(c); share = [0.0] * n
    for L in LOOKS:
        st = False
        for i in range(L, n):
            win = c[i - L:i]; hi = max(win); lo = min(win)
            if not st and c[i] > hi: st = True
            elif st and c[i] < (hi + lo) / 2: st = False
            if st: share[i] += 1.0 / len(LOOKS)
    return share

def build(nd, nc, ppy, upd, target, spread, irx, grid):
    """All variants for one asset: signals on native days, money on the calendar grid."""
    n = len(nc); m200 = sma(nc, 200); m50 = sma(nc, 50)
    g0 = [m200[i] is not None and m50[i] is not None and nc[i] > m200[i] and nc[i] > m50[i] for i in range(n)]
    nat = {"LIVE gate, cash 0%": [1.0 if x else 0.0 for x in g0], "Y1 gate + T-bill cash": [1.0 if x else 0.0 for x in g0],
           "Y2a vol-sized, cap 1x": vol_sized(nc, g0, 1.0, target, ppy, upd), "Y2b vol-sized, cap 2x": vol_sized(nc, g0, 2.0, target, ppy, upd),
           "Y3 Donchian ensemble (9)": donchian(nc), "REF fixed 1.5x when IN": [1.5 if x else 0.0 for x in g0]}
    P = mapto(nd, nc, grid); rf = ffill(nd, irx, grid) if irx else [0.0] * len(grid)
    fin = [8.0] * len(grid) if spread is None else [x + spread for x in rf]
    W = {k: mapto(nd, v, grid) for k, v in nat.items()}
    return dict(P=P, rf=rf, fin=fin, W=W, g0=g0, m200=m200, m50=m50, nc=nc, nd=nd, nat=nat, ppy=ppy)

def run_asset(label, A, grid, windows, out, rnd, table):
    P, rf, fin = A["P"], A["rf"], A["fin"]; bh = L42.bh(P); R = {}
    for k, w in A["W"].items(): R[k] = daily_x(P, w, [0.0] * len(P) if k.startswith("LIVE") else rf, fin)
    for wn, (s0, half) in windows.items():
        shifts = rnd.sample(range(30, len(P) - s0 - 30), 150); yrs = (len(P) - s0) / 365.0
        out.append(f"{label}  WINDOW {wn}: {fd(grid[s0])} to {fd(grid[-1])} ({yrs:.1f} years); halves split at {fd(grid[half])}")
        out.append(f"{'variant':<28}{'final x':>9}{'CAGR%':>7}{'DD%':>6}{'Calmar':>8}{'CAGR 1st':>9}{'CAGR 2nd':>9}{'avg exp':>8}{'plac p':>8}")
        p = L42.perf(bh, s0, len(P)); out.append(f"{'buy & hold':<28}{p[0]:>9.1f}{p[2] * 100:>7.0f}{p[1]:>6.0f}{p[3]:>8.2f}{L42.perf(bh, s0, half)[2] * 100:>9.0f}{L42.perf(bh, half, len(P))[2] * 100:>9.0f}")
        table[(label, wn, "buy & hold")] = dict(cagr=p[2], calmar=p[3], dd=p[1], c1=L42.perf(bh, s0, half)[2], c2=L42.perf(bh, half, len(P))[2])
        for k, w in A["W"].items():
            rr = R[k]; p = L42.perf(rr, s0, len(P)); c1 = L42.perf(rr, s0, half)[2]; c2 = L42.perf(rr, half, len(P))[2]
            exp = sum(w[s0 - 1:len(P) - 1]) / (len(P) - s0); better = 0; r_ = [0.0] * len(P) if k.startswith("LIVE") else rf
            for s in shifts:
                ww = w[s0:]; w2 = w[:s0] + ww[s:] + ww[:s]
                better += L42.perf(daily_x(P, w2, r_, fin), s0, len(P))[3] >= p[3]
            table[(label, wn, k)] = dict(cagr=p[2], calmar=p[3], dd=p[1], c1=c1, c2=c2, p=better / len(shifts))
            out.append(f"{k:<28}{p[0]:>9.1f}{p[2] * 100:>7.0f}{p[1]:>6.0f}{p[3]:>8.2f}{c1 * 100:>9.0f}{c2 * 100:>9.0f}{exp:>8.2f}{better / len(shifts):>8.2f}")
        out.append("")
    return R, bh

def main(btc=None, spy=None, irx=None, src="synthetic"):
    if btc is None:
        days, closes, src = L40.load(); btc = (days, closes)
    bd, bc = btc
    if spy is None or irx is None:
        import backtest_stocks2b as B2
        spy = spy or B2.fetch("SPY", adj=True)
        try: irx = irx or B2.fetch("^IRX", adj=False)
        except Exception as e: print("T-bill data unavailable:", str(e)[:100]); irx = None
    sd = sorted(spy); sc = [spy[d] for d in sd]
    gB = list(bd); gS = list(range(sd[0], max(bd[-1], sd[-1]) + 1))
    AB = build(bd, bc, 365, 7, 0.50, None, irx, gB); AS = build(sd, sc, 252, 5, 0.15, 1.5, irx, gS)
    first = lambda g, d: next(i for i, x in enumerate(g) if x >= d)
    def win(g, d0): s = first(g, d0); return (s, s + (len(g) - s) // 2)
    WB = {"LONG (2012+)": (400, 400 + (len(gB) - 400) // 2), "B (2021+)": win(gB, day_of(2021, 5, 11))}
    WS = {"LONG (2000+)": win(gS, day_of(2000, 1, 3)), "A (2012+)": win(gS, day_of(2012, 10, 17)), "B (2021+)": win(gS, day_of(2021, 5, 11))}
    rnd = random.Random(45); out = [f"LAB 45: RETURN-BOOSTING IDEAS ON BTC AND US STOCKS  BTC source {src}; BTC {fd(bd[0])} to {fd(bd[-1])}; SPY (dividends reinvested) {fd(sd[0])} to {fd(sd[-1])}; T-bill {'latest ' + format(AB['rf'][-1], '.2f') + '% a year' if irx else 'NOT available (cash earns 0%)'}", ""]
    table = {}
    RB, bhB = run_asset("BTC", AB, gB, WB, out, rnd, table)
    RS, bhS = run_asset("STOCKS (SPY)", AS, gS, WS, out, rnd, table)
    # ---- BOTH
    off = gB[0] - gS[0]; n = len(gB)
    legB = RB["Y1 gate + T-bill cash"]; legS = RS["Y1 gate + T-bill cash"][off:off + n]
    combo = [0.5 * a + 0.5 * b for a, b in zip(legB, legS)]; cbh = [0.5 * a + 0.5 * b for a, b in zip(bhB, bhS[off:off + n])]
    out.append("BOTH: 50/50 BTC leg + SPY leg, each with its own gate and T-bill cash (Y1), rebalanced daily; benchmark 50/50 buy and hold. Same days for everything.")
    for wn, (s0, half) in {"A (2012+)": (400, 400 + (n - 400) // 2), "B (2021+)": WB["B (2021+)"]}.items():
        out.append(f"WINDOW {wn}: {fd(gB[s0])} to {fd(gB[-1])}")
        out.append(f"{'portfolio':<34}{'final x':>9}{'CAGR%':>7}{'DD%':>6}{'Calmar':>8}{'CAGR 1st':>9}{'CAGR 2nd':>9}")
        for nm, r in (("50/50 BTC + SPY buy & hold", cbh), ("BTC gate alone (Y1)", legB), ("SPY gate alone (Y1)", RS["Y1 gate + T-bill cash"][off:off + n]), ("BOTH gates, 50/50 (Y1)", combo)):
            p = L42.perf(r, s0, n); out.append(f"{nm:<34}{p[0]:>9.1f}{p[2] * 100:>7.0f}{p[1]:>6.0f}{p[3]:>8.2f}{L42.perf(r, s0, half)[2] * 100:>9.0f}{L42.perf(r, half, n)[2] * 100:>9.0f}")
        out.append("")
    # ---- verdicts
    out.append("VERDICT (rule declared in the header):")
    for label, long_ in (("BTC", "LONG (2012+)"), ("STOCKS (SPY)", "LONG (2000+)")):
        passed = []
        for k in AB["W"]:
            if k.startswith("LIVE"): continue
            ref = "LIVE gate, cash 0%" if k.startswith("Y1") else "Y1 gate + T-bill cash"
            a = table[(label, long_, k)]; ra = table[(label, long_, ref)]; b = table[(label, "B (2021+)", k)]; rb = table[(label, "B (2021+)", ref)]
            ck = [("1st-half CAGR", a["c1"] > ra["c1"]), ("2nd-half CAGR", a["c2"] > ra["c2"]), ("B CAGR", b["cagr"] > rb["cagr"]), ("long Calmar", a["calmar"] >= ra["calmar"] - 0.05),
                  ("B Calmar", b["calmar"] >= rb["calmar"] - 0.05), ("long drawdown", a["dd"] >= ra["dd"] - 10), ("B drawdown", b["dd"] >= rb["dd"] - 10)]
            ok = all(v for _, v in ck); passed.append(k) if ok else None
            out.append(f"  {label:<14}{k:<28}vs {ref.split(',')[0]:<22}{'PASS' if ok else 'fail'}   " + ("" if ok else "failed: " + ", ".join(x for x, v in ck if not v)))
        out.append(f"  {label}: passing: {', '.join(passed) if passed else 'none'}")
    # ---- now
    out.append("")
    for label, A, g in (("BTC", AB, gB), ("STOCKS (SPY)", AS, gS)):
        nc, nd = A["nc"], A["nd"]; i = len(nc) - 1; ppy = A["ppy"]
        sdv = S.pstdev([nc[k] / nc[k - 1] - 1 for k in range(i - 89, i + 1)]) * (ppy ** 0.5)
        out.append(f"NOW {label} (latest close in the data: {fd(nd[i])}): {nc[i]:,.2f}  vs 200-day {(nc[i] / A['m200'][i] - 1) * 100:+.1f}%  vs 50-day {(nc[i] / A['m50'][i] - 1) * 100:+.1f}%  90-day vol {sdv * 100:.0f}%  gate {'IN' if A['g0'][i] else 'OUT'}")
        out.append("   exposure now: " + "; ".join(f"{k.split(' ')[0]} {v[i] * 100:.0f}%" for k, v in A["nat"].items()))
    text = "\n".join(out); open(os.path.join(OUT, "lab45_summary.txt"), "w").write(text + "\n"); print(text)

if __name__ == "__main__":
    main()
