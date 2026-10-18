#!/usr/bin/env python3
"""Strategy lab 18: perpetual-futures funding rates as a crowd-positioning signal for BTC and ETH.
Data: Binance's public history downloads (data.binance.vision monthly files), which normally work from GitHub's servers even when the live API is blocked.
Funding is paid every 8 hours; 0.010% per 8h is the neutral default. Strongly positive = crowded longs; negative = crowded shorts.
Tests: (1) forward return of the coin after days in each funding bucket (next 1 / 7 / 30 days); (2) 'buy when funding is at or below a level, hold 7/14/30 days' versus random entries, older/newer half. Cost LAB_SIDE per side.
Writes lab18_summary.txt."""
import os, io, csv, time, zipfile, calendar, random
from multiprocessing import Pool
import scanner, backtest as B
import backtest_lab16 as L16

START = L16.START; RT = L16.RT; fmt = L16.fmt

def fetch(sym):
    out = {}; fails = []; t = time.gmtime(); ny, nm = t.tm_year, t.tm_mon
    y, m = 2022, 6
    while (y, m) < (ny, nm):
        url = f"https://data.binance.vision/data/futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{y}-{m:02d}.zip"
        try:
            z = zipfile.ZipFile(io.BytesIO(scanner.http(url)))
            for line in z.read(z.namelist()[0]).decode().splitlines():
                p = line.split(",")
                try: ts = int(p[0]); v = float(p[-1])
                except ValueError: continue
                out.setdefault(ts // 86400000, []).append(v)
        except Exception as e: fails.append(f"{y}-{m:02d}: {str(e)[:30]}")
        m += 1
        if m > 12: y, m = y + 1, 1
    return {d: sum(v) / len(v) for d, v in out.items()}, fails

def main():
    with Pool(2) as p: res = p.map(L16.load, ["BTC", "ETH"])
    data = {t: d for t, d, e in res if len(d) > 300}
    days = sorted(data["BTC"]); n = len(days)
    i0 = next(i for i, d in enumerate(days) if d * 86400 >= START); imid = (i0 + n - 1) // 2
    rng = random.Random(5)
    text = [f"LAB 18: funding rates, {fmt(days[i0])} to {fmt(days[-1])}; older half to {fmt(days[imid])}. Cost {RT:.2%} round trip. Entry next day's open.", ""]
    for sym, tok in (("BTCUSDT", "BTC"), ("ETHUSDT", "ETH")):
        fr, fails = fetch(sym)
        text.append(f"{tok}: funding history {len(fr)} days" + (f" (missing months: {len(fails)}; first error: {fails[0]})" if fails else ""))
        if len(fr) < 300: text += ["   not enough funding data - skipped", ""]; continue
        fv = [fr.get(d) for d in days]; s = [data[tok].get(d) for d in days]
        O = [x[0] if x else None for x in s]; C = [x[3] if x else None for x in s]
        text.append("   Forward return by funding level (average per-8h rate that day). Overlapping days, so a rough guide: bucket -> days, next 1d / 7d / 30d, share of days in the older half")
        for lo, hi, nm in ((-1, 0, "negative"), (0, 0.00005, "0 to 0.005%"), (0.00005, 0.0001, "0.005 to 0.01% (normal)"), (0.0001, 0.0003, "0.01 to 0.03%"), (0.0003, 1, "above 0.03% (crowded longs)")):
            ix = [i for i in range(i0, n - 31) if fv[i] is not None and lo <= fv[i] < hi and C[i] and C[i + 30] and C[i + 7] and C[i + 1]]
            if len(ix) < 10: text.append(f"   {nm:<30} only {len(ix)} days"); continue
            av = lambda h: sum(C[i + h] / C[i] - 1 for i in ix) / len(ix) * 100
            text.append(f"   {nm:<30} {len(ix):>4} days   {av(1):+5.2f}%  {av(7):+5.1f}%  {av(30):+5.1f}%   {100 * sum(i < imid for i in ix) / len(ix):.0f}% older")
        allr = [i for i in range(i0, n - 31) if C[i] and C[i + 30] and C[i + 7] and C[i + 1]]
        text.append(f"   {'ALL DAYS':<30} {len(allr):>4} days   {sum(C[i + 1] / C[i] - 1 for i in allr) / len(allr) * 100:+5.2f}%  {sum(C[i + 7] / C[i] - 1 for i in allr) / len(allr) * 100:+5.1f}%  {sum(C[i + 30] / C[i] - 1 for i in allr) / len(allr) * 100:+5.1f}%")
        text.append("")
        for thr, lab in ((0, "funding <= 0"), (0.00005, "funding <= 0.005%"), (0.0003, "funding >= 0.03% (SHORT-side test: buy only if NOT crowded -> shown as 'avoid')")):
            for hold in (7, 14, 30):
                if thr == 0.0003: continue
                sig = [fv[i] is not None and fv[i] <= thr for i in range(n)]
                text.append(L16.line(f"{tok}: {lab}, hold {hold}d", L16.trades(sig, O, C, hold, i0, n), L16.randoms(O, C, hold, i0, n, 500, rng), imid))
        for hold in (7, 14, 30):
            sig = [fv[i] is not None and fv[i] >= 0.0003 for i in range(n)]
            text.append(L16.line(f"{tok}: funding >= 0.03% (crowded longs, buying here), hold {hold}d", L16.trades(sig, O, C, hold, i0, n), L16.randoms(O, C, hold, i0, n, 500, rng), imid))
        text.append("")
    text += ["HOW TO READ: the idea to confirm is 'negative/low funding precedes bounces and very high funding precedes weak returns'. It only matters if the edge is clearly above the error margin in BOTH halves. Funding extremes cluster in a few episodes, so n overstates the evidence."]
    t = "\n".join(text)
    open(os.path.join(scanner.HERE, "lab18_summary.txt"), "w").write(t + "\n"); print(t)
    try: scanner.notify("Strategy lab 18 finished", "Funding-rate test done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
