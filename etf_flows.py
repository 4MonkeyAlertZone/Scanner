#!/usr/bin/env python3
"""US spot Bitcoin ETF daily net flows, logged to etf_flows.csv (one row per US trading session, from 2024-01-11).
Source: The Commoner Bitcoin ETF Tracker by TFTC (tftc.io/bitcoin-etf-flows), data.json, CC BY 4.0, daily aggregates from SoSoValue. Net flow = netFlowUsd (all funds, US dollars, negative = outflow); vendorNetFlowUsd is kept for reference.
Display/log only: nothing here changes the live gate or any paper bot, and nothing places orders. The schema of data.json is not documented in full, so the parser looks for the list of rows that holds 'netFlowUsd' and prints the field names it found. If the source cannot be read the run says so and leaves the old file unchanged.
Writes etf_flows.csv. Not financial advice."""
import os, sys, json, csv, datetime as D, urllib.request
import scanner

OUT = scanner.HERE; URL = "https://www.tftc.io/bitcoin-etf-flows/data.json"; CSV = os.path.join(OUT, "etf_flows.csv")

def fetch(url=URL):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (scanner research; github actions)", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r: return json.loads(r.read().decode("utf-8"))

def find_rows(o):
    """First list of dicts in which the rows carry netFlowUsd (searched recursively)."""
    if isinstance(o, list):
        if o and all(isinstance(x, dict) for x in o) and any("netFlowUsd" in x for x in o): return o
        for x in o:
            r = find_rows(x)
            if r: return r
    elif isinstance(o, dict):
        for v in o.values():
            r = find_rows(v)
            if r: return r
    return None

def to_date(v):
    if isinstance(v, (int, float)):
        v = v / 1000 if v > 1e11 else v; return D.datetime.fromtimestamp(v, D.timezone.utc).date().isoformat()
    s = str(v)[:10]; D.date.fromisoformat(s); return s

def parse(j):
    rows = find_rows(j)
    if not rows: raise ValueError("no rows with netFlowUsd found; top-level keys: " + (str(list(j)[:12]) if isinstance(j, dict) else type(j).__name__))
    keys = list(rows[0].keys()); dk = next((k for k in ("date", "session", "sessionDate", "day", "d", "t", "time") if k in rows[0]), None)
    if dk is None: dk = next((k for k in keys if "date" in k.lower()), None)
    if dk is None: raise ValueError("no date field in row keys " + str(keys))
    out = {}
    for x in rows:
        try:
            v = x.get("netFlowUsd")
            if v is None: continue
            out[to_date(x[dk])] = (float(v), float(x["vendorNetFlowUsd"]) if x.get("vendorNetFlowUsd") is not None else "")
        except (ValueError, TypeError, KeyError): continue
    if len(out) < 100: raise ValueError(f"only {len(out)} usable rows (row keys {keys})")
    return out, keys, dk

def load(j=None):
    """{date 'YYYY-MM-DD': net flow USD} for all sessions, sorted by date."""
    d, keys, dk = parse(j if j is not None else fetch())
    return {k: d[k][0] for k in sorted(d)}

def main():
    try: d, keys, dk = parse(fetch())
    except Exception as e:
        print("ETF FLOWS: could not read the source (" + str(e)[:300] + "); file left unchanged."); return 1
    ds = sorted(d)
    with open(CSV, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "net_flow_usd", "vendor_net_flow_usd"])
        for k in ds: w.writerow([k, round(d[k][0], 2), d[k][1]])
    last = ds[-1]; t5 = sum(d[k][0] for k in ds[-5:]); t20 = sum(d[k][0] for k in ds[-20:])
    print(f"ETF FLOWS: {len(ds)} sessions {ds[0]} to {last}; row fields {keys}; date field '{dk}'")
    print(f"  last session {last}: {d[last][0] / 1e6:+,.1f}m; last 5 sessions {t5 / 1e6:+,.0f}m; last 20 sessions {t20 / 1e6:+,.0f}m")
    print("  Source: The Commoner Bitcoin ETF Tracker by TFTC (tftc.io/bitcoin-etf-flows), CC BY 4.0")
    return 0

if __name__ == "__main__": sys.exit(main())
