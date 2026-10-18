#!/usr/bin/env python3
"""Strategy lab 19: how much do the sharp-drop and ATR-trend ideas lose when you trade at REAL live prices after a delay?
Uses HOURLY candles (top 40 coins + BTC, about 4 years). Every price used is the open of a specific hour, i.e. a price you could actually have got.
A. SHARP-DROP, intraday: signal = a coin is down X% (12% or 16%) over the last 48 HOURS, checked every hour (not only at the daily close). You buy at the open of the hour that is DELAY hours after the signal hour closes
   (delay 0 = the very next hour, as fast as a phone alert allows), hold 10 days (240 hours), sell at that hour's close. Delays 0, 1, 3, 6, 12, 24 hours. Compared with random entries. Cost 0.2% round trip.
B. ATR TREND: the same signals as the live paper test (55-day breakout, 3 x daily-range trailing stop, BTC above 200-day average, built from daily candles made from the hourly data).
   The signal appears at the daily close (00:00 UTC). Entries and exits are then executed at the open of the hour DELAY hours later (0, 1, 6, 12, 24), and compared with the 'daily close price' used in the paper test.
Reports trades, win rate, average and median return per trade. Writes lab19_summary.txt."""
import os, time, random, calendar, math
from multiprocessing import Pool
import scanner, backtest as B
import trend_paper as TP

START = calendar.timegm((2022, 11, 21, 0, 0, 0)); SIDE = float(os.environ.get("LAB_SIDE", "0.001")); RT = 2 * SIDE
fmt = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))

def load(tok):
    try:
        m = B.hist_crypto(tok, "1h", 36500)
        return tok, {int(r[0] // 3600): (r[1], r[2], r[3], r[4]) for r in m}, ""
    except Exception as e: return tok, {}, str(e)[:60]

def mean(v): return sum(v) / len(v) if v else 0.0

def main():
    toks = [c for c in scanner.top100() if c != "BTC"][:40]
    print("Lab 19: loading hourly candles (this takes a while)...", flush=True)
    with Pool(max(1, min(4, os.cpu_count() or 1))) as p: res = p.map(load, ["BTC"] + toks)
    data = {t: d for t, d, e in res if len(d) > 5000}
    if "BTC" not in data: raise SystemExit("no BTC hourly data")
    h0 = min(data["BTC"]); h1 = max(data["BTC"]); HN = h1 - h0 + 1
    arr = {}
    for t, d in data.items():
        O = [None] * HN; H = [None] * HN; L = [None] * HN; C = [None] * HN
        for k, (o, h, l, c) in d.items():
            if h0 <= k <= h1: O[k - h0] = o; H[k - h0] = h; L[k - h0] = l; C[k - h0] = c
        arr[t] = (O, H, L, C)
    s_idx = max(0, START // 3600 - h0); mid = (s_idx + HN) // 2; rng = random.Random(3)
    coins = [t for t in data if t != "BTC"]
    groups = [("ranks 1-10", [c for c in toks[:10] if c in data]), ("ranks 11-40", [c for c in toks[10:] if c in data])]
    text = [f"LAB 19: hourly candles, {len(coins)} coins + BTC, from {time.strftime('%Y-%m-%d', time.gmtime(max(START, h0 * 3600)))} to {time.strftime('%Y-%m-%d', time.gmtime(h1 * 3600))}. Cost {RT:.2%} round trip.", ""]
    # ---------------- A
    text.append("A. SHARP DROP on hourly data: down X% over 48h, buy DELAY hours after the signal hour, hold 10 days. edge = rule minus random entries.")
    HOLD = 240
    for gname, gl in groups:
        text.append(f"  {gname} ({len(gl)} coins)")
        for X in (0.12, 0.16):
            for delay in (0, 1, 3, 6, 12, 24):
                tr = []; rnd = []
                for t in gl:
                    O, H, L, C = arr[t]; nxt = 0
                    for i in range(max(48, s_idx), HN - HOLD - delay - 3):
                        if i < nxt: continue
                        if C[i] and C[i - 48] and C[i] / C[i - 48] - 1 <= -X:
                            e = i + 1 + delay; x = e + HOLD - 1
                            if O[e] and C[x]: tr.append((i, C[x] / O[e] - 1 - RT)); nxt = e + HOLD
                    for _ in range(300):
                        e = rng.randrange(max(48, s_idx) + 1, HN - HOLD - 3)
                        if O[e] and C[e + HOLD - 1]: rnd.append(C[e + HOLD - 1] / O[e] - 1 - RT)
                if len(tr) < 8: text.append(f"     drop>={int(X * 100)}% delay {delay:>2}h  n={len(tr)} too few"); continue
                r = [x for _, x in tr]; byd = {}
                for i, x in tr: byd.setdefault(i // 24, []).append(x)
                ep = mean([mean(v) for v in byd.values()]) * 100; a = [x for i, x in tr if i < mid]; b = [x for i, x in tr if i >= mid]
                text.append(f"     drop>={int(X * 100)}% delay {delay:>2}h  n={len(tr):>3} days={len(byd):>3}  avg {mean(r) * 100:+5.1f}%  random {mean(rnd) * 100:+4.1f}%  edge {(mean(r) - mean(rnd)) * 100:+5.1f}%  by-day edge {ep - mean(rnd) * 100:+5.1f}%  older {mean(a) * 100:+.1f}%/newer {mean(b) * 100:+.1f}% ({len(a)}/{len(b)})  win {100 * sum(x > 0 for x in r) / len(r):.0f}%")
        text.append("")
    # ---------------- B
    n_days_total = HN // 24
    day0 = (h0 + 23) // 24                      # first full UTC day
    days = list(range(day0, day0 + (HN - (day0 * 24 - h0)) // 24))
    Hd = {}; Ld = {}; Cd = {}
    for t in data:
        O, H, L, C = arr[t]; hh = []; ll = []; cc = []
        for d in days:
            a = d * 24 - h0; seg = list(range(a, a + 24))
            if a < 0 or a + 24 > HN or any(C[k] is None for k in seg): hh.append(None); ll.append(None); cc.append(None); continue
            hh.append(max(H[k] for k in seg)); ll.append(min(L[k] for k in seg)); cc.append(C[a + 23])
        Hd[t], Ld[t], Cd[t] = hh, ll, cc
    i0 = next(i for i, d in enumerate(days) if d * 86400 >= START)
    pos, trades, events, curve, _ = TP.replay(days, Hd, Ld, Cd, coins, i0)
    text.append("B. ATR TREND, executed at hourly prices. Signal at the daily close; entry/exit price = open of the hour DELAY hours later (or the daily close price used by the paper test).")
    opn = {}; rets = {}
    pairs = []
    for i, kind, c, px, why in sorted(events, key=lambda e: e[0]):
        if kind == "BUY": opn[c] = (i, px)
        elif c in opn: pairs.append((c, opn.pop(c), (i, px), why))
    def price(c, day_i, delay):
        if delay is None: return None
        k = (days[day_i] + 1) * 24 + delay - h0
        return arr[c][0][k] if 0 <= k < HN else None
    text.append(f"   {len(pairs)} completed trades on {len(coins)} coins")
    for delay in (None, 0, 1, 6, 12, 24):
        rs = []
        for c, (ie, pe), (ix, px), why in pairs:
            if delay is None: pe2, px2 = pe, px
            else:
                pe2 = price(c, ie, delay); px2 = price(c, ix, delay)
                if not pe2 or not px2: continue
            rs.append(px2 / pe2 - 1 - RT)
        if not rs: continue
        rs2 = sorted(rs); med = rs2[len(rs2) // 2]
        lab = "daily close price (paper test)" if delay is None else f"open of the hour {delay}h after the close"
        text.append(f"   {lab:<40} n={len(rs):>3}  win {100 * sum(x > 0 for x in rs) / len(rs):3.0f}%  avg {mean(rs) * 100:+5.1f}%  median {med * 100:+5.1f}%  worst {min(rs) * 100:+5.0f}%  best {max(rs) * 100:+5.0f}%  rough account effect (1/20 per trade) {sum(rs) / 20 * 100:+.0f}%")
    text += ["", "HOW TO READ: in A, if the edge stays similar for delays of 1-6 hours, an alert-based approach is realistic; if it collapses after a few hours, only a fast order would capture it. In B the paper test's daily-close price should be close to the 0-6 hour lines; a big gap would mean the paper results overstate what you could get. Trailing stops here are checked at the daily close; a live stop order could trigger earlier (usually a smaller loss, sometimes a whipsaw)."]
    t = "\n".join(text)
    open(os.path.join(scanner.HERE, "lab19_summary.txt"), "w").write(t + "\n"); print(t)
    try: scanner.notify("Strategy lab 19 finished", "Live-price delay test done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
