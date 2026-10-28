#!/usr/bin/env python3
"""SWING SCANNER (daily, after the 00:00 UTC close). Looks at the top-100 coins (scanner.top100(), minus BTC) for the trigger that did best in lab 36:
 the close crosses ABOVE the 50-day average while above the 200-day average, with the day's volume at least 1.5x its 20-day average.
 Telegram/phone alert ONLY when the BTC regime is IN (live rule from regime_state.json; if that file is stale, BTC above its 200d and 50d). When BTC is OUT the signal is still logged silently so we can measure it.
Every signal becomes a paper trade: entry = that close, exit = first close below the coin's 50-day average (the exit rule the lab used), plus the fixed 30-day result. Same coin is not re-signalled within 14 days.
Honest status: in lab 36 these triggers beat random days, but only ~25% of trades won (a few big winners carried the average), the edge faded in the second half and coins were today's survivors. Treat alerts as candidates, size small (about 1% of account at risk, stop at a close below the 50-day), max 5 open.
Writes swing_state.json, swing_report.txt, swing_log.csv. Not financial advice."""
import os, json, csv, time, statistics as S
import scanner, backtest as B

HERE = scanner.HERE; P = lambda f: os.path.join(HERE, f)
VOLX = 1.5; COST = 0.002; GAP = 14
NTFY = os.environ.get("NTFY_TOPIC", "")
fd = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))

def sma_last(x, k, off=0):
    seg = x[len(x) - k - off:len(x) - off]
    return sum(seg) / k if len(seg) == k else None

def load_state():
    try: return json.load(open(P("swing_state.json")))
    except Exception: return {"trades": [], "last": {}}

def btc_regime(btc_rows):
    c = [r[4] for r in btc_rows]; day = int(btc_rows[-1][0] // 86400)
    try:
        s = json.load(open(P("regime_state.json")))
        if s.get("date") and abs(day - int(time.mktime(time.strptime(s["date"], "%Y-%m-%d")) // 86400)) <= 2: return s.get("state") == "IN", "live regime"
    except Exception: pass
    return (c[-1] > sma_last(c, 200) and c[-1] > sma_last(c, 50)), "BTC 200d/50d"

def main():
    st = load_state(); today = None
    btc = B.hist_crypto("BTC", "1d", 260)
    if len(btc) < 210: raise SystemExit("BTC history too short")
    bt_in, src = btc_regime(btc); today = int(btc[-1][0] // 86400)
    syms = [s for s in scanner.top100() if s != "BTC"]
    sig = []; data = {}; fails = 0
    for s in syms:
        try: rows = B.hist_crypto(s, "1d", 260)
        except Exception: rows = []
        if len(rows) < 210: fails += 1; continue
        data[s] = rows; c = [r[4] for r in rows]; v = [r[5] for r in rows]; d = int(rows[-1][0] // 86400)
        if d != today: continue
        m50, m50p, m200, vm = sma_last(c, 50), sma_last(c, 50, 1), sma_last(c, 200), sma_last(v, 20)
        if None in (m50, m50p, m200, vm) or vm <= 0: continue
        if not (c[-1] > m50 and c[-2] <= m50p and c[-1] > m200 and v[-1] >= VOLX * vm): continue
        if today - st["last"].get(s, -99) < GAP: continue
        h = [r[2] for r in rows]; l = [r[3] for r in rows]
        a = sum(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(len(c) - 14, len(c))) / 14
        sig.append(dict(coin=s, day=today, entry=c[-1], m50=m50, m200=m200, volx=v[-1] / vm, atr=a, alerted=bool(bt_in), exit=None, status="open"))
        st["last"][s] = today
    # update open trades with data
    for t in st["trades"]:
        if t["status"] != "open" or t["coin"] not in data: continue
        rows = data[t["coin"]]; c = [r[4] for r in rows]; days = [int(r[0] // 86400) for r in rows]
        for i in range(len(rows)):
            if days[i] <= t["day"]: continue
            m = sma_last(c[:i + 1], 50)
            if m and c[i] < m:
                t.update(status="closed", exit_day=days[i], exit=c[i], ret=c[i] / t["entry"] - 1 - COST); break
        if t["status"] == "open" and "ret30" not in t:
            k = [i for i, d in enumerate(days) if d == t["day"] + 30]
            if k: t["ret30"] = c[k[0]] / t["entry"] - 1 - COST
        if t["status"] == "closed" and "ret30" not in t:
            k = [i for i, d in enumerate(days) if d == t["day"] + 30]
            if k: t["ret30"] = c[k[0]] / t["entry"] - 1 - COST
    st["trades"] += sig
    # alerts
    for s in sig:
        if not s["alerted"]: continue
        risk = (s["entry"] - s["m50"]) / s["entry"] * 100; sz = 1.0 / risk * 100 if risk > 0 else 0
        msg = (f"{s['coin']}/USDT crossed above its 50-day on {s['volx']:.1f}x volume, above the 200-day. BTC regime IN.\n"
               f"Price {s['entry']:.6g}   50d {s['m50']:.6g}   200d {s['m200']:.6g}   ATR14 {s['atr']:.4g}\n"
               f"Plan: exit on a daily close below the 50-day ({risk:.1f}% below now). Risking 1% of the account means about {min(sz, 25):.0f}% of the account in it; keep the sleeve small.\n"
               f"Honest odds (lab 36): about 1 in 4 of these trades won; a few large winners made the average. Send me '{s['coin']}' in the token bot for the chart.")
        scanner.notify(f"SWING CANDIDATE: {s['coin']}", msg, NTFY, "chart_with_upwards_trend", 3)
    # report
    tr = st["trades"]; L = [f"SWING SCANNER  data to {fd(today)}  BTC regime {'IN' if bt_in else 'OUT'} ({src})  scanned {len(data)} coins ({fails} without enough history)", ""]
    todays = [s for s in sig]
    L.append(f"Signals today: {len(todays)}" + (" (" + ", ".join(s['coin'] for s in todays) + ")" + ("" if bt_in else "  SILENT, BTC OUT") if todays else ""))
    op = [t for t in tr if t["status"] == "open"]
    L += ["", f"Open paper trades ({len(op)}):"]
    for t in op:
        cur = data.get(t["coin"]); px = cur[-1][4] if cur else None
        L.append(f"  {t['coin']:<8} since {fd(t['day'])}  entry {t['entry']:.6g}  now {('%+.1f%%' % ((px / t['entry'] - 1) * 100)) if px else 'n/a'}  {'ALERTED' if t['alerted'] else 'silent (BTC OUT)'}")
    for nm, sel in (("ALERTED (BTC IN)", [t for t in tr if t["alerted"]]), ("SILENT (BTC OUT)", [t for t in tr if not t["alerted"]])):
        cl = [t for t in sel if t["status"] == "closed"]; r30 = [t["ret30"] for t in sel if "ret30" in t]
        L += ["", f"{nm}: {len(sel)} signals, {len(cl)} closed" + (f", avg trade {S.mean(t['ret'] for t in cl) * 100:+.1f}%, win {100 * sum(t['ret'] > 0 for t in cl) / len(cl):.0f}%" if cl else "") + (f"; 30-day result avg {S.mean(r30) * 100:+.1f}% over {len(r30)}" if r30 else "")]
    L += ["", "Lab 36 reference: avg trade about +11%, win about 25-30%, 30-day avg +12% (BTC IN). Early live numbers mean nothing; judge after 30+ closed trades."]
    open(P("swing_report.txt"), "w").write("\n".join(L) + "\n"); print("\n".join(L))
    json.dump(st, open(P("swing_state.json"), "w"))
    new = not os.path.exists(P("swing_log.csv"))
    with open(P("swing_log.csv"), "a", newline="") as f:
        w = csv.writer(f)
        if new: w.writerow(["date", "coin", "entry", "volx", "btc_in", "alerted"])
        for s in sig: w.writerow([fd(s["day"]), s["coin"], s["entry"], f"{s['volx']:.2f}", int(bt_in), int(s["alerted"])])

if __name__ == "__main__":
    main()
