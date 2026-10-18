#!/usr/bin/env python3
"""Strategy lab 16: short-term mean reversion, crowd sentiment (Fear & Greed index) and futures funding rates, tested on BTC, ETH and a basket of large alts.
Window: 21 Nov 2022 (BTC bottom) to today, daily candles. A signal is read at a day's close, the trade is entered at the NEXT day's open and held a fixed number of days.
Costs: LAB_SIDE per side (default 0.1%). Every rule is compared with RANDOM entries on the same asset, same holding time, same period (random captures the drift of a rising market), and split into older half / newer half.
A. MEAN REVERSION: buy after a 2-day drop of X% (5/8/12%), hold 3/5/10 days. Also the classic RSI(2) < 10 rule while the coin is above its own 200-day average, hold 5 days.
B. SENTIMENT: Fear & Greed index (alternative.me, daily). Buy BTC/ETH when the index is at or below 10/20/25/30 (extreme fear), hold 7/14/30/60 days. Also a table of average forward returns by index bucket.
C. FUNDING RATES: BTC perpetual funding (tries Binance, then Bybit). Table of forward returns by funding bucket, and 'buy when funding is negative'. Skipped with a clear message if the data cannot be fetched.
Overlapping trades are not allowed (after an entry the next one waits until the hold ends), but market-wide events still cluster: the number of independent episodes is far smaller than n.
Writes lab16_summary.txt."""
import os, json, time, calendar, random, math
from multiprocessing import Pool
import scanner, backtest as B

START = calendar.timegm((2022, 11, 21, 0, 0, 0)); SIDE = float(os.environ.get("LAB_SIDE", "0.001")); RT = 2 * SIDE
fmt = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))

def load(tok):
    try:
        m = B.hist_crypto(tok, "1d", 2100)
        return tok, {int(r[0] // 86400): (r[1], r[2], r[3], r[4]) for r in m}, ""
    except Exception as e: return tok, {}, str(e)[:60]

def series(d, days):
    return [d.get(x) for x in days]

def trades(sig, O, C, hold, i0, i1):
    """sig[i] True at close i -> buy open i+1, sell close i+hold (return incl. costs). No overlap. Returns list of (index, return)."""
    out = []; nxt = i0
    for i in range(i0, min(i1, len(sig) - hold - 2)):
        if i < nxt or not sig[i] or O[i + 1] is None or C[i + hold] is None: continue
        out.append((i, C[i + hold] / O[i + 1] - 1 - RT)); nxt = i + hold + 1
    return out

def randoms(O, C, hold, i0, i1, k, rng):
    xs = []
    for _ in range(k):
        i = rng.randrange(i0, i1 - hold - 2)
        if O[i + 1] and C[i + hold]: xs.append(C[i + hold] / O[i + 1] - 1 - RT)
    return xs

def line(label, tr, rnd, imid):
    if len(tr) < 5: return f"   {label:<48} n={len(tr):>3}  too few trades"
    r = [x for _, x in tr]; m = sum(r) / len(r) * 100; sd = (sum((x - m / 100) ** 2 for x in r) / (len(r) - 1)) ** .5 * 100 / len(r) ** .5
    rm = sum(rnd) / len(rnd) * 100 if rnd else 0.0; w = 100 * sum(1 for x in r if x > 0) / len(r)
    a = [x for i, x in tr if i < imid]; b = [x for i, x in tr if i >= imid]
    ha = f"{sum(a) / len(a) * 100:+.1f}%" if a else "  n/a"; hb = f"{sum(b) / len(b) * 100:+.1f}%" if b else "  n/a"
    return f"   {label:<48} n={len(tr):>3}  {m:+5.1f}% (+/-{sd:.1f})  win {w:3.0f}%  random {rm:+5.1f}%  edge {m - rm:+5.1f}%  older {ha}/newer {hb} (n={len(a)}/{len(b)})"

def rsi2(c):
    out = [None] * len(c); ag = al = None
    for i in range(1, len(c)):
        if c[i] is None or c[i - 1] is None: ag = al = None; continue
        ch = c[i] - c[i - 1]; g = max(ch, 0); l = max(-ch, 0)
        if ag is None: ag, al = g, l
        else: ag = (ag + g) / 2; al = (al + l) / 2
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al) if i > 5 else None
    return out

def fng():
    try:
        j = json.loads(scanner.http("https://api.alternative.me/fng/?limit=0&format=json"))
        return {int(int(x["timestamp"]) // 86400): int(x["value"]) for x in j["data"]}
    except Exception as e:
        print("Fear & Greed fetch failed:", str(e)[:80]); return {}

def funding():
    out = {}; err = []
    try:
        t = int((START - 86400 * 400) * 1000)
        while True:
            j = json.loads(scanner.http(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&startTime={t}&limit=1000"))
            if not j: break
            for x in j: out.setdefault(int(x["fundingTime"]) // 86400000, []).append(float(x["fundingRate"]))
            t = j[-1]["fundingTime"] + 1
            if len(j) < 1000: break
    except Exception as e: err.append("binance: " + str(e)[:50])
    if len(out) > 300: return {d: sum(v) / len(v) for d, v in out.items()}, "Binance"
    out = {}
    try:
        end = int(time.time() * 1000); start_ms = int((START - 86400 * 400) * 1000)
        while end > start_ms:
            j = json.loads(scanner.http(f"https://api.bybit.com/v5/market/funding/history?category=linear&symbol=BTCUSDT&limit=200&endTime={end}"))["result"]["list"]
            if not j: break
            for x in j: out.setdefault(int(x["fundingRateTimestamp"]) // 86400000, []).append(float(x["fundingRate"]))
            end = min(int(x["fundingRateTimestamp"]) for x in j) - 1
    except Exception as e: err.append("bybit: " + str(e)[:50])
    if len(out) > 300: return {d: sum(v) / len(v) for d, v in out.items()}, "Bybit"
    return {}, "; ".join(err) or "no data"

def main():
    coins = [c for c in scanner.top100() if c not in ("BTC", "ETH")][:10]
    print("Lab 16: loading...", flush=True)
    with Pool(max(1, os.cpu_count() or 1)) as p: res = p.map(load, ["BTC", "ETH"] + coins)
    data = {t: d for t, d, e in res if len(d) > 300}
    days = sorted(data["BTC"]); n = len(days); idx = {d: i for i, d in enumerate(days)}
    i0 = next(i for i, d in enumerate(days) if d * 86400 >= START); imid = (i0 + n - 1) // 2
    A = {}
    for t in data:
        s = series(data[t], days); A[t] = dict(O=[x[0] if x else None for x in s], H=[x[1] if x else None for x in s], L=[x[2] if x else None for x in s], C=[x[3] if x else None for x in s])
    assets = [("BTC", ["BTC"]), ("ETH", ["ETH"]), ("10 large alts", [c for c in coins if c in A])]
    rng = random.Random(7); text = [f"LAB 16: {fmt(days[i0])} to {fmt(days[-1])}; older half to {fmt(days[imid])}. Cost {RT:.2%} round trip. Entry next day's open. 'edge' = rule minus random entries on the same asset and hold time.", ""]
    # A. mean reversion
    text.append("A. SHORT-TERM MEAN REVERSION (buy after a sharp 2-day drop)")
    for name, group in assets:
        for X in (0.05, 0.08, 0.12):
            for hold in (3, 5, 10):
                tr = []; rnd = []
                for t in group:
                    C = A[t]["C"]; sig = [i >= 2 and C[i] and C[i - 2] and C[i] / C[i - 2] - 1 <= -X for i in range(n)]
                    tr += trades(sig, A[t]["O"], C, hold, i0, n); rnd += randoms(A[t]["O"], C, hold, i0, n, 400, rng)
                text.append(line(f"{name}: 2-day drop >= {int(X * 100)}%, hold {hold}d", tr, rnd, imid))
        for hold in (5,):
            tr = []; rnd = []
            for t in group:
                C = A[t]["C"]; r = rsi2(C)
                sig = [bool(r[i] is not None and r[i] < 10 and i >= 200 and C[i] and sum(x for x in C[i - 199:i + 1] if x) / 200 < C[i]) for i in range(n)]
                tr += trades(sig, A[t]["O"], C, hold, i0, n); rnd += randoms(A[t]["O"], C, hold, i0, n, 400, rng)
            text.append(line(f"{name}: RSI(2) < 10 and above 200-day avg, hold {hold}d", tr, rnd, imid))
        text.append("")
    # B. sentiment
    f = fng()
    text.append("B. FEAR & GREED (crowd sentiment)")
    if not f: text.append("   Fear & Greed data could not be fetched from this machine - section skipped.")
    else:
        fv = [f.get(d) for d in days]
        for name, group in assets[:2]:
            C = A[group[0]]["C"]; O = A[group[0]]["O"]
            for T in (10, 20, 25, 30):
                for hold in (7, 14, 30, 60):
                    sig = [fv[i] is not None and fv[i] <= T for i in range(n)]
                    tr = trades(sig, O, C, hold, i0, n); rnd = randoms(O, C, hold, i0, n, 600, rng)
                    text.append(line(f"{name}: index <= {T}, hold {hold}d", tr, rnd, imid))
        text.append("")
        text.append("   Forward BTC return by index level (all days, overlapping, so only a rough guide): bucket -> days, avg next 7d / 30d / 60d")
        C = A["BTC"]["C"]
        for lo, hi, nm in ((0, 20, "extreme fear 0-20"), (20, 40, "fear 20-40"), (40, 60, "neutral 40-60"), (60, 80, "greed 60-80"), (80, 101, "extreme greed 80+")):
            ix = [i for i in range(i0, n - 61) if fv[i] is not None and lo <= fv[i] < hi and C[i] and C[i + 60]]
            if len(ix) < 10: text.append(f"   {nm:<20} only {len(ix)} days"); continue
            av = lambda h: sum(C[i + h] / C[i] - 1 for i in ix) / len(ix) * 100
            text.append(f"   {nm:<20} {len(ix):>4} days   {av(7):+5.1f}%  {av(30):+5.1f}%  {av(60):+5.1f}%")
        allr = [i for i in range(i0, n - 61) if C[i] and C[i + 60]]
        text.append(f"   {'ALL DAYS':<20} {len(allr):>4} days   {sum(C[i + 7] / C[i] - 1 for i in allr) / len(allr) * 100:+5.1f}%  {sum(C[i + 30] / C[i] - 1 for i in allr) / len(allr) * 100:+5.1f}%  {sum(C[i + 60] / C[i] - 1 for i in allr) / len(allr) * 100:+5.1f}%")
    text.append("")
    # C. funding
    text.append("C. FUTURES FUNDING RATE (BTC perpetual, average of the day's 8-hour rates)")
    fr, src = funding()
    if not fr: text.append(f"   Funding data could not be fetched ({src}); exchanges often block cloud servers. Section skipped.")
    else:
        text.append(f"   source: {src}, {len(fr)} days")
        fv = [fr.get(d) for d in days]; C = A["BTC"]["C"]; O = A["BTC"]["O"]
        text.append("   Forward BTC return by funding level (rate per 8h; 0.010% is the exchange default): bucket -> days, avg next 7d / 30d")
        for lo, hi, nm in ((-1, 0, "negative"), (0, 0.0001, "0 to 0.01%"), (0.0001, 0.0003, "0.01 to 0.03%"), (0.0003, 1, "above 0.03% (crowded longs)")):
            ix = [i for i in range(i0, n - 31) if fv[i] is not None and lo <= fv[i] < hi and C[i] and C[i + 30]]
            if len(ix) < 10: text.append(f"   {nm:<30} only {len(ix)} days"); continue
            av = lambda h: sum(C[i + h] / C[i] - 1 for i in ix) / len(ix) * 100
            text.append(f"   {nm:<30} {len(ix):>4} days   {av(7):+5.1f}%  {av(30):+5.1f}%")
        for hold in (7, 14, 30):
            sig = [fv[i] is not None and fv[i] <= 0 for i in range(n)]
            text.append(line(f"BTC: funding <= 0, hold {hold}d", trades(sig, O, C, hold, i0, n), randoms(O, C, hold, i0, n, 600, rng), imid))
    text += ["", "HOW TO READ: a rule is interesting only if its edge is clearly above its error margin and has the same sign in the older and newer half. With dozens of settings tried, a few will look good by luck; settings next to each other should agree. These are daily-data tests on one 3-year cycle; sentiment and funding extremes happen only a handful of independent times."]
    t = "\n".join(text)
    open(os.path.join(scanner.HERE, "lab16_summary.txt"), "w").write(t + "\n"); print(t)
    try: scanner.notify("Strategy lab 16 finished", "Mean reversion / sentiment / funding test done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
