#!/usr/bin/env python3
"""ALT REGIME ALERT: phone notification when the 'alts in / alts out' state changes. Runs once a day just after the daily candle closes.
State = IN only when ALL of: (1) BTC closed above its 200-day average, (2) BTC closed above its 50-day average, (3) no BTC open-interest warning C in the last 14 days
(C = BTC futures open interest at a new 180-day high AND up 15%+ in 30 days; data from data.binance.vision, cached in basketgate_oi.csv by basket_paper.py).
Otherwise OUT. These are the 'gate + 50-day' and 'gate + OI C-14' rules from the majors/coins5 reports, combined. Rules fixed on 19 Oct 2026, never changed.
Honest status: the OI part was chosen after seeing the data (not out-of-sample); backtests are survivorship-flattered and cover ~3 phases. Use as a prompt to look, not an order.
Writes regime_state.json, regime_log.csv, regime_report.txt. Sends a phone alert on every change (and once on first run)."""
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
    cur = {"state": state, "g200": g200, "g50": g50, "oi_warn": oi_warn, "date": fd(days[-1]), "btc": round(c[-1], 2)}
    msg = (f"BTC {c[-1]:,.0f}  200d avg {ma(200):,.0f} ({'above' if g200 else 'below'})  50d avg {ma(50):,.0f} ({'above' if g50 else 'below'})\n"
           f"OI warning in last {COOL}d: {'YES' if oi_warn else 'no'}" + ("" if oi_ok else " (OI data unavailable, treated as no)") + "\n"
           + ("Why OUT: " + "; ".join(reasons) if state == "OUT" else "All three conditions clear.") + "\nSignal from the daily close; rule-based prompt, not advice.")
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
