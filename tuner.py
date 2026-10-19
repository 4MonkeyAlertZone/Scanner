#!/usr/bin/env python3
"""Weekly self-review. Reads backtest_signals.csv (and your live signals.csv), re-tests the alert filters
(MIN_SCORE, MIN_RR) on older vs newer data, and changes config.json ONLY if strict safety checks pass.
Writes tuning_log.md, tuning_state.json and sends a short summary to your phone.  Run: python tuner.py [--dry]"""
import csv, json, os, re, statistics as st, sys, time
from datetime import datetime, timezone
import scanner

def P(n): return os.path.join(scanner.HERE, n)
GRID_SCORE, GRID_RR = (2, 3, 4, 5), (0, 1.0, 1.2, 1.5, 2.0, 2.5)
MIN_TRAIN_N = 60    # a rule needs this many past signals to be considered
MIN_TEST_N = 40     # ...and this many in the newest 30% of data, which it was NOT chosen on
MARGIN = 0.05       # must beat the current filters by this much (in R) on that unseen data
CONFIRM = 2         # same recommendation in this many weekly reviews in a row
COOLDOWN_DAYS = 14  # at most one change per two weeks

def read_csv(name):
    try:
        with open(P(name), newline="") as f: return list(csv.DictReader(f))
    except Exception: return []

def prep(rows):
    out = []
    for r in rows:
        try: out.append(dict(epoch=int(float(r["epoch"])), score=int(r["score"]), R=float(r["R"]), rr=float(r["rr"]) if r["rr"] not in ("", None) else None))
        except Exception: pass
    return sorted(out, key=lambda r: r["epoch"])

def pick(rows, ms, mr): return [r["R"] for r in rows if r["score"] >= ms and (r["rr"] is None or r["rr"] >= mr)]

def stats(R):
    n = len(R)
    if n == 0: return 0, 0.0, 0.0
    return n, st.mean(R), (1.96 * st.stdev(R) / n ** .5 if n > 1 else 0.0)

def fmt(s): return f"n={s[0]}, avg R {s[1]:+.2f} (+/-{s[2]:.2f})"

def live_R(rows):
    out = []
    for r in rows:
        if r.get("passed_filters") != "1": continue
        try:
            e, s = float(r["entry"]), float(r["stop"]); risk = e - s
            tg = float(r["target"]) if r["target"] else None
        except Exception: continue
        if risk <= 0: continue
        cost = 0.002 * e / risk
        if r["result"] == "stop": out.append(-1 - cost)
        elif r["result"] == "target" and tg: out.append((tg - e) / risk - cost)
        elif r["status"] == "final" and r["ret_7d"] not in ("", None): out.append(float(r["ret_7d"]) * e / risk - cost)
    return out

def main(dry=False):
    now = time.time(); today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bt = prep(read_csv("backtest_signals.csv"))
    state = scanner.load(P("tuning_state.json"))
    cur = (scanner.MIN_SCORE, scanner.MIN_RR)
    L = [f"## Review {today}", f"Current filters: score >= {cur[0]}, risk/reward >= {cur[1]}"]
    decision, push = "no change", ""
    if len(bt) < 150:
        L.append(f"Only {len(bt)} backtest signals: too few to judge anything. No change.")
        push = "Weekly review: not enough backtest data yet. No change."
    else:
        cut = int(len(bt) * .7); train, test = bt[:cut], bt[cut:]
        best = None
        for ms in GRID_SCORE:
            for mr in GRID_RR:
                s = stats(pick(train, ms, mr))
                if s[0] >= MIN_TRAIN_N and s[1] > 0 and (best is None or s[1] > best[0][1]): best = (s, ms, mr)
        cs_tr, cs_te = stats(pick(train, *cur)), stats(pick(test, *cur))
        L += ["", f"Current filters, older 70% of data: {fmt(cs_tr)}", f"Current filters, newest 30% (unseen): {fmt(cs_te)}"]
        try:
            txt = open(P("backtest_summary.txt")).read()
            ctl = float(re.search(r"random entries.*?avg R ([+-]\d+\.\d+)", txt).group(1))
            L.append(f"Random entries with the same stop/target: avg R {ctl:+.2f}")
        except Exception: ctl = None
        warn = ""
        if cs_te[0] >= 20 and (cs_te[1] <= 0 or (ctl is not None and cs_te[1] - cs_te[2] <= ctl and cs_te[1] <= ctl + 0.05)):
            warn = "WARNING: on recent data the signals show no clear edge over chance or are losing. Consider pausing real-money use."
            L += ["", warn]
        cand, pend = None, state.get("pending")
        if best:
            ms, mr = best[1], best[2]; te = stats(pick(test, ms, mr)); cand = (ms, mr)
            L += ["", f"Best rule found on the older data: score >= {ms}, risk/reward >= {mr}", f"  older data: {fmt(best[0])}", f"  newest 30% (unseen): {fmt(te)}"]
            ok = cand != cur and te[0] >= MIN_TEST_N and te[1] > 0 and te[1] >= cs_te[1] + MARGIN
            if cand == cur: L.append("  That is already the current rule.")
            elif not ok: L.append(f"  Not good enough on unseen data (needs n>={MIN_TEST_N}, positive, and at least {MARGIN} R better than current).")
        else:
            ok = False; L.append("No rule was profitable on the older data with enough signals.")
        if ok:
            k = pend["count"] + 1 if pend and (pend["MIN_SCORE"], pend["MIN_RR"]) == cand else 1
            state["pending"] = dict(MIN_SCORE=cand[0], MIN_RR=cand[1], count=k)
            if k >= CONFIRM and now - state.get("last_change", 0) > COOLDOWN_DAYS * 86400:
                decision = f"CHANGED filters to score >= {cand[0]}, risk/reward >= {cand[1]}"
                if not dry:
                    scanner.save(P("config.json"), dict(MIN_SCORE=cand[0], MIN_RR=cand[1], updated=today, was=dict(MIN_SCORE=cur[0], MIN_RR=cur[1])))
                    state.setdefault("history", []).append(dict(date=today, was=list(cur), now=list(cand)))
                    state["last_change"] = now
                state["pending"] = None
            else:
                decision = f"candidate score >= {cand[0]}, risk/reward >= {cand[1]} seen {k}/{CONFIRM} times; waiting for confirmation"
        else:
            state["pending"] = None
        push = f"Weekly review: {decision}. Current filters on unseen data: {fmt(cs_te)}." + (f" {warn}" if warn else "")
    lv = live_R(read_csv("signals.csv"))
    if lv: L += ["", f"Live results so far (alerts that passed filters): {fmt(stats(lv))}"]
    L += ["", f"Decision: {decision}", ""]
    text = "\n".join(L); print(text)
    if not dry:
        with open(P("tuning_log.md"), "a") as f: f.write(text + "\n")
        scanner.save(P("tuning_state.json"), state)
        if not scanner.QUIET_OLD: scanner.notify("Weekly review", push[:380], scanner.NTFY_TOPIC, "mag")
        attach("tuning_log.md"); attach("backtest_summary.txt")

def attach(name):
    """Send a file to your phone as an ntfy attachment (PUT = the body is the file). ntfy.sh keeps it for about 3 hours."""
    if not scanner.NTFY_TOPIC or not os.path.exists(P(name)): return
    try:
        req = scanner.urllib.request.Request("https://ntfy.sh/" + scanner.NTFY_TOPIC, data=open(P(name), "rb").read(), method="PUT",
                                             headers={"Filename": name, "Title": name, "Tags": "page_facing_up", "User-Agent": "support-scanner"})
        scanner.urllib.request.urlopen(req, timeout=30).read()
    except Exception as e: print("(could not attach", name, ":", e, ")")

if __name__ == "__main__":
    main("--dry" in sys.argv)
