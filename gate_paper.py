#!/usr/bin/env python3
"""GATE PAPER BOT (daily, after the 00:00 UTC close). Paper-trades the one rule that held up in lab 39: hold BTC (and ETH) only while BTC is IN, otherwise sit in cash.
RULE (fixed 31 Oct 2026, never to be tuned): BTC's latest completed daily close is above BOTH its 200-day and its 50-day average -> IN (hold). Otherwise OUT (cash).
 The decision made at a close is held for the NEXT day, exactly as lab 39 simulated; a switch costs 0.1% of the position value. No open-interest filter (lab 39 tested the plain 200/50 gate only).
Three virtual accounts start at 1.0 (in cash) on the first run: BTC when IN, ETH when IN, 50/50 BTC+ETH when IN (daily rebalanced, rebalancing cost ignored, as in lab 39). Three buy&hold benchmarks run alongside (no cost).
Each run replays every completed day since the last run, so a missed or delayed run catches up by itself. A phone/Telegram alert is sent only when the gate flips (and once on the first run); the daily report shows distance to the next flip.
Honest status: lab 39 found the gate unusually good against a time-shift placebo and stable across parameters, costs and delays, but the history holds only a few bear markets, BTC/ETH were chosen in hindsight, and 39 labs were run on the same data.
Expected: a drawdown roughly half of buy&hold (still around -40%), many small whipsaws, and no guarantee. Paper only: nothing here places an order. Not financial advice.
Writes gate_paper_state.json, gate_paper_log.csv, gate_paper_report.txt."""
import os, csv, json, time
import scanner, backtest as B

HERE = scanner.HERE; P = lambda f: os.path.join(HERE, f)
COST = 0.001; SLOW = 200; FAST = 50
NTFY = os.environ.get("NTFY_TOPIC", "")
fd = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))
ACC = ("btc", "eth", "mix")
NAMES = {"btc": "BTC when IN", "eth": "ETH when IN", "mix": "50/50 BTC+ETH when IN"}

def ma(c, k): return sum(c[-k:]) / k

def gate_at(closes):
    """closes: BTC closes up to and including the day being judged."""
    return len(closes) >= SLOW and closes[-1] > ma(closes, SLOW) and closes[-1] > ma(closes, FAST)

def fresh(day):
    return {"start": day, "last_day": day, "gate": None, "w": 0.0, "flips": 0, "since": day,
            "eq": {a: 1.0 for a in ACC}, "bh": {a: 1.0 for a in ACC}, "peak": {a: 1.0 for a in ACC}, "maxdd": {a: 0.0 for a in ACC}}

def step(st, d, cb, ce, hist_btc):
    """Advance the state by one completed day d. cb, ce: today's and yesterday's closes as (today, yesterday). hist_btc: BTC closes up to d.
    Returns 'IN', 'OUT' if the gate flipped at this close, else None."""
    rb = cb[0] / cb[1] - 1; re_ = ce[0] / ce[1] - 1
    rets = {"btc": rb, "eth": re_, "mix": (rb + re_) / 2}
    w = 1.0 if st["gate"] else 0.0
    for a in ACC:
        st["eq"][a] *= 1 + w * rets[a] - COST * abs(w - st["w"]); st["bh"][a] *= 1 + rets[a]
        st["peak"][a] = max(st["peak"][a], st["eq"][a]); st["maxdd"][a] = min(st["maxdd"][a], st["eq"][a] / st["peak"][a] - 1)
    st["w"] = w
    new = gate_at(hist_btc); flip = None
    if new != st["gate"]:
        st["flips"] += 1; st["since"] = d; flip = "IN" if new else "OUT"
    st["gate"] = new; st["last_day"] = d
    return flip

def load_state():
    try: return json.load(open(P("gate_paper_state.json")))
    except Exception: return None

def main():
    btc = B.hist_crypto("BTC", "1d", 400); eth = B.hist_crypto("ETH", "1d", 400)
    if len(btc) < SLOW + 5 or len(eth) < 20: raise SystemExit("not enough history for BTC/ETH; leaving state unchanged")
    cb = {int(r[0] // 86400): r[4] for r in btc}; ce = {int(r[0] // 86400): r[4] for r in eth}
    days = [d for d in sorted(cb) if d in ce]
    latest = days[-1]
    st = load_state(); events = []; first = st is None
    series = lambda d: [cb[x] for x in sorted(cb) if x <= d]
    if first:
        st = fresh(latest); st["gate"] = gate_at(series(latest)); events.append(("START", latest))
    else:
        for d in days:
            if d <= st["last_day"]: continue
            prev = d - 1
            if prev not in cb or prev not in ce or d not in ce: raise SystemExit(f"missing data around {fd(d)}; leaving state unchanged")
            f = step(st, d, (cb[d], cb[prev]), (ce[d], ce[prev]), series(d))
            if f: events.append((f, d))
    json.dump(st, open(P("gate_paper_state.json"), "w"))
    c = series(latest); m200 = ma(c, SLOW); m50 = ma(c, FAST)
    state = "IN" if st["gate"] else "OUT"; p = cb[latest]
    # log one row per run (today's snapshot)
    new = not os.path.exists(P("gate_paper_log.csv"))
    with open(P("gate_paper_log.csv"), "a", newline="") as f:
        w = csv.writer(f)
        if new: w.writerow(["date", "state", "btc", "eth", "btc_vs_200d_pct", "btc_vs_50d_pct", "eq_btc", "eq_eth", "eq_mix", "bh_btc", "bh_eth", "bh_mix"])
        w.writerow([fd(latest), state, f"{p:.2f}", f"{ce[latest]:.2f}", f"{(p / m200 - 1) * 100:.2f}", f"{(p / m50 - 1) * 100:.2f}"] + [f"{st['eq'][a]:.4f}" for a in ACC] + [f"{st['bh'][a]:.4f}" for a in ACC])
    # alerts
    for kind, d in events:
        if kind == "START":
            msg = (f"Gate paper bot started on {fd(d)}. BTC {p:,.0f}: 200-day {m200:,.0f}, 50-day {m50:,.0f}. State {state}. "
                   f"Paper only; it holds BTC/ETH while BTC is above both averages, otherwise cash. First position {'will be taken tomorrow' if st['gate'] else 'stays in cash'}.")
            scanner.notify("GATE PAPER BOT: started", msg, NTFY, "robot", 3)
        elif kind == "IN":
            msg = (f"BTC closed at {cb[d]:,.0f} above both its 200-day ({m200:,.0f}) and 50-day ({m50:,.0f}) on {fd(d)}. Paper bot BUYS BTC/ETH at this close. "
                   f"Paper only. Expect whipsaws: the rule flipped {st['flips']} times since {fd(st['start'])}.")
            scanner.notify("GATE FLIPPED: IN (buy)", msg, NTFY, "green_circle", 4)
        elif kind == "OUT":
            msg = (f"BTC closed at {cb[d]:,.0f} on {fd(d)}, below its 200-day ({m200:,.0f}) or 50-day ({m50:,.0f}). Paper bot SELLS to cash at this close. Paper only.")
            scanner.notify("GATE FLIPPED: OUT (sell)", msg, NTFY, "red_circle", 4)
    # report
    L = [f"GATE PAPER BOT  data to {fd(latest)}  state {state} since {fd(st['since'])}  ({latest - st['since']} days)  started {fd(st['start'])} ({latest - st['start']} days)", "",
         f"BTC {p:,.0f}   200-day {m200:,.0f} ({(p / m200 - 1) * 100:+.1f}%)   50-day {m50:,.0f} ({(p / m50 - 1) * 100:+.1f}%)"]
    if st["gate"]: L.append(f"To flip OUT: a close below {min(m200, m50):,.0f} ({(min(m200, m50) / p - 1) * 100:+.1f}% from here, using today's averages).")
    else: L.append(f"To flip IN: a close above {max(m200, m50):,.0f} ({(max(m200, m50) / p - 1) * 100:+.1f}% from here, using today's averages).")
    L += ["", f"{'account':<26}{'equity x':>10}{'worst DD%':>11}{'buy&hold x':>12}", ]
    for a in ACC: L.append(f"{NAMES[a]:<26}{st['eq'][a]:>10.3f}{st['maxdd'][a] * 100:>11.1f}{st['bh'][a]:>12.3f}")
    L += ["", f"Gate flips so far: {st['flips']}. Equity is net of 0.1% per switch; buy&hold has no cost.",
          "Judge only after at least one full IN and OUT cycle and ideally 6+ months: early numbers mean nothing. Lab 39 expectation: roughly half of buy&hold's drawdown, many small whipsaws. Paper only. Not financial advice."]
    open(P("gate_paper_report.txt"), "w").write("\n".join(L) + "\n"); print("\n".join(L))

if __name__ == "__main__":
    main()
