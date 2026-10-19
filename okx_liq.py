#!/usr/bin/env python3
"""Collects OKX perpetual-swap liquidation events (free, recent-only endpoint) into monthly CSV files so real liquidation history builds up from today.
Run hourly. Writes okx_liq_YYYY-MM.csv (deduplicated). No trading, no alerts."""
import csv, json, os, time, urllib.request
from datetime import datetime, timezone
HERE = os.path.dirname(os.path.abspath(__file__))
FAMILIES = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT", "BNB-USDT", "LINK-USDT", "ADA-USDT", "NEAR-USDT", "HYPE-USDT"]
FIELDS = ["ts", "instId", "posSide", "side", "sz", "ctVal", "bkPx", "bkLoss"]
def get(u):
    r = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=25); return json.loads(r.read())
def main():
    try: ct = {x["instId"]: x["ctVal"] for x in get("https://www.okx.com/api/v5/public/instruments?instType=SWAP")["data"]}
    except Exception as e: ct = {}; print("instrument sizes failed:", str(e)[:80])
    new = []
    for fam in FAMILIES:
        try: j = get(f"https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&uly={fam}&state=filled&limit=100")
        except Exception as e: print(fam, "failed:", str(e)[:80]); continue
        for blk in j.get("data", []):
            for d in blk.get("details", []):
                new.append(dict(ts=d["ts"], instId=blk.get("instId", fam + "-SWAP"), posSide=d["posSide"], side=d["side"], sz=d["sz"], ctVal=ct.get(blk.get("instId"), ""), bkPx=d["bkPx"], bkLoss=d.get("bkLoss", "")))
        time.sleep(0.3)
    by = {}
    for r in new: by.setdefault(datetime.fromtimestamp(int(r["ts"]) / 1000, timezone.utc).strftime("%Y-%m"), []).append(r)
    added = 0
    for month, rows in by.items():
        p = os.path.join(HERE, f"okx_liq_{month}.csv"); seen = set()
        if os.path.exists(p): seen = {(r["ts"], r["instId"], r["sz"], r["bkPx"]) for r in csv.DictReader(open(p))}
        out = [r for r in rows if (r["ts"], r["instId"], r["sz"], r["bkPx"]) not in seen]
        if not out: continue
        fresh = not os.path.exists(p)
        with open(p, "a", newline="") as fh:
            w = csv.DictWriter(fh, FIELDS)
            if fresh: w.writeheader()
            for r in sorted(out, key=lambda r: int(r["ts"])): w.writerow(r)
        added += len(out)
    print("new liquidation rows:", added)
if __name__ == "__main__":
    main()
