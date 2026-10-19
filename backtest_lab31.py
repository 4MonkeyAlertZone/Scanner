#!/usr/bin/env python3
"""Lab 31: DIP AUDIT. The goal is to dodge as many dips as possible while the BTC 200-day gate says 'bull', without paying too much in missed rallies.
Dips: every alt-basket drawdown of 15%+ (zigzag on the equal-weight alt index) and every BTC pullback of 10%+ that started while the gate was ON.
Rules (all also require the gate; all declared in advance): OI step-outs B/C (B = BTC OI at a 180-day high; C = B and OI up 15%+ in 30d) with cash for 7/14/30 days; I4 = 3 days cash after an
unusually large intraday 4-hour OI jump (top 10% of the past year); P20 / P50 = cash while BTC is below its 20 / 50-day average; M7 = 7 days cash after a BTC 7-day fall of 8%+;
ALT20 = cash while the alt index is below its own 20-day average; U1 = B-cool14 or P20; U2 = C-cool14 or M7.
For each rule: how many dips were dodged (>= 50% of the fall avoided), how many of the rule's own cash periods were GOOD (basket fell 10%+ meanwhile) or BAD (basket rose 10%+), time in cash while the gate was on,
period results, and a random-timing comparison (the same cash periods shifted to random dates: does the rule dodge more dips than chance?). Writes lab31_summary.txt."""
import csv, os, math, random, calendar, statistics as st
from multiprocessing import Pool
from datetime import datetime, timezone
import scanner, backtest as B
from backtest_lab23 import zig, dstr, med, STABLES

COST = 0.001
P1 = calendar.timegm((2021, 12, 1, 0, 0, 0)); P2 = calendar.timegm((2022, 12, 1, 0, 0, 0))
PER = [("cycle 1", lambda t: t < P1), ("bear", lambda t: P1 <= t < P2), ("cycle 2", lambda t: t >= P2)]

def load(s):
    try: return s, B.hist_crypto(s, "1d", 2600)
    except Exception: return s, []

def pct_rank(series, i, win=365, minn=120):
    v = series[i]
    if v is None: return None
    prev = [x for x in series[max(0, i - win):i] if x is not None]
    return sum(1 for x in prev if x < v) / len(prev) if len(prev) >= minn else None

def main():
    path = os.path.join(scanner.HERE, "btc_metrics_daily.csv")
    if not os.path.exists(path): print("btc_metrics_daily.csv missing - run lab 26 first"); return
    oi_by = {}
    for r in csv.DictReader(open(path)):
        try: oi_by[calendar.timegm(datetime.strptime(r["date"], "%Y-%m-%d").timetuple())] = float(r["open_interest_btc"])
        except Exception: pass
    m4_by = {}; mp = os.path.join(scanner.HERE, "metrics_daily_multi.csv")
    if os.path.exists(mp):
        for r in csv.DictReader(open(mp)):
            if r["sym"] == "BTC":
                try: m4_by[calendar.timegm(datetime.strptime(r["date"], "%Y-%m-%d").timetuple())] = float(r["max_4h_oi_rise"])
                except Exception: pass
    btc = B.hist_crypto("BTC", "1d", 2600); fx = []
    for t, o, h, l, c, v in btc:
        hb, lb = max(o, c), min(o, c); fx.append((t, o, min(h, hb * 1.25), max(l, lb / 1.25), c, v))
    T = [r[0] for r in fx]; H = [r[2] for r in fx]; L = [r[3] for r in fx]; C = [r[4] for r in fx]; n = len(fx)
    OI = [oi_by.get(t - t % 86400) for t in T]; M4 = [m4_by.get(t - t % 86400) for t in T]
    first = next(i for i in range(n) if OI[i]); last_oi = max(i for i in range(n) if OI[i])
    hi180 = [False] * n; o30 = [None] * n
    for i in range(first + 120, last_oi + 1):
        prev = [x for x in OI[i - 180:i] if x]; hi180[i] = bool(OI[i]) and len(prev) > 100 and OI[i] >= max(prev)
        if OI[i] and OI[i - 30]: o30[i] = OI[i] / OI[i - 30] - 1
    WB = [bool(hi180[i]) for i in range(n)]; WC = [bool(hi180[i] and o30[i] is not None and o30[i] >= .15) for i in range(n)]
    pM4 = [pct_rank(M4, i) if M4[i] is not None else None for i in range(n)]
    WI = [pM4[i] is not None and pM4[i] >= .90 for i in range(n)]
    gate = [i >= 199 and C[i] > sum(C[i - 199:i + 1]) / 200 for i in range(n)]
    coins = [t for t in scanner.top100()[:45] if t.upper() not in STABLES]
    with Pool(2) as p: res = p.map(load, coins, chunksize=1)
    A = {s: {r[0]: r[4] for r in rows} for s, rows in res if len(rows) > 500}
    ret = [0.0] * n
    for i in range(1, n):
        q = [A[s][T[i]] / A[s][T[i - 1]] - 1 for s in A if T[i] in A[s] and T[i - 1] in A[s]]; ret[i] = sum(q) / len(q) if q else 0.0
    idx = [1.0]
    for i in range(1, n): idx.append(idx[-1] * (1 + ret[i]))
    ma = lambda s, k: [sum(s[max(0, i - k + 1):i + 1]) / min(k, i + 1) for i in range(n)]
    ma20, ma50, ima20 = ma(C, 20), ma(C, 50), ma(idx, 20)
    days = list(range(first + 120, min(n - 1, last_oi + 1))); d0, d1 = days[0], days[-1]
    def out_cool(W, N):
        o = [False] * n; left = 0
        for i in range(n):
            if W[i]: left = N
            o[i] = left > 0
            if left > 0: left -= 1
        return o
    OR = lambda a, b: [x or y for x, y in zip(a, b)]
    M7 = [i >= 7 and C[i] / C[i - 7] - 1 <= -.08 for i in range(n)]
    OUT = {"B+cool7": out_cool(WB, 7), "B+cool14": out_cool(WB, 14), "B+cool30": out_cool(WB, 30), "C+cool7": out_cool(WC, 7), "C+cool14": out_cool(WC, 14), "C+cool30": out_cool(WC, 30),
           "I4 (intraday)": out_cool(WI, 3), "P20 (BTC<20d)": [C[i] < ma20[i] for i in range(n)], "P50 (BTC<50d)": [C[i] < ma50[i] for i in range(n)], "M7 (7d fall)": out_cool(M7, 7),
           "ALT20 (alts<20d)": [idx[i] < ima20[i] for i in range(n)]}
    OUT["U1 B14|P20"] = OR(OUT["B+cool14"], OUT["P20 (BTC<20d)"]); OUT["U2 C14|M7"] = OR(OUT["C+cool14"], OUT["M7 (7d fall)"])
    names = list(OUT)
    expo = lambda out: [gate[i] and not out[i] for i in range(n)]
    def run(ex, lo_=d0, hi_=d1):
        eq = 1.0; pk = 1.0; mdd = 0.0; prev = 0; inm = 0
        for i in range(lo_, hi_):
            e_ = 1 if ex[i] else 0; eq *= 1 + ret[i + 1] * e_ - COST * abs(e_ - prev); prev = e_; inm += e_; pk = max(pk, eq); mdd = max(mdd, 1 - eq / pk)
        return eq, mdd, inm / max(1, hi_ - lo_)
    # ---- dips ----
    def dips(series_h, series_l, thr, use_idx=False):
        z = zig(series_h, series_l, thr); out = []
        for a, b in zip(z, z[1:]):
            if a[2] == "H" and b[2] == "L" and b[0] > a[0] and a[0] >= d0 and b[0] <= d1 and gate[a[0]]:
                rb = 1.0
                for i in range(a[0], b[0]): rb *= 1 + ret[i + 1]
                if rb - 1 <= -.05: out.append(dict(pi=a[0], ti=b[0], rb=rb - 1, depth=1 - b[1] / a[1]))
        return out
    AD = dips(idx, idx, .15); BD = dips(H, L, .10)
    def avoided(ex, x):
        rs = 1.0
        for i in range(x["pi"], x["ti"]): rs *= 1 + ret[i + 1] * (1 if ex[i] else 0)
        return ((rs - 1) - x["rb"]) / abs(x["rb"])
    def dodged(ex, ev): return sum(1 for x in ev if avoided(ex, x) >= .5)
    def outruns(ex):
        """cash periods while the gate is on: (good, bad, neutral, sum of avoided log-return)"""
        g = b_ = nn = 0; tot = 0.0; i = d0
        while i < d1:
            if gate[i] and not ex[i]:
                j = i; r = 1.0
                while j < d1 and gate[j] and not ex[j]: r *= 1 + ret[j + 1]; j += 1
                if r - 1 <= -.10: g += 1
                elif r - 1 >= .10: b_ += 1
                else: nn += 1
                tot += -math.log(r) if r > 0 else 0; i = j
            else: i += 1
        return g, b_, nn, tot
    Lx = [f"LAB 31  {datetime.now(timezone.utc):%Y-%m-%d}  DIP AUDIT while the BTC 200-day gate is on. Window {dstr(T[d0])} to {dstr(T[d1])}; alt basket = {len(A)} large coins listed today (survivorship-flattered); 0.1% per switch.", "",
          f"Dips studied (gate ON at the peak): {len(AD)} alt-basket drawdowns of 15%+ (median fall {med([x['rb'] for x in AD]):.0%}) and {len(BD)} BTC pullbacks of 10%+ (median {med([-x['depth'] for x in BD]):.0%}). 'dodged' = the rule avoided at least half of the fall.", "",
          f"{'rule':<18}{'alt dips dodged':>16}{'BTC dips dodged':>16}{'cash when gate on':>18}{'good/bad/neutral cash spells':>30}{'net avoided':>12}   {'random-timing: dodged (mean of shifts)':>40}"]
    random.seed(9); span = list(range(d0, d1 + 1)); Ln = len(span); R = {}
    def shifted(out):
        k = random.randint(60, Ln - 60); sh = [False] * n
        for j, i in enumerate(span): sh[i] = out[span[(j + k) % Ln]]
        return sh
    for nm in ["gate only"] + names:
        out = [False] * n if nm == "gate only" else OUT[nm]; ex = expo(out)
        gd = [i for i in days if gate[i]]; cash = sum(1 for i in gd if out[i]) / max(1, len(gd))
        g_, b_, n_, tot = outruns(ex); da, db = dodged(ex, AD), dodged(ex, BD)
        if nm != "gate only":
            sa = []; sb = []; sm = []
            for _ in range(100):
                s = expo(shifted(out)); sa.append(dodged(s, AD)); sb.append(dodged(s, BD))
            rnd = f"alt {da} vs {sum(sa) / len(sa):.1f}; BTC {db} vs {sum(sb) / len(sb):.1f}"
        else: rnd = ""
        Lx.append(f"{nm:<18}{str(da) + ' of ' + str(len(AD)):>16}{str(db) + ' of ' + str(len(BD)):>16}{cash:>18.0%}{str(g_) + ' / ' + str(b_) + ' / ' + str(n_):>30}{tot:>+12.2f}   {rnd:>40}")
        R[nm] = ex
    Lx += ["", "cash spells = periods the rule was in cash while the gate was on; good = alt basket fell 10%+ during the spell, bad = it rose 10%+ (a missed rally); net avoided = sum of -log(basket return) over those spells (positive = cash helped overall)."]
    Lx += ["", "== Results by period (multiple, max drawdown, share of days invested) ==", f"{'rule':<18}{'whole':>22}" + "".join(f"{pn:>22}" for pn, _ in PER)]
    RES = {}
    for nm, ex in [("hold alt basket", [True] * n)] + [(k, R[k]) for k in ["gate only"] + names]:
        cells = []; per = []
        for pn, sub in PER:
            ii = [i for i in days if sub(T[i])]
            if len(ii) < 30: cells.append(f"{'--':>22}"); per.append(None); continue
            m, dd, im = run(ex, ii[0], ii[-1]); per.append(m); cells.append(f"{'x%.2f dd %.0f%% in %.0f%%' % (m, dd * 100, im * 100):>22}")
        m, dd, im = run(ex); RES[nm] = (m, per); Lx.append(f"{nm:<18}{'x%.2f dd %.0f%% in %.0f%%' % (m, dd * 100, im * 100):>22}" + "".join(cells))
    g = RES["gate only"][1]; Lx += ["", "== Leave-one-period-out: pick the rule with the best (rule / gate-only) multiple on the other two periods, then see its ratio on the held-out period =="]
    tp = []; ta = []
    for k, (pn, _) in enumerate(PER):
        tr = [j for j in range(3) if j != k and g[j] and all(RES[nm][1][j] for nm in names)]
        if g[k] is None or len(tr) < 2: Lx.append(f"  hold out {pn}: not enough periods"); continue
        best = max(names, key=lambda nm: sum(math.log(RES[nm][1][j] / g[j]) for j in tr)); r_ = RES[best][1][k] / g[k]; allr = sum(RES[nm][1][k] / g[k] for nm in names) / len(names); tp.append(r_); ta.append(allr)
        Lx.append(f"  hold out {pn}: picked {best:<16} -> ratio vs gate {r_:.2f}; average of all rules {allr:.2f}")
    if tp: Lx.append(f"  average: picked {sum(tp) / len(tp):.2f} vs all rules {sum(ta) / len(ta):.2f}")
    Lx += ["", "Read: a rule is useful for your goal only if it dodges clearly more dips than its random-timing average, has more GOOD than BAD cash spells, a positive net avoided, and does not wreck the period multiples.",
           "Caveats: alt basket survivorship; ~3 market phases; OI-based rules start mid-2021; many rules compared, so differences of a dip or two are noise; fills at the signal-day close."]
    text = "\n".join(Lx); open(os.path.join(scanner.HERE, "lab31_summary.txt"), "w").write(text + "\n"); print(text)
    try: scanner.notify("Strategy lab 31 finished", "Dip audit done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
