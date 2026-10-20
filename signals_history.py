#!/usr/bin/env python3
"""SIGNAL HISTORY REPLAY from 1 Oct 2020: what the live alert system (regime_alert.py + intraday_watch.py) WOULD have sent, using only data available at each time.
DAILY signals (fire at 00:50 UTC the day after the candle closes; price = that daily close, the live alert prices at ~00:50 will differ by a little):
  REGIME: GET IN / GET OUT (BTC > 200d avg AND > 50d avg AND no BTC open-interest warning C in the last 14 days; OI data exists from 2021-01, so 2020 has none)
  REGIME-COMPONENT: quiet note when one of the three conditions flips without changing IN/OUT
  LEVERAGE+SPOT COLOUR: GREEN (BTC 2%+ above 50d) / ORANGE (0-2% above) / RED (OUT). A note is sent EVERY day; only colour changes are listed here.
INTRADAY warnings (replayed on HOURLY candles, so timestamps are the hour in which the live 10-minute check would have fired, and prices are the level crossed or the hour open/close; the real alert would arrive up to ~10-30 minutes into/after that hour):
  near 50-day line (<1% above), below 50-day line, below 200-day line (all BTC, only while the regime is IN, once per day each), FAST DROP (BTC/ETH 5%+ below the 6h high or 9%+ below the 24h high, once per 6h per coin, any state), and 20%+ below the IN entry price (BTC/ETH, once per day).
The regime state used for intraday checks is the state after the previous daily close. Past prices only; the OI condition was chosen with hindsight; this is a replay, not proof of future results.
Writes signals_history.csv (all rows) and signals_history.txt (readable)."""
import os, csv, json, time, calendar
from datetime import datetime
import scanner, backtest as B

HERE = scanner.HERE; P = lambda f: os.path.join(HERE, f)
START = calendar.timegm((2020, 10, 1, 0, 0, 0)) // 86400
fd = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))
ft = lambda t: time.strftime("%Y-%m-%d %H:%M", time.gmtime(t))

def hourly(sym, t0):
    """Binance.US hourly candles from t0 (epoch seconds) to now: [(t,o,h,l,c)] oldest first."""
    out = []; start = int(t0 * 1000)
    while True:
        k = json.loads(scanner.http(f"https://api.binance.us/api/v3/klines?symbol={sym}USDT&interval=1h&startTime={start}&limit=1000"))
        if not k: break
        out += [(x[0] / 1000, float(x[1]), float(x[2]), float(x[3]), float(x[4])) for x in k]
        start = int(k[-1][0]) + 3600000
        if len(k) < 1000: break
    seen = {}; [seen.setdefault(r[0], r) for r in out]
    return [seen[t] for t in sorted(seen)][:-1]          # drop the hour still forming

def load_daily(sym):
    rows = B.hist_crypto(sym, "1d", 2700)
    d = {}
    for r in rows: d.setdefault(int(r[0] // 86400), r[4])
    return d

def load_oi():
    oi = {}; mp = P("btc_metrics_daily.csv")
    if os.path.exists(mp):
        for r in csv.DictReader(open(mp)):
            try: oi[calendar.timegm(datetime.strptime(r["date"], "%Y-%m-%d").timetuple()) // 86400] = float(r["open_interest_btc"])
            except Exception: pass
    return oi

def main(daily=None, oi=None, hr=None):
    daily = daily or {s: load_daily(s) for s in ("BTC", "ETH")}
    oi = load_oi() if oi is None else oi
    bt, et = daily["BTC"], daily["ETH"]
    days = [d for d in sorted(bt) if d >= START - 260]; n = len(days); C = [bt[d] for d in days]
    OI = [oi.get(d) for d in days]; W = [False] * n
    for i in range(n):
        prev = [x for x in OI[max(0, i - 180):i] if x]
        if OI[i] and len(prev) > 100 and OI[i] >= max(prev) and i >= 30 and OI[i - 30] and OI[i] / OI[i - 30] - 1 >= .15: W[i] = True
    ow = [False] * n; left = 0
    for i in range(n):
        if W[i]: left = 14
        ow[i] = left > 0
        if left > 0: left -= 1
    g200 = [None] * n; g50 = [None] * n; st = [None] * n; gap = [None] * n
    for i in range(199, n):
        m200 = sum(C[i - 199:i + 1]) / 200; m50 = sum(C[i - 49:i + 1]) / 50
        g200[i] = C[i] > m200; g50[i] = C[i] > m50; gap[i] = (C[i] / m50 - 1) * 100
        st[i] = "IN" if (g200[i] and g50[i] and not ow[i]) else "OUT"
    col = [None] * n
    for i in range(199, n): col[i] = "RED" if st[i] == "OUT" else ("GREEN" if gap[i] >= 2 else "ORANGE")
    eb = [None] * n; ee = [None] * n                       # IN-entry prices (close of the day the state turned IN)
    for i in range(199, n):
        if st[i] == "IN":
            if i > 199 and st[i - 1] == "IN" and eb[i - 1]: eb[i] = eb[i - 1]; ee[i] = ee[i - 1]
            else: eb[i] = C[i]; ee[i] = et.get(days[i])
    rows = []
    def add(t, cat, sig, asset, price, detail, state):
        rows.append((t, ft(t), cat, sig, asset, round(price, 2) if price else "", detail, state))
    first = next(i for i, d in enumerate(days) if d >= START)
    for i in range(first, n):
        t = (days[i] + 1) * 86400 + 50 * 60                 # 00:50 UTC the day after the candle
        dt = f"daily close {fd(days[i])}"
        reasons = [x for x, f in (("BTC below 200d avg", not g200[i]), ("BTC below 50d avg", not g50[i]), ("BTC open-interest warning in last 14d", ow[i])) if f]
        if i == first:
            add(t, "REGIME", "Alt regime started: " + st[i], "BTC", C[i], dt + "; " + ("; ".join(reasons) if reasons else "all three conditions clear"), st[i])
            add(t, "LEVERAGE+SPOT COLOUR", "started: " + col[i], "BTC", C[i], f"{gap[i]:+.1f}% vs 50d avg", st[i])
            continue
        if st[i] != st[i - 1]:
            add(t, "REGIME", "GET IN" if st[i] == "IN" else "GET OUT", "BTC", C[i], dt + "; " + ("; ".join(reasons) if reasons else "all three conditions clear"), st[i])
        else:
            ch = [k for k, a, b in (("200d", g200[i], g200[i - 1]), ("50d", g50[i], g50[i - 1]), ("OI warning", ow[i], ow[i - 1])) if a != b]
            if ch: add(t, "REGIME-COMPONENT", "component change: " + ", ".join(ch), "BTC", C[i], dt + f"; now {st[i]}; " + ("; ".join(reasons) if reasons else "clear"), st[i])
        if col[i] != col[i - 1]: add(t, "LEVERAGE+SPOT COLOUR", f"{col[i - 1]} -> {col[i]}", "BTC", C[i], f"{gap[i]:+.1f}% vs 50d avg; " + dt, st[i])
    # ---- intraday replay on hourly candles
    hr = hr or {s: hourly(s, (START - 2) * 86400) for s in ("BTC", "ETH")}
    idx = {d: i for i, d in enumerate(days)}
    sent = set(); H = {s: hr[s] for s in hr}; MAXT = max(r[0] for r in H["BTC"])
    for k, (t, o, h, l, c) in enumerate(H["BTC"]):
        D = int(t // 86400)
        if D < START or D not in idx or idx[D] < 200: continue
        i = idx[D] - 1; state = st[i]                       # state after the previous daily close
        for sym in ("BTC", "ETH"):
            hs = H[sym]
            if k >= len(hs) or hs[k][0] != t: continue
            ho, hh, hl, hc = hs[k][1:]
            lo7 = max(x[2] for x in hs[max(0, k - 6):k + 1]); hi24 = max(x[2] for x in hs[max(0, k - 24):k + 1])
            d6 = (1 - hl / lo7) * 100; d24 = (1 - hl / hi24) * 100
            if (d6 >= 5 or d24 >= 9) and (sym, "fast", int(t // 21600)) not in sent:
                sent.add((sym, "fast", int(t // 21600)))
                add(t, "INTRADAY", f"FAST DROP {sym}", sym, hc, f"hour low {hl:,.2f} is {d6:.1f}% below 6h high, {d24:.1f}% below 24h high; hour close shown", state)
            e = (eb[i] if sym == "BTC" else ee[i]) if state == "IN" else None
            if e and hl <= e * 0.8 and (sym, "entry", D) not in sent:
                sent.add((sym, "entry", D)); lv = e * 0.8
                add(t, "INTRADAY", f"{sym} 20% BELOW IN ENTRY", sym, min(lv, ho), f"IN entry {e:,.2f}; 20% line {lv:,.2f} (3x liquidation ~33%, 2x ~50% below entry)", state)
        if state != "IN": continue
        S49 = sum(C[i - 48:i + 1]); S199 = sum(C[i - 198:i + 1])      # last 49 / 199 completed closes
        L200 = S199 / 199; L50 = S49 / 49; LN = 1.01 * S49 / 48.99
        for px, lab in ((o, "open"), (l, "low"), (c, "close")):
            if px < L200:
                if ("b200", D) not in sent:
                    sent.add(("b200", D)); add(t, "INTRADAY", "BTC BELOW 200-DAY LINE", "BTC", L200 if lab == "low" and o > L200 else px, f"200d line {L200:,.0f} (hour {lab} {px:,.0f}); regime was IN", state)
            elif px < L50:
                if ("b50", D) not in sent:
                    sent.add(("b50", D)); add(t, "INTRADAY", "BTC BELOW 50-DAY LINE", "BTC", L50 if lab == "low" and o > L50 else px, f"50d line {L50:,.0f} (hour {lab} {px:,.0f}); a daily close there flips regime to OUT", state)
            elif px < LN:
                if ("n50", D) not in sent:
                    sent.add(("n50", D)); add(t, "INTRADAY", "BTC NEAR 50-DAY LINE (<1% above)", "BTC", LN if lab == "low" and o > LN else px, f"50d line {L50:,.0f}; within 1% (hour {lab} {px:,.0f})", state)
    rows.sort(key=lambda r: (r[0], r[2]))
    with open(P("signals_history.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["time_utc", "time_text", "category", "signal", "asset", "price_at_signal", "detail", "regime_state_after"])
        for r in rows: w.writerow(r)
    cnt = {}
    for r in rows: cnt[(r[2], r[3].split(" (")[0] if r[2] != "INTRADAY" else r[3].replace("ETH", "BTC/ETH").replace("BTC/BTC/ETH", "BTC/ETH"))] = cnt.get((r[2], r[3]), 0)
    cats = {}
    for r in rows: cats[r[2]] = cats.get(r[2], 0) + 1
    ndays = sum(1 for i in range(first, n))
    L = ["SIGNAL HISTORY REPLAY  1 Oct 2020 -> " + ft(max(r[0] for r in rows)) + " UTC", "",
         "How to read: 'time' = when the alert would have fired (daily signals 00:50 UTC after the candle close; intraday = the hour). 'price' = daily close for daily signals; for intraday the level crossed or the hour open/close.",
         "Daily LEVERAGE and SPOT notes are sent every day (" + str(ndays) + " days in this period); this list shows only colour changes. OI warnings need data from 2021-01, so 2020 regime signals exclude them.", "",
         "COUNTS: " + ", ".join(f"{k}: {v}" for k, v in sorted(cats.items())),
         "Days by colour: " + ", ".join(f"{c} {sum(1 for i in range(first, n) if col[i] == c)}" for c in ("GREEN", "ORANGE", "RED")), ""]
    cur = None
    for r in rows:
        y = r[1][:4]
        if y != cur: L += ["", f"======== {y} ========"]; cur = y
        L.append(f"{r[1]} UTC  {r[2]:<22} {r[3]:<36} {r[4]:<4} {('%s' % format(r[5], ',.2f')) if r[5] != '' else '':>12}  {r[6]}")
    open(P("signals_history.txt"), "w").write("\n".join(L) + "\n"); print("\n".join(L[:60])); print("... rows:", len(rows))

if __name__ == "__main__":
    main()
