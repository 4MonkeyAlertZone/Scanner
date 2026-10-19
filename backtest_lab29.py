#!/usr/bin/env python3
"""Lab 29: does the open-interest (OI) warning replicate on OTHER assets, or was it one lucky BTC pattern?
For each of ETH, SOL, XRP, DOGE, BNB, LINK, ADA (and BTC as the reference) the asset's OWN Binance futures OI is used to warn about the asset's OWN falls.
Pre-declared flags (same as lab 27/28, nothing tuned here): G1 OI up 15%+ in 30 days; G2 OI at a new 180-day high; G3 = G1 and G2; G4 = price down 5%+ over 30 days and OI up 10%+.
Target: a fall in the next 14 days (low vs close) of at least one 14-day volatility unit (trailing 60-day daily std x sqrt(14)), so assets of different wildness are comparable; the plain 10% fall is shown too.
Each flag is judged by episodes, lift over the asset's own base rate, and a circular-shift test (the same flag dates moved to random places, keeping clustering).
Second table: does BTC's OI warning predict the ALTS' falls (that is what matters for an alt basket).
Reads metrics_daily_multi.csv written by lab 28. Writes lab29_summary.txt."""
import csv, os, math, random, calendar, statistics as st
from multiprocessing import Pool
from datetime import datetime, timezone
import scanner, backtest as B
from backtest_lab23 import dstr, med

SYMS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "LINK", "ADA"]
P1 = calendar.timegm((2021, 12, 1, 0, 0, 0)); P2 = calendar.timegm((2022, 12, 1, 0, 0, 0))
PER = [("c1", lambda t: t < P1), ("bear", lambda t: P1 <= t < P2), ("c2", lambda t: t >= P2)]

def load(s):
    try: return s, B.hist_crypto(s, "1d", 2600)
    except Exception: return s, []

def build(rows, oi_by):
    fx = []
    for t, o, h, l, c, v in rows:
        hb, lb = max(o, c), min(o, c); fx.append((t, o, min(h, hb * 1.25), max(l, lb / 1.25), c, v))
    T = [r[0] for r in fx]; H = [r[2] for r in fx]; L = [r[3] for r in fx]; C = [r[4] for r in fx]; n = len(fx)
    OI = [oi_by.get(t - t % 86400) for t in T]
    return dict(T=T, H=H, L=L, C=C, n=n, OI=OI)

def main():
    path = os.path.join(scanner.HERE, "metrics_daily_multi.csv")
    if not os.path.exists(path): print("metrics_daily_multi.csv missing - run lab 28 first"); return
    oi = {s: {} for s in SYMS}
    for r in csv.DictReader(open(path)):
        if r["sym"] in oi:
            try: oi[r["sym"]][calendar.timegm(datetime.strptime(r["date"], "%Y-%m-%d").timetuple())] = float(r["oi_coins"])
            except Exception: pass
    with Pool(2) as p: rows = dict(p.map(load, SYMS, chunksize=1))
    A = {}
    for s in SYMS:
        if len(rows[s]) > 500 and oi[s]: A[s] = build(rows[s], oi[s])
    ch = lambda s, i, k: (s[i] / s[i - k] - 1) if i >= k and s[i] and s[i - k] else None
    ge = lambda x, v: x is not None and x >= v
    le = lambda x, v: x is not None and x <= v
    for s, a in A.items():
        OI, C, L, H, n = a["OI"], a["C"], a["L"], a["H"], a["n"]
        first = next(i for i in range(n) if OI[i]); last = max(i for i in range(n) if OI[i])
        hi = [False] * n
        for i in range(first + 120, last + 1):
            prev = [x for x in OI[i - 180:i] if x]; hi[i] = bool(OI[i]) and len(prev) > 100 and OI[i] >= max(prev)
        o30 = [ch(OI, i, 30) for i in range(n)]; p30 = [ch(C, i, 30) for i in range(n)]
        G1 = [ge(o30[i], .15) for i in range(n)]; G2 = hi; G3 = [G1[i] and G2[i] for i in range(n)]; G4 = [le(p30[i], -.05) and ge(o30[i], .10) for i in range(n)]
        a["flags"] = [("G1 OI +15% in 30d", G1), ("G2 OI new 180d high", G2), ("G3 both", G3), ("G4 price down 5%+ & OI +10%", G4)]
        lr = [None] + [math.log(C[i] / C[i - 1]) for i in range(1, n)]
        sig = [None] * n
        for i in range(61, n):
            x = lr[i - 59:i + 1]; sig[i] = st.pstdev(x)
        a["sig"] = sig
        a["days"] = [i for i in range(first + 120, min(n - 15, last + 1)) if OI[i] and sig[i]]
        fall = lambda i, th: 1 - min(L[i + 1:i + 15]) / C[i] >= th
        a["fs"] = {i: fall(i, sig[i] * math.sqrt(14)) for i in a["days"]}; a["f10"] = {i: fall(i, .10) for i in a["days"]}
        a["first"], a["last"] = first, last
    def eps_of(fl, allf):
        if allf: return fl[::14]
        out = []; last = -99
        for i in fl:
            if i - last > 7: out.append(i)
            last = i
        return out
    zf = lambda p, q, k: (p - q) / math.sqrt(q * (1 - q) / k) if k and 0 < q < 1 else float("nan")
    random.seed(5)
    def evalflag(days, flag, outcome, T, sub=None, allf=False):
        fl = [i for i in days if flag[i] and (sub is None or sub(T[i]))]
        if not fl: return None
        ep = eps_of(fl, allf); return len(fl), len(ep), sum(outcome[i] for i in ep) / len(ep)
    def shift_p(days, flag, outcome, T, real_lift, base):
        L_ = len(days); ge_n = 0; N = 200
        for _ in range(N):
            k = random.randint(60, max(61, L_ - 60)); sh = {days[j]: flag[days[(j + k) % L_]] for j in range(L_)}
            fl = [i for i in days if sh[i]]
            if not fl: continue
            ep = eps_of(fl, False); lift = sum(outcome[i] for i in ep) / len(ep) - base; ge_n += lift >= real_lift
        return ge_n / N
    Lx = [f"LAB 29  {datetime.now(timezone.utc):%Y-%m-%d}  Does the OI warning replicate on other assets? Each asset uses its OWN Binance futures OI. Flags fixed in advance (G1-G4). Target: a fall within 14 days of at least one 14-day volatility unit; 'abs10' = a plain 10% fall.", "",
          "lift = hit rate minus the asset's own base rate; p = share of 200 random-timing shifts with a lift at least this good (small = real); c1/bear/c2 = lift per period (episodes). Crypto assets move together, so these are NOT independent confirmations.",
          f"{'asset':<6}{'flag':<30}{'days':>5}{'eps':>4}{'hit':>5}{'base':>5}{'lift':>6}{'z':>5}{'p':>6}  {'abs10 lift':>10}   {'lift c1':>10}{'lift bear':>11}{'lift c2':>10}"]
    tally = {}
    for s in SYMS:
        if s not in A: Lx.append(f"{s:<6}no OI data"); continue
        a = A[s]; days = a["days"]; T = a["T"]; allf = [True] * a["n"]
        b = evalflag(days, allf, a["fs"], T, None, True); b10 = evalflag(days, allf, a["f10"], T, None, True)
        pb = [evalflag(days, allf, a["fs"], T, sub, True) for _, sub in PER]
        for name, flag in a["flags"]:
            r = evalflag(days, flag, a["fs"], T)
            if not r or r[1] < 3: Lx.append(f"{s:<6}{name:<30}{(r[0] if r else 0):>5}{(r[1] if r else 0):>4}   too few episodes"); continue
            lift = r[2] - b[2]; z = zf(r[2], b[2], r[1]); p = shift_p(days, flag, a["fs"], T, lift, b[2])
            r10 = evalflag(days, flag, a["f10"], T); l10 = (r10[2] - b10[2]) if r10 and b10 else float("nan")
            cells = []
            for (pn, sub), pbb in zip(PER, pb):
                x = evalflag(days, flag, a["fs"], T, sub); cells.append(f"{(format(x[2] - pbb[2], '+.0%') + ' (' + str(x[1]) + ')') if x and pbb else '--':>10}")
            Lx.append(f"{s:<6}{name:<30}{r[0]:>5}{r[1]:>4}{r[2]:>5.0%}{b[2]:>5.0%}{lift:>+6.0%}{z:>5.1f}{p:>6.2f}  {l10:>+10.0%}   " + "".join(cells))
            t_ = tally.setdefault(name, []); t_.append((s, lift, p))
    Lx += ["", "== Replication count per flag (assets other than BTC) =="]
    for name, v in tally.items():
        o = [x for x in v if x[0] != "BTC"]
        if o: Lx.append(f"{name:<32} positive lift in {sum(1 for x in o if x[1] > 0)} of {len(o)} assets; p<0.10 in {sum(1 for x in o if x[2] < .10)}; median lift {med([x[1] for x in o]):+.0%}   (BTC: " + (", ".join(f"{x[1]:+.0%} p={x[2]:.2f}" for x in v if x[0] == "BTC") or "n/a") + ")")
    # BTC warning -> alt falls
    Lx += ["", "== BTC's OI warning vs each ALT's own falls (volatility-unit target). Flag dates from BTC OI; outcome from the alt's price. =="]
    Lx.append(f"{'alt':<6}{'BTC flag':<30}{'days':>5}{'eps':>4}{'hit':>5}{'base':>5}{'lift':>6}{'z':>5}{'p':>6}")
    if "BTC" in A:
        bt = A["BTC"]; pos = {t - t % 86400: i for i, t in enumerate(bt["T"])}; sumry = {}
        for s in SYMS[1:]:
            if s not in A: continue
            a = A[s]; T = a["T"]; days = a["days"]
            for name, flag in bt["flags"][:3]:
                fa = [False] * a["n"]
                for i, t in enumerate(T):
                    j = pos.get(t - t % 86400)
                    if j is not None and flag[j]: fa[i] = True
                b = evalflag(days, [True] * a["n"], a["fs"], T, None, True); r = evalflag(days, fa, a["fs"], T)
                if not r or r[1] < 3: continue
                lift = r[2] - b[2]; p = shift_p(days, fa, a["fs"], T, lift, b[2])
                Lx.append(f"{s:<6}{name:<30}{r[0]:>5}{r[1]:>4}{r[2]:>5.0%}{b[2]:>5.0%}{lift:>+6.0%}{zf(r[2], b[2], r[1]):>5.1f}{p:>6.2f}"); sumry.setdefault(name, []).append((lift, p))
        Lx.append("")
        for name, v in sumry.items(): Lx.append(f"{name:<32} BTC warning preceded bigger-than-normal ALT falls in {sum(1 for x in v if x[0] > 0)} of {len(v)} alts; p<0.10 in {sum(1 for x in v if x[1] < .10)}; median lift {med([x[0] for x in v]):+.0%}")
    Lx += ["", "Read: replication is real if most assets show positive lift with small p for G2/G3 (own OI) and, separately, BTC's warning also precedes alt falls. If only BTC works, treat it as a BTC-specific or lucky pattern.",
           "Caveats: assets are highly correlated (not independent tests); 4 flags x 8 assets; periods are short for assets listed after 2021; falls measured low-vs-close on daily candles."]
    text = "\n".join(Lx); open(os.path.join(scanner.HERE, "lab29_summary.txt"), "w").write(text + "\n"); print(text)
    try: scanner.notify("Strategy lab 29 finished", "OI replication study done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
