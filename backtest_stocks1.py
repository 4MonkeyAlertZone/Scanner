#!/usr/bin/env python3
"""Stocks step 1: does the crypto 'in / out' regime idea work on stock INDEXES? S&P 500 (since 1950) and Nasdaq Composite (since 1971), Yahoo daily closes (price index, dividends NOT included, cash earns 0 in the strategy = conservative for the strategy).
Signal at the close of day i is applied to day i+1's return (no peeking), cost 0.05% per position change (index ETF), long only.
Rules (all declared before running, ALL printed):
 1. 200d: IN while close > 200-day average
 2. 200d+50d: IN while close > 200-day AND > 50-day average (the crypto rule, without OI)
 3. MA grid: slow 150/200/250 x fast 40/50/60 (both required)
 4. Band: 200d+50d with a 1% / 2% band around the 50-day line (enter above 1.01x, leave below 0.99x)
 5. VIX filter (from 1990): 200d+50d AND VIX close below 25 / 30 / 35;  VIX only: IN while VIX below 25 / 30
 6. Breadth is NOT tested here (needs constituent history, not available for free); a later step with the stock basket can use 'share of stocks above their 200-day'.
 Periods: S&P: 1950-1999 (old) vs 2000-now (new); Nasdaq: 1971-1999 vs 2000-now; 'new' is the honest test of anything chosen by looking at 'old'. Each row also shows the strategy's growth multiple, CAGR, worst drawdown, flips per year, time in market.
 BEAR MARKETS: every buy-and-hold drawdown of 20%+ (peak to trough on closes) and what the 200d+50d rule did over the same dates (drawdown from the same peak date to the same trough date, and whether it was IN at the peak and at the trough).
 Random-timing null for 200d+50d (800 circular shifts, same time in market). Writes stocks1_summary.txt."""
import os, json, time, random, calendar, urllib.parse
import scanner

OUT = scanner.HERE; fd = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))
COST = 0.0005
def d0(y, m, dd): return calendar.timegm((y, m, dd, 0, 0, 0)) // 86400

def fetch(sym):
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?interval=1d&period1=-631152000&period2={int(time.time())}&includePrePost=false"
    j = json.loads(scanner.http(u, headers=scanner.UA))["chart"]["result"][0]
    q = j["indicators"]["quote"][0]["close"]; out = {}
    for t, c in zip(j["timestamp"], q):
        if c: out[int(t // 86400)] = c
    ks = sorted(out)
    print(f"{sym}: {len(out)} daily rows {fd(ks[0])} to {fd(ks[-1])}")
    if (sym != "^VIX" and len(out) < 3000) or (ks[-1] - ks[0]) / max(1, len(out)) > 3: raise SystemExit(f"{sym}: data looks too sparse ({len(out)} rows), stopping")
    return out

def sma(C, k):
    out = [None] * len(C); s = 0.0
    for i, x in enumerate(C):
        s += x
        if i >= k: s -= C[i - k]
        if i >= k - 1: out[i] = s / k
    return out

def hyst(C, m, h):
    out = [False] * len(C); st = False
    for i in range(len(C)):
        if m[i] is None: continue
        if st and C[i] < m[i] * (1 - h): st = False
        elif not st and C[i] > m[i] * (1 + h): st = True
        out[i] = st
    return out

def ev(pos, R, a, b):
    """pos[i] earns R[i+1]; period = index range [a, b)."""
    eq = 1.0; curve = [1.0]; prev = 0.0; flips = 0; inm = 0; last = False
    for i in range(a, b - 1):
        p = pos[i]; eq *= 1 + p * R[i + 1] - COST * abs(p - prev); prev = p; curve.append(eq)
        isin = p > 0
        if isin != last: flips += 1
        last = isin; inm += isin
    pk = 0; dd = 0
    for x in curve: pk = max(pk, x); dd = min(dd, x / pk - 1)
    yrs = max(0.5, (b - 1 - a) / 365.25)
    return dict(final=eq, cagr=(eq ** (1 / yrs) - 1) * 100, dd=dd * 100, flips=flips / yrs, tim=inm / max(1, b - 1 - a) * 100)

def analyse(name, px, vix, split, start_note):
    days = sorted(px); n = len(days); C = [px[d] for d in days]
    R = [0.0] + [C[i] / C[i - 1] - 1 for i in range(1, n)]
    ma = {k: sma(C, k) for k in (40, 50, 60, 150, 200, 250)}
    A = {k: [ma[k][i] is not None and C[i] > ma[k][i] for i in range(n)] for k in ma}
    V = [vix.get(d) if vix else None for d in days]
    # carry VIX forward over missing days
    last = None
    for i in range(n):
        if V[i] is None: V[i] = last
        else: last = V[i]
    rules = {}
    rules["buy and hold"] = [1] * n
    rules["200d"] = A[200]
    rules["200d + 50d (crypto rule)"] = [A[200][i] and A[50][i] for i in range(n)]
    for s in (150, 200, 250):
        for f in (40, 50, 60):
            rules[f"grid slow {s} / fast {f}"] = [A[s][i] and A[f][i] for i in range(n)]
    for h in (.01, .02):
        hm = hyst(C, ma[50], h); rules[f"200d + 50d band {int(h * 100)}%"] = [A[200][i] and hm[i] for i in range(n)]
    if vix:
        for th in (25, 30, 35):
            rules[f"200d + 50d + VIX<{th}"] = [A[200][i] and A[50][i] and V[i] is not None and V[i] < th for i in range(n)]
        for th in (25, 30):
            rules[f"VIX<{th} only"] = [V[i] is not None and V[i] < th for i in range(n)]
    i0 = next(i for i, d in enumerate(days) if d >= START_AFTER[name]); isp = next(i for i, d in enumerate(days) if d >= split)
    vstart = next((i for i in range(n) if vix and days[i] >= min(vix)), i0)
    L = [f"{'=' * 4} {name}  {fd(days[i0])} to {fd(days[-1])}  ({start_note}) {'=' * 4}", "",
         f"{'rule':<32}{'all x':>9}{'CAGR%':>7}{'DD%':>6}{'flips':>6}{'in%':>5} |{'OLD CAGR':>9}{'DD%':>6} |{'NEW x':>8}{'CAGR%':>7}{'DD%':>6}"]
    res = {}
    for lab, pos in rules.items():
        pos = [1.0 if x else 0.0 for x in pos]
        a0 = max(i0, vstart) if "VIX" in lab else i0
        allm = ev(pos, R, a0, n); old = ev(pos, R, a0, isp); new = ev(pos, R, max(a0, isp), n); res[lab] = (allm, old, new)
        L.append(f"{lab:<32}{allm['final']:>9.1f}{allm['cagr']:>7.1f}{allm['dd']:>6.0f}{allm['flips']:>6.1f}{allm['tim']:>5.0f} |{old['cagr']:>9.1f}{old['dd']:>6.0f} |{new['final']:>8.1f}{new['cagr']:>7.1f}{new['dd']:>6.0f}")
    if vix: L.append(f"(VIX rows start {fd(min(vix))}, so their 'all' and 'old' periods are shorter and not comparable with the others)")
    b = res["200d + 50d (crypto rule)"]; bh = res["buy and hold"]
    # consistency: Calmar vs base, old and new
    cal = lambda m: m["cagr"] / max(1.0, -m["dd"])
    good = [lab for lab, (al, ol, nw) in res.items() if lab not in ("buy and hold", "200d + 50d (crypto rule)") and "VIX" not in lab and cal(ol) >= cal(b[1]) and cal(nw) >= cal(b[2])]
    L += ["", f"Variants with a better return-to-drawdown ratio than the 200d+50d rule in BOTH eras (excluding VIX rows): {', '.join(good) if good else 'none'}"]
    # bear markets
    pos = [1.0 if x else 0.0 for x in rules["200d + 50d (crypto rule)"]]
    eq = [1.0]
    for i in range(1, n): eq.append(eq[-1] * (1 + pos[i - 1] * R[i] - COST * abs(pos[i - 1] - (pos[i - 2] if i > 1 else 0))))
    bears = []; pk = 0; peak_i = 0; i = 0
    while i < n:
        if C[i] >= C[pk]: pk = i; i += 1; continue
        # in a drawdown from pk; find trough until recovery
        j = i; tr = i
        while j < n and C[j] < C[pk]:
            if C[j] < C[tr]: tr = j
            j += 1
        if C[tr] / C[pk] - 1 <= -.20 and days[pk] >= days[i0] - 400: bears.append((pk, tr, j))
        i = j; pk = j if j < n else pk
    L += ["", "BEAR MARKETS (buy-and-hold fell 20%+): dates, buy-and-hold drop, what the 200d+50d rule's account did from the same peak to the same trough, state at peak/trough", f"{'peak':<12}{'trough':<12}{'hold%':>7}{'rule%':>8}  IN at peak / at trough / exit date"]
    for pk, tr, rec in bears:
        if days[pk] < days[i0]: continue
        sdrop = (eq[tr] / eq[pk] - 1) * 100
        ex = next((days[k] for k in range(pk, tr + 1) if not pos[k]), None)
        L.append(f"{fd(days[pk]):<12}{fd(days[tr]):<12}{(C[tr] / C[pk] - 1) * 100:>7.0f}{sdrop:>8.0f}  {'IN' if pos[pk] else 'out'} / {'IN' if pos[tr] else 'out'} / {fd(ex) if ex else 'never left'}")
    # null
    rng = random.Random(3); cnt_f = cnt_d = 0; N = 800
    for _ in range(N):
        sh = rng.randrange(250, n - 250); ps = pos[-sh:] + pos[:-sh]; m = ev(ps, R, i0, n)
        cnt_f += m["final"] >= b[0]["final"]; cnt_d += m["dd"] >= b[0]["dd"]
    L += ["", f"Random-timing null (800 shifts of the 200d+50d IN/OUT series, same time in market): share ending at least as high {cnt_f / N:.2f}; share with a drawdown at least as small {cnt_d / N:.2f}", ""]
    return L

START_AFTER = {}
def main(data=None):
    if data is None:
        data = {"S&P 500": fetch("^GSPC"), "Nasdaq Composite": fetch("^IXIC"), "VIX": fetch("^VIX")}
    vix = data["VIX"]
    START_AFTER["S&P 500"] = d0(1950, 1, 3); START_AFTER["Nasdaq Composite"] = d0(1971, 3, 1)
    L = ["STOCKS STEP 1: INDEX REGIME BACKTEST", "",
         "Price indexes (no dividends), cash earns 0, 0.05% per position change, signal at the close earns the next day. S&P 500 from 1950, Nasdaq from 1971; OLD = before 2000, NEW = 2000 to now. VIX rules start 1990.",
         "Read the NEW columns first: they are the part not used to form the idea. Indexes are not survivorship-biased, but the large-stock basket in step 2 will be.", ""]
    L += analyse("S&P 500", data["S&P 500"], vix, d0(2000, 1, 1), "price index")
    L += analyse("Nasdaq Composite", data["Nasdaq Composite"], vix, d0(2000, 1, 1), "price index")
    L += ["Honest limits: dividends and cash interest are excluded (cash interest would help the rule, dividends help buy-and-hold), signals are on closes while real trades happen next day, and a rule that avoided 2000-02 and 2008 may simply have had few false exits in a few big bears."]
    t = "\n".join(L); open(os.path.join(OUT, "stocks1_summary.txt"), "w").write(t + "\n"); print(t)

if __name__ == "__main__":
    main()
