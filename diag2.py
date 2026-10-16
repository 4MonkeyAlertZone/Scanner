#!/usr/bin/env python3
"""Data-source check 2: how far back does daily history go, is taker-buy volume there, and can ETF flow data be reached? Writes diag2_output.txt."""
import json, time, urllib.request
from datetime import datetime, timezone
OUT = []
def say(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); OUT.append(s)
def get(url):
    try: return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=25).read().decode("utf-8", "replace")
    except Exception as e: return "ERR " + str(e)[:80]
D = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
# Binance.US daily, pages back
for sym in ("BTC", "ETH", "SOL"):
    out, end = [], int(time.time() * 1000)
    for _ in range(6):
        r = get(f"https://api.binance.us/api/v3/klines?symbol={sym}USDT&interval=1d&endTime={end}&limit=1000")
        if r.startswith("ERR"): say("Binance.US", sym, r); break
        k = json.loads(r)
        if not k: break
        out = k + out; end = int(k[0][0]) - 1
        if len(k) < 1000: break
    if out: say(f"Binance.US {sym} daily: {len(out)} days, {D(out[0][0] / 1000)} -> {D(out[-1][0] / 1000)}, taker-buy field sample {out[-1][9]} of volume {out[-1][5]}")
# OKX daily
out, after = [], ""
for _ in range(40):
    r = get("https://www.okx.com/api/v5/market/history-candles?instId=BTC-USDT&bar=1D&limit=100" + (f"&after={after}" if after else ""))
    if r.startswith("ERR"): say("OKX", r); break
    k = json.loads(r)["data"]
    if not k: break
    out += k; after = k[-1][0]; time.sleep(0.5)
    if len(k) < 100: break
if out: say(f"OKX BTC daily: {len(out)} days, {D(int(out[-1][0]) / 1000)} -> {D(int(out[0][0]) / 1000)}")
# Yahoo: BTC history and ETF (price x volume only; real ETF flows need creation/redemption data)
for sym in ("BTC-USD", "IBIT", "FBTC", "GBTC"):
    r = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=max&interval=1d")
    try:
        j = json.loads(r)["chart"]["result"][0]; ts = j["timestamp"]
        say(f"Yahoo {sym}: {len(ts)} days, {D(ts[0])} -> {D(ts[-1])}")
    except Exception: say(f"Yahoo {sym}: {r[:100]}")
# ETF flow pages
for name, url in (("Farside BTC ETF flows", "https://farside.co.uk/bitcoin-etf-flow-all-data/"),
                  ("SoSoValue", "https://api.sosovalue.xyz/openapi/v2/etf/historicalInflowChart"),
                  ("CoinGlass", "https://open-api.coinglass.com/public/v2/bitcoin_etf_flow"),
                  ("Blockchain.com BTC volume", "https://api.blockchain.info/charts/trade-volume?timespan=all&format=json")):
    r = get(url)
    say(f"{name}: {'NOT REACHABLE ' + r[:80] if r.startswith('ERR') else 'reachable, ' + str(len(r)) + ' bytes, starts: ' + r[:120].replace(chr(10), ' ')}")
open("diag2_output.txt", "w").write("\n".join(OUT) + "\n")
