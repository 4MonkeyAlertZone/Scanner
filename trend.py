#!/usr/bin/env python3
"""Trend-cross paper test (crypto only). After the history bug was fixed, strategy lab 3 (3 real years of 4H data, 55 altcoins) found one
rule that kept working on data it had not seen: an altcoin whose 20-candle average crosses above its 50-candle average while it trades
above its 200-candle average, bought at the next candle's open with a stop 2.5 ATR below, selling a third at 1x, 2x and 3x the risk
(TP1, TP2, TP3), and closing what is left after 7 days. It did best when BTC was in an uptrend, so three versions run side by side:
  CROSS A: only when BTC is above its own 200-candle average
  CROSS B: only when BTC is up over 7 days and above its 20-candle average (a rising mini-cycle)
  CROSS C: any BTC condition (the control, to see live whether the BTC gate really helps)
Each signal opens three paper trades (one per target) in paper.py, so the daily report shows how often each target is hit.
A low-priority phone note is sent for new signals. It is a paper test, not advice: the backtest edge is modest and unproven live.
Used by tracker.py."""
import os, time
import scanner

N_COINS = int(os.environ.get("TREND_COINS", "60"))       # lab 3 tested the top 60 altcoins by market cap
MAX_HOURS = 168                                          # 42 four-hour candles = 7 days
STOP_ATR = 2.5
NOTIFY = os.environ.get("TREND_NOTIFY", "1") == "1"
STATE = os.path.join(scanner.HERE, "trend_state.json")
RULES = (("CROSS A", "BTC above its 200-avg"), ("CROSS B", "BTC rising (7-day up, above 20-avg)"), ("CROSS C", "any BTC"))

# reuse the 4H candles the scanner already downloaded in this run, so this check adds no extra requests
_orig, _cache = scanner.candles, {}
def _cached(tok, tf):
    if tok.startswith("STOCK:") or tf != "4h": return _orig(tok, tf)
    if tok not in _cache: _cache[tok] = _orig(tok, tf)
    return _cache[tok]
scanner.candles = _cached

def sma(c, i, k): return sum(c[i - k + 1:i + 1]) / k

def facts(d):
    """Numbers for the last CLOSED candle (d[-1] is still forming). Same definitions as backtest_lab2/3."""
    dc = d[:-1]; i = len(dc) - 1
    if i < 210: return None
    c = [r["c"] for r in dc]
    tr = [max(dc[k]["h"] - dc[k]["l"], abs(dc[k]["h"] - dc[k-1]["c"]), abs(dc[k]["l"] - dc[k-1]["c"])) for k in range(i - 13, i + 1)]
    return dict(c=c[i], sma20=sma(c, i, 20), sma50=sma(c, i, 50), sma200=sma(c, i, 200), p20=sma(c, i - 1, 20), p50=sma(c, i - 1, 50),
                ret42=c[i] / c[i - 42] - 1, atr=sum(tr) / 14)

def crossed(f): return f["sma20"] > f["sma50"] and f["p20"] <= f["p50"] and f["c"] > f["sma200"]

def btc_gates(fb):
    """(above its 200-avg, rising mini-cycle) for BTC, same definitions as lab 3."""
    return fb["c"] > fb["sma200"], bool(fb["ret42"] > 0 and fb["c"] > fb["sma20"])

def check(coins=None):
    """Fresh paper signals, one dict per target leg: tok, verdict, last, stop, target, max_hours. Never raises."""
    out, state, now = [], scanner.load(STATE), time.time()
    try:
        fb = facts(scanner.candles("BTC", "4h"))
        coins = coins or [c for c in scanner.top100() if c != "BTC"][:N_COINS]
    except Exception as e:
        print("trend check: no BTC data or coin list (", str(e)[:50], ")"); return out
    if not fb: print("trend check: not enough BTC history"); return out
    g200, grise = btc_gates(fb); gates = {"CROSS A": g200, "CROSS B": grise, "CROSS C": True}
    crosses = notes = 0
    for tok in coins:
        try:
            d = scanner.candles(tok, "4h"); f = facts(d)
            if not f or not crossed(f): continue
            crosses += 1
            last = d[-1]["c"]; stop = last - STOP_ATR * f["atr"]; risk = last - stop
            if stop <= 0 or risk <= 0: continue
            fired = []
            for name, label in RULES:
                k = f"{tok}|{name}"
                if not gates[name] or now - state.get(k, 0) < MAX_HOURS * 3600: continue
                state[k] = now; fired.append(name)
                for n in (1, 2, 3):
                    out.append(dict(tok=tok, key=tok, verdict=f"{name} TP{n}", last=last, stop=stop, target=last + n * risk, max_hours=MAX_HOURS))
            if fired and NOTIFY:
                pct = lambda n: n * risk / last * 100
                msg = (f"PAPER TEST, not advice. 20/50 trend cross, price {scanner.fmt(last)}. Stop {scanner.fmt(stop)} (-{pct(1):.1f}%). "
                       f"TP1 {scanner.fmt(last + risk)} (+{pct(1):.1f}%, reached ~55% of the time in the backtest), "
                       f"TP2 {scanner.fmt(last + 2 * risk)} (+{pct(2):.1f}%, ~38%), TP3 {scanner.fmt(last + 3 * risk)} (+{pct(3):.1f}%, ~25%). "
                       f"Passed: {', '.join(fired)}. BTC above 200-avg: {'yes' if g200 else 'no'}; BTC rising: {'yes' if grise else 'no'}. "
                       "Backtest edge is modest (about +0.2R per trade) and not yet proven live.")
                scanner.notify(f"{tok}: trend cross (paper test)", msg, scanner.NTFY_TOPIC, "chart_with_upwards_trend", 2); notes += 1
        except Exception as e: print(f"trend check {tok}: could not check ({str(e)[:50]})")
    scanner.save(STATE, state)
    print(f"Trend cross check: {len(coins)} coins, BTC above 200-avg {g200}, rising {grise}; {crosses} fresh crosses, {len(out) // 3} paper signals, {notes} phone notes")
    return out
