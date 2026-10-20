#!/usr/bin/env python3
"""Lab 33: REGIME ROBUSTNESS AND IMPROVEMENT TEST. Base = the live rule: IN while BTC closes above its 200-day AND 50-day average and no BTC open-interest (OI) warning C in the last 14 days (C = OI at a new 180-day high AND up 15%+ in 30 days).
Spot long, signal at the close of day i applied to day i+1's return (no peeking), 0.1% cost per unit of position change, BTC and ETH each traded on the BTC signal, from 1 Oct 2020. OI exists from 2021-01 only (before that no OI warnings).
EVERY variant below was declared before running; ALL are printed, not only the good ones. Families:
 1. MA grid: slow average 100/150/200/250/300 x fast average 20/30/50/70/100 (is 200/50 a fragile pick or a plateau?)
 2. OI grid: lookback 90/180/365 x rise 10/15/20/30% x cooldown 7/14/21 (and no OI at all)
 3. Whipsaw reducers: a band around the 50-day line (0/1/2/3/5%) x days of confirmation before a flip (1/2/3)
 4. RSI add-ons (completed bars only): weekly RSI above 75/80/85 = cash for 14 days; or require 2-day RSI above 40/45/50 to be IN
 5. Volatility sizing: position = min(1, target / 30-day realised volatility) while IN, targets 40/60/80% a year
 6. ETH only: also require ETH/BTC above its own 20/50-day average
 7. Voting: IN if at least 3/4/5 of the 50/100/150/200/250-day averages are below the price (and no OI warning)
Each row shows, for BTC and ETH: final multiple of 1.0 from 1 Oct 2020, worst drawdown, flips per year, time in market, and the multiple in the two halves (Oct 2020-Dec 2022 and 2023-now).
A variant is listed as a 'consistent improver' only if, on BOTH BTC and ETH, it ends at least as high as the base, cuts the worst drawdown by 3+ points, and each half is at least 95% of the base's. With ~95 variants tried on one history, a few lucky passes are expected: look for neighbours that also pass, not single cells.
Also a random-timing null for the base rule (its position series circularly shifted). Writes lab33_summary.txt."""
import os, csv, time, random, calendar, bisect, statistics as S
from datetime import datetime
import scanner, backtest as B, chart_data as CD

OUT = scanner.HERE; fd = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))
COST = 0.001; START = calendar.timegm((2020, 10, 1, 0, 0, 0)) // 86400; SPLIT = calendar.timegm((2023, 1, 1, 0, 0, 0)) // 86400

def sma(C, k):
    out = [None] * len(C); s = 0.0
    for i, x in enumerate(C):
        s += x
        if i >= k: s -= C[i - k]
        if i >= k - 1: out[i] = s / k
    return out

def rsi_at_days(daily, days, tf):
    ends, r = CD.sample_daily(daily, tf)
    return [(r[bisect.bisect_right(ends, d) - 1] if bisect.bisect_right(ends, d) > 0 else None) for d in days]

def oi_warn(OI, lb, rise, cool):
    n = len(OI); W = [False] * n
    for i in range(n):
        prev = [x for x in OI[max(0, i - lb):i] if x]
        if OI[i] and len(prev) > 0.55 * lb and OI[i] >= max(prev) and i >= 30 and OI[i - 30] and OI[i] / OI[i - 30] - 1 >= rise: W[i] = True
    out = [False] * n; left = 0
    for i in range(n):
        if W[i]: left = cool
        out[i] = left > 0
        if left > 0: left -= 1
    return out

def confirm(raw, k):
    if k <= 1: return raw[:]
    out = [False] * len(raw); st = False; run = 0
    for i, x in enumerate(raw):
        if x != st:
            run += 1
            if run >= k: st = x; run = 0
        else: run = 0
        out[i] = st
    return out

def hyst(C, ma, h):
    out = [False] * len(C); st = False
    for i in range(len(C)):
        if ma[i] is None: out[i] = False; continue
        if st and C[i] < ma[i] * (1 - h): st = False
        elif not st and C[i] > ma[i] * (1 + h): st = True
        out[i] = st
    return out

def evaluate(pos, R, i0, n):
    """pos[i] decided at close i, earns R[i+1]. -> dict of metrics"""
    eq = 1.0; curve = [1.0]; prev = 0.0; h1 = h2 = 1.0; flips = 0; inm = 0; last_in = False
    for i in range(i0, n - 1):
        p = pos[i]; ret = p * R[i + 1] - COST * abs(p - prev)
        eq *= 1 + ret; prev = p; curve.append(eq)
        if i + 1 < SPLIT_IDX[0]: h1 *= 1 + ret
        else: h2 *= 1 + ret
        isin = p > 0
        if isin != last_in: flips += 1
        last_in = isin; inm += isin
    pk = 0; dd = 0
    for x in curve: pk = max(pk, x); dd = min(dd, x / pk - 1)
    yrs = (n - 1 - i0) / 365.0
    return dict(final=eq, dd=dd * 100, flips=flips / yrs, tim=inm / (n - 1 - i0) * 100, h1=h1, h2=h2)
SPLIT_IDX = [0]

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
    i0 = next(i for i, d in enumerate(days) if d >= START); SPLIT_IDX[0] = next(i for i, d in enumerate(days) if d >= SPLIT)
    RB = [0.0] + [CB[i] / CB[i - 1] - 1 for i in range(1, n)]; RE = [0.0] + [CE[i] / CE[i - 1] - 1 for i in range(1, n)]
    ma = {k: sma(CB, k) for k in (20, 30, 50, 70, 100, 150, 200, 250, 300)}
    above = lambda k: [ma[k][i] is not None and CB[i] > ma[k][i] for i in range(n)]
    A = {k: above(k) for k in ma}
    owB = oi_warn(OI, 180, .15, 14)
    def base_in(slow=200, fast=50, ow=owB): return [A[slow][i] and A[fast][i] and not ow[i] for i in range(n)]
    pos0 = [1.0 if x else 0.0 for x in base_in()]
    rows = {}
    def run(label, pos, fam, eth_pos=None):
        b = evaluate(pos, RB, i0, n); e = evaluate(eth_pos or pos, RE, i0, n); rows[label] = (fam, b, e)
    run("BASE 200/50 + OI(180,15%,14d)", pos0, "base")
    run("buy and hold", [1.0] * n, "base")
    base_b, base_e = rows["BASE 200/50 + OI(180,15%,14d)"][1], rows["BASE 200/50 + OI(180,15%,14d)"][2]
    for s in (100, 150, 200, 250, 300):
        for f in (20, 30, 50, 70, 100):
            if f >= s: continue
            run(f"MA slow {s} / fast {f}", [1.0 if x else 0.0 for x in base_in(s, f)], "1 MA grid")
    run("OI none", [1.0 if (A[200][i] and A[50][i]) else 0.0 for i in range(n)], "2 OI grid")
    for lb in (90, 180, 365):
        for rs in (.10, .15, .20, .30):
            for cl in (7, 14, 21):
                run(f"OI lookback {lb} / rise {int(rs * 100)}% / cool {cl}d", [1.0 if x else 0.0 for x in base_in(ow=oi_warn(OI, lb, rs, cl))], "2 OI grid")
    ow = owB
    for h in (0, .01, .02, .03, .05):
        hm = hyst(CB, ma[50], h)
        for k in (1, 2, 3):
            raw = [A[200][i] and hm[i] and not ow[i] for i in range(n)]
            run(f"band {int(h * 100)}% on 50d / confirm {k}d", [1.0 if x else 0.0 for x in confirm(raw, k)], "3 whipsaw")
    w1 = rsi_at_days(daily["BTC"], days, "1w"); d2 = rsi_at_days(daily["BTC"], days, "2d")
    for th in (75, 80, 85):
        cool = [False] * n; left = 0
        for i in range(n):
            if w1[i] is not None and w1[i] > th: left = 14
            cool[i] = left > 0
            if left > 0: left -= 1
        run(f"weekly RSI > {th}: 14d cash", [1.0 if (base_in()[i] and not cool[i]) else 0.0 for i in range(n)], "4 RSI")
    for th in (40, 45, 50):
        run(f"need 2-day RSI > {th}", [1.0 if (base_in()[i] and d2[i] is not None and d2[i] > th) else 0.0 for i in range(n)], "4 RSI")
    vol = [None] * n
    for i in range(30, n):
        w = RB[i - 29:i + 1]; m = sum(w) / 30; vol[i] = (sum((x - m) ** 2 for x in w) / 29) ** .5 * 365 ** .5
    for tg in (.40, .60, .80):
        run(f"vol sizing, target {int(tg * 100)}%/yr", [min(1.0, tg / vol[i]) if (base_in()[i] and vol[i]) else 0.0 for i in range(n)], "5 vol size")
    ratio = [CE[i] / CB[i] for i in range(n)]
    for k in (20, 50):
        mr = sma(ratio, k)
        ep = [1.0 if (base_in()[i] and mr[i] is not None and ratio[i] > mr[i]) else 0.0 for i in range(n)]
        run(f"ETH only: ETH/BTC above its {k}d avg", pos0, "6 ETH/BTC", eth_pos=ep)
    for need in (3, 4, 5):
        run(f"vote: {need} of 5 averages", [1.0 if (sum(A[k][i] for k in (50, 100, 150, 200, 250)) >= need and not ow[i]) else 0.0 for i in range(n)], "7 vote")
    L = [f"LAB 33: REGIME ROBUSTNESS  data to {fd(days[-1])}  from {fd(days[i0])}  ({len(rows)} rows, base + buy-and-hold + variants)", "",
         "Per asset: final x = growth of 1.0; DD = worst drawdown; flips = IN/OUT changes per year; in% = time in market; H1 = Oct 2020-Dec 2022, H2 = 2023-now (growth multiples).", ""]
    hdr = f"{'variant':<42}" + "".join(f"{a + ' ' + c:>10}" for a in ("BTC", "ETH") for c in ("final", "DD%", "flips", "in%", "H1", "H2"))
    fam_prev = None
    for lab, (fam, b, e) in rows.items():
        if fam != fam_prev: L += ["", f"== {fam} ==", hdr]; fam_prev = fam
        cell = lambda m: f"{m['final']:>10.2f}{m['dd']:>10.0f}{m['flips']:>10.1f}{m['tim']:>10.0f}{m['h1']:>10.2f}{m['h2']:>10.2f}"
        L.append(f"{lab:<42}{cell(b)}{cell(e)}")
    # consistent improvers
    def beats(m, base): return m["final"] >= base["final"] and m["dd"] >= base["dd"] + 3 and m["h1"] >= .95 * base["h1"] and m["h2"] >= .95 * base["h2"]
    win = [lab for lab, (fam, b, e) in rows.items() if fam not in ("base",) and beats(b, base_b) and beats(e, base_e)]
    L += ["", f"== CONSISTENT IMPROVERS (both BTC and ETH: final >= base, worst drawdown 3+ points better, each half >= 95% of base) : {len(win)} of {len(rows) - 2} variants ==", *(["  " + w for w in win] or ["  none"]),
          "A single passing cell among ~95 is what luck alone could produce; a block of neighbouring cells all passing would be more convincing."]
    # Calmar leaders
    def calmar(m): yrs = (n - 1 - i0) / 365.0; return (m["final"] ** (1 / yrs) - 1) / max(.01, -m["dd"] / 100)
    ld = sorted(((calmar(b) + calmar(e)) / 2, lab) for lab, (fam, b, e) in rows.items() if fam != "base")[::-1][:8]
    L += ["", "Top 8 by average return-to-drawdown (CAGR / worst drawdown) across BTC and ETH:", *[f"  {v:.2f}  {lab}" for v, lab in ld]]
    # null: shift the base position
    rng = random.Random(5); res = {}
    for nm, R, base in (("BTC", RB, base_b), ("ETH", RE, base_e)):
        cnt_f = cnt_d = 0; N = 800
        for _ in range(N):
            sh = rng.randrange(60, n - 60); ps = pos0[-sh:] + pos0[:-sh]
            m = evaluate(ps, R, i0, n)
            cnt_f += m["final"] >= base["final"]; cnt_d += m["dd"] >= base["dd"]
        res[nm] = (cnt_f / N, cnt_d / N)
    L += ["", "== Random-timing null for the base rule (800 circular shifts of its IN/OUT series, same time in market) ==",
          *(f"  {nm}: share of shifts ending at least as high as the base: {a:.2f}; share with a drawdown at least as small: {d:.2f}" for nm, (a, d) in res.items())]
    L += ["", "Read: start with family 1 and 2. If the neighbours of 200/50 and of the OI settings give similar results, the live rule sits on a plateau and is not a fragile pick. A family that helps both assets in both halves and cuts drawdown is the kind of change worth adding to a live paper test first. Everything here is one history with about three market phases."]
    text = "\n".join(L); open(os.path.join(OUT, "lab33_summary.txt"), "w").write(text + "\n"); print(text)

if __name__ == "__main__":
    main()
