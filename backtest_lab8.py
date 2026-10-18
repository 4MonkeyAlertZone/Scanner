#!/usr/bin/env python3
"""Strategy lab 8: a trader's Bitcoin idea, tested as rules on daily candles (as far back as the data goes, about 7 years).
His story: (1) a bearish RSI divergence (price makes a higher high while the daily RSI makes a lower high) warns of a pullback;
(2) after that, BTC falls back to a rising moving average with the RSI cooled to about 50, and bounces from there.
Rules tested on BTC:
  PULLBACK k   in an uptrend (price above its 200-day average and the k-day average above the 200-day), BTC touches the k-day average
               (low within 1% of it) after being at least 6% above it in the last 15 days, with the RSI at 50 or lower.  k = 20, 50, 100.
  DIVERGENCE   a swing high (highest of 11 days) that is higher than the previous swing high (10-80 days earlier) while the RSI is lower and the earlier RSI was 60+.
  COMBO        a PULLBACK (k=50) within 60 days after a DIVERGENCE (his whole story).
Every event is compared with ordinary days in the same trend (the benchmark), split into older and newer halves, and also shown for a basket of the top 20 altcoins.
Forward returns are measured from the close of the signal day (a signal needs that close, so this is slightly optimistic for every rule and the benchmark alike).
Writes lab8_summary.txt and lab8_results.csv."""
import csv, os, time
from multiprocessing import Pool
import scanner, backtest as B

OUT = scanner.HERE
HS = (7, 14, 28)
N_ALTS = int(os.environ.get("LAB8_ALTS", "20"))
tf = lambda t: time.strftime("%Y-%m-%d", time.gmtime(t))

def ema(c, k):
    a = 2 / (k + 1); out = [c[0]]
    for x in c[1:]: out.append(out[-1] + a * (x - out[-1]))
    return out

def sma(c, k):
    pre = [0.0]
    for x in c: pre.append(pre[-1] + x)
    return [None if i < k - 1 else (pre[i + 1] - pre[i + 1 - k]) / k for i in range(len(c))]

def rsi14(c):
    out = [None] * len(c); ag = al = 0.0
    for i in range(1, len(c)):
        d = c[i] - c[i - 1]; g, l = max(d, 0), max(-d, 0)
        if i <= 14:
            ag += g / 14; al += l / 14
            if i == 14: out[i] = 100 - 100 / (1 + ag / al) if al else 100
        else:
            ag = (ag * 13 + g) / 14; al = (al * 13 + l) / 14
            out[i] = 100 - 100 / (1 + ag / al) if al else 100
    return out

def alt(sym):
    try:
        m = B.hist_crypto(sym, "1d", 2700)
        return sym, {int(r[0] // 86400): r[4] for r in m} if len(m) > 300 else {}
    except Exception:
        return sym, {}

def mean(x): return sum(x) / len(x) if x else 0.0
def med(x):
    s = sorted(x); n = len(s)
    return 0.0 if not n else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2)
def sd(x):
    if len(x) < 2: return 0.0
    m = mean(x); return (sum((v - m) ** 2 for v in x) / (len(x) - 1)) ** .5

def events(m):
    n = len(m); c = [r[4] for r in m]; hi = [r[2] for r in m]; lo = [r[3] for r in m]
    R = rsi14(c); S200 = sma(c, 200); E = {k: ema(c, k) for k in (20, 50, 100)}
    ev = {}
    def up(i, k): return S200[i] is not None and c[i] > S200[i] and E[k][i] > S200[i]
    for k in (20, 50, 100):
        out, nxt = [], 0
        for i in range(260, n - 1):
            if i < nxt: continue
            if up(i, k) and lo[i] <= E[k][i] * 1.01 and max(c[i - 15:i]) >= E[k][i] * 1.06 and R[i] is not None and R[i] <= 50:
                out.append(i); nxt = i + 10
        ev[f"PULLBACK {k}-day average"] = out
    piv = [i for i in range(5, n - 5) if hi[i] == max(hi[i - 5:i + 6])]
    out, nxt, div_days = [], 0, []
    for a, i in enumerate(piv):
        d = i + 5                                       # a swing high is only known 5 days after it happened
        if d >= n - 1 or d < nxt or i < 260: continue
        prev = [j for j in piv[:a] if 10 <= i - j <= 80]
        if not prev: continue
        j = prev[-1]
        if hi[i] >= hi[j] * 1.01 and R[i] is not None and R[j] is not None and R[j] >= 60 and R[i] <= R[j] - 2:
            out.append(d); nxt = d + 20
    ev["DIVERGENCE (bearish)"] = out
    combo, nxt = [], 0
    for i in ev["PULLBACK 50-day average"]:
        if i >= nxt and any(0 < i - d <= 60 for d in out): combo.append(i); nxt = i + 10
    ev["COMBO (divergence, then pullback to 50-day)"] = combo
    base = {k: [i for i in range(260, n - 1) if up(i, k)] for k in (20, 50, 100)}
    allr = list(range(260, n - 1))
    return c, lo, ev, base, allr

def fwd(c, i, h):
    return (c[i + h] / c[i] - 1) * 100 if i + h < len(c) else None

def worst(c, lo, i, h=28):
    return (min(lo[i + 1:i + 1 + h]) / c[i] - 1) * 100 if i + h < len(c) else None

def line(xs, ref):
    if not xs: return "n=0"
    m = mean(xs); se = sd(xs) / len(xs) ** .5
    return f"n={len(xs):3d} avg {m:+5.1f}% median {med(xs):+5.1f}% up {sum(1 for x in xs if x > 0) / len(xs) * 100:3.0f}% (benchmark avg {mean(ref):+5.1f}%) edge {m - mean(ref):+5.1f}% +/-{1.96 * se:.1f}"

def main():
    m = B.hist_crypto("BTC", "1d", 2700)
    c, lo, ev, base, allr = events(m); ep = [r[0] for r in m]
    print(f"BTC daily candles: {len(m)}, {tf(ep[0])} to {tf(ep[-1])}", flush=True)
    syms = [s for s in scanner.top100() if s != "BTC"][:N_ALTS]
    with Pool(max(1, os.cpu_count() or 1)) as p: alts = dict(p.map(alt, syms))
    days = [int(t // 86400) for t in ep]
    def basket(i, h):
        xs = []
        for d in alts.values():
            a, b = d.get(days[i]), d.get(days[i] + h)
            if a and b: xs.append((b / a - 1) * 100)
        return mean(xs) if len(xs) >= 5 else None
    cut = ep[len(ep) // 2]
    L = [f"BTC daily candles {tf(ep[0])} to {tf(ep[-1])} ({len(m)} days). Era 1 = before {tf(cut)}, era 2 = after. Forward returns from the signal-day close, no costs (a few trades per year, so costs are tiny).",
         "Benchmark = every ordinary day in the same trend condition (for DIVERGENCE: every day). 'edge' = rule average minus benchmark average; the +/- is a rough 95% margin, and it is too narrow when events cluster, so only a clear edge in BOTH eras counts.", ""]
    res = []
    for name, idx in ev.items():
        k = int(name.split()[1].split("-")[0]) if name.startswith("PULLBACK") else None
        bidx = base[k] if k else allr
        L.append(name + f"   ({len(idx)} events)")
        for h in HS:
            xs = [fwd(c, i, h) for i in idx]; xs = [x for x in xs if x is not None]
            bs = [fwd(c, i, h) for i in bidx]; bs = [x for x in bs if x is not None]
            L.append(f"   {h:2d} days ahead, BTC: {line(xs, bs)}")
            parts = []; both = True
            for era in (0, 1):
                a = [fwd(c, i, h) for i in idx if (ep[i] >= cut) == bool(era)]; a = [x for x in a if x is not None]
                b = [fwd(c, i, h) for i in bidx if (ep[i] >= cut) == bool(era)]; b = [x for x in b if x is not None]
                if len(a) < 4: both = False; parts.append(f"era{era + 1} n={len(a)}"); continue
                parts.append(f"era{era + 1} n={len(a)} {mean(a):+.1f}% vs {mean(b):+.1f}%"); both = both and mean(a) > mean(b)
            ab = [basket(i, h) for i in idx]; ab = [x for x in ab if x is not None]
            ar = [basket(i, h) for i in bidx[::5]]; ar = [x for x in ar if x is not None]
            L.append(f"        {' | '.join(parts)}{'  <-- LEANS POSITIVE (beats benchmark in both eras)' if both else ''}")
            L.append(f"        top-{N_ALTS} altcoin basket {h} days ahead: {line(ab, ar)}")
            res.append(dict(event=name, horizon=h, n=len(xs), avg=round(mean(xs), 2), median=round(med(xs), 2), benchmark=round(mean(bs), 2), edge=round(mean(xs) - mean(bs), 2), both_eras=int(both)))
        w = [worst(c, lo, i) for i in idx]; w = [x for x in w if x is not None]
        wb = [worst(c, lo, i) for i in bidx]; wb = [x for x in wb if x is not None]
        if w: L.append(f"   worst dip in the next 28 days: typical {med(w):+.1f}%, 1 in 4 events worse than {sorted(w)[len(w) // 4]:+.1f}% (benchmark typical {med(wb):+.1f}%)")
        L.append("")
    L.append("EVERY EVENT (date, BTC close, what happened over the next 14 days)")
    for name, idx in ev.items():
        L.append("  " + name + ": " + ", ".join(f"{tf(ep[i])} ${c[i]:,.0f} ({fwd(c, i, 14):+.0f}%)" if fwd(c, i, 14) is not None else f"{tf(ep[i])} ${c[i]:,.0f}" for i in idx[-14:]) + (f"  [showing last 14 of {len(idx)}]" if len(idx) > 14 else ""))
    L.append("")
    L.append("HOW TO READ: this is one asset with few events, so only a large, consistent edge in both eras means anything, and 'LEANS POSITIVE' is a hint, not proof. A rule that merely matches the benchmark has no edge: BTC drifts up in uptrends anyway. Divergence is expected to show NEGATIVE edge if the warning works. Overlapping 28-day windows make the margins look better than they are.")
    text = "\n".join(L)
    with open(os.path.join(OUT, "lab8_results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, list(res[0].keys())); w.writeheader(); w.writerows(res)
    with open(os.path.join(OUT, "lab8_summary.txt"), "w") as f: f.write(text + "\n")
    print("\n" + text)
    try: scanner.notify("Strategy lab 8 finished", "BTC divergence / pullback lab done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
