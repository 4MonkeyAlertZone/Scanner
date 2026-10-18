#!/usr/bin/env python3
"""Strategy lab 12: our reclaim tool replayed only over the window from the BTC cycle bottom (about $16-17K, 21 Nov 2022) to the end of August 2025.
Same rules, stops, costs, random controls and BTC filters as lab 7 (100 coins, code reused); only entries inside the window are kept.
Writes lab12_summary.txt and lab12_results.csv."""
import os, shutil, calendar
os.environ.setdefault("LAB6_MONTHS", "84")
import scanner, backtest_lab6 as L6, backtest_lab7 as L7

START = calendar.timegm((2022, 11, 21, 0, 0, 0)); END = calendar.timegm((2025, 9, 1, 0, 0, 0))
_coin = L6.coin
def coin(tok):
    t, rows, e = _coin(tok)
    return t, [r for r in rows if START <= r[1] < END], e
L6.coin = coin

def main():
    tmp = os.path.join(scanner.HERE, "lab12_tmp"); os.makedirs(tmp, exist_ok=True)
    L7.OUT = tmp; notify, scanner.notify = scanner.notify, (lambda *a, **k: None)
    try: L7.main()
    finally: scanner.notify = notify
    text = open(os.path.join(tmp, "lab7_summary.txt")).read()
    note = ("LAB 12 = lab 7 restricted to entries from 21 Nov 2022 (BTC about $16-17K cycle bottom) to 31 Aug 2025 (when Dr Profit turned bearish). 'Group 1/2' split is as in lab 7. "
            "Era 1/era 2 here = the older/newer half of this window. Only coins still listed today are included (survivorship bias), and coins with little history in 2022-23 drop out.\n\n")
    open(os.path.join(scanner.HERE, "lab12_summary.txt"), "w").write(note + text)
    shutil.copy(os.path.join(tmp, "lab7_results.csv"), os.path.join(scanner.HERE, "lab12_results.csv")); shutil.rmtree(tmp, ignore_errors=True)
    try: scanner.notify("Strategy lab 12 finished", "Cycle-window test done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
