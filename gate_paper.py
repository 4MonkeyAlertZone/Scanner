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
ACC = ("btc", "eth", "mix", "sh")
NAMES = {"btc": "BTC when IN", "eth": "ETH when IN", "mix": "50/50 BTC+ETH when IN", "sh": "BTC gate + window short"}
# EXPERIMENTAL calendar short (labs 086/090 in the Lab repo; added 25 Nov 2026 at the owner's request). While the gate is OUT AND the date is inside the bear window
# [halving + 548 days (18 months), midterm election day + 28 days], the paper account is SHORT BTC 1x instead of in cash. Only 4 cycles, windows drawn after seeing the bears: not proven.
BORROW = 0.0002   # per day on short notional (lab assumption)
CYCLES = [("2012-11-28", "2014-11-04"), ("2016-07-09", "2018-11-06"), ("2020-05-11", "2022-11-08"), ("2024-04-20", "2026-11-03"), ("2028-04-20", "2030-11-05")]   # last halving date is an ESTIMATE
OFFSET = 548; TAIL = 28
def _dn(s_):
    y, m, d = map(int, s_.split("-")); import datetime as _D
    return _D.date(y, m, d).toordinal() - _D.date(1970, 1, 1).toordinal()
WINDOWS = [(_dn(h) + OFFSET, _dn(e) + TAIL) for h, e in CYCLES]
def in_window(day): return any(a <= day <= b for a, b in WINDOWS)
def window_end(day):
    for a, b in WINDOWS:
        if a <= day <= b: return b
    return None
def next_window(day):
    for a, b in WINDOWS:
        if a > day: return a
    return None
def pos_state(gate, day): return "LONG" if gate else ("SHORT" if in_window(day) else "FLAT")

def ma(c, k): return sum(c[-k:]) / k

def gate_at(closes):
    """closes: BTC closes up to and including the day being judged."""
    return len(closes) >= SLOW and closes[-1] > ma(closes, SLOW) and closes[-1] > ma(closes, FAST)

def signal_since(cb, latest):
    """(date, exact): the close on which the CURRENT gate state first showed, from the closes we hold (display only, never touches the accounts). exact is False if the state already held at the oldest day we can judge."""
    ds = sorted(d for d in cb if d <= latest); cl = [cb[d] for d in ds]
    if len(cl) < SLOW: return latest, False
    cur = gate_at(cl); j = len(cl) - 1
    while j - 1 >= SLOW - 1 and gate_at(cl[:j]) == cur: j -= 1
    return ds[j], j > SLOW - 1

def fresh(day):
    return {"start": day, "last_day": day, "gate": None, "w": 0.0, "flips": 0, "since": day, "ws": 0.0, "pos": "FLAT", "sh_start": day,
            "eq": {a: 1.0 for a in ACC}, "bh": {a: 1.0 for a in ACC}, "peak": {a: 1.0 for a in ACC}, "maxdd": {a: 0.0 for a in ACC}}

def migrate(st):
    """Older state files have no short account: add it, starting at 1.0 from the last processed day, flat."""
    if "sh" not in st["eq"]:
        st["eq"]["sh"] = 1.0; st["bh"]["sh"] = 1.0; st["peak"]["sh"] = 1.0; st["maxdd"]["sh"] = 0.0; st["ws"] = 0.0; st["sh_start"] = st["last_day"]
        st["pos"] = "LONG" if st["gate"] else "FLAT"     # what the old bot was doing; a short opens only if the window is open now
    return st

def step(st, d, cb, ce, hist_btc):
    """Advance the state by one completed day d. cb, ce: today's and yesterday's closes as (today, yesterday). hist_btc: BTC closes up to d.
    Returns (flip, change): flip is 'IN'/'OUT' if the gate flipped at this close, else None; change is (old, new) position state ('LONG','SHORT','FLAT') if it changed, else None."""
    rb = cb[0] / cb[1] - 1; re_ = ce[0] / ce[1] - 1
    rets = {"btc": rb, "eth": re_, "mix": (rb + re_) / 2}
    w = 1.0 if st["gate"] else 0.0
    for a in ("btc", "eth", "mix"):
        st["eq"][a] *= 1 + w * rets[a] - COST * abs(w - st["w"]); st["bh"][a] *= 1 + rets[a]
    ws = st.get("ws", 0.0)    # the short account's position held through today (decided at yesterday's close)
    st["eq"]["sh"] *= 1 + ws * rb - (BORROW if ws < 0 else 0.0) - COST * abs(ws - st.get("ws_prev", 0.0)); st["bh"]["sh"] *= 1 + rb
    for a in ACC:
        st["peak"][a] = max(st["peak"][a], st["eq"][a]); st["maxdd"][a] = min(st["maxdd"][a], st["eq"][a] / st["peak"][a] - 1)
    st["w"] = w; st["ws_prev"] = ws
    new = gate_at(hist_btc); flip = None
    if new != st["gate"]:
        st["flips"] += 1; st["since"] = d; flip = "IN" if new else "OUT"
    st["gate"] = new; st["last_day"] = d
    ps = pos_state(new, d); old = st.get("pos", "FLAT"); st["ws"] = {"LONG": 1.0, "SHORT": -1.0, "FLAT": 0.0}[ps]; st["pos"] = ps
    return flip, ((old, ps) if ps != old else None)

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
        st = fresh(latest); st["gate"] = gate_at(series(latest)); events.append(("START", None, latest))
        st["pos"] = pos_state(st["gate"], latest); st["ws"] = {"LONG": 1.0, "SHORT": -1.0, "FLAT": 0.0}[st["pos"]]
    else:
        if "sh" not in st["eq"]:
            st = migrate(st)
            ps = pos_state(st["gate"], st["last_day"])      # open a short right away if the window is open (it earns from the next day)
            if ps != st["pos"]: events.append(("POS", (st["pos"], ps), st["last_day"])); st["pos"] = ps; st["ws"] = {"LONG": 1.0, "SHORT": -1.0, "FLAT": 0.0}[ps]
        for d in days:
            if d <= st["last_day"]: continue
            prev = d - 1
            if prev not in cb or prev not in ce or d not in ce: raise SystemExit(f"missing data around {fd(d)}; leaving state unchanged")
            f, ch = step(st, d, (cb[d], cb[prev]), (ce[d], ce[prev]), series(d))
            if ch: events.append(("POS", ch, d))
    json.dump(st, open(P("gate_paper_state.json"), "w"))
    c = series(latest); m200 = ma(c, SLOW); m50 = ma(c, FAST)
    state = "IN" if st["gate"] else "OUT"; p = cb[latest]
    # log one row per run (today's snapshot)
    new = not os.path.exists(P("gate_paper_log.csv"))
    with open(P("gate_paper_log.csv"), "a", newline="") as f:
        w = csv.writer(f)
        if new: w.writerow(["date", "state", "btc", "eth", "btc_vs_200d_pct", "btc_vs_50d_pct", "eq_btc", "eq_eth", "eq_mix", "bh_btc", "bh_eth", "bh_mix"])
        w.writerow([fd(latest), state, f"{p:.2f}", f"{ce[latest]:.2f}", f"{(p / m200 - 1) * 100:.2f}", f"{(p / m50 - 1) * 100:.2f}"] + [f"{st['eq'][a]:.4f}" for a in ACC] + [f"{st['bh'][a]:.4f}" for a in ACC])
    # alerts: ONE short message, only when the position state changes (LONG / FLAT cash / SHORT). Nothing is sent on days where the state stays the same.
    for kind, ch, d in events:
        wend = window_end(d); wtxt = f" until {fd(wend)}" if wend else ""
        if kind == "START":
            scanner.notify("GATE BOT started", f"BTC {p:,.0f}, state {pos_state(st['gate'], d)}. Paper only. Alerts only when the state changes.", NTFY, "robot", 2)
            continue
        cd_ = series(d); old, new = ch; lv = f"BTC {cb[d]:,.0f} | 200d {ma(cd_, SLOW):,.0f} | 50d {ma(cd_, FAST):,.0f}"
        if new == "LONG": t, m, tag, pr = ("GATE IN: buy" if old != "SHORT" else "GATE IN: cover short, buy"), f"{lv}\nClosed above both averages. Paper: hold BTC/ETH.", "green_circle", 4
        elif new == "FLAT" and old == "LONG": t, m, tag, pr = "GATE OUT: sell to cash", f"{lv}\nClosed below an average. Paper: cash.", "red_circle", 4
        elif new == "SHORT" and old == "LONG": t, m, tag, pr = "GATE OUT: sell + SHORT window", f"{lv}\nPaper: cash and short BTC{wtxt}, or until gate IN. Experimental (4 cycles).", "red_circle", 4
        elif new == "SHORT": t, m, tag, pr = "SHORT window open: short BTC", f"{lv}\nGate OUT and bear window open. Paper short{wtxt}, or until gate IN. Experimental (4 cycles); short losses can be large.", "red_circle", 4
        else: t, m, tag, pr = "SHORT window closed: cover", f"{lv}\nBear window ended. Paper: close short, cash.", "white_circle", 3
        scanner.notify(t, m, NTFY, tag, pr)
    # report
    sig, exact = signal_since(cb, latest)
    L = [f"GATE PAPER BOT  data to {fd(latest)}  signal {state} since the {fd(sig)} close{'' if exact else ' or earlier'}  ({latest - sig} days)  |  paper accounts started {fd(st['start'])} ({latest - st['start']} days)", "",
         f"BTC {p:,.0f}   200-day {m200:,.0f} ({(p / m200 - 1) * 100:+.1f}%)   50-day {m50:,.0f} ({(p / m50 - 1) * 100:+.1f}%)"]
    if st["gate"]: L.append(f"To flip OUT: a close below {min(m200, m50):,.0f} ({(min(m200, m50) / p - 1) * 100:+.1f}% from here, using today's averages).")
    else: L.append(f"To flip IN: a close above {max(m200, m50):,.0f} ({(max(m200, m50) / p - 1) * 100:+.1f}% from here, using today's averages).")
    pstate = st.get("pos", "FLAT"); we = window_end(latest); nw = next_window(latest)
    L.append(f"Position now: {pstate}. Calendar short window: " + (f"OPEN until {fd(we)} ({we - latest} days left)" if we else "closed" + (f"; next opens {fd(nw)} (estimate)" if nw else "")) + ".")
    L += ["", f"{'account':<26}{'equity x':>10}{'worst DD%':>11}{'buy&hold x':>12}", ]
    for a in ACC: L.append(f"{NAMES[a]:<26}{st['eq'][a]:>10.3f}{st['maxdd'][a] * 100:>11.1f}{st['bh'][a]:>12.3f}")
    L.append(f"The short account started {fd(st.get('sh_start', st['start']))}; it is long when IN, short only while the gate is OUT and the calendar window is open, otherwise cash (cash earns 0 here, borrow 0.02%/day on the short).")
    if st["start"] > sig: L.append(f"Note: the {state} signal came before the paper accounts began on {fd(st['start'])}, so the accounts started in the {state} state and have not traded yet.")
    L += ["", f"Gate flips since the accounts started: {st['flips']}. Equity is net of 0.1% per switch; buy&hold has no cost.",
          "Judge only after at least one full IN and OUT cycle and ideally 6+ months: early numbers mean nothing. Lab 39 expectation: roughly half of buy&hold's drawdown, many small whipsaws. Paper only. Not financial advice."]
    open(P("gate_paper_report.txt"), "w").write("\n".join(L) + "\n"); print("\n".join(L))

if __name__ == "__main__":
    main()
