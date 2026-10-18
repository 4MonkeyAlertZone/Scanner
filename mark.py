#!/usr/bin/env python3
"""What-if report: put a fixed amount into every paper BUY SIGNAL opened since a date, and show profit/loss now.
Closed paper trades use their real exit price; open ones use the latest price. Env: SINCE (UTC, e.g. 2026-10-16T15:30), AMOUNT (default 1000), VERDICT (default 'BUY SIGNAL').
Writes mark_report.txt. Stocks show the last daily close when the US market is shut."""
import calendar, csv, os, time
import scanner

def main():
    since = calendar.timegm(time.strptime(os.environ.get("SINCE", "2026-10-16T15:30"), "%Y-%m-%dT%H:%M"))
    amt = float(os.environ.get("AMOUNT", "1000")); verdict = os.environ.get("VERDICT", "BUY SIGNAL")
    rows = [r for r in csv.DictReader(open(os.path.join(scanner.HERE, "paper_trades.csv"), encoding="utf-8"))
            if r["verdict"].startswith(verdict) and int(r["open_epoch"]) >= since and r["side"] == "long"]
    L = [f"What-if: ${amt:,.0f} in every paper '{verdict}' opened since {time.strftime('%d %b %H:%M', time.gmtime(since))} UTC. Prices read {time.strftime('%d %b %Y %H:%M', time.gmtime())} UTC. No fees or slippage.", ""]
    tot = {"crypto": [0.0, 0.0, 0, 0, 0], "stock": [0.0, 0.0, 0, 0, 0]}   # pnl, invested, n, wins, closed
    for r in rows:
        e = float(r["entry"]); mk = r["market"]
        try:
            if r["status"] == "closed": p = float(r["exit"]); state = "closed (" + r["reason"] + ")"
            else:
                p = scanner.candles(("STOCK:" if mk == "stock" else "") + r["token"], "1d" if mk == "stock" else "4h")[-1]["c"]; state = "open"
        except Exception as ex:
            L.append(f"  {r['token']:8} could not get a price ({str(ex)[:40]})"); continue
        pnl = amt * (p / e - 1); t = tot[mk]; t[0] += pnl; t[1] += amt; t[2] += 1; t[3] += pnl > 0; t[4] += r["status"] == "closed"
        L.append(f"  {r['token']:8} {mk:6} bought {r['open_time']:13} at {e:<12.6g} now {p:<12.6g} {(p / e - 1) * 100:+6.2f}%  ${pnl:+8.2f}  {state}")
    L.append("")
    for mk, t in tot.items():
        if t[2]: L.append(f"{mk.upper():7} {t[2]:3d} trades, ${t[1]:,.0f} invested: profit/loss ${t[0]:+,.2f} ({t[0] / t[1] * 100:+.2f}%), {t[3]} up / {t[2] - t[3]} down, {t[4]} already closed")
    a = [sum(t[i] for t in tot.values()) for i in range(5)]
    if a[2]: L.append(f"TOTAL   {a[2]:3d} trades, ${a[1]:,.0f} invested: profit/loss ${a[0]:+,.2f} ({a[0] / a[1] * 100:+.2f}%)")
    text = "\n".join(L); open(os.path.join(scanner.HERE, "mark_report.txt"), "w").write(text + "\n"); print(text)

if __name__ == "__main__":
    main()
