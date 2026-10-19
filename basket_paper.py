#!/usr/bin/env python3
"""BTC-gated large-coin basket: paper test. Runs once a day after the daily candle closes.
Rule, on completed daily candles: while BTC closes above its 200-day average, hold the 10 biggest coins (by market size order of the coin list, BTC and stablecoins excluded),
equal weight, refreshed every 30 days (rank = the market-size order of the scanner's coin list on the day of the refresh, stored in basketgate_baskets.json so history is never re-ranked with hindsight). When BTC closes below its 200-day average, move to cash. Re-enter at the close of the first day BTC is back above it.
Paper account of 1000, 0.1% cost per side on the amount traded. Fills are at the signal day's close (a real order would be placed the next morning, so real fills will differ).
Compared with: BTC held over the same days, and the same basket held WITHOUT the BTC switch (to show what the switch costs or saves).
The record is rebuilt each day from daily candles starting on the first run day (basketgate_start.txt). Writes basketgate_report.txt, basketgate_trades.csv; quiet phone note on entries, exits and refreshes."""
import os, csv, time, json
from multiprocessing import Pool
import scanner, backtest as B

TOPK = 10; REFRESH = 30; SIDE = 0.001; GATE_N = 200
STABLES = {"USDT", "USDC", "DAI", "TUSD", "FDUSD", "USDE", "USD1", "PYUSD", "USDD", "BUSD", "USDP", "FRAX", "WBTC", "BTC", "STETH", "WSTETH", "WBETH"}
HERE = scanner.HERE; P = lambda f: os.path.join(HERE, f)
fd = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))

def load(a):
    tok, need = a
    try:
        m = B.hist_crypto(tok, "1d", need)
        return tok, {int(r[0] // 86400): (r[4], r[5]) for r in m}, ""
    except Exception as e: return tok, {}, str(e)[:60]

def pick(C, coins, i, days, store):
    """The first TOPK coins of the size-ordered list that have a price on day i. The choice is stored the first time it is made, so later daily rebuilds reuse it (no re-ranking with hindsight)."""
    key = fd(days[i])
    if key in store: return [c for c in store[key] if c in C and C[c][i] is not None]
    basket = [c for c in coins if C[c][i] is not None and sum(x is not None for x in C[c][max(0, i - 89):i + 1]) >= 80][:TOPK]
    store[key] = basket; return basket

def run(days, C, coins, i0, gated, store):
    n = len(days); cb = C["BTC"]; val = {}; cash = 1.0; last_ref = None; hist = []; trades = []; events = []; curve = {i0: 1.0}
    for i in range(i0, n):
        if i > i0:                                     # mark holdings to today's close
            for c in list(val):
                a, b = C[c][i - 1], C[c][i]
                if a and b: val[c] *= b / a
        seg = [x for x in cb[max(0, i - GATE_N + 1):i + 1] if x is not None]
        g = i >= GATE_N - 1 and cb[i] is not None and len(seg) >= GATE_N * 0.9 and cb[i] > sum(seg) / len(seg)
        invest = g or not gated
        total = cash + sum(val.values())
        if invest and (not val or last_ref is None or i - last_ref >= REFRESH):
            basket = pick(C, coins, i, days, store)
            if basket:
                new = {c: total / len(basket) for c in basket}
                cost = SIDE * sum(abs(new.get(c, 0) - val.get(c, 0)) for c in set(new) | set(val))   # amount bought + sold
                total -= cost; new = {c: total / len(basket) for c in basket}
                kind = "ENTER" if not val else "REFRESH"
                trades.append(dict(date=fd(days[i]), action=kind, coins=" ".join(basket), account=round(total * 1000, 2), gate="on" if g else "off"))
                events.append((i, kind, basket)); val = new; cash = 0.0; last_ref = i
        elif not invest and val:
            total -= SIDE * sum(val.values()); cash = total; val = {}; last_ref = None
            trades.append(dict(date=fd(days[i]), action="EXIT TO CASH", coins="", account=round(total * 1000, 2), gate="off")); events.append((i, "EXIT", []))
        curve[i] = cash + sum(val.values())
    return val, trades, events, curve, g

def main():
    sp = P("basketgate_start.txt"); today = int(time.time() // 86400)
    start = int(open(sp).read().strip()) if os.path.exists(sp) else today - 1
    if not os.path.exists(sp): open(sp, "w").write(str(start))
    need = 330 + max(0, today - start)
    coins = [c for c in scanner.top100() if c.upper() not in STABLES][:99]
    with Pool(max(1, os.cpu_count() or 1)) as p: res = p.map(load, [(t, need) for t in ["BTC"] + coins])
    data = {t: d for t, d, e in res if len(d) > 100}
    if "BTC" not in data: raise SystemExit("no BTC data")
    days = sorted(data["BTC"]); n = len(days); idx = {d: i for i, d in enumerate(days)}
    C, V = {}, {}
    for t, d in data.items():
        c = [None] * n; v = [None] * n
        for dd, (cc, vv) in d.items():
            if dd in idx: c[idx[dd]] = cc; v[idx[dd]] = vv
        C[t], V[t] = c, v
    alts = [t for t in data if t != "BTC" and max(x for x in C[t] if x) / min(x for x in C[t] if x) >= 1.3]
    i0 = next((i for i, d in enumerate(days) if d >= start), n - 1)
    bp = P("basketgate_baskets.json"); store = json.load(open(bp)) if os.path.exists(bp) else {}
    val, trades, events, curve, g = run(days, C, alts, i0, True, store)
    _, _, _, curve_u, _ = run(days, C, alts, i0, False, store)
    json.dump(store, open(bp, "w"))
    cb = C["BTC"]; gate_now = cb[-1] > sum(cb[-GATE_N:]) / GATE_N; last = days[-1]
    eq, equ, btc = curve[n - 1], curve_u[n - 1], cb[n - 1] / cb[i0]
    L_ = [f"BTC-GATED BASKET PAPER TEST  data to {fd(last)} (completed daily candles)   started {fd(days[i0])}   universe {len(alts)} coins",
          f"BTC {'ABOVE' if gate_now else 'BELOW'} its 200-day average -> {'basket held' if gate_now else 'cash'}. Rule: top-{TOPK} coins by market size order, equal weight, refreshed every {REFRESH} days; cash while BTC is below its 200-day average.",
          f"Paper account (1000 start, 0.1% per side): {1000 * eq:,.0f} ({(eq - 1) * 100:+.1f}%)   |   same basket WITHOUT the BTC switch: {1000 * equ:,.0f} ({(equ - 1) * 100:+.1f}%)   |   BTC held: {1000 * btc:,.0f} ({(btc - 1) * 100:+.1f}%)", ""]
    if val:
        tot = sum(val.values()); L_.append(f"HOLDING ({len(val)} coins, last refreshed {[t['date'] for t in trades if t['action'] in ('ENTER', 'REFRESH')][-1]}):")
        for c, v_ in sorted(val.items(), key=lambda x: -x[1]): L_.append(f"  {c:<8} {100 * v_ / tot:4.1f}% of account   price {C[c][-1]:.6g}")
    else: L_.append("HOLDING: cash")
    L_ += ["", f"ACTIONS ({len(trades)}):"] + [f"  {t['date']}  {t['action']:<13} {t['coins']}   account {t['account']}" for t in trades[-10:]]
    L_ += ["", "Judge it only after a full BTC bull-to-bear switch has happened, or many months. The lab 25 test showed the switch avoids most bear-market losses but gives up much of the bull-market profit; this paper test shows whether that holds live."]
    open(P("basketgate_report.txt"), "w").write("\n".join(L_) + "\n"); print("\n".join(L_))
    if trades:
        with open(P("basketgate_trades.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, list(trades[0].keys())); w.writeheader(); w.writerows(trades)
    ev = [e for e in events if e[0] == n - 1]; np_ = P("basketgate_notified.txt")
    done = open(np_).read().strip() if os.path.exists(np_) else ""
    if ev and done != str(last):
        msg = "; ".join(f"{k} {' '.join(b)}" for _, k, b in ev)
        try: scanner.notify("Basket paper test: " + ", ".join(k for _, k, _ in ev), msg + "\nPaper test - signals from the daily close.", scanner.NTFY_TOPIC, "bar_chart", 2)
        except Exception as e: print("(phone send failed:", e, ")")
        open(np_, "w").write(str(last))

if __name__ == "__main__":
    main()
