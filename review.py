#!/usr/bin/env python3
"""Weekly paper-test review: reads paper_trades.csv, summarises each trend rule (CROSS A/B/C, RECLAIM A/B/C), writes review_latest.txt and sends one phone note."""
import csv, os, time
import scanner

def num(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def main():
    rows = list(csv.DictReader(open(os.path.join(scanner.HERE, "paper_trades.csv"), encoding="utf-8")))
    g = {}
    for r in rows:
        v = r.get("verdict", "")
        if not v.startswith(("CROSS", "RECLAIM")) or " TP" not in v: continue
        rule, tp = v.rsplit(" TP", 1)
        g.setdefault(rule, []).append((tp, r))
    L = [f"Paper review {time.strftime('%d %b %Y', time.gmtime())}. R = profit in units of risk. Judge a rule only once it has about 30 closed legs.", ""]
    short = []
    for rule in sorted(g):
        legs = g[rule]; closed = [(tp, r) for tp, r in legs if r.get("status") == "closed"]
        Rs = [num(r.get("R")) for _, r in closed]; Rs = [x for x in Rs if x is not None]
        wins = sum(1 for x in Rs if x > 0)
        avg = sum(Rs) / len(Rs) if Rs else 0
        L.append(f"{rule}: {len(legs)} legs opened, {len(Rs)} closed, {len(legs) - len(closed)} open" + (f", average {avg:+.2f}R, win rate {wins / len(Rs) * 100:.0f}%" if Rs else ""))
        for tp in "123":
            x = [num(r.get("R")) for t, r in closed if t == tp]; x = [y for y in x if y is not None]
            if x: L.append(f"    TP{tp}: {len(x)} closed, average {sum(x) / len(x):+.2f}R, hit target {sum(1 for t, r in closed if t == tp and r.get('reason') == 'target') / len(x) * 100:.0f}%")
        short.append(f"{rule}: {len(Rs)} closed" + (f", {avg:+.2f}R" if Rs else ""))
    if not g: L.append("No trend-rule trades yet.")
    L += ["", "Backtest expectation: about +0.1R to +0.15R per trade for RECLAIM A; B slightly lower; C close to zero. Small samples swing wildly, so do not act on a handful of trades."]
    text = "\n".join(L)
    open(os.path.join(scanner.HERE, "review_latest.txt"), "w").write(text + "\n"); print(text)
    if not scanner.QUIET_OLD: scanner.notify("Weekly paper-test review", "; ".join(short) if short else "No trend-rule trades yet.", scanner.NTFY_TOPIC, "bar_chart", 3)

if __name__ == "__main__":
    main()
