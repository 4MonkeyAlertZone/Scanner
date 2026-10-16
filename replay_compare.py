#!/usr/bin/env python3
"""Puts every replay_<name>.csv side by side: how each trader's calls did against random entries with the same stop/target shapes."""
import csv, glob, os, scanner
def mean(x): return sum(x) / len(x) if x else 0.0
def ci(x):
    n = len(x)
    if n < 2: return 0.0
    m = mean(x); return 1.96 * (sum((v - m) ** 2 for v in x) / (n - 1) / n) ** .5
L = ["TRADER COMPARISON (average R after 0.2% costs; 'edge' = trader minus random entries with the same stop/target shape; +/- is the 95% margin of the trader's own average)", ""]
for tg in ("1R", "2R", "3R", "TP1"):
    rows_out = []
    for f in sorted(glob.glob(os.path.join(scanner.HERE, "replay_*.csv"))):
        name = os.path.basename(f)[7:-4]
        r = list(csv.DictReader(open(f)))
        def sel(model): return [float(x["R"]) for x in r if x["model"] == model and x["target"] == tg]
        mk, lm, rd = sel("MARKET"), sel("LIMIT"), sel("RANDOM")
        if len(mk) < 10: continue
        hit = sum(1 for x in r if x["model"] == "MARKET" and x["target"] == tg and x["outcome"] == "target") / len(mk)
        rows_out.append(f"  {name:10} MARKET n={len(mk):>4} {mean(mk):+.2f}R (+/-{ci(mk):.2f}) target hit {hit * 100:3.0f}% | LIMIT n={len(lm):>4} {mean(lm):+.2f}R | RANDOM {mean(rd):+.2f}R | edge market {mean(mk) - mean(rd):+.2f}R, limit {mean(lm) - mean(rd):+.2f}R")
    if rows_out: L += [f"TARGET {tg}" + (" (his stated first target)" if tg == "TP1" else ""), *rows_out, ""]
L.append("A trader only counts if the edge is clearly above zero in BOTH halves of the period (see each replay_<name>.txt, section B). With several traders one will look good by luck, so a good number here is a reason to look closer, not a verdict.")
open(os.path.join(scanner.HERE, "replay_compare.txt"), "w").write("\n".join(L) + "\n"); print("\n".join(L))
