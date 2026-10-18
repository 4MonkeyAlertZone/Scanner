#!/usr/bin/env python3
"""ATR trend paper test (from lab 15: the best trend variant, BTC-gated). Runs once a day after the daily candle closes.
Rule, on completed daily candles: BUY a coin when it closes above its highest high of the previous 55 days AND BTC closes above its 200-day average.
SELL when it closes more than 3 x its 20-day average daily range below its highest close since entry, or when BTC closes below its 200-day average.
Paper account: up to 20 equal slots (each 1/20 of the account; 1/n if more than 20), 0.1% cost per side, trades taken at the signal day's close price (a real order would be placed the next morning, so real fills will differ).
The whole record is rebuilt each day from daily candles starting on the first run day (atrtrend_start.txt), so nothing can get out of sync.
Writes atrtrend_report.txt, atrtrend_trades.csv; sends one quiet phone note on days with a buy or sell."""
import os, csv, time, math
from multiprocessing import Pool
import scanner, backtest as B

NE = 55; ATRK = 3.0; SLOTS = 20; SIDE = 0.001; GATE_N = 200
HERE = scanner.HERE; P = lambda f: os.path.join(HERE, f)
fd = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))

def load(a):
    tok, need = a
    try:
        m = B.hist_crypto(tok, "1d", need)
        return tok, {int(r[0] // 86400): (r[2], r[3], r[4]) for r in m}, ""
    except Exception as e: return tok, {}, str(e)[:60]

def build(data, days):
    n = len(days); idx = {d: i for i, d in enumerate(days)}; H = {}; L = {}; C = {}
    for t, d in data.items():
        h = [None] * n; l = [None] * n; c = [None] * n
        for dd, (hh, ll, cc) in d.items():
            if dd in idx: h[idx[dd]] = hh; l[idx[dd]] = ll; c[idx[dd]] = cc
        H[t], L[t], C[t] = h, l, c
    return H, L, C

def atr_at(H, L, C, i):
    trs = []
    for j in range(i - 19, i + 1):
        if j < 1 or None in (H[j], L[j], C[j - 1]): return None
        trs.append(max(H[j] - L[j], abs(H[j] - C[j - 1]), abs(L[j] - C[j - 1])))
    return sum(trs) / 20

def replay(days, H, L, C, coins, i0):
    n = len(days); cb = C["BTC"]; pos = {}; trades = []; events = []; W = {}
    for i in range(i0, n):
        seg = [x for x in cb[max(0, i - GATE_N + 1):i + 1] if x is not None]
        g = i >= GATE_N - 1 and cb[i] is not None and len(seg) >= GATE_N * 0.9 and cb[i] > sum(seg) / len(seg)
        for c in coins:
            cl = C[c][i]
            if cl is None: continue
            if c in pos:
                pos[c]["top"] = max(pos[c]["top"], cl); a = atr_at(H[c], L[c], C[c], i)
                reason = "BTC below its 200-day average" if not g else ("trailing stop" if a and cl < pos[c]["top"] - ATRK * a else None)
                if reason:
                    p = pos.pop(c); r = cl / p["px"] - 1 - 2 * SIDE
                    trades.append(dict(coin=c, entry_date=fd(days[p["i"]]), entry_px=p["px"], exit_date=fd(days[i]), exit_px=cl, ret_pct=round(r * 100, 2), reason=reason, days=i - p["i"])); events.append((i, "SELL", c, cl, reason))
            elif g and i >= NE + 1:
                seg = [x for x in H[c][i - NE:i] if x is not None]
                if len(seg) >= NE * 0.9 and cl > max(seg): pos[c] = dict(px=cl, i=i, top=cl); events.append((i, "BUY", c, cl, "55-day breakout"))
        W[i] = {c: 1.0 / max(SLOTS, len(pos)) for c in pos}
    eq = 1.0; curve = {i0: 1.0}
    for i in range(i0 + 1, n):
        w = W[i - 1]; wp = W.get(i - 2, {})
        g = sum(wt * (C[c][i] / C[c][i - 1] - 1) for c, wt in w.items() if C[c][i] and C[c][i - 1])
        turn = sum(abs(w.get(c, 0) - wp.get(c, 0)) for c in set(w) | set(wp))
        eq *= 1 + g - SIDE * turn; curve[i] = eq
    return pos, trades, events, curve, g

def main():
    sp = P("atrtrend_start.txt"); today = int(time.time() // 86400)
    start = int(open(sp).read().strip()) if os.path.exists(sp) else today - 1
    if not os.path.exists(sp): open(sp, "w").write(str(start))
    need = 420 + max(0, today - start)
    coins = [c for c in scanner.top100() if c != "BTC"][:99]
    with Pool(max(1, os.cpu_count() or 1)) as p: res = p.map(load, [(t, need) for t in ["BTC"] + coins])
    data = {t: d for t, d, e in res if len(d) > 100}
    if "BTC" not in data: raise SystemExit("no BTC data")
    days = sorted(data["BTC"]); n = len(days)
    data = {t: d for t, d in data.items() if max(v[2] for v in d.values()) / min(v[2] for v in d.values()) >= 1.3 or t == "BTC"}
    H, L, C = build(data, days); alts = [t for t in data if t != "BTC"]
    i0 = next((i for i, d in enumerate(days) if d >= start), n - 1)
    pos, trades, events, curve, _ = replay(days, H, L, C, alts, i0)
    cb = C["BTC"]; gate_now = cb[-1] > sum(cb[-GATE_N:]) / GATE_N
    last = days[-1]; eq = curve[n - 1]; btc = cb[n - 1] / cb[i0]
    L_ = [f"ATR TREND PAPER TEST  data to {fd(last)} (completed daily candles)   started {fd(days[i0])}   universe {len(alts)} coins + BTC",
          f"BTC {'ABOVE' if gate_now else 'BELOW'} its 200-day average -> new buys {'allowed' if gate_now else 'blocked'}. Rule: buy 55-day breakout; sell at 3 x daily-range trailing stop or when BTC falls below its 200-day average.",
          f"Paper account (1000 start, 20 slots, 0.1% per side): {1000 * eq:,.0f}   ({(eq - 1) * 100:+.1f}%)   |   BTC held over the same days: {1000 * btc:,.0f} ({(btc - 1) * 100:+.1f}%)", ""]
    L_.append(f"OPEN POSITIONS ({len(pos)}):")
    for c, p in sorted(pos.items(), key=lambda x: x[1]["i"]):
        a = atr_at(H[c], L[c], C[c], n - 1); st = p["top"] - ATRK * a if a else float("nan")
        L_.append(f"  {c:<8} bought {fd(days[p['i']])} at {p['px']:.6g}   now {C[c][-1]:.6g} ({(C[c][-1] / p['px'] - 1) * 100:+.1f}%)   trailing stop about {st:.6g}")
    if not pos: L_.append("  none")
    L_.append(""); L_.append(f"CLOSED TRADES ({len(trades)}), after 0.2% round-trip cost:")
    if trades:
        r = [t["ret_pct"] for t in trades]; L_.append(f"  win rate {100 * sum(x > 0 for x in r) / len(r):.0f}%   average {sum(r) / len(r):+.1f}%   best {max(r):+.1f}%   worst {min(r):+.1f}%")
        for t in trades[-10:]: L_.append(f"  {t['coin']:<8} {t['entry_date']} -> {t['exit_date']}  {t['ret_pct']:+.1f}%  ({t['days']}d, {t['reason']})")
    L_ += ["", "Prices are the signal day's close; a real order would be placed the next morning. Judge the strategy only after many trades (the lab 15 test suggested a low win rate with a few large winners, so long quiet or losing stretches are normal)."]
    open(P("atrtrend_report.txt"), "w").write("\n".join(L_) + "\n"); print("\n".join(L_))
    if trades:
        with open(P("atrtrend_trades.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, list(trades[0].keys())); w.writeheader(); w.writerows(trades)
    ev = [e for e in events if e[0] == n - 1]; np_ = P("atrtrend_notified.txt")
    done = open(np_).read().strip() if os.path.exists(np_) else ""
    if ev and done != str(last):
        msg = "\n".join(f"{k} {c} at {px:.6g} ({why})" for _, k, c, px, why in ev[:12])
        try: scanner.notify("ATR trend: " + ", ".join(f"{k} {c}" for _, k, c, _, _ in ev[:4]), msg + "\nPaper test - signals from the daily close.", scanner.NTFY_TOPIC, "chart_with_upwards_trend", 2)
        except Exception as e: print("(phone send failed:", e, ")")
        open(np_, "w").write(str(last))

if __name__ == "__main__":
    main()
