#!/usr/bin/env python3
"""Lab 27: (1) is the open-interest (OI) warning about DOWN moves or just BIG moves? (2) can the OI surge be detected dynamically (scaled to OI's own recent volatility, its own trend, new highs, or the rise from its latest low) instead of a fixed 30 days?
(3) does stepping out of the alt basket for 7 days after an OI warning improve the BTC-200-day-gated basket? Reads btc_metrics_daily.csv written by lab 26.
Honest limits: the flags were chosen after seeing lab 26 on the same data, so part 3 is NOT out-of-sample; a circular-shift null shows what random timing of the same warnings would give. Writes lab27_summary.txt."""
import csv, os, math, random, calendar, statistics as st
from multiprocessing import Pool
from datetime import datetime, timezone
import scanner, backtest as B
from backtest_lab23 import STABLES, dstr, med

COST = 0.001; COOL = 7
P1 = calendar.timegm((2021, 12, 1, 0, 0, 0)); P2 = calendar.timegm((2022, 12, 1, 0, 0, 0))
PER = [("cycle 1 (May-Nov 2021)", lambda t: t < P1), ("bear (Dec 2021-Nov 2022)", lambda t: P1 <= t < P2), ("cycle 2 (Dec 2022 on)", lambda t: t >= P2)]

def load(sym):
    try: return sym, B.hist_crypto(sym, "1d", 2600)
    except Exception: return sym, []

def sd(x):
    return st.pstdev(x) if len(x) > 5 else None

def main():
    path = os.path.join(scanner.HERE, "btc_metrics_daily.csv")
    if not os.path.exists(path): print("btc_metrics_daily.csv missing - run lab 26 first"); return
    oi_by = {}
    for r in csv.DictReader(open(path)):
        try: oi_by[calendar.timegm(datetime.strptime(r["date"], "%Y-%m-%d").timetuple())] = float(r["open_interest_btc"])
        except Exception: pass
    btc = B.hist_crypto("BTC", "1d", 2600); fixed = []
    for t, o, h, l, c, v in btc:
        hb, lb = max(o, c), min(o, c); fixed.append((t, o, min(h, hb * 1.25), max(l, lb / 1.25), c, v))
    btc = fixed; T = [r[0] for r in btc]; H = [r[2] for r in btc]; L = [r[3] for r in btc]; C = [r[4] for r in btc]; n = len(btc)
    OI = [oi_by.get(t) for t in T]
    first = next(i for i in range(n) if OI[i]); last_oi = max(i for i in range(n) if OI[i])
    # ---- dynamic OI measures, each using only data up to day i ----
    lo = [math.log(x) if x else None for x in OI]
    ema = [None] * n; e = None
    for i in range(n):
        if lo[i] is None: ema[i] = e; continue
        e = lo[i] if e is None else e + (lo[i] - e) * 2 / 61; ema[i] = e
    dev = [lo[i] - ema[i] if lo[i] is not None and ema[i] is not None else None for i in range(n)]
    dlo = [lo[i] - lo[i - 1] if i and lo[i] is not None and lo[i - 1] is not None else None for i in range(n)]
    z_dev = [None] * n; surge = [None] * n; hi180 = [False] * n; rise = [None] * n; win = [None] * n
    for i in range(first + 120, last_oi + 1):
        if lo[i] is None: continue
        s1 = sd([x for x in dev[i - 90:i] if x is not None]); s2 = sd([x for x in dlo[i - 90:i] if x is not None])
        if s1 and dev[i] is not None: z_dev[i] = dev[i] / s1
        if s2 and lo[i - 7] is not None: surge[i] = (lo[i] - lo[i - 7]) / (s2 * math.sqrt(7))
        prev = [x for x in OI[i - 180:i] if x]
        hi180[i] = len(prev) > 100 and OI[i] >= max(prev)
        seg = [(OI[j], j) for j in range(i - 60, i + 1) if OI[j]]
        m, j = min(seg); rise[i] = OI[i] / m - 1; win[i] = i - j
    ch = lambda s, i, k: (s[i] / s[i - k] - 1) if i >= k and s[i] and s[i - k] else None
    ok = lambda x, v: x is not None and x >= v
    flags = [("REFERENCE fixed: OI up >=15% in 30d", lambda i: ok(ch(OI, i, 30), .15)),
             ("OI above its 60d trend by >=1.5 std", lambda i: ok(z_dev[i], 1.5)), ("OI above its 60d trend by >=2.0 std", lambda i: ok(z_dev[i], 2.0)),
             ("7d OI rise >=2x its normal weekly noise", lambda i: ok(surge[i], 2.0)), ("7d OI rise >=3x its normal weekly noise", lambda i: ok(surge[i], 3.0)),
             ("OI at a new 180-day high", lambda i: hi180[i]),
             ("OI up >=15% from its lowest of last 60d", lambda i: ok(rise[i], .15)), ("OI up >=25% from its lowest of last 60d", lambda i: ok(rise[i], .25))]
    days = [i for i in range(first + 120, min(n - 15, last_oi + 1)) if OI[i]]
    def fdd(i, d=14): j = min(n - 1, i + d); return 1 - min(L[i + 1:j + 1]) / C[i]
    def fup(i, d=14): j = min(n - 1, i + d); return max(H[i + 1:j + 1]) / C[i] - 1
    def eps_of(fl, allf):
        if allf: return fl[::14]
        out = []; last = -99
        for i in fl:
            if i - last > 7: out.append(i)
            last = i
        return out
    def stat(f, sub=None, allf=False):
        fl = [i for i in days if f(i) and (sub is None or sub(T[i]))]
        if not fl: return None
        ep = eps_of(fl, allf)
        return len(fl), len(ep), sum(fdd(i) >= .10 for i in ep) / len(ep), sum(fup(i) >= .10 for i in ep) / len(ep)
    allf = lambda i: True
    b = stat(allf, None, True); pb = [stat(allf, s, True) for _, s in PER]
    Lx = [f"LAB 27  {datetime.now(timezone.utc):%Y-%m-%d}  BTC open interest warnings: direction, dynamic detection, and an exposure test. OI data {dstr(T[first])} to {dstr(T[last_oi])}.", "",
          "== 1+2. Down vs up, fixed vs dynamic. Episodes = flagged days merged within 7 days. dn = share followed by a 10%+ fall within 14 days (low vs close); up = by a 10%+ rise (high vs close). z vs the all-days base rate. ==",
          f"{'flag':<44}{'days':>6}{'eps':>5}{'dn':>6}{'z dn':>6}{'up':>6}{'z up':>6}   " + "  ".join(f"{p[0][:9]:>16}" for p in PER),
          f"{'ALL DAYS (base)':<44}{b[0]:>6}{b[1]:>5}{b[2]:>6.0%}{'':>6}{b[3]:>6.0%}{'':>6}   " + "  ".join(f"{(str(x[1]) + ' eps dn ' + format(x[2], '.0%') + ' up ' + format(x[3], '.0%')) if x else '--':>16}" for x in pb)]
    zf = lambda p, q, k: (p - q) / math.sqrt(q * (1 - q) / k) if k and 0 < q < 1 else float("nan")
    for name, f in flags:
        s = stat(f)
        if not s: Lx.append(f"{name:<44}     0"); continue
        cells = []
        for (pn, sub), bb in zip(PER, pb):
            ps = stat(f, sub); cells.append(f"{(str(ps[1]) + ' eps dn ' + format(ps[2], '.0%') + ' up ' + format(ps[3], '.0%')) if ps else '--':>16}")
        Lx.append(f"{name:<44}{s[0]:>6}{s[1]:>5}{s[2]:>6.0%}{zf(s[2], b[2], s[1]):>6.1f}{s[3]:>6.0%}{zf(s[3], b[3], s[1]):>6.1f}   " + "  ".join(cells))
    wins = [win[i] for i in days if ok(rise[i], .15)]
    if wins: Lx.append(f"The 'rise from lowest of last 60d' window the data chose: median {med(wins):.0f} days (range {min(wins)}-{max(wins)}), not a fixed 30.")
    Lx.append("Read: if 'dn' is far above 'up' the warning is about falls; if both are above base it only says 'big move coming'.")
    # ---- part 3: alt basket exposure ----
    coins = [t for t in scanner.top100()[:45] if t.upper() not in STABLES]
    with Pool(2) as p: res = p.map(load, coins, chunksize=1)
    A = {s: {r[0]: r[4] for r in rows} for s, rows in res if len(rows) > 500}
    ret = [0.0] * n
    for i in range(1, n):
        r = [A[s][T[i]] / A[s][T[i - 1]] - 1 for s in A if T[i] in A[s] and T[i - 1] in A[s]]
        ret[i] = sum(r) / len(r) if r else 0.0
    gate = [i >= 199 and C[i] > sum(C[i - 199:i + 1]) / 200 for i in range(n)]
    d0, d1 = days[0], days[-1]
    def run(expo, lo_=d0, hi_=d1):
        """expo[i] = exposure decided at close of i, earned on day i+1. Returns equity multiple and max drawdown over [lo_,hi_]."""
        eq = 1.0; peak = 1.0; mdd = 0.0; prev = 0
        for i in range(lo_, hi_):
            e_ = 1 if expo[i] else 0
            eq *= 1 + ret[i + 1] * e_ - COST * abs(e_ - prev); prev = e_
            peak = max(peak, eq); mdd = max(mdd, 1 - eq / peak)
        return eq, mdd
    def make_flag_series(f): return [bool(i in daysset and f(i)) for i in range(n)]
    daysset = set(range(d0, d1 + 1))
    def recent(fs): return [any(fs[max(0, i - COOL + 1):i + 1]) for i in range(n)]
    hold = [True] * n; gonly = gate[:]
    Lx += ["", f"== 3. Alt basket (equal-weight of {len(A)} large coins listed today; survivorship-flattered) with OI warnings. Account in cash for {COOL} days after any warning; 0.1% per switch. NOT out-of-sample: flags were picked after lab 26. ==",
           f"{'rule':<52}{'whole':>14}" + "".join(f"{p[0][:9]:>18}" for p in PER)]
    def row(name, expo):
        cells = []
        for pn, sub in PER:
            ii = [i for i in days if sub(T[i])]
            if len(ii) < 30: cells.append(f"{'--':>18}"); continue
            m, dd = run(expo, ii[0], ii[-1]); cells.append(f"{'x%.2f dd %.0f%%' % (m, dd * 100):>18}")
        m, dd = run(expo); Lx.append(f"{name:<52}{'x%.2f dd %.0f%%' % (m, dd * 100):>14}" + "".join(cells)); return m
    row("hold the alt basket", hold); mg = row("BTC 200-day gate only", gonly)
    best = None
    series = {}
    for name, f in flags:
        fs = make_flag_series(f); series[name] = fs; rc = recent(fs)
        m = row(f"gate + out after warning: {name[:36]}", [gate[i] and not rc[i] for i in range(n)])
    # shift null for each flag: same warning series moved to random dates (keeps clustering), full-period multiple
    random.seed(7); Lx += ["", "Random-timing check: the same warning dates shifted by a random number of days (circular, at least 60 days), 300 shifts. 'beats' = share of shifts whose result was WORSE than the real warnings (want >95%)."]
    span = list(range(d0, d1 + 1)); L_ = len(span)
    for name, f in flags:
        fs = series[name]; real = run([gate[i] and not recent(fs)[i] for i in range(n)])[0]; worse = 0; tot = 0
        for _ in range(300):
            k = random.randint(60, L_ - 60); sh = [False] * n
            for j, i in enumerate(span): sh[i] = fs[span[(j + k) % L_]]
            rc = recent(sh); m = run([gate[i] and not rc[i] for i in range(n)])[0]; worse += m < real; tot += 1
        Lx.append(f"  {name[:50]:<52} real x{real:.2f} vs gate-only x{mg:.2f}; beats {worse / tot:.0%} of random timings")
    Lx += ["", "Read: part 3 matters only if the warning rule beats gate-only in the bear year AND does not give up most of the bull profit AND beats most random timings. Three market phases, flags chosen after the fact: treat as a lead, not proof."]
    text = "\n".join(Lx); open(os.path.join(scanner.HERE, "lab27_summary.txt"), "w").write(text + "\n"); print(text)
    try: scanner.notify("Strategy lab 27 finished", "OI warning study done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
