#!/usr/bin/env python3
"""Lab 47: DO US SPOT BITCOIN ETF FLOWS ADD ANYTHING TO THE 200/50 GATE?  (2024-01-11 onward: the only years with ETF flows, ONE bull run and ONE bear market)
Rule baseline: the live gate (IN while the BTC close is above both its 200-day and 50-day average; decision at close i-1 earns day i; cost 0.1% per unit traded).
Flow signal: rolling net flow over the last W trading sessions > 0, using only sessions dated up to the PREVIOUS UTC day (the data is published after the US close). GRID of W = 3, 5, 10, 20, 30, 60 sessions.
Variants per W (declared before the run):
  F1 FILTER: IN only if the gate is IN AND the W-session flow > 0 (can only cut exposure)
  F3 BOOST : IN if the gate is IN OR the W-session flow > 0 (can only add exposure)
  F2 FLOW ONLY (reference): IN while the W-session flow > 0
PASS RULE (fixed in advance): a variant family passes only if, on the whole 2024-01-11+ window, at least 5 of the 6 windows beat the plain gate on BOTH Calmar and CAGR, and the same holds with costs x2 and with a one-day later decision. Anything else is reported as FAIL and not adopted. Halves and the current signal are shown for context only.
CAUTION: ~2.8 years, one bear market, six overlapping windows on one series: even a pass would be a hypothesis to track forward, not proof. Not financial advice.
Reads ETF flows from etf_flows.py (TFTC data.json, CC BY 4.0). Writes lab47_summary.txt."""
import os, bisect
import scanner
import backtest_lab36 as L36
import backtest_lab39 as L39
import backtest_lab40 as L40
import backtest_lab42 as L42
import backtest_lab44 as L44
import etf_flows as EF

OUT = scanner.HERE; CT = L36.CT; fd = L36.fd; day_of = L44.day_of
WINDOWS = (3, 5, 10, 20, 30, 60)

def flow_signal(days, flows, W):
    """sig[i]: net flow over the last W sessions with session date <= day i-1 is > 0 (None before enough sessions)."""
    sess = sorted((day_of(*map(int, d.split("-"))), v) for d, v in flows.items())
    sd = [s[0] for s in sess]; cum = [0.0]
    for _, v in sess: cum.append(cum[-1] + v)
    out = []
    for i in range(len(days)):
        k = bisect.bisect_right(sd, days[i] - 1)
        out.append(None if k < W else (cum[k] - cum[k - W]) > 0)
    return out

def run(c, sig, a, b, cost, delay):
    r = L42.daily(c, sig, cost, delay); return L42.perf(r, a, b)

def main(days=None, closes=None, flows=None, src="synthetic"):
    if days is None: days, closes, src = L40.load()
    if flows is None: flows = EF.load()
    n = len(days); c = closes; a0 = next(i for i, x in enumerate(days) if x >= day_of(2024, 1, 11)); mid = (a0 + n) // 2
    gate = L39.gate_series(c, 200, 50)
    ds = sorted(flows)
    out = [f"LAB 47  ETF FLOWS AND THE 200/50 GATE. Prices {src}; flows {len(ds)} sessions {ds[0]} to {ds[-1]}. Window {fd(days[a0])} to {fd(days[-1])} ({n - a0} days). Not financial advice.", ""]
    def tab(lbl, fn, cost=CT, delay=0):
        res = {}
        for nm, sg in fn.items():
            res[nm] = run(c, sg, a0, n, cost, delay)
        return res
    base = {"gate": gate}
    fams = {"F1 filter": {}, "F3 boost": {}, "F2 flow only": {}}
    for W in WINDOWS:
        s = flow_signal(days, flows, W)
        fams["F1 filter"][W] = [bool(gate[i] and s[i]) if s[i] is not None else bool(gate[i]) for i in range(n)]
        fams["F3 boost"][W] = [bool(gate[i] or s[i]) if s[i] is not None else bool(gate[i]) for i in range(n)]
        fams["F2 flow only"][W] = [bool(s[i]) if s[i] is not None else False for i in range(n)]
    scen = [("base", CT, 0), ("costs x2", CT * 2, 0), ("decision 1 day later", CT, 1)]
    g0 = {nm: run(c, gate, a0, n, cost, dl) for nm, cost, dl in scen}
    bhr = L42.perf(L42.bh(c), a0, n)
    out.append(f"PLAIN GATE  x{g0['base'][0]:.2f}  maxDD {g0['base'][1]:.0f}%  CAGR {g0['base'][2] * 100:.0f}%  Calmar {g0['base'][3]:.2f}   |  buy&hold x{bhr[0]:.2f}  maxDD {bhr[1]:.0f}%  CAGR {bhr[2] * 100:.0f}%  Calmar {bhr[3]:.2f}")
    verdict = {}
    for fam, d in fams.items():
        out += ["", f"{fam.upper()}   (W = sessions; x = final multiple; time IN = share of days invested)",
                f"{'W':>4}{'x':>8}{'maxDD%':>8}{'CAGR%':>7}{'Calmar':>8}{'timeIN%':>9}{'switches':>9}{'1st half':>10}{'2nd half':>10}  {'beats gate (base / costs x2 / 1-day later)'}"]
        wins = {nm: 0 for nm, _, _ in scen}
        for W in WINDOWS:
            sg = d[W]; r = {nm: run(c, sg, a0, n, cost, dl) for nm, cost, dl in scen}; p = r["base"]
            beat = {nm: (r[nm][3] > g0[nm][3] and r[nm][2] > g0[nm][2]) for nm, _, _ in scen}
            for nm in beat: wins[nm] += beat[nm]
            sw = sum(1 for i in range(a0 + 1, n) if sg[i] != sg[i - 1]); tin = sum(sg[a0:n]) / (n - a0) * 100
            rr = L42.daily(c, sg, CT, 0); h1 = L42.perf(rr, a0, mid)[3]; h2 = L42.perf(rr, mid, n)[3]
            out.append(f"{W:>4}{p[0]:>8.2f}{p[1]:>8.0f}{p[2] * 100:>7.0f}{p[3]:>8.2f}{tin:>9.0f}{sw:>9}{h1:>10.2f}{h2:>10.2f}  " + " / ".join("yes" if beat[nm] else "no" for nm, _, _ in scen))
        ok = all(wins[nm] >= 5 for nm, _, _ in scen); verdict[fam] = ok
        out.append(f"  windows beating the gate on Calmar and CAGR: " + ", ".join(f"{nm} {wins[nm]}/6" for nm, _, _ in scen) + f"  ->  {'PASS' if ok else 'FAIL'}")
        gh1 = L42.perf(L42.daily(c, gate, CT, 0), a0, mid)[3]; gh2 = L42.perf(L42.daily(c, gate, CT, 0), mid, n)[3]
        out.append(f"  (plain gate halves for reference: {gh1:.2f} / {gh2:.2f})")
    out += ["", "NOW (latest data)"]
    lastd = n - 1
    for W in WINDOWS:
        s = flow_signal(days, flows, W)[lastd]; tot = sum(flows[k] for k in ds[-W:])
        out.append(f"  last {W:>2} sessions net flow {tot / 1e6:>+9,.0f}m  signal {'positive' if s else 'negative'}")
    out.append(f"  gate state {'IN' if gate[lastd] else 'OUT'} at {fd(days[lastd])}")
    out += ["", "VERDICT: " + "; ".join(f"{k} {'PASS' if v else 'FAIL'}" for k, v in verdict.items()) + ". A FAIL means nothing here is adopted. A PASS would still be one bear market, so it would only start a forward paper track."]
    text = "\n".join(out); open(os.path.join(OUT, "lab47_summary.txt"), "w").write(text + "\n"); print(text)

if __name__ == "__main__":
    main()
