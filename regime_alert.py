#!/usr/bin/env python3
"""ALT REGIME ALERT: phone notification when the 'alts in / alts out' state changes. Runs once a day just after the daily candle closes.
State = IN only when ALL of: (1) BTC closed above its 200-day average, (2) BTC closed above its 50-day average, (3) no BTC open-interest warning C in the last 14 days
(C = BTC futures open interest at a new 180-day high AND up 15%+ in 30 days; data from data.binance.vision, cached in basketgate_oi.csv by basket_paper.py).
Otherwise OUT. These are the 'gate + 50-day' and 'gate + OI C-14' rules from the majors/coins5 reports, combined. Rules fixed on 19 Oct 2026, never changed.
Honest status: the OI part was chosen after seeing the data (not out-of-sample); backtests are survivorship-flattered and cover ~3 phases. Use as a prompt to look, not an order.
Writes regime_state.json, regime_log.csv, regime_report.txt. Sends a phone alert on every change (and once on first run). Also sends a separate daily LEVERAGE traffic-light note: GREEN 2%+ above the BTC 50-day average, ORANGE 0-2% above, RED below / regime OUT; louder when the colour changes."""
import os, csv, json, time
import scanner, backtest as B, basket_paper as BP

P = BP.P; fd = BP.fd; COOL = 14

def main():
    today = int(time.time() // 86400)
    m = B.hist_crypto("BTC", "1d", 400)
    cl = {int(r[0] // 86400): r[4] for r in m}
    days = [d for d in sorted(cl) if d < today]
    c = [cl[d] for d in days]; n = len(days)
    ma = lambda k: sum(c[-k:]) / k
    g200 = c[-1] > ma(200); g50 = c[-1] > ma(50)
    try:
        oi = BP.get_oi(days); a, b = BP.warnings(days, oi); oi_ok = bool(oi)
    except Exception as e:
        a = b = [False] * n; oi_ok = False
    cw = [x and y for x, y in zip(a, b)]
    recent = [i for i in range(max(0, n - COOL), n) if cw[i]]
    oi_warn = bool(recent)
    state = "IN" if (g200 and g50 and not oi_warn) else "OUT"
    reasons = []
    if not g200: reasons.append("BTC below its 200-day average")
    if not g50: reasons.append("BTC below its 50-day average")
    if oi_warn: reasons.append(f"BTC open-interest warning on {fd(days[recent[-1]])} (cash until {fd(days[recent[-1]] + COOL)})")
    sp = P("regime_state.json")
    old = json.load(open(sp)) if os.path.exists(sp) else None
    try:
        e = B.hist_crypto("ETH", "1d", 10); eth = e[-1][4]
    except Exception: eth = None
    cur = {"state": state, "g200": g200, "g50": g50, "oi_warn": oi_warn, "date": fd(days[-1]), "btc": round(c[-1], 2), "eth": round(eth, 2) if eth else None}
    # entry prices of the current IN spell (kept while IN, cleared when OUT)
    if state == "IN":
        cur["entry_btc"] = (old or {}).get("entry_btc") if old and old.get("state") == "IN" and old.get("entry_btc") else cur["btc"]
        cur["entry_eth"] = (old or {}).get("entry_eth") if old and old.get("state") == "IN" and old.get("entry_eth") else cur["eth"]
    msg = (f"BTC {c[-1]:,.0f}  200d avg {ma(200):,.0f} ({'above' if g200 else 'below'})  50d avg {ma(50):,.0f} ({'above' if g50 else 'below'})\n"
           f"OI warning in last {COOL}d: {'YES' if oi_warn else 'no'}" + ("" if oi_ok else " (OI data unavailable, treated as no)") + "\n"
           + ("Why OUT: " + "; ".join(reasons) if state == "OUT" else "All three conditions clear.") + "\nSignal from the daily close; rule-based prompt, not advice.")
    MM = 0.005
    def lev(name, entry, now):
        if not entry or not now: return ""
        out = f"{name} since IN {entry:,.0f} (now {now:,.0f}, {(now / entry - 1) * 100:+.1f}%): "
        out += "; ".join(f"{L}x liq {entry * (1 - (1 - MM * L) / L):,.0f} ({(1 - entry * (1 - (1 - MM * L) / L) / now) * 100:.0f}% below now)" for L in (2, 3))
        return out
    if state == "IN":
        msg += "\nLEVERAGE VIEW (if you opened at the IN price; 0.5% maintenance margin, exchange fees/funding extra):\n" + lev("BTC", cur.get("entry_btc"), cur["btc"]) + "\n" + lev("ETH", cur.get("entry_eth"), cur["eth"])
        msg += f"\nBTC exit trigger: close below 50-day avg {ma(50):,.0f} ({(1 - ma(50) / c[-1]) * 100:.1f}% below now). Past worst dip below entry in IN spells: BTC 10%, ETH 19% (40 spells) - a fast wick can still hit before a daily signal."
    changed = old is None or old["state"] != state
    parts = ""
    if old and not changed:
        ch = [k for k in ("g200", "g50", "oi_warn") if old.get(k) != cur[k]]
        if ch: parts = "component change: " + ", ".join(ch)
    if changed:
        title = ("ALTS: GET IN" if state == "IN" else "ALTS: GET OUT") if old else f"Alt regime started: {state}"
        scanner.notify(title, msg, scanner.NTFY_TOPIC, "green_circle" if state == "IN" else "red_circle", 4 if state == "OUT" else 3)
    elif parts:
        scanner.notify("Alt regime: " + state + " (" + parts + ")", msg, scanner.NTFY_TOPIC, "yellow_circle", 2)
    # ---- separate LEVERAGE alert: traffic light, sent every day. GREEN = 2%+ above the 50-day line, ORANGE = 0-2% above, RED = below / regime OUT.
    gap = (c[-1] / ma(50) - 1) * 100                     # % BTC is above (+) or below (-) its 50-day average
    if state == "OUT": color = "RED"
    elif gap >= 2: color = "GREEN"
    else: color = "ORANGE"
    cur["lev_color"] = color
    prev_color = (old or {}).get("lev_color")
    EMO = {"GREEN": "green_circle", "ORANGE": "orange_circle", "RED": "red_circle"}
    head = {"GREEN": "LEVERAGE GREEN: OK to hold or open", "ORANGE": "LEVERAGE ORANGE: hold only, do not add", "RED": "LEVERAGE RED: close leveraged longs"}[color]
    act = {"GREEN": "ACTION: leveraged longs are allowed (BTC 2x or less is the steadiest in the tests). Open or hold.",
           "ORANGE": "ACTION: do NOT open new leveraged positions. Existing ones can stay, but the exit line is close.",
           "RED": "ACTION: close leveraged longs and stay out of leverage. " + ("; ".join(reasons) + "." if reasons else "")}[color]
    body = [act, "",
            f"BTC {c[-1]:,.0f} is {gap:+.1f}% vs its 50-day average ({ma(50):,.0f}).",
            "Colours: GREEN = 2%+ above 50-day, ORANGE = 0 to 2% above, RED = below 50-day / 200-day or OI warning."]
    if state == "IN":
        body += ["", "If you opened at the IN price:", lev("BTC", cur.get("entry_btc"), cur["btc"]), lev("ETH", cur.get("entry_eth"), cur["eth"]),
                 f"EXIT LINE: BTC daily close below {ma(50):,.0f} (now {max(gap, 0):.1f}% away)."]
        dip = (1 - cur["btc"] / cur["entry_btc"]) * 100 if cur.get("entry_btc") else 0
        dipe = (1 - cur["eth"] / cur["entry_eth"]) * 100 if cur.get("entry_eth") and cur.get("eth") else 0
        if dip >= 10 or dipe >= 15: body.append(f"WARNING: price is {max(dip, dipe):.0f}% below the IN entry. 3x liquidation is ~33% away, 2x ~50%.")
    body += ["", "Fast wicks can liquidate before a daily signal. Use your own fill price and an exchange stop. Rule-based prompt, not advice."]
    changed_c = prev_color is not None and prev_color != color
    title = head + (" (colour changed)" if changed_c else "")
    scanner.notify(title, "\n".join(body), scanner.NTFY_TOPIC, EMO[color], 4 if (changed_c or color == "RED") else 2 if color == "GREEN" else 3)
    json.dump(cur, open(sp, "w"))
    lp = P("regime_log.csv"); new = not os.path.exists(lp)
    with open(lp, "a", newline="") as f:
        w = csv.writer(f)
        if new: w.writerow(["date", "state", "btc", "above_200d", "above_50d", "oi_warning_14d"])
        w.writerow([cur["date"], state, cur["btc"], g200, g50, oi_warn])
    open(P("regime_report.txt"), "w").write(f"ALT REGIME  data to {cur['date']}: {state}\n{msg}\n")
    print(open(P("regime_report.txt")).read())

if __name__ == "__main__":
    main()
