#!/usr/bin/env python3
"""Strategy lab 21: lab 20 plus the pre-declared variants: the drop sleeve switched off while BTC is below its 200-day average, and a BTC-heavy 70/15/15 mix.
It runs exactly the lab 20 simulation (same data, rules and costs) and saves the report as lab21_summary.txt. Nothing was tuned after seeing lab 20's results."""
import os, shutil
import scanner
import backtest_lab20 as L

if __name__ == "__main__":
    L.main()
    shutil.copy(os.path.join(scanner.HERE, "lab20_summary.txt"), os.path.join(scanner.HERE, "lab21_summary.txt"))
