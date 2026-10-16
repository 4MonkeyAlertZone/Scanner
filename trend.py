#!/usr/bin/env python3
"""Trend-breakout paper test (crypto only, NO phone alerts). Strategy lab 2 found that buying a break above the highest high of the last
55 four-hour candles, with a wide 2.5-ATR stop, held up on unseen data. This module checks the top coins for that signal on every scan and
hands any signal to the paper-trading ledger (paper.py), so live results can confirm or kill the idea. Used by tracker.py.
Rules (same as the lab): the last CLOSED 4H candle closes above the highest high of the 55 candles before it, and
  A) it is also above its 200-candle average -> stop 2.5 ATR below entry, target 2x risk
  B) volume is at least 1.5x its 20-candle average -> stop 2.5 ATR below entry, target 3x risk
Time limit 7 days, then the trade is closed at market. Same coin and rule: at most one signal per 7 days."""
import os, time
import scanner

N_COINS = int(os.environ.get("TREND_COINS", "30"))      # the lab tested the top 30 coins by market cap
MAX_HOURS = 168                                         # 42 four-hour candles = 7 days
STATE = os.path.join(scanner.HERE, "trend_state.json")
RULES = (("BREAKOUT 55 + trend", dict(vol=0.0, trend=True, stop=2.5, rr=2.0)),
         ("BREAKOUT 55 + volume", dict(vol=1.5, trend=False, stop=2.5, rr=3.0)))

# reuse the 4H candles the scanner already downloaded in this run, so this check adds no extra requests
_orig, _cache = scanner.candles, {}
def _cached(tok, tf):
    if tok.startswith("STOCK:") or tf != "4h": return _orig(tok, tf)
    if tok not in _cache: _cache[tok] = _orig(tok, tf)
    return _cache[tok]
scanner.candles = _cached

def facts(d):
    """Numbers for the last closed candle (d[-1] is still forming). Same definitions as backtest_lab2.py."""
    dc = d[:-1]; i = len(dc) - 1
    if i < 210: return None
    c = dc[i]["c"]
    tr = [max(dc[k]["h"] - dc[k]["l"], abs(dc[k]["h"] - dc[k-1]["c"]), abs(dc[k]["l"] - dc[k-1]["c"])) for k in range(i - 13, i + 1)]
    av = sum(r["v"] for r in dc[i-20:i]) / 20
    return dict(c=c, hh=max(r["h"] for r in dc[i-55:i]), sma200=sum(r["c"] for r in dc[i-199:i+1]) / 200, atr=sum(tr) / 14,
                volr=dc[i]["v"] / av if av > 0 else 0.0)

def signal(f, p):
    return f["c"] > f["hh"] and (not p["trend"] or f["c"] > f["sma200"]) and (not p["vol"] or f["volr"] >= p["vol"])

def check(coins=None):
    """List of fresh signals: dicts with tok, key, verdict, last, stop, target, max_hours. Never raises."""
    out, state, now = [], scanner.load(STATE), time.time()
    try: coins = coins or scanner.top100()[:N_COINS]
    except Exception as e: print("trend check: no coin list (", str(e)[:50], ")"); return out
    hits = 0
    for tok in coins:
        try:
            d = scanner.candles(tok, "4h"); f = facts(d)
            if not f: continue
            last = d[-1]["c"]
            for name, p in RULES:
                if not signal(f, p): continue
                hits += 1
                k = f"{tok}|{name}"
                if now - state.get(k, 0) < MAX_HOURS * 3600: continue
                stop = last - p["stop"] * f["atr"]
                if stop <= 0 or stop >= last: continue
                state[k] = now
                out.append(dict(tok=tok, key=tok, verdict=name, last=last, stop=stop, target=last + p["rr"] * (last - stop), max_hours=MAX_HOURS))
        except Exception as e: print(f"trend check {tok}: could not check ({str(e)[:50]})")
    scanner.save(STATE, state)
    print(f"Trend breakout check: {len(coins)} coins, {hits} breakouts, {len(out)} new paper signals")
    return out
