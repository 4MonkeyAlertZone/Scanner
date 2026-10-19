#!/usr/bin/env python3
"""Lab 30: be in alts during the bull phase, out around the top and through the bear. How close to each top did each rule get out, and how much of the fall did it avoid?
Alt basket (large coins listed today, equal weight, survivorship-flattered) with: hold; BTC 200-day gate; and the gate plus an open-interest (OI) step-out.
Warnings (from labs 27/28): B = BTC OI at a new 180-day high; C = B and OI up 15%+ in 30 days. Step-out variants, all declared in advance:
  cool7 / cool14 / cool30 = cash for N days after a warning; dyn = cash until OI is back at or below its 60-day trend (min 3 days);
  brk20 / brk50 = after a warning (armed for 30 days) go to cash if BTC closes below its 20-day / 50-day average, back in when it is above again or the 30 days end.
Every variant also needs the BTC 200-day gate. Part 1 lists BTC falls of 20%+; part 2 shows per-period results; part 3 is the EXIT AUDIT (days after the peak, BTC % below its peak at the exit, share of the alt basket's fall avoided);
part 4 is leave-one-period-out and a random-timing check. Reads btc_metrics_daily.csv from lab 26. Writes lab30_summary.txt."""
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

def main():
    path = os.path.join(scanner.HERE, "btc_metrics_daily.csv")
    if not os.path.exists(path): print("btc_metrics_daily.csv missing - run lab 26 first"); return
    oi_by = {}
    for r in csv.DictReader(open(path)):
        try: oi_by[calendar.timegm(datetime.strptime(r["date"], "%Y-%m-%d").timetuple())] = float(r["open_interest_btc"])
        except Exception: pass
    btc = B.hist_crypto("BTC", "1d", 2600); fx = []
    for t, o, h, l, c, v in btc:
        hb, lb = max(o, c), min(o, c); fx.append((t, o, min(h, hb * 1.25), max(l, lb / 1.25), c, v))
    T = [r[0] for r in fx]; H = [r[2] for r in fx]; L = [r[3] for r in fx]; C = [r[4] for r in fx]; n = len(fx)
    OI = [oi_by.get(t - t % 86400) for t in T]
    first = next(i for i in range(n) if OI[i]); last_oi = max(i for i in range(n) if OI[i])
    lo = [math.log(x) if x else None for x in OI]; ema = [None] * n; e = None
    for i in range(n):
        if lo[i] is not None: e = lo[i] if e is None else e + (lo[i] - e) * 2 / 61
        ema[i] = e
    dev = [lo[i] - ema[i] if lo[i] is not None and ema[i] is not None else None for i in range(n)]
    hi180 = [False] * n; o30 = [None] * n
    for i in range(first + 120, last_oi + 1):
        prev = [x for x in OI[i - 180:i] if x]; hi180[i] = bool(OI[i]) and len(prev) > 100 and OI[i] >= max(prev)
        if OI[i] and OI[i - 30]: o30[i] = OI[i] / OI[i - 30] - 1
    WB = [bool(hi180[i]) for i in range(n)]; WC = [bool(hi180[i] and o30[i] is not None and o30[i] >= .15) for i in range(n)]
    ma = lambda k: [sum(C[max(0, i - k + 1):i + 1]) / min(k, i + 1) for i in range(n)]
    ma20, ma50 = ma(20), ma(50)
    gate = [i >= 199 and C[i] > sum(C[i - 199:i + 1]) / 200 for i in range(n)]
    coins = [t for t in scanner.top100()[:45] if t.upper() not in STABLES]
    with Pool(2) as p: res = p.map(load, coins, chunksize=1)
    A = {s: {r[0]: r[4] for r in rows} for s, rows in res if len(rows) > 500}
    ret = [0.0] * n
    for i in range(1, n):
        q = [A[s][T[i]] / A[s][T[i - 1]] - 1 for s in A if T[i] in A[s] and T[i - 1] in A[s]]; ret[i] = sum(q) / len(q) if q else 0.0
    days = list(range(first + 120, min(n - 1, last_oi + 1))); d0, d1 = days[0], days[-1]
    # ---- step-out rules: each maps a warning series to a "stay out" series ----
    def out_cool(W, N):
        o = [False] * n; left = 0
        for i in range(n):
            if W[i]: left = N
            o[i] = left > 0
            if left > 0: left -= 1
        return o
    def out_dyn(W):
        o = [False] * n; st_ = False; since = 0
        for i in range(n):
            if W[i]: st_ = True; since = 0
            elif st_:
                since += 1
                if since >= 3 and dev[i] is not None and dev[i] <= 0: st_ = False
            o[i] = st_
        return o
    def out_brk(W, MA):
        o = [False] * n; left = 0
        for i in range(n):
            if W[i]: left = 30
            o[i] = left > 0 and C[i] < MA[i]
            if left > 0: left -= 1
        return o
    VARS = []
    for wn, W in (("B", WB), ("C", WC)):
        VARS += [(f"{wn}+cool7", lambda W=W: out_cool(W, 7)), (f"{wn}+cool14", lambda W=W: out_cool(W, 14)), (f"{wn}+cool30", lambda W=W: out_cool(W, 30)),
                 (f"{wn}+dyn", lambda W=W: out_dyn(W)), (f"{wn}+brk20", lambda W=W: out_brk(W, ma20)), (f"{wn}+brk50", lambda W=W: out_brk(W, ma50))]
    def expo_from(outs): return [gate[i] and not outs[i] for i in range(n)]
    def run(expo, lo_=d0, hi_=d1):
        eq = 1.0; pk = 1.0; mdd = 0.0; prev = 0; inm = 0; sw = 0
        for i in range(lo_, hi_):
            e_ = 1 if expo[i] else 0; eq *= 1 + ret[i + 1] * e_ - COST * abs(e_ - prev); sw += e_ != prev; prev = e_; inm += e_; pk = max(pk, eq); mdd = max(mdd, 1 - eq / pk)
        return eq, mdd, inm / max(1, hi_ - lo_), sw
    # ---- BTC falls of 20%+ ----
    ev = []
    for a, b in zip(zig(H, L, .20), zig(H, L, .20)[1:]):
        if a[2] == "H" and b[2] == "L" and b[0] > a[0] and b[0] > d0 and a[0] >= d0 - 40:
            pi, ti = a[0], b[0]; rb = 1.0
            for i in range(pi, ti): rb *= 1 + ret[i + 1]
            ev.append(dict(pi=pi, ti=ti, depth=1 - b[1] / a[1], rb=rb - 1, peak=a[1]))
    Lx = [f"LAB 30  {datetime.now(timezone.utc):%Y-%m-%d}  In alts in the bull, out around the top and through the bear. OI data {dstr(T[first])} to {dstr(T[last_oi])}. Alt basket = {len(A)} large coins listed today (survivorship-flattered), 0.1% per switch.", "",
          "== 1. BTC falls of 20%+ in the test window (peak to trough on daily highs/lows) ==", f"{'peak':<12}{'trough':<12}{'BTC fall':>9}{'days':>6}{'alt basket fall':>17}"]
    for k, x in enumerate(ev): Lx.append(f"{dstr(T[x['pi']]):<12}{dstr(T[x['ti']]):<12}{-x['depth']:>9.0%}{x['ti'] - x['pi']:>6}{x['rb']:>17.0%}   (event {k + 1})")
    # ---- strategies ----
    S = [("hold alt basket", [True] * n), ("BTC 200-day gate only", gate[:])] + [(nm, expo_from(f())) for nm, f in VARS]
    Lx += ["", "== 2. Results (multiple, max drawdown, share of days invested) =="]
    Lx.append(f"{'rule':<24}{'whole':>20}" + "".join(f"{pn:>20}" for pn, _ in PER) + f"{'switches':>9}")
    R = {}
    for nm, ex in S:
        cells = []; per = []
        for pn, sub in PER:
            ii = [i for i in days if sub(T[i])]
            if len(ii) < 30: cells.append(f"{'--':>20}"); per.append(None); continue
            m, dd, im, sw = run(ex, ii[0], ii[-1]); per.append(m); cells.append(f"{'x%.2f dd %.0f%% in %.0f%%' % (m, dd * 100, im * 100):>20}")
        m, dd, im, sw = run(ex); R[nm] = (m, per); Lx.append(f"{nm:<24}{'x%.2f dd %.0f%% in %.0f%%' % (m, dd * 100, im * 100):>20}" + "".join(cells) + f"{sw:>9}")
    # ---- exit audit ----
    Lx += ["", "== 3. EXIT AUDIT: for each BTC fall: exit day vs the peak ('d+12' = 12 days after; 'd-5' = out 5 days BEFORE), BTC % below its peak at that exit, and the share of the alt basket's fall avoided (100% = fully out; negative = lost more than buy-and-hold) ==",
          ""]
    def audit(ex, x):
        pi, ti = x["pi"], x["ti"]; rs = 1.0
        for i in range(pi, ti): rs *= 1 + ret[i + 1] * (1 if ex[i] else 0)
        big = x["rb"] <= -.05
        avoided = ((rs - 1) - x["rb"]) / abs(x["rb"]) if big else None
        w0 = max(d0, pi - 20)
        xi = next((i for i in range(w0, ti) if not ex[i] and all(not ex[j] for j in range(i, min(i + 5, ti)))), None)
        av = f"{avoided:.0%}" if avoided is not None else "n/a"
        if xi is None: return f"never out/{av}"
        if xi == w0: return f"pre-out/{av}"
        return f"d{xi - pi:+d} {max(0, 1 - C[xi] / x['peak']):.0%}/{av}"
    Lx[-1:] = []
    Lx += [f"{'event (BTC peak, fall, alt basket fall)':<46}" + "".join(f"{nm:>17}" for nm, _ in S[1:])]
    for k, x in enumerate(ev):
        Lx.append(f"{k + 1:>2} {dstr(T[x['pi']])} {-x['depth']:>5.0%} / alts {x['rb']:>5.0%}".ljust(46) + "".join(f"{audit(ex, x):>17}" for nm, ex in S[1:]))
    Lx.append("cell = exit day vs the peak and BTC % below its peak at the exit / share of the alt fall avoided. 'pre-out' = in cash when the 20-day look-back began (e.g. the gate was already off). 'n/a' = the alt basket fell less than 5% in that window.")

    # ---- LOPO ----
    Lx += ["", "== 4a. Leave-one-period-out: choose the variant with the best (variant / gate-only) multiple on the other two periods, then see its ratio on the held-out period. 'all variants' = the average ratio of every variant there =="]
    g = R["BTC 200-day gate only"][1]; names = [nm for nm, _ in S[2:]]; tp = []; ta = []
    for k, (pn, _) in enumerate(PER):
        tr = [j for j in range(3) if j != k and g[j] and all(R[nm][1][j] for nm in names)]
        if g[k] is None or len(tr) < 2: Lx.append(f"  hold out {pn}: not enough periods"); continue
        best = max(names, key=lambda nm: sum(math.log(R[nm][1][j] / g[j]) for j in tr)); r_ = R[best][1][k] / g[k]
        allr = sum(R[nm][1][k] / g[k] for nm in names) / len(names); tp.append(r_); ta.append(allr)
        Lx.append(f"  hold out {pn}: picked {best:<10} -> x{R[best][1][k]:.2f} vs gate x{g[k]:.2f} (ratio {r_:.2f}); all variants avg ratio {allr:.2f}")
    if tp: Lx.append(f"  average ratio picked {sum(tp) / len(tp):.2f} vs all variants {sum(ta) / len(ta):.2f}   (>1 = better than gate-only)")
    Lx += ["", "== 4b. Random-timing check: the warning dates shifted at random (300 circular shifts, >= 60 days); 'beats' = share of shifts with a WORSE whole-period multiple than the real dates (want > 95%) =="]
    random.seed(3); span = list(range(d0, d1 + 1)); Ln = len(span); gm = R["BTC 200-day gate only"][0]
    mk = {}
    for wn, W in (("B", WB), ("C", WC)):
        mk[f"{wn}+cool7"] = lambda w: out_cool(w, 7); mk[f"{wn}+cool14"] = lambda w: out_cool(w, 14); mk[f"{wn}+cool30"] = lambda w: out_cool(w, 30)
        mk[f"{wn}+dyn"] = lambda w: out_dyn(w); mk[f"{wn}+brk20"] = lambda w: out_brk(w, ma20); mk[f"{wn}+brk50"] = lambda w: out_brk(w, ma50)
    for nm in names:
        W = WB if nm.startswith("B") else WC; real = R[nm][0]; worse = 0
        for _ in range(300):
            k = random.randint(60, Ln - 60); sh = [False] * n
            for j, i in enumerate(span): sh[i] = W[span[(j + k) % Ln]]
            worse += run(expo_from(mk[nm](sh)))[0] < real
        Lx.append(f"  {nm:<12} real x{real:.2f} vs gate-only x{gm:.2f}; beats {worse / 300:.0%} of random timings")
    Lx += ["", "Read: for your goal the exit audit matters most. A good rule exits within days of the peak (or before), at a small BTC % below the peak, and avoids most of each fall without giving up the bull profit in part 2. Treat small differences between variants as noise: there are ~5 BTC tops in the data and 12 variants.",
           "Caveats: alt basket survivorship; OI history starts 2021 so cycle 1 is only May-Nov 2021; warnings chosen after seeing labs 27/28; fills at the signal-day close."]
    text = "\n".join(Lx); open(os.path.join(scanner.HERE, "lab30_summary.txt"), "w").write(text + "\n"); print(text)
    try: scanner.notify("Strategy lab 30 finished", "Exit-timing audit done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
