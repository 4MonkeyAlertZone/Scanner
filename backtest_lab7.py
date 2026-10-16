#!/usr/bin/env python3
"""Strategy lab 7: is the 50-average reclaim edge real, or fitted to the first 60 coins and the last 3 years?
Same rules, stops and random controls as lab 6 (code reused), but:
  GROUP 1 = the 60 coins lab 6 already used, GROUP 2 = coins ranked 61-100 that lab 6 never saw (the real out-of-sample test).
  History goes back as far as the data allows (up to about 7 years), so older markets (2019-2022, including the 2022 bear market) are included.
Results are shown per group, per calendar year, and by BTC trend filter. Writes lab7_summary.txt and lab7_results.csv."""
import csv, os, time
os.environ.setdefault("LAB6_MONTHS", "84")
from multiprocessing import Pool
import scanner, backtest as B, backtest_lab3 as L3, backtest_lab4 as L4, backtest_lab6 as L6

OUT = scanner.HERE
SEEN = int(os.environ.get("LAB7_SEEN", "60")); TOTAL = int(os.environ.get("LAB7_TOTAL", "100"))
yr = lambda t: time.strftime("%Y", time.gmtime(t))

def by_year(rows, k):
    L = []
    for y in sorted({yr(r[1]) for r in rows}):
        sel = [r for r in rows if r[2] == k and r[3] == 0 and r[4] == 0 and yr(r[1]) == y]
        bm = [r for r in rows if r[2] == 3 and r[3] == 0 and r[4] == 0 and yr(r[1]) == y]
        if len(sel) < 5: continue
        mr = sum(r[8] for r in sel) / len(sel)
        L.append(f"     {y}: rule {L4.f_acc([r[5] for r in sel])}  random {mr:+.2f}R | benchmark {L4.f_acc([r[5] for r in bm])}")
    return L

def main():
    L6.btc_setup()
    coins = [c for c in scanner.top100() if c != "BTC"][:TOTAL - 1]
    print(f"Lab 7: {len(coins)} coins, history up to {L6.MONTHS} months...", flush=True)
    with Pool(max(1, os.cpu_count() or 1)) as p: res = p.map(L6.coin, coins)
    seen_set = set(coins[:SEEN])
    groups = {"GROUP 1: the 60 coins lab 6 already used": [], "GROUP 2: coins 61-100, never seen before (true out-of-sample)": []}
    errs = []
    for tok, rs, e in res:
        if e: errs.append((tok, e))
        groups["GROUP 1: the 60 coins lab 6 already used" if tok in seen_set else "GROUP 2: coins 61-100, never seen before (true out-of-sample)"] += rs
    allrows = [r for g in groups.values() for r in g]
    text = []
    if allrows: text.append(B.coverage([dict(market="crypto", epoch=r[1]) for r in allrows]))
    results = []
    for name, rows in groups.items():
        text.append("=" * 100); text.append(name)
        if len(rows) < 50: text.append(f"  too few entries ({len(rows)}) - not enough coins with history"); continue
        t, r = L6.summarise(rows, errs if "GROUP 1" in name else [])
        text.append(t)
        text.append("")
        text.append("D. BY CALENDAR YEAR (range-low stop, 7-day limit). Does the rule beat random in every year, or only in some?")
        for k in range(3):
            ys = by_year(rows, k)
            if ys: text.append(f"  {L6.RULES[k]}"); text += ys
        for x in r: x["group"] = name[:7]; results.append(x)
    text.append("=" * 100)
    text.append("HOW TO READ: the real question is GROUP 2 and the older years. If the EMA50 reclaim line shows HOLDS (or at least an edge above random in both eras) for group 2 too, and is not negative in most years, the edge is more believable. If it vanishes there, lab 6 was probably fitted to its coins and period. Survivorship bias remains (only coins still listed today).")
    out = "\n".join(text)
    if results:
        with open(os.path.join(OUT, "lab7_results.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, list(results[0].keys())); w.writeheader(); w.writerows(results)
    with open(os.path.join(OUT, "lab7_summary.txt"), "w") as f: f.write(out + "\n")
    print("\n" + out)
    try: scanner.notify("Strategy lab 7 finished", "Out-of-sample reclaim test done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
