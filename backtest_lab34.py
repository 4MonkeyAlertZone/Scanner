#!/usr/bin/env python3
"""Lab 34: GET IN FASTER WITHOUT LOSING THE PROTECTION. Base = live rule: IN while BTC closes above its 200-day AND 50-day average and no BTC open-interest (OI) warning in the last 14 days
(warning = OI at a new 180-day high and up 15%+ over 30 days). Spot long, signal at close i earns the next period's return (no peeking), 0.1% cost per position change, BTC and ETH traded on the BTC signal, from 1 Oct 2020.
EVERY variant was declared before running and ALL are printed. Families:
 A. Fine average grid: fast 35/40/45/50/55/60 x slow 150/180/200/220/250 (is there a plateau around 40-60 and 150-250?)
 B. OI grid: rise-window 14/21/30/45/60 days x rise 10/15/20% x cooldown 7/14 days (180-day lookback kept)
 C. Faster ENTRY, normal exit (daily): enter when the close is above the 50-day (C2) or 20-day (C3) average AND the 200-day average is rising over the last 10 or 30 days, even if price is still below the 200-day;
    a position entered this way is closed when price falls below its 50-day average (or an OI warning), and returns to the normal rules once the base rule is IN.
 D. Hourly triggers (hourly candles, live 50/200-day lines = prior completed daily closes + the current hourly close; decisions need an hourly close): entry daily/hourly x exit daily/hourly.
    'daily/daily' in this hourly frame is the reference for D; rows in D must only be compared with each other (hourly equity gives slightly different drawdown numbers than the daily frame).
Each row: final multiple of 1.0, worst drawdown, flips per year, time in market, multiples in H1 (Oct 2020-Dec 2022) and H2 (2023-now), for BTC and ETH; plus for BTC's signal: number of entries, median distance of the entry price above the lowest close of the previous 60 days (lower = earlier in the move),
and the share of entries that lost money (false starts).
'Consistent improver' = on BOTH BTC and ETH: final >= base, worst drawdown no more than 1 point worse, each half >= 95% of base. With ~100 variants a single pass is what luck produces; a block of neighbours is more convincing. Writes lab34_summary.txt."""
import os, csv, time, calendar, statistics as S
from datetime import datetime
import scanner, backtest as B, signals_history as SH
import backtest_lab33 as L33

OUT = scanner.HERE; fd = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))
COST = 0.001; START = L33.START; SPLIT = L33.SPLIT
sma = L33.sma

def oi_warn(OI, lb, rise, cool, w):
    n = len(OI); W = [False] * n
    for i in range(n):
        prev = [x for x in OI[max(0, i - lb):i] if x]
        if OI[i] and len(prev) > 0.55 * lb and OI[i] >= max(prev) and i >= w and OI[i - w] and OI[i] / OI[i - w] - 1 >= rise: W[i] = True
    out = [False] * n; left = 0
    for i in range(n):
        if W[i]: left = cool
        out[i] = left > 0
        if left > 0: left -= 1
    return out

def evaluate_h(pos, R, i0, n, split):
    """generic: pos[i] decided at close i earns R[i+1]; split = first index of H2."""
    eq = 1.0; curve = [1.0]; prev = 0.0; h1 = h2 = 1.0; flips = 0; inm = 0; last = False
    for i in range(i0, n - 1):
        p = pos[i]; ret = p * R[i + 1] - COST * abs(p - prev)
        eq *= 1 + ret; prev = p; curve.append(eq)
        if i + 1 < split: h1 *= 1 + ret
        else: h2 *= 1 + ret
        isin = p > 0
        if isin != last: flips += 1
        last = isin; inm += isin
    pk = 0; dd = 0
    for x in curve: pk = max(pk, x); dd = min(dd, x / pk - 1)
    return eq, dd * 100, h1, h2, flips, inm

def spells(pos, price, i0, win):
    """entry stats from a boolean-ish position list decided at close i."""
    ent = []; n = len(pos); i = i0
    prev = False
    for i in range(i0, n):
        p = pos[i] > 0
        if p and not prev:
            j = i
            while j < n and pos[j] > 0: j += 1
            lo = min(price[max(0, i - win):i + 1])
            exitp = price[min(j, n - 1)]
            ent.append((price[i] / lo - 1, exitp / price[i] - 1 - 2 * COST, j >= n))
        prev = p
    return ent

def main(daily=None, oi=None):
    daily = daily or {s: {int(r[0] // 86400): r[4] for r in B.hist_crypto(s, "1d", 2700)} for s in ("BTC", "ETH")}
    if oi is None:
        oi = {}; mp = os.path.join(scanner.HERE, "btc_metrics_daily.csv")
        if os.path.exists(mp):
            for r in csv.DictReader(open(mp)):
                try: oi[calendar.timegm(datetime.strptime(r["date"], "%Y-%m-%d").timetuple()) // 86400] = float(r["open_interest_btc"])
                except Exception: pass
    bt, et = daily["BTC"], daily["ETH"]
    days = [d for d in sorted(bt) if d in et]; n = len(days)
    CB = [bt[d] for d in days]; CE = [et[d] for d in days]; OI = [oi.get(d) for d in days]
    i0 = next(i for i, d in enumerate(days) if d >= START); split = next(i for i, d in enumerate(days) if d >= SPLIT)
    RB = [0.0] + [CB[i] / CB[i - 1] - 1 for i in range(1, n)]; RE = [0.0] + [CE[i] / CE[i - 1] - 1 for i in range(1, n)]
    ma = {k: sma(CB, k) for k in (20, 35, 40, 45, 50, 55, 60, 150, 180, 200, 220, 250)}
    above = lambda k: [ma[k][i] is not None and CB[i] > ma[k][i] for i in range(n)]
    A = {k: above(k) for k in ma}
    ow0 = oi_warn(OI, 180, .15, 14, 30)
    rows = {}
    def run(label, pos, fam, extra=""):
        pos = [1.0 if x else 0.0 for x in pos]
        res = []
        for R in (RB, RE):
            eq, dd, h1, h2, fl, inm = evaluate_h(pos, R, i0, n, split); yrs = (n - 1 - i0) / 365.0
            res.append(dict(final=eq, dd=dd, flips=fl / yrs, tim=inm / (n - 1 - i0) * 100, h1=h1, h2=h2))
        sp = spells(pos, CB, i0, 60)
        info = (len(sp), S.median([s[0] for s in sp]) * 100 if sp else 0, 100 * sum(s[1] < 0 for s in sp if not s[2]) / max(1, sum(1 for s in sp if not s[2])))
        rows[label] = (fam, res[0], res[1], info)
    base_in = lambda slow=200, fast=50, ow=ow0: [A[slow][i] and A[fast][i] and not ow[i] for i in range(n)]
    run("BASE 200/50 + OI(180,15%,30d,14d)", base_in(), "base")
    run("buy and hold", [1] * n, "base")
    base_b, base_e = rows["BASE 200/50 + OI(180,15%,30d,14d)"][1], rows["BASE 200/50 + OI(180,15%,30d,14d)"][2]
    for f in (35, 40, 45, 50, 55, 60):
        for s in (150, 180, 200, 220, 250):
            run(f"A slow {s} / fast {f}", base_in(s, f), "A fine grid")
    for w in (14, 21, 30, 45, 60):
        for rs in (.10, .15, .20):
            for cl in (7, 14):
                run(f"B OI window {w}d / rise {int(rs * 100)}% / cool {cl}d", base_in(ow=oi_warn(OI, 180, rs, cl, w)), "B OI grid")
    ma200 = ma[200]
    def fast_entry(entry_k, slope):
        base = base_in(); pos = [False] * n; st = False; fastflag = False
        for i in range(n):
            if ma[50][i] is None or ma200[i] is None or i < slope or ma200[i - slope] is None: pos[i] = False; continue
            rising = ma200[i] > ma200[i - slope]
            if base[i]: st = True; fastflag = False
            elif st and not fastflag: st = False                       # base exit
            elif st and fastflag:
                if CB[i] < ma[50][i] or ow0[i]: st = False; fastflag = False
            if not st and A[entry_k][i] and rising and not ow0[i]: st = True; fastflag = True
            pos[i] = st
        return pos
    for ek, nm in ((50, "C2 above 50d"), (20, "C3 above 20d")):
        for sl in (10, 30):
            run(f"{nm} + 200d rising over {sl}d", fast_entry(ek, sl), "C faster entry")
    # ---- D hourly
    t0 = START * 86400
    hb = SH.hourly("BTC", t0 - 3600); he = SH.hourly("ETH", t0 - 3600)
    eh = {r[0]: r[4] for r in he}
    HT = [r[0] for r in hb]; HB = [r[4] for r in hb]; m = len(HT)
    HE = []; lastp = None
    for t in HT:
        lastp = eh.get(t, lastp); HE.append(lastp)
    HE = [x if x else HB[0] for x in HE]
    didx = {d: i for i, d in enumerate(days)}
    cs = [0.0]
    for x in CB: cs.append(cs[-1] + x)
    def cond_live(i, x, ow_prev):
        if i < 200 or ow_prev: return False
        m200 = (cs[i] - cs[i - 199] + x) / 200; m50 = (cs[i] - cs[i - 49] + x) / 50
        return x > m200 and x > m50
    def hourly_pos(entry_h, exit_h):
        pos = [0.0] * m; st = False
        for h in range(m):
            t = HT[h]; i = didx.get(int(t // 86400))
            if i is None or i < 200: pos[h] = 0.0; continue
            lasthour = (t % 86400) == 82800
            if lasthour:
                c = A[200][i] and A[50][i] and not ow0[i]            # daily-close decision (as the live rule)
                if st and not c and not exit_h: st = False
                elif not st and c and not entry_h: st = True
                if exit_h and st and not cond_live(i, HB[h], ow0[i - 1]): st = False
                if entry_h and not st and cond_live(i, HB[h], ow0[i - 1]): st = True
            else:
                cl = cond_live(i, HB[h], ow0[i - 1])
                if st and exit_h and not cl: st = False
                elif not st and entry_h and cl: st = True
            pos[h] = 1.0 if st else 0.0
        return pos
    RHB = [0.0] + [HB[h] / HB[h - 1] - 1 for h in range(1, m)]; RHE = [0.0] + [HE[h] / HE[h - 1] - 1 for h in range(1, m)]
    hs = next(h for h, t in enumerate(HT) if t >= SPLIT * 86400); yrs = (m - 1) / 8766.0
    for en, ex in ((False, False), (True, False), (False, True), (True, True)):
        pos = hourly_pos(en, ex); res = []
        for R in (RHB, RHE):
            eq, dd, h1, h2, fl, inm = evaluate_h(pos, R, 0, m, hs); res.append(dict(final=eq, dd=dd, flips=fl / yrs, tim=inm / (m - 1) * 100, h1=h1, h2=h2))
        sp = spells(pos, HB, 0, 60 * 24)
        info = (len(sp), S.median([s[0] for s in sp]) * 100 if sp else 0, 100 * sum(s[1] < 0 for s in sp if not s[2]) / max(1, sum(1 for s in sp if not s[2])))
        rows[f"D entry {'hourly' if en else 'daily '} / exit {'hourly' if ex else 'daily '}"] = ("D hourly triggers", res[0], res[1], info)
    # ---- report
    L = [f"LAB 34: GET IN FASTER  data to {fd(days[-1])}  from {fd(days[i0])}  ({len(rows)} rows)", "",
         "final x = growth of 1.0; DD = worst drawdown; flips = IN/OUT changes per year; in% = time in market; H1 = Oct 2020-Dec 2022, H2 = 2023-now. Entry columns (BTC signal): number of entries, median % above the lowest close of the previous 60 days at entry, % of finished spells that lost money.", ""]
    hdr = f"{'variant':<46}" + "".join(f"{a + ' ' + c:>10}" for a in ("BTC", "ETH") for c in ("final", "DD%", "flips", "in%", "H1", "H2")) + f"{'entries':>9}{'above low%':>12}{'false%':>8}"
    fam_prev = None
    for lab, (fam, b, e, info) in rows.items():
        if fam != fam_prev: L += ["", f"== {fam} ==", hdr]; fam_prev = fam
        cell = lambda mm: f"{mm['final']:>10.2f}{mm['dd']:>10.0f}{mm['flips']:>10.1f}{mm['tim']:>10.0f}{mm['h1']:>10.2f}{mm['h2']:>10.2f}"
        L.append(f"{lab:<46}{cell(b)}{cell(e)}{info[0]:>9}{info[1]:>12.1f}{info[2]:>8.0f}")
    def ok(mm, base): return mm["final"] >= base["final"] and mm["dd"] >= base["dd"] - 1 and mm["h1"] >= .95 * base["h1"] and mm["h2"] >= .95 * base["h2"]
    grid = lambda fam: [lab for lab, v in rows.items() if v[0] == fam]
    for fam in ("A fine grid", "B OI grid", "C faster entry"):
        g = grid(fam); win = [lab for lab in g if ok(rows[lab][1], base_b) and ok(rows[lab][2], base_e)]
        L += ["", f"== {fam}: {len(win)} of {len(g)} cells match or beat the base on BOTH coins in BOTH halves (drawdown within 1 point) ==", *(["  " + w for w in win] or ["  none"])]
    L += ["", "== A fine grid, BTC final by fast (rows) and slow (columns 150/180/200/220/250), then flips per year =="]
    for f in (35, 40, 45, 50, 55, 60):
        L.append(f"  fast {f}: " + "  ".join(f"{rows[f'A slow {s} / fast {f}'][1]['final']:6.1f}" for s in (150, 180, 200, 220, 250)) + "    flips " + "  ".join(f"{rows[f'A slow {s} / fast {f}'][1]['flips']:4.1f}" for s in (150, 180, 200, 220, 250)))
    L.append("  ETH final:")
    for f in (35, 40, 45, 50, 55, 60):
        L.append(f"  fast {f}: " + "  ".join(f"{rows[f'A slow {s} / fast {f}'][2]['final']:6.1f}" for s in (150, 180, 200, 220, 250)))
    L += ["", "Read: a flat area of similar numbers around 40-60 / 150-250 means the choice is not fragile and a faster entry line is a safe tweak; a drop between 50 and 40 means whipsaws start there. Faster entry only counts if the 'above low%' falls WITHOUT the false-start share and flips per year rising a lot and without worse drawdown. Hindsight, ~3 market phases, many variants on the same data."]
    text = "\n".join(L); open(os.path.join(OUT, "lab34_summary.txt"), "w").write(text + "\n"); print(text)

if __name__ == "__main__":
    main()
