#!/usr/bin/env python3
"""ETF-FLOW FORWARD PAPER TRACK (daily). Judges the hypothesis from lab 47 on data nobody has seen yet. Display and paper only: it does not change the live gate or the gate paper bot, and nothing places orders.
HYPOTHESIS (declared 16 Nov 2026, never to be tuned): the 'boost' rule  IN = (BTC above its 200-day AND 50-day average) OR (net US spot BTC ETF flow over the last W trading sessions > 0)  beats the plain 200/50 gate. W = 10 is the main account (named in advance); W = 5 and W = 20 are its neighbours. Lab 47 (2024-01-11 on, one bear market) did NOT pass its pre-declared rule (5 of 6 windows); this track exists only to test it forward.
Accounts (all start at 1.0, BTC only, decision at a close held for the next day, 0.1% per unit traded): plain gate, boost W=5, boost W=10, boost W=20, plus buy&hold. Flows use only sessions dated up to the previous UTC day. Each run replays every completed day since the last run.
JUDGE: not before 16 May 2027 (6 months) or the start of the next bear market, whichever comes first; early numbers mean nothing. Pass would mean W=10 ahead of the plain gate on equity AND worst drawdown no worse by more than 5 points; anything else is a fail.
Flows: etf_flows.py (TFTC data.json, CC BY 4.0). Writes etf_paper_state.json, etf_paper_log.csv, etf_paper_report.txt. Not financial advice."""
import os, csv, json, time, bisect, datetime as D
import scanner, backtest as B
import gate_paper as G
import etf_flows as EF

P = lambda f: os.path.join(scanner.HERE, f); COST = 0.001; WS = (5, 10, 20); ACC = ("gate",) + tuple(f"boost{w}" for w in WS)
NAMES = {"gate": "plain 200/50 gate", "boost5": "boost, flow W=5", "boost10": "boost, flow W=10 (main)", "boost20": "boost, flow W=20"}
fd = G.fd; dnum = lambda s: int(D.date.fromisoformat(s).toordinal() - D.date(1970, 1, 1).toordinal())

def flow_pos(flows, d, W):
    """net flow over the last W sessions dated <= day d-1 is positive; None if fewer than W sessions exist."""
    sd = sorted(dnum(k) for k in flows); k = bisect.bisect_right(sd, d - 1)
    if k < W: return None
    by = {dnum(x): v for x, v in flows.items()}
    return sum(by[x] for x in sd[k - W:k]) > 0

def weights(cl, flows, d):
    g = G.gate_at(cl); w = {"gate": 1.0 if g else 0.0}
    for W in WS:
        f = flow_pos(flows, d, W); w[f"boost{W}"] = 1.0 if (g or f) else 0.0
    return w

def fresh(day, w):
    return {"start": day, "last_day": day, "w": w, "eq": {a: 1.0 for a in ACC}, "bh": 1.0, "peak": {a: 1.0 for a in ACC}, "maxdd": {a: 0.0 for a in ACC}, "flips": {a: 0 for a in ACC}}

def advance(st, d, r, w_new):
    """Day d earns the weight decided at the previous close; the cost is charged when that weight differs from the one before it."""
    for a in ACC:
        wt = st["w"][a]; prev = st["prevw"][a]
        st["eq"][a] *= 1 + wt * r - COST * abs(wt - prev)
        st["peak"][a] = max(st["peak"][a], st["eq"][a]); st["maxdd"][a] = min(st["maxdd"][a], st["eq"][a] / st["peak"][a] - 1)
        if w_new[a] != wt: st["flips"][a] += 1
    st["bh"] *= 1 + r; st["prevw"] = dict(st["w"]); st["w"] = w_new; st["last_day"] = d

def load_state():
    try: return json.load(open(P("etf_paper_state.json")))
    except Exception: return None

def main(btc=None, flows=None):
    if btc is None: btc = B.hist_crypto("BTC", "1d", 400)
    if flows is None:
        try: flows = EF.load()
        except Exception as e: raise SystemExit("ETF flows unavailable (" + str(e)[:150] + "); leaving state unchanged")
    cb = {int(r[0] // 86400): r[4] for r in btc}; days = sorted(cb); latest = days[-1]
    if len(days) < G.SLOW + 5: raise SystemExit("not enough BTC history; leaving state unchanged")
    if latest - 1 - dnum(max(flows)) > 4: raise SystemExit("ETF flow data is stale (last session " + max(flows) + "); leaving state unchanged")
    series = lambda d: [cb[x] for x in days if x <= d]
    st = load_state(); first = st is None
    if first:
        w0 = weights(series(latest), flows, latest); st = fresh(latest, w0); st["prevw"] = dict(w0)
    else:
        for d in days:
            if d <= st["last_day"]: continue
            if d - 1 not in cb: raise SystemExit(f"missing BTC data around {fd(d)}; leaving state unchanged")
            advance(st, d, cb[d] / cb[d - 1] - 1, weights(series(d), flows, d))
    json.dump(st, open(P("etf_paper_state.json"), "w"))
    c = series(latest); p = cb[latest]; m200 = G.ma(c, G.SLOW); m50 = G.ma(c, G.FAST)
    new = not os.path.exists(P("etf_paper_log.csv"))
    with open(P("etf_paper_log.csv"), "a", newline="") as f:
        w = csv.writer(f)
        if new: w.writerow(["date", "btc"] + [f"w_{a}" for a in ACC] + [f"eq_{a}" for a in ACC] + ["bh"])
        w.writerow([fd(latest), f"{p:.2f}"] + [int(st["w"][a]) for a in ACC] + [f"{st['eq'][a]:.4f}" for a in ACC] + [f"{st['bh']:.4f}"])
    sums = {W: sum(flows[k] for k in sorted(flows)[-W:]) for W in WS}
    L = [f"ETF-FLOW FORWARD PAPER TRACK  data to {fd(latest)}  accounts started {fd(st['start'])} ({latest - st['start']} days)  |  BTC {p:,.0f}  200-day {m200:,.0f}  50-day {m50:,.0f}", "",
         f"{'account':<26}{'state':>6}{'equity x':>10}{'worst DD%':>11}{'changes':>9}"]
    for a in ACC: L.append(f"{NAMES[a]:<26}{'IN' if st['w'][a] else 'OUT':>6}{st['eq'][a]:>10.3f}{st['maxdd'][a] * 100:>11.1f}{st['flips'][a]:>9}")
    L += [f"{'buy&hold BTC':<26}{'':>6}{st['bh']:>10.3f}", "", "Latest net flow over the last " + ", ".join(f"{W} sessions {sums[W] / 1e6:+,.0f}m" for W in WS) + f" (last session {max(flows)}).",
          "Hypothesis declared 16 Nov 2026: boost (gate OR flow>0) with W=10 beats the plain gate; W=5 and W=20 are neighbours. Lab 47 did not pass its own rule, so this is a forward test only.",
          "Judge on 16 May 2027 or at the start of the next bear market, whichever is first; before that the numbers mean nothing. Paper only. Not financial advice."]
    open(P("etf_paper_report.txt"), "w").write("\n".join(L) + "\n"); print("\n".join(L))

if __name__ == "__main__": main()
