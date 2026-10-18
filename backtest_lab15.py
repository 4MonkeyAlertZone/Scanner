#!/usr/bin/env python3
"""Strategy lab 15: trend following with trailing exits, momentum rotation, and volatility targeting, versus simply holding.
Daily candles, 21 Nov 2022 (BTC bottom) to today, up to 99 alts + BTC (today's top-100 list, so survivorship bias flatters everything).
A signal is decided at a day's close and traded at that same close (the usual backtest convention - slightly optimistic); the position earns the NEXT day's return.
Costs: LAB_SIDE per side on every change of position (default 0.1% per side, deliberately more than the exchange fee, to allow for slippage).
STRATEGIES
  Benchmarks: hold BTC; hold BTC only while above its 200-day average; hold the alt basket (equal weight, rebalanced every 30 days).
  TREND: each coin is bought when it closes above its N-day high and sold when it closes below its M-day low (or, in one variant, 3 x average daily range below its highest close since entry).
         Up to 20 positions, each 1/20 of the account (1/n if more than 20). Variants with and without 'flat when BTC is below its 200-day average'.
  MOMENTUM: every 30 days rank coins by their L-day return, hold the top N equal-weighted (only those with a positive return, the rest in cash). Variants with and without the BTC 200-day gate.
  VOL-TARGET: the same strategy with exposure scaled down when its own 30-day volatility is above 40% a year (never above 100% invested).
Reports $1000 outcomes, yearly returns, max drawdown, Sharpe, and the older half versus newer half. Writes lab15_summary.txt and lab15_results.csv."""
import os, csv, time, calendar, math
from multiprocessing import Pool
import scanner, backtest as B

START = calendar.timegm((2022, 11, 21, 0, 0, 0)); SIDE = float(os.environ.get("LAB_SIDE", "0.001")); VT = 0.40; SLOTS = 20; REB = 30
fmt = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))

def load(tok):
    try:
        m = B.hist_crypto(tok, "1d", 2100)
        return tok, {int(r[0] // 86400): (r[2], r[3], r[4]) for r in m}, ""
    except Exception as e: return tok, {}, str(e)[:60]

# ---------------------------------------------------------------- engine
def engine(n, rets, target, side=SIDE):
    """target[i] = {coin: weight} decided at close i; it earns the return of day i+1. Returns daily strategy returns (list, index i)."""
    out = [0.0] * n; prev = {}
    for i in range(1, n):
        w = target[i - 1] or {}
        turn = sum(abs(w.get(c, 0) - prev.get(c, 0)) for c in set(w) | set(prev))
        g = 0.0
        for c, wt in w.items():
            r = rets[c][i]
            if r is not None: g += wt * r
        out[i] = g - side * turn; prev = {c: wt * (1 + (rets[c][i] or 0)) / (1 + g) for c, wt in w.items()} if (1 + g) > 0 else {}
    return out

def voltarget(n, rets, target, base):
    """scale target weights by min(1, VT / realised vol of the unscaled strategy over the past 30 days)."""
    new = [None] * n
    for i in range(n):
        if i < 31 or not target[i]: new[i] = target[i]; continue
        win = base[i - 29:i + 1]; mu = sum(win) / 30; sd = (sum((x - mu) ** 2 for x in win) / 29) ** .5 * math.sqrt(365)
        s = 1.0 if sd <= 0 else min(1.0, VT / sd)
        new[i] = {c: w * s for c, w in target[i].items()}
    return new

def stats(days, r, i0, imid):
    eq = [1.0]
    for x in r[i0 + 1:]: eq.append(eq[-1] * (1 + x))
    fin = eq[-1]; peak = 1.0; dd = 0.0
    for x in eq: peak = max(peak, x); dd = min(dd, x / peak - 1)
    xs = r[i0 + 1:]; mu = sum(xs) / len(xs); sd = (sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)) ** .5
    sh = mu / sd * math.sqrt(365) if sd > 0 else 0.0
    yrs = {}; ds = days[i0:]
    for d, x in zip(ds, eq): y = time.strftime("%Y", time.gmtime(d * 86400)); yrs.setdefault(y, [x, x]); yrs[y][1] = x
    yl = []; prev = 1.0
    for y in sorted(yrs): yl.append((y, yrs[y][1] / prev - 1)); prev = yrs[y][1]
    k = imid - i0; h1 = eq[k] / eq[0]; h2 = eq[-1] / eq[k]
    return dict(final=1000 * fin, dd=dd * 100, sharpe=sh, years=yl, h1=(h1 - 1) * 100, h2=(h2 - 1) * 100)

# ---------------------------------------------------------------- signals
def roll(arr, k, fn, i):
    seg = [x for x in arr[max(0, i - k):i] if x is not None]
    return fn(seg) if len(seg) >= k * 0.9 else None

def trend_targets(n, coins, H, L, C, gate, ne, nx, atrk):
    pos = {c: False for c in coins}; top = {c: 0.0 for c in coins}; tg = [None] * n
    atr = {}
    for c in coins:
        a = [None] * n
        for i in range(21, n):
            if None in (H[c][i], L[c][i], C[c][i], C[c][i - 1]): continue
            trs = []
            for j in range(i - 19, i + 1):
                if None in (H[c][j], L[c][j], C[c][j - 1]): trs = None; break
                trs.append(max(H[c][j] - L[c][j], abs(H[c][j] - C[c][j - 1]), abs(L[c][j] - C[c][j - 1])))
            if trs: a[i] = sum(trs) / 20
        atr[c] = a
    for i in range(max(ne, nx) + 1, n):
        g = gate[i]
        for c in coins:
            cl = C[c][i]
            if cl is None: pos[c] = False; continue
            if pos[c]:
                top[c] = max(top[c], cl)
                hi_exit = atrk and atr[c][i] and cl < top[c] - atrk * atr[c][i]
                lo_exit = (not atrk) and (lambda m: m is not None and cl < m)(roll(L[c], nx, min, i))
                if hi_exit or lo_exit or (gate is not None and g is False): pos[c] = False
            else:
                m = roll(H[c], ne, max, i)
                if m is not None and cl > m and g is not False: pos[c] = True; top[c] = cl
        held = [c for c in coins if pos[c]]
        tg[i] = {c: 1.0 / max(SLOTS, len(held)) for c in held} if held else None
    return tg

def momentum_targets(n, coins, C, gate, lookback, topn, i0):
    tg = [None] * n; cur = None
    for i in range(lookback + 1, n):
        if cur is None or (i - i0) % REB == 0:
            sc = []
            for c in coins:
                a, b = C[c][i - lookback], C[c][i]
                if a and b: sc.append((b / a - 1, c))
            sc.sort(reverse=True); pick = [c for r, c in sc[:topn] if r > 0]
            cur = {c: 1.0 / topn for c in pick}
        tg[i] = (cur if gate[i] is not False else None) or None
    return tg

def main():
    coins = [c for c in scanner.top100() if c != "BTC"][:99]
    print(f"Lab 15: loading {len(coins)} coins + BTC...", flush=True)
    with Pool(max(1, os.cpu_count() or 1)) as p: res = p.map(load, ["BTC"] + coins)
    data = {t: d for t, d, e in res if len(d) > 300}
    if "BTC" not in data: raise SystemExit("no BTC data")
    days = sorted(data["BTC"]); n = len(days); idx = {d: i for i, d in enumerate(days)}
    alts = []
    for t in data:
        if t == "BTC": continue
        cs = [v[2] for v in data[t].values()]
        if max(cs) / min(cs) < 1.3: continue
        alts.append(t)
    H = {}; L = {}; C = {}
    for t in ["BTC"] + alts:
        h = [None] * n; l = [None] * n; c = [None] * n
        for d, (hh, ll, cc) in data[t].items():
            if d in idx: h[idx[d]] = hh; l[idx[d]] = ll; c[idx[d]] = cc
        H[t] = h; L[t] = l; C[t] = c
    rets = {t: [None] + [(C[t][i] / C[t][i - 1] - 1) if C[t][i] and C[t][i - 1] else None for i in range(1, n)] for t in C}
    i0 = next(i for i, d in enumerate(days) if d * 86400 >= START); imid = (i0 + n - 1) // 2
    cb = C["BTC"]; gate = [None] * n
    for i in range(200, n): gate[i] = cb[i] > sum(cb[i - 199:i + 1]) / 200
    results = []; rows = []
    def add(group, name, tg):
        base = engine(n, rets, tg); st = stats(days, base, i0, imid); results.append((group, name, st)); return base
    def add_vt(group, name, tg, base):
        tg2 = voltarget(n, rets, tg, base); add(group, name + "  [vol-targeted]", tg2)
    # benchmarks
    add("BENCHMARKS", "hold BTC", [{"BTC": 1.0}] * n)
    add("BENCHMARKS", "hold BTC only while above its 200-day avg", [({"BTC": 1.0} if gate[i] else None) for i in range(n)])
    bk = [None] * n; cur = None
    for i in range(n):
        if cur is None or (i - i0) % REB == 0:
            av = [c for c in alts if C[c][i]]; cur = {c: 1.0 / len(av) for c in av} if av else None
        bk[i] = cur
    b = add("BENCHMARKS", "hold the alt basket (equal weight, monthly rebalance)", bk)
    # trend
    for (ne, nx, atrk, label) in ((20, 10, None, "20-day breakout, exit below 10-day low"), (55, 20, None, "55-day breakout, exit below 20-day low"), (100, 50, None, "100-day breakout, exit below 50-day low"), (55, 20, 3.0, "55-day breakout, trailing stop 3 x daily range")):
        for gname, g in (("", [None] * n), (", flat when BTC < 200-day avg", gate)):
            tg = trend_targets(n, ["BTC"] + alts, H, L, C, g, ne, nx, atrk)
            base = add("TREND FOLLOWING", label + gname, tg)
            if not gname: add_vt("TREND FOLLOWING", label + gname, tg, base)
    # momentum
    for lb in (30, 60, 90):
        for tn in (5, 10):
            for gname, g in (("", [None] * n), (", flat when BTC < 200-day avg", gate)):
                tg = momentum_targets(n, ["BTC"] + alts, C, g, lb, tn, i0)
                base = add("MOMENTUM ROTATION", f"top {tn} by {lb}-day return, monthly" + gname, tg)
                if lb == 60 and not gname: add_vt("MOMENTUM ROTATION", f"top {tn} by {lb}-day return, monthly" + gname, tg, base)
    text = [f"LAB 15: {len(alts)} alts + BTC, {fmt(days[i0])} to {fmt(days[-1])}; older half to {fmt(days[imid])}. Start 1000. Cost {SIDE:.2%} per side. Strategy returns are applied the day after the signal.",
            "Survivorship bias: only coins listed today are used, which flatters coin-picking strategies (momentum, trend) more than BTC. 3 years is one market cycle: treat differences as hints, not proof.", ""]
    out = []; last = None
    for group, name, s in results:
        if group != last: text += ["", group]; last = group
        yrs = "  ".join(f"{y[2:]} {g * 100:+.0f}%" for y, g in s["years"])
        text.append(f"  {name}\n      final {s['final']:>7,.0f}  max drawdown {s['dd']:>4.0f}%  Sharpe {s['sharpe']:.2f}  older half {s['h1']:+.0f}%  newer half {s['h2']:+.0f}%  | {yrs}")
        out.append(dict(group=group, name=name, final=round(s["final"]), max_dd_pct=round(s["dd"]), sharpe=round(s["sharpe"], 2), older_half_pct=round(s["h1"]), newer_half_pct=round(s["h2"])))
    text += ["", "HOW TO READ: look for a strategy that (1) beats holding BTC on Sharpe or max drawdown, and (2) is positive in BOTH halves. Neighbouring settings (20/55/100 days, 30/60/90 days) should give similar answers; if only one setting works, it is luck. The vol-targeted lines show whether scaling down in turbulent times cuts the drawdown without killing the profit."]
    t = "\n".join(text)
    with open(os.path.join(scanner.HERE, "lab15_results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, list(out[0].keys())); w.writeheader(); w.writerows(out)
    open(os.path.join(scanner.HERE, "lab15_summary.txt"), "w").write(t + "\n"); print(t)
    try: scanner.notify("Strategy lab 15 finished", "Trend / momentum / vol-target test done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
