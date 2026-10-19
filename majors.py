#!/usr/bin/env python3
"""$10,000 in BTC, ETH, BNB (each alone) and in an equal mix of the three: value after each market phase, plus the same coins under the lab rules. Reuses coins5.py. Writes majors_report.txt."""
import os, scanner, coins5 as X
SETS = [("BTC", {"BTC": ["BTC"]}), ("ETH", {"ETH": ["ETH"]}), ("BNB", {"BNB": ["BNB"]}), ("BTC + ETH + BNB equally", {"BTC": ["BTC"], "ETH": ["ETH"], "BNB": ["BNB"]})]
def main():
    out = []
    for name, coins in SETS:
        out.append("#" * 100); out.append(X.main(coins, f"$10,000 IN {name.upper()}: what it would be worth after each market phase", "_tmp_majors.txt"))
    try: os.remove(os.path.join(scanner.HERE, "_tmp_majors.txt"))
    except Exception: pass
    open(os.path.join(scanner.HERE, "majors_report.txt"), "w").write("\n".join(out) + "\n")
if __name__ == "__main__":
    main()
