#!/usr/bin/env python3
"""Strategy lab 20: the COMBINED strategy, executed on HOURLY data at live prices, tested over both bull cycles.
Everything is evaluated hour by hour, with prices you could actually have got - never 'the daily close' or 'the next open of a daily candle':
  RISK SWITCH   BTC's last hourly close above its 200-day average (4800 hours). Decisions in an hour use the switch as it stood at the end of the previous hour.
  CORE sleeve   hold BTC while the switch is on (buy/sell at the open of the hour after the switch flips).
  TREND sleeve  up to 20 alts, each 1/20 of the sleeve. BUY-STOP at the 55-day high (1320 hours): when an hour's high trades above it, you are filled at the higher of the level and that hour's open.
                Trailing stop = highest hourly close since entry minus 3 x the 20-day average daily range; when an hour's low trades through it you are out at the stop (or at that hour's open if it gapped below).
                Also sold at the next hour's open if the risk switch turns off. Only opened while the switch is on.
  DROP sleeve   up to 10 positions of 1/10: a coin down 16% or more over the last 48 hours (checked every hour) is bought at the next hour's open and sold 240 hours later at that open. No risk switch (as tested in labs 17 and 19).
Costs: LAB_SIDE per side on every fill (default 0.1%, which also covers slippage). Data: Binance.US hourly candles, top 40 coins + BTC, as far back as they go.
COMBINATIONS are fixed in advance (not searched): core/trend/drop = 50/30/20, 40/40/20, 34/33/33, and each sleeve alone. Sleeves are rebalanced to their weights every 30 days.
Windows: bull cycle 1 (1 Oct 2020 - 10 Nov 2021), the bear year (10 Nov 2021 - 21 Nov 2022), bull cycle 2 (21 Nov 2022 - 31 Aug 2025), plus the whole period. All rules were developed on cycle 2, so cycle 1 is the genuine out-of-sample test.
Writes lab20_summary.txt."""
import os, time, math, calendar
from collections import deque
from multiprocessing import Pool
import scanner, backtest as B

SIDE = float(os.environ.get("LAB_SIDE", "0.001")); HBTC = 4800; HIGHN = 1320; HOLD = 240; DROPH = 48; DROPX = 0.16; TSLOTS = 20; DSLOTS = 10; ATRK = 3.0
ts = lambda y, m, d: calendar.timegm((y, m, d, 0, 0, 0)) // 3600
WINDOWS = [("BULL CYCLE 1 (1 Oct 2020 - 10 Nov 2021) [out-of-sample]", ts(2020, 10, 1), ts(2021, 11, 10)), ("BEAR YEAR (10 Nov 2021 - 21 Nov 2022)", ts(2021, 11, 10), ts(2022, 11, 21)),
           ("BULL CYCLE 2 (21 Nov 2022 - 31 Aug 2025) [where the rules were found]", ts(2022, 11, 21), ts(2025, 8, 31)), ("WHOLE PERIOD", None, None)]

def load(tok):
    best = []
    for attempt in range(4):
        try:
            m = B.hist_crypto(tok, "1h", 64000)
            if len(m) > 1000 and len(m) <= len(best): break
            if len(m) > len(best): best = m
            if len(best) > 55000: break
        except Exception as e: print(f"  {tok}: attempt {attempt + 1} failed: {str(e)[:60]}", flush=True)
        time.sleep(4 * (attempt + 1))
    print(f"  {tok}: {len(best)} hourly candles", flush=True)
    return tok, {int(r[0] // 3600): (r[1], r[2], r[3], r[4]) for r in best}, ""

def prep(d, h0, HN):
    O = [None] * HN; H = [None] * HN; L = [None] * HN; C = [None] * HN
    for k, (o, h, l, c) in d.items():
        if h0 <= k < h0 + HN: O[k - h0] = o; H[k - h0] = h; L[k - h0] = l; C[k - h0] = c
    return O, H, L, C

def rolling_high(H, n):
    """LV[t] = max of H[t-n..t-1] (None entries skipped; needs at least 90% of the window)."""
    HN = len(H); out = [None] * HN; dq = deque(); cnt = 0
    for t in range(HN):
        lo = t - n
        while dq and dq[0][0] < lo: dq.popleft()
        if t >= n and len(dq) and cnt >= n * 0.9: out[t] = dq[0][1]
        h = H[t]
        if h is not None:
            while dq and dq[-1][1] <= h: dq.pop()
            dq.append((t, h))
        cnt = min(n, cnt + 1) if h is not None else max(0, cnt - 0)
    return out

def daily_atr(h0, H, L, C):
    """ATR (20-day average true range) of the last COMPLETED UTC day, mapped to every hour."""
    HN = len(H); out = [None] * HN; days = {}
    for t in range(HN):
        if C[t] is None: continue
        d = (h0 + t) // 24; r = days.setdefault(d, [H[t], L[t], C[t]]); r[0] = max(r[0], H[t]); r[1] = min(r[1], L[t]); r[2] = C[t]
    ds = sorted(days); tr = {}; prev = None
    for d in ds:
        hh, ll, cc = days[d]
        tr[d] = max(hh - ll, abs(hh - prev), abs(ll - prev)) if prev is not None else hh - ll
        prev = cc
    atr = {}
    for i, d in enumerate(ds):
        if i >= 20 and ds[i - 20] == d - 20: atr[d] = sum(tr[x] for x in ds[i - 19:i + 1]) / 20
    for t in range(HN):
        a = atr.get((h0 + t) // 24 - 1)
        if a: out[t] = a
    return out

def sim(kind, HN, h0, A, coins, gate, start):
    """Returns the sleeve's hourly equity list (1.0 at 'start'). A[tok] = (O,H,L,C)."""
    cash = 1.0; pos = {}; eq = [1.0] * HN; pend = []; last = {c: None for c in A}
    extra = {}
    if kind == "trend":
        extra["LV"] = {c: rolling_high(A[c][1], HIGHN) for c in coins}; extra["ATR"] = {c: daily_atr(h0, A[c][1], A[c][2], A[c][3]) for c in coins}
    for t in range(start, HN):
        g = gate[t - 1]
        for c in coins + (["BTC"] if kind == "core" else []):
            c_ = A[c][3][t]
            if c_ is not None: last[c] = c_
        e_est = cash + sum(p["u"] * (last[c] or p["px"]) for c, p in pos.items())
        if kind == "core":
            O, H, L, C = A["BTC"]
            if g and "BTC" not in pos and O[t]: pos["BTC"] = dict(u=cash * (1 - SIDE) / O[t], px=O[t]); cash = 0.0
            elif (g is False) and "BTC" in pos and O[t]: cash = pos["BTC"]["u"] * O[t] * (1 - SIDE); pos.pop("BTC")
        elif kind == "trend":
            for c in list(pos):
                O, H, L, C = A[c]
                if O[t] is None: continue
                p = pos[c]; atr = extra["ATR"][c][t]; out = None
                if g is False: out = O[t]
                elif atr is not None and L[t] <= p["top"] - ATRK * atr: out = min(O[t], p["top"] - ATRK * atr)
                if out is not None: cash += p["u"] * out * (1 - SIDE); pos.pop(c)
                elif C[t] is not None: p["top"] = max(p["top"], C[t])
            if g and len(pos) < TSLOTS:
                cand = []
                for c in coins:
                    if c in pos: continue
                    O, H, L, C = A[c]; lv = extra["LV"][c][t]
                    if lv is not None and O[t] is not None and H[t] is not None and H[t] > lv: cand.append((H[t] / lv, c, max(lv, O[t])))
                cand.sort(reverse=True)
                for _, c, px in cand:
                    if len(pos) >= TSLOTS: break
                    size = min(cash, e_est / TSLOTS)
                    if size <= 1e-9: break
                    pos[c] = dict(u=size * (1 - SIDE) / px, px=px, top=px); cash -= size
        else:  # drop
            for c in list(pos):
                p = pos[c]
                if t >= p["exit"] and A[c][0][t] is not None: cash += p["u"] * A[c][0][t] * (1 - SIDE); pos.pop(c)
            for c in pend:
                if c in pos or len(pos) >= DSLOTS or A[c][0][t] is None: continue
                size = min(cash, e_est / DSLOTS)
                if size <= 1e-9: break
                pos[c] = dict(u=size * (1 - SIDE) / A[c][0][t], px=A[c][0][t], exit=t + HOLD); cash -= size
            pend = []
            for c in coins:
                C = A[c][3]
                if c not in pos and C[t] is not None and t >= DROPH and C[t - DROPH] is not None and C[t] / C[t - DROPH] - 1 <= -DROPX: pend.append(c)
        eq[t] = cash + sum(p["u"] * (last[c] or p["px"]) for c, p in pos.items())
    return eq

def metrics(eq, a, b, HN):
    a = max(a, 0); b = min(b, HN - 1)
    xs = eq[a:b + 1]
    if len(xs) < 500 or xs[0] <= 0: return None
    r = [xs[i] / xs[i - 1] - 1 for i in range(1, len(xs))]; mu = sum(r) / len(r); sd = (sum((x - mu) ** 2 for x in r) / (len(r) - 1)) ** .5
    peak = xs[0]; dd = 0.0
    for x in xs: peak = max(peak, x); dd = min(dd, x / peak - 1)
    return xs[-1] / xs[0], dd * 100, (mu / sd * math.sqrt(8760) if sd > 0 else 0)

def combine(eqs, w, HN, start):
    r = {k: [0.0] + [eqs[k][i] / eqs[k][i - 1] - 1 if eqs[k][i - 1] > 0 else 0.0 for i in range(1, HN)] for k in w}
    v = {k: w[k] for k in w}; out = [1.0] * HN
    for t in range(start, HN):
        for k in v: v[k] *= 1 + r[k][t]
        tot = sum(v.values()); out[t] = tot
        if (t - start) % 720 == 719: v = {k: w[k] * tot for k in w}
    return out

def main():
    toks = [c for c in scanner.top100() if c != "BTC"][:40]
    print("Lab 20: loading hourly candles (long)...", flush=True)
    with Pool(2) as p: res = p.map(load, ["BTC"] + toks)
    data = {t: d for t, d, e in res if len(d) > 3000}
    if "BTC" not in data: raise SystemExit("no BTC hourly data")
    h0 = min(data["BTC"]); h1 = max(data["BTC"]); HN = h1 - h0 + 1
    A = {t: prep(d, h0, HN) for t, d in data.items()}
    coins = [t for t in A if t != "BTC"]
    cb = A["BTC"][3]; pre = [0.0]; lastc = None; cf = []
    for x in cb:
        lastc = x if x is not None else lastc; cf.append(lastc)
    for x in cf: pre.append(pre[-1] + (x or 0))
    gate = [None] * HN
    for t in range(HN):
        if t >= HBTC and cf[t]: gate[t] = cf[t] > (pre[t + 1] - pre[t + 1 - HBTC]) / HBTC
    start = HBTC + 1
    text = [f"LAB 20: hourly data for {len(coins)} coins + BTC from {time.strftime('%Y-%m-%d', time.gmtime(h0 * 3600))} to {time.strftime('%Y-%m-%d', time.gmtime(h1 * 3600))}. Cost {SIDE:.2%} per side. Sleeves traded from {time.strftime('%Y-%m-%d', time.gmtime((h0 + start) * 3600))} (200-day warm-up).", ""]
    eqs = {}
    for kind in ("core", "trend", "drop"):
        print(f"simulating {kind}...", flush=True); eqs[kind] = sim(kind, HN, h0, A, coins, gate, start)
    allv = {"CORE only: BTC while BTC > 200-day avg": {"core": 1.0}, "TREND only: alt breakouts with ATR trailing stop": {"trend": 1.0}, "DROP only: buy 16% two-day drops, hold 10 days": {"drop": 1.0},
            "COMBO 50/30/20  (core/trend/drop)": {"core": .5, "trend": .3, "drop": .2}, "COMBO 40/40/20": {"core": .4, "trend": .4, "drop": .2}, "COMBO 34/33/33": {"core": .34, "trend": .33, "drop": .33}}
    curves = {n: combine(eqs, w, HN, start) for n, w in allv.items()}
    btc = [1.0] * HN
    for t in range(start, HN): btc[t] = (cf[t] / cf[start]) if cf[t] and cf[start] else btc[t - 1]
    basket = [1.0] * HN; hold = {}
    for t in range(start, HN):
        if t > start:
            for c in list(hold):
                a, b = A[c][3][t - 1], A[c][3][t]
                if a and b: hold[c] *= b / a
        tot = sum(hold.values()) if hold else 1.0
        if not hold or (t - start) % 720 == 0:
            av = [c for c in coins if A[c][3][t]]
            hold = {c: tot / len(av) for c in av} if av else {}
        basket[t] = sum(hold.values()) if hold else (basket[t - 1] if t > start else 1.0)
    curves = {"BENCHMARK: hold BTC": btc, "BENCHMARK: hold the alt basket (equal weight, rebalanced monthly)": basket, **curves}
    for wn, a, b in WINDOWS:
        a2 = start if a is None else a - h0; b2 = HN - 1 if b is None else b - h0
        text.append(wn)
        if a2 < start or a2 >= HN: text.append("   not covered by the downloaded data"); text.append(""); continue
        for n, c in curves.items():
            m = metrics(c, a2, b2, HN)
            text.append(f"   {n:<66} " + (f"x{m[0]:5.2f}  worst fall {m[1]:4.0f}%  Sharpe {m[2]:.2f}" if m else "no data in this window"))
        text.append("")
    text += ["HOW TO READ: look at BULL CYCLE 1 first - the rules never saw it. A combination is only convincing if it (a) beats its own best single sleeve or holding BTC on Sharpe and worst fall in BOTH cycles and (b) does not depend on one sleeve. In a strong bull run, a strategy that sits in cash part of the time will usually earn less than holding BTC; the gain from combining shows up as a smaller fall and a smoother ride. Coins are survivors of today's top 40; early-cycle alt coverage is thin. Hourly candles still hide the order of prices inside each hour, so stop fills are approximate. Not financial advice."]
    t = "\n".join(text)
    open(os.path.join(scanner.HERE, "lab20_summary.txt"), "w").write(t + "\n"); print(t)
    try: scanner.notify("Strategy lab 20 finished", "Combined-strategy test done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
