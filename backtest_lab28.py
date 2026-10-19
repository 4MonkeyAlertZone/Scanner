#!/usr/bin/env python3
"""Lab 28: the open-interest (OI) warning, pushed harder but with guard rails.
Data (free): Binance USD-M futures daily 'metrics' files (5-minute rows) for BTC, ETH, SOL, XRP, DOGE, BNB, LINK, ADA, from 2021.
Everything declared in advance: ~34 flags built from (a) BTC OI levels/changes, (b) INTRADAY OI jumps (max 1-hour and 4-hour OI rise inside the day), (c) price-vs-OI quadrants,
(d) alt OI crowding (alt OI vs BTC OI), (e) OI combined with RSI, stretch above the 50-day average, volume spike and fib-extension distance.
Target: a BTC fall of 10%+ within 14 days (grid of 5/10/15% x 7/14/30 days for the survivors only).
Guard rails: episodes not days; lift vs the base rate in EACH period (cycle 1 / bear / cycle 2); leave-one-period-out (choose on two periods, score on the third);
random-timing shifts for the exposure test. Writes lab28_summary.txt and metrics_daily_multi.csv."""
import csv, io, os, zipfile, time, calendar, math, random, statistics as st, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from multiprocessing import Pool
import scanner, backtest as B
from backtest_lab23 import zig, rsi_series, dstr, med, STABLES

SYMS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "LINK", "ADA"]
START = datetime(2021, 1, 1, tzinfo=timezone.utc).date(); COST = 0.001; COOL = 7
P1 = calendar.timegm((2021, 12, 1, 0, 0, 0)); P2 = calendar.timegm((2022, 12, 1, 0, 0, 0))
PER = [("cycle 1", lambda t: t < P1), ("bear", lambda t: P1 <= t < P2), ("cycle 2", lambda t: t >= P2)]
URL = "https://data.binance.vision/data/futures/um/daily/metrics/%sUSDT/%sUSDT-metrics-%s.zip"

def fetch(a):
    sym, d = a
    for k in range(3):
        try:
            r = urllib.request.urlopen(urllib.request.Request(URL % (sym, sym, d.isoformat()), headers={"User-Agent": "Mozilla/5.0"}), timeout=30)
            z = zipfile.ZipFile(io.BytesIO(r.read())); rows = list(csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())))
            oi = [float(x["sum_open_interest"]) for x in rows if x.get("sum_open_interest")]
            oiv = [float(x["sum_open_interest_value"]) for x in rows if x.get("sum_open_interest_value")]
            if not oi: return sym, d, None
            m1 = max((oi[k + 12] / oi[k] - 1 for k in range(len(oi) - 12)), default=0.0); m4 = max((oi[k + 48] / oi[k] - 1 for k in range(len(oi) - 48)), default=0.0)
            return sym, d, (oi[-1], oiv[-1] if oiv else 0.0, m1, m4)
        except Exception as e:
            if getattr(e, "code", None) == 404: return sym, d, None
            time.sleep(1.5)
    return sym, d, None

def load(s):
    try: return s, B.hist_crypto(s, "1d", 2600)
    except Exception: return s, []

def pct_rank(series, i, win=365, minn=120):
    v = series[i]
    if v is None: return None
    prev = [x for x in series[max(0, i - win):i] if x is not None]
    return sum(1 for x in prev if x < v) / len(prev) if len(prev) >= minn else None

def main():
    today = datetime.now(timezone.utc).date(); ds = [START + timedelta(days=k) for k in range((today - START).days)]
    with ThreadPoolExecutor(24) as ex: got = list(ex.map(fetch, [(s, d) for s in SYMS for d in ds]))
    raw = {s: {} for s in SYMS}
    for s, d, v in got:
        if v: raw[s][d] = v
    print("files read:", {s: len(raw[s]) for s in SYMS})
    with open(os.path.join(scanner.HERE, "metrics_daily_multi.csv"), "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["date", "sym", "oi_coins", "oi_usd", "max_1h_oi_rise", "max_4h_oi_rise"])
        for s in SYMS:
            for d in sorted(raw[s]): w.writerow([d.isoformat(), s, round(raw[s][d][0], 2), round(raw[s][d][1]), round(raw[s][d][2], 4), round(raw[s][d][3], 4)])
    btc = B.hist_crypto("BTC", "1d", 2600); fx = []; bad = 0
    for t, o, h, l, c, v in btc:
        hb, lb = max(o, c), min(o, c); h2, l2 = min(h, hb * 1.25), max(l, lb / 1.25); bad += (h2 != h) + (l2 != l); fx.append((t, o, h2, l2, c, v))
    btc = fx; T = [r[0] for r in btc]; H = [r[2] for r in btc]; L = [r[3] for r in btc]; C = [r[4] for r in btc]; V = [r[5] for r in btc]; n = len(btc)
    dd_ = lambda t: datetime.fromtimestamp(t, timezone.utc).date()
    ser = lambda s, k: [raw[s][dd_(t)][k] if dd_(t) in raw[s] else None for t in T]
    OI = ser("BTC", 0); OIV = ser("BTC", 1); M1 = ser("BTC", 2); M4 = ser("BTC", 3)
    first = next(i for i in range(n) if OI[i]); last_oi = max(i for i in range(n) if OI[i])
    ALT = {s: ser(s, 0) for s in SYMS if s != "BTC"}
    rsi = rsi_series(C); ma50 = [sum(C[max(0, i - 49):i + 1]) / min(50, i + 1) for i in range(n)]
    p20 = zig(H, L, .20)
    def ext_today(i):
        ups = [q for q in p20 if q[3] < i]
        if len(ups) < 3 or ups[-1][2] != "L": return None
        Lc, Hp, Lpp = ups[-1], ups[-2], ups[-3]
        return (C[i] - Lc[1]) / (Hp[1] - Lpp[1]) if Hp[1] > Lpp[1] else None
    ch = lambda s, i, k: (s[i] / s[i - k] - 1) if i >= k and s[i] and s[i - k] else None
    lo = [math.log(x) if x else None for x in OI]; ema = [None] * n; e = None
    for i in range(n):
        if lo[i] is not None: e = lo[i] if e is None else e + (lo[i] - e) * 2 / 61
        ema[i] = e
    dev = [lo[i] - ema[i] if lo[i] is not None and ema[i] is not None else None for i in range(n)]
    sdv = lambda x: st.pstdev(x) if len(x) > 5 else None
    zdev = [None] * n; hi180 = [False] * n; volz = [None] * n
    for i in range(first + 120, last_oi + 1):
        s1 = sdv([x for x in dev[i - 90:i] if x is not None])
        if s1 and dev[i] is not None: zdev[i] = dev[i] / s1
        prev = [x for x in OI[i - 180:i] if x]; hi180[i] = len(prev) > 100 and OI[i] and OI[i] >= max(prev)
        vv = V[i - 90:i]; sv = sdv(vv)
        if sv: volz[i] = (V[i] - sum(vv) / len(vv)) / sv
    pM1 = [pct_rank(M1, i) if M1[i] is not None else None for i in range(n)]; pM4 = [pct_rank(M4, i) if M4[i] is not None else None for i in range(n)]
    def alt_med(i):
        r = [ch(a, i, 30) for a in ALT.values()]; r = [x for x in r if x is not None]
        return med(r) if len(r) >= 3 else None
    def alt_hi(i):
        c = t_ = 0
        for a in ALT.values():
            prev = [x for x in a[max(0, i - 180):i] if x]
            if a[i] and len(prev) > 100: t_ += 1; c += a[i] >= max(prev)
        return c / t_ if t_ >= 3 else None
    ge = lambda x, v: x is not None and x >= v
    le = lambda x, v: x is not None and x <= v
    near = lambda i, lv: (lambda x: x is not None and abs(x - lv) <= .05)(ext_today(i))
    p30 = lambda i: ch(C, i, 30); o30 = lambda i: ch(OI, i, 30)
    F1 = lambda i: ge(o30(i), .15); F2 = lambda i: hi180[i]; F3 = lambda i: ge(zdev[i], 1.5)
    RSI = lambda i: rsi[i] >= 70; STR = lambda i: C[i] / ma50[i] > 1.25; VOL = lambda i: ge(volz[i], 2.0)
    FIB = lambda i: near(i, 1.272) or near(i, 1.618) or near(i, 2.0)
    flags = [("OI +15% in 30d  [lab27 fixed]", F1), ("OI new 180d high  [lab27 dynamic]", F2), ("OI 1.5 std above 60d trend", F3),
             ("OI +25% in 30d", lambda i: ge(o30(i), .25)), ("OI +10% in 30d", lambda i: ge(o30(i), .10)), ("OI +10% in 7d", lambda i: ge(ch(OI, i, 7), .10)), ("OI +5% in 3d", lambda i: ge(ch(OI, i, 3), .05)),
             ("INTRADAY: biggest 1h OI rise in top 10% of year", lambda i: ge(pM1[i], .90)), ("INTRADAY: biggest 4h OI rise in top 10% of year", lambda i: ge(pM4[i], .90)), ("INTRADAY: 4h OI rise in top 5%", lambda i: ge(pM4[i], .95)),
             ("QUADRANT price up 5%+ & OI up 10%+ (30d)", lambda i: ge(p30(i), .05) and ge(o30(i), .10)), ("QUADRANT price up 5%+ & OI down 10%+", lambda i: ge(p30(i), .05) and le(o30(i), -.10)),
             ("QUADRANT price down 5%+ & OI up 10%+", lambda i: le(p30(i), -.05) and ge(o30(i), .10)), ("QUADRANT price down 5%+ & OI down 10%+", lambda i: le(p30(i), -.05) and le(o30(i), -.10)),
             ("ALT OI median up 25%+ in 30d", lambda i: ge(alt_med(i), .25)), ("ALT OI up 10%+ more than BTC OI", lambda i: alt_med(i) is not None and o30(i) is not None and alt_med(i) - o30(i) >= .10),
             ("ALT: half or more of alts at OI 180d high", lambda i: ge(alt_hi(i), .5)), ("ALT half at OI high AND BTC OI +15%", lambda i: ge(alt_hi(i), .5) and F1(i)),
             ("OI +15% AND RSI >= 70", lambda i: F1(i) and RSI(i)), ("OI +15% AND >25% above 50d avg", lambda i: F1(i) and STR(i)), ("OI +15% AND volume spike (2 std)", lambda i: F1(i) and VOL(i)), ("OI +15% AND fib ext 1.272/1.618/2.0", lambda i: F1(i) and FIB(i)),
             ("OI 180d high AND RSI >= 70", lambda i: F2(i) and RSI(i)), ("OI 180d high AND >25% above 50d avg", lambda i: F2(i) and STR(i)), ("OI 180d high AND volume spike", lambda i: F2(i) and VOL(i)), ("OI 180d high AND fib ext", lambda i: F2(i) and FIB(i)),
             ("OI 180d high AND OI +15%", lambda i: F2(i) and F1(i)), ("OI 180d high AND price up 5%+ (30d)", lambda i: F2(i) and ge(p30(i), .05)), ("OI 180d high AND price down (30d)", lambda i: F2(i) and le(p30(i), 0)),
             ("INTRADAY 4h top 10% AND OI +10% in 30d", lambda i: ge(pM4[i], .90) and ge(o30(i), .10)), ("INTRADAY 4h top 10% AND RSI >= 70", lambda i: ge(pM4[i], .90) and RSI(i)),
             ("RSI >= 70 alone (control)", RSI), ("volume spike alone (control)", VOL), ("fib ext alone (control)", FIB)]
    days = [i for i in range(first + 120, min(n - 31, last_oi + 1)) if OI[i]]
    def fall(i, s, d): j = min(n - 1, i + d); return 1 - min(L[i + 1:j + 1]) / C[i] >= s
    def episodes(fl, allf): 
        if allf: return fl[::14]
        out = []; last = -99
        for i in fl:
            if i - last > 7: out.append(i)
            last = i
        return out
    def stat(f, sub=None, allf=False, s=.10, d=14):
        fl = [i for i in days if f(i) and (sub is None or sub(T[i]))]
        if not fl: return None
        ep = episodes(fl, allf); return len(fl), len(ep), sum(fall(i, s, d) for i in ep) / len(ep)
    allday = lambda i: True
    zf = lambda p, q, k: (p - q) / math.sqrt(q * (1 - q) / k) if k and 0 < q < 1 else float("nan")
    base = stat(allday, None, True); pb = [stat(allday, s_, True) for _, s_ in PER]
    pbs = lambda x: f"{x[2]:.0%} ({x[1]} eps)" if x else "--"
    res = []
    for name, f in flags:
        s_all = stat(f)
        if not s_all: res.append(dict(name=name, f=f, n=0)); continue
        pp = [stat(f, sub) for _, sub in PER]
        res.append(dict(name=name, f=f, n=s_all[1], hit=s_all[2], z=zf(s_all[2], base[2], s_all[1]), days=s_all[0], pp=pp, lift=[(p_[2] - b_[2]) if p_ and b_ else None for p_, b_ in zip(pp, pb)], pe=[p_[1] if p_ else 0 for p_ in pp]))
    Lx = [f"LAB 28  {datetime.now(timezone.utc):%Y-%m-%d}  OI warnings with intraday, quadrants, alt crowding and filters. BTC OI {dstr(T[first])} to {dstr(T[last_oi])}; files read {sum(len(raw[s]) for s in SYMS)}; {len(flags)} flags declared in advance; bad price ticks clipped {bad}.", "",
          f"== 1. Flags vs a 10%+ BTC fall within 14 days. eps = episodes (flagged days within 7 days merged). lift = hit rate minus the base rate of that period (base: all {base[1]} eps {base[2]:.0%}; cycle 1 {pbs(pb[0])}, bear {pbs(pb[1])}, cycle 2 {pbs(pb[2])}). With {len(flags)} flags expect ~{len(flags) * .023:.0f} to reach z>2 by luck. ==",
          f"{'flag':<50}{'days':>5}{'eps':>5}{'hit':>6}{'z':>6}   {'lift c1 (eps)':>14}{'lift bear':>13}{'lift c2':>13}"]
    fmt = lambda l, e_: f"{l:>+7.0%} ({e_:>2})" if l is not None else f"{'--':>7} ({e_:>2})"
    for r in res:
        if not r["n"]: Lx.append(f"{r['name']:<50}    0"); continue
        Lx.append(f"{r['name']:<50}{r['days']:>5}{r['n']:>5}{r['hit']:>6.0%}{r['z']:>6.1f}   " + "".join(f"{fmt(l, e_):>14}" for l, e_ in zip(r["lift"], r["pe"])))
    # survivors: z >= 2, lift > 0 in every period with >= 3 episodes, at least two such periods
    def survives(r):
        if not r["n"] or r["z"] < 2: return False
        ok_ = [l for l, e_ in zip(r["lift"], r["pe"]) if l is not None and e_ >= 3]
        return len(ok_) >= 2 and all(l > 0 for l in ok_)
    surv = sorted([r for r in res if survives(r)], key=lambda r: -r["z"])
    Lx += ["", f"SURVIVORS (z >= 2 and positive lift in every period that has 3+ episodes, in at least two periods): {len(surv)} of {len(flags)}"] + [f"  {r['name']}  (z {r['z']:.1f}, {r['n']} eps)" for r in surv]
    # leave-one-period-out
    Lx += ["", "== 2. Leave-one-period-out: pick the 3 flags with the best average lift on the OTHER two periods (needs 4+ episodes in each), then score them on the held-out period ==",
           f"{'held out':<12}{'picked flags':<84}{'their lift there':>18}{'all flags avg':>15}"]
    tot_p = []; tot_a = []
    for k, (pn, _) in enumerate(PER):
        tr = [j for j in range(3) if j != k]; cand = [r for r in res if r["n"] and all(r["pe"][j] >= 4 for j in tr)]
        if len(cand) < 4: Lx.append(f"{pn:<12}too few candidates"); continue
        cand.sort(key=lambda r: -sum(r["lift"][j] for j in tr) / 2); top = [r for r in cand if r["pe"][k] >= 2 and r["lift"][k] is not None][:3]
        allh = [r["lift"][k] for r in res if r["n"] and r["pe"][k] >= 2 and r["lift"][k] is not None]
        if top:
            ph = sum(r["lift"][k] for r in top) / len(top); ah = sum(allh) / len(allh); tot_p.append(ph); tot_a.append(ah)
            Lx.append(f"{pn:<12}{'; '.join(r['name'][:26] for r in top):<84}{ph:>+18.0%}{ah:>+15.0%}")
    if tot_p: Lx.append(f"{'AVERAGE':<12}{'':<84}{sum(tot_p) / len(tot_p):>+18.0%}{sum(tot_a) / len(tot_a):>+15.0%}   (want the first clearly above the second and above 0)")
    # grid for top survivors
    if surv:
        Lx += ["", "== 3. Size x horizon grid for the top survivors: hit rate (episodes) vs base, falls of 5/10/15% within 7/14/30 days =="]
        for r in surv[:3]:
            Lx.append(r["name"])
            for s_ in (.05, .10, .15):
                row = []
                for d_ in (7, 14, 30):
                    a = stat(r["f"], None, False, s_, d_); b_ = stat(allday, None, True, s_, d_); row.append(f"{d_}d: {a[2]:.0%} vs {b_[2]:.0%}" if a and b_ else f"{d_}d: --")
                Lx.append(f"   fall >= {s_:.0%}   " + "   ".join(row))
    # exposure test on survivors
    coins = [t for t in scanner.top100()[:45] if t.upper() not in STABLES]
    with Pool(2) as p: rr = p.map(load, coins, chunksize=1)
    A = {s: {r_[0]: r_[4] for r_ in rows} for s, rows in rr if len(rows) > 500}
    ret = [0.0] * n
    for i in range(1, n):
        q = [A[s][T[i]] / A[s][T[i - 1]] - 1 for s in A if T[i] in A[s] and T[i - 1] in A[s]]; ret[i] = sum(q) / len(q) if q else 0.0
    gate = [i >= 199 and C[i] > sum(C[i - 199:i + 1]) / 200 for i in range(n)]
    d0, d1 = days[0], days[-1]
    def run(expo, lo_=d0, hi_=d1):
        eq = 1.0; pk = 1.0; mdd = 0.0; prev = 0
        for i in range(lo_, hi_):
            e_ = 1 if expo[i] else 0; eq *= 1 + ret[i + 1] * e_ - COST * abs(e_ - prev); prev = e_; pk = max(pk, eq); mdd = max(mdd, 1 - eq / pk)
        return eq, mdd
    dset = set(range(d0, d1 + 1))
    mk = lambda f: [bool(i in dset and f(i)) for i in range(n)]
    recent = lambda fs: [any(fs[max(0, i - COOL + 1):i + 1]) for i in range(n)]
    Lx += ["", f"== 4. Exposure test (alt basket of {len(A)} coins listed today = survivorship-flattered): gate + {COOL} days in cash after the warning. NOT out-of-sample for the picked flags. =="]
    cell = lambda ex, lo_, hi_: "x%.2f dd %.0f%%" % (lambda m: (m[0], m[1] * 100))(run(ex, lo_, hi_))
    Lx.append(f"{'rule':<52}{'whole':>16}" + "".join(f"{pn:>16}" for pn, _ in PER))
    def line(name, ex):
        cs = []
        for pn, sub in PER:
            ii = [i for i in days if sub(T[i])]; cs.append(f"{cell(ex, ii[0], ii[-1]) if len(ii) > 30 else '--':>16}")
        Lx.append(f"{name:<52}{cell(ex, d0, d1):>16}" + "".join(cs))
    line("hold the alt basket", [True] * n); line("BTC 200-day gate only", gate[:])
    gm = run(gate[:])[0]; random.seed(11); span = list(range(d0, d1 + 1)); Ln = len(span); nulls = []
    for r in surv[:6]:
        fs = mk(r["f"]); ex = [gate[i] and not x for i, x in enumerate(recent(fs))]; line("gate + out after: " + r["name"][:34], ex)
        real = run(ex)[0]; worse = 0
        for _ in range(300):
            k = random.randint(60, Ln - 60); sh = [False] * n
            for j, i in enumerate(span): sh[i] = fs[span[(j + k) % Ln]]
            worse += run([gate[i] and not x for i, x in enumerate(recent(sh))])[0] < real
        nulls.append(f"  {r['name'][:50]:<52} real x{real:.2f} vs gate-only x{gm:.2f}; beats {worse / 300:.0%} of random timings")
    if nulls: Lx += ["", "Random-timing check (300 circular shifts of the same warning dates; want > 95%):"] + nulls
    Lx += ["", "Read: trust a flag only if it is a SURVIVOR, the leave-one-period-out score is above both zero and the all-flags average, and it beats random timings. Otherwise it is noise from a large menu.",
           "Caveats: one asset (BTC) for the target, about 3 phases, 34 flags, flags in part 4 chosen after seeing the data, alt basket survivorship, exchange volume = Binance.US BTC volume."]
    text = "\n".join(Lx); open(os.path.join(scanner.HERE, "lab28_summary.txt"), "w").write(text + "\n"); print(text)
    try: scanner.notify("Strategy lab 28 finished", "OI deep-dive done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
