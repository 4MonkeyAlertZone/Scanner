#!/usr/bin/env python3
"""INTRADAY WARNING WATCH. Runs about every 10 minutes. It NEVER changes the official signal (that is the daily close, regime_alert.py). It only sends a phone warning when something is warning-worthy, and each warning is sent at most once per day (fast drops: once per 6 hours).
Warnings (BTC levels apply only while the regime state is IN):
  1. BTC live price is BELOW its 50-day average (computed as if today closed at the live price)   -> priority 4
  2. BTC is within 1% ABOVE that 50-day line                                                    -> priority 3
  3. BTC live price is BELOW its 200-day average                                                -> priority 5
  4. FAST DROP: BTC or ETH is 5%+ below its high of the last ~6 hours, or 9%+ below its 24-hour high -> priority 4
  5. 20%+ below your IN entry price (stored by regime_alert.py): 3x liquidation is ~33% away, 2x ~50%   -> priority 5
Data: Binance.US (OKX as backup). State of what was already sent: intraday_state.json."""
import os, json, time
import scanner, backtest as B

HERE = scanner.HERE; P = lambda f: os.path.join(HERE, f)
today = lambda: time.strftime("%Y-%m-%d", time.gmtime())

def klines(sym, interval, limit):
    """[(t, o, h, l, c)] oldest first; the LAST row is the candle still forming (its close = live price)."""
    try:
        k = json.loads(scanner.http(f"https://api.binance.us/api/v3/klines?symbol={sym}USDT&interval={interval}&limit={limit}"))
        return [(x[0] / 1000, float(x[1]), float(x[2]), float(x[3]), float(x[4])) for x in k]
    except Exception:
        bar = {"1d": "1D", "1h": "1H"}[interval]
        k = json.loads(scanner.http(f"https://www.okx.com/api/v5/market/candles?instId={sym}-USDT&bar={bar}&limit={min(limit, 100)}"))["data"]
        return sorted((int(x[0]) / 1000, float(x[1]), float(x[2]), float(x[3]), float(x[4])) for x in k)

def daily_closes(sym, need=210):
    try:
        k = klines(sym, "1d", need)
        if len(k) >= 200: return [x[4] for x in k[:-1]], k[-1][4]
    except Exception: pass
    rows = B.hist_crypto(sym, "1d", 260)
    return [r[4] for r in rows], klines(sym, "1h", 2)[-1][4]

def main():
    sp = P("intraday_state.json")
    st = json.load(open(sp)) if os.path.exists(sp) else {"sent": {}}
    now = time.time(); st["sent"] = {k: v for k, v in st["sent"].items() if now - v < 3 * 86400}
    reg = json.load(open(P("regime_state.json"))) if os.path.exists(P("regime_state.json")) else {}
    new = []
    def send(key, title, body, prio, tag):
        if key in st["sent"]: return
        scanner.notify(title, body + "\nIntraday warning only: the official signal is the daily close. Not advice.", scanner.NTFY_TOPIC, tag, prio)
        st["sent"][key] = now; new.append(key)
    d = today(); live = {}
    cl, px = daily_closes("BTC"); live["BTC"] = px
    ma50 = (sum(cl[-49:]) + px) / 50; ma200 = (sum(cl[-199:]) + px) / 200; gap = (px / ma50 - 1) * 100
    info = f"BTC live {px:,.0f}, 50-day line {ma50:,.0f} ({gap:+.1f}%), 200-day line {ma200:,.0f}; regime state {reg.get('state', '?')}"
    if reg.get("state") == "IN":
        if px < ma200: send(f"below200-{d}", "BTC BELOW 200-DAY LINE (live)", "BIG WARNING: BTC is trading under its 200-day average. If it closes the day there the regime goes RED.\nACTION: leveraged longs are in danger - reduce or close.\n" + info, 5, "rotating_light")
        elif px < ma50: send(f"below50-{d}", "BTC BELOW 50-DAY LINE (live)", "WARNING: BTC is trading under its 50-day line. If it CLOSES the day there (00:00 UTC), the regime flips to OUT / RED.\nACTION: do not add; consider closing leveraged longs now.\n" + info, 4, "red_circle")
        elif gap < 1: send(f"near50-{d}", "BTC near 50-day line (live)", f"HEADS-UP: BTC is only {gap:.1f}% above its exit line.\nACTION: no new leveraged positions; be ready to act.\n" + info, 3, "orange_circle")
    for sym in ("BTC", "ETH"):
        try:
            h = klines(sym, "1h", 26); last = h[-1][4]; live[sym] = last
            hi6 = max(x[2] for x in h[-7:]); hi24 = max(x[2] for x in h[-25:])
            d6 = (1 - last / hi6) * 100; d24 = (1 - last / hi24) * 100
            if d6 >= 5 or d24 >= 9:
                send(f"fast-{sym}-{int(now // 21600)}", f"FAST DROP {sym}: {d6:.1f}% in ~6h", f"{sym} is {d6:.1f}% below its 6-hour high and {d24:.1f}% below its 24-hour high (now {last:,.2f}).\nACTION: check leveraged positions and exchange stops.", 4, "warning")
        except Exception as e: print(sym, "hourly check failed:", str(e)[:60])
    for sym, key in (("BTC", "entry_btc"), ("ETH", "entry_eth")):
        e = reg.get(key); l = live.get(sym)
        if reg.get("state") == "IN" and e and l and l <= e * 0.8:
            send(f"entrydrop-{sym}-{d}", f"{sym} is {(1 - l / e) * 100:.0f}% below IN entry", f"{sym} {l:,.2f} vs IN entry {e:,.2f}. 3x liquidation is ~33% below entry, 2x ~50%.\nACTION: leveraged positions are close to danger.", 5, "rotating_light")
    if new: json.dump(st, open(sp, "w"))
    print(time.strftime("%H:%M:%SZ", time.gmtime()), info, "| sent:", new or "none")

if __name__ == "__main__":
    main()
