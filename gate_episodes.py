#!/usr/bin/env python3
"""Every IN and OUT episode of the BTC 200/50 gate, with dates and durations (not a backtest: a record).
Gate = IN while BTC's daily close is above BOTH its 200-day and 50-day average, else OUT; the same rule and the same daily BTC/USD (Bitstamp) history as labs 39-46.
signal date = the close on which the gate first showed that state; next signal = the close on which it showed the opposite state. days = next signal minus signal date (calendar days between the two signals). BTC change = close at the next signal / close at the signal date. For IN episodes that is roughly what holding BTC through the episode earned; for OUT episodes a negative number means the gate avoided a fall.
The first episode (from the first day with 200 days of history) is partial and the last one is still open; both are marked.
Writes gate_episodes.csv and gate_episodes.txt. Not financial advice."""
import os, csv, statistics as S
import scanner
import backtest_lab36 as L36
import backtest_lab39 as L39
import backtest_lab40 as L40

OUT = scanner.HERE; fd = L36.fd

def build(days, closes):
    n = len(days); gate = L39.gate_series(closes, 200, 50); first = next(i for i in range(n) if L40.sma_ok(closes, i))
    eps = L40.episodes(gate, first); rows = []
    for k, e in enumerate(eps):
        a, b = e["a"], e["b"]; ongoing = (k == len(eps) - 1); partial = (k == 0)
        last = n - 1 if ongoing else b
        rows.append(dict(n=k + 1, state="IN" if e["state"] else "OUT", signal=fd(days[a]), next_signal=("open" if ongoing else fd(days[b])),
                         days=(n - a) if ongoing else (b - a), btc_signal=closes[a], btc_next=closes[last], chg=(closes[last] / closes[a] - 1) * 100,
                         note=("partial start" if partial else ("still open, " + fd(days[-1]) + " is the latest close" if ongoing else ""))))
    return rows

def stats(rows, st):
    v = [r["days"] for r in rows if r["state"] == st and not r["note"]]
    return f"{st:<4}n={len(v):>3}  median {S.median(v):>5.1f}  mean {S.mean(v):>5.1f}  shortest {min(v)}  longest {max(v)}  <=5 days: {100 * sum(x <= 5 for x in v) / len(v):.0f}%  >=30 days: {100 * sum(x >= 30 for x in v) / len(v):.0f}%"

def main(days=None, closes=None, src="synthetic"):
    if days is None: days, closes, src = L40.load()
    rows = build(days, closes)
    with open(os.path.join(OUT, "gate_episodes.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["n", "state", "signal_date", "next_signal_date", "days", "btc_at_signal", "btc_at_next_signal", "btc_change_pct", "note"])
        for r in rows: w.writerow([r["n"], r["state"], r["signal"], r["next_signal"], r["days"], f"{r['btc_signal']:.2f}", f"{r['btc_next']:.2f}", f"{r['chg']:.1f}", r["note"]])
    out = [f"BTC 200/50 GATE: EVERY IN/OUT EPISODE  source {src}; {fd(days[0])} to {fd(days[-1])}; {len(rows)} episodes (first partial, last open)", "",
           stats(rows, "IN"), stats(rows, "OUT"), "", f"{'#':>4} {'state':<5} {'signal date':<12}{'next signal':<12}{'days':>5} {'BTC at signal':>14}{'BTC at next':>13}{'BTC chg %':>10}  note"]
    for r in rows: out.append(f"{r['n']:>4} {r['state']:<5} {r['signal']:<12}{r['next_signal']:<12}{r['days']:>5} {r['btc_signal']:>14,.0f}{r['btc_next']:>13,.0f}{r['chg']:>10.1f}  {r['note']}")
    for st in ("IN", "OUT"):
        top = sorted((r for r in rows if r["state"] == st and not r["note"]), key=lambda r: -r["days"])[:5]
        out += ["", f"Longest {st} episodes:"] + [f"  {r['signal']} to {r['next_signal']}: {r['days']} days, BTC {r['chg']:+.0f}%" for r in top]
    text = "\n".join(out); open(os.path.join(OUT, "gate_episodes.txt"), "w").write(text + "\n"); print(text)

if __name__ == "__main__":
    main()
