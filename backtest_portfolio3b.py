#!/usr/bin/env python3
"""Step 3b: WHAT IF THE CRYPTO (or core) SHARE IS REALLOCATED WHEN ITS ENGINE IS OUT, instead of sitting in cash? (all variants declared before running, ALL printed)
Uses the engines from step 3 (core = QQQ while the S&P regime is IN; trend = 12 ETFs above their 200-day, inverse-vol; crypto = BTC/ETH while BTC > 200d and 50d). Period 2018-01-02 to now, 0.1% per unit of weight changed, cash earns T-bills.
For splits 40/40/20, 50/30/20 and 34/33/33 (core/trend/crypto), the share of an engine that is OUT is handled in one of these ways:
 A  CASH            (the step 3 baseline: the OUT share stays in T-bills)
 B  CRYPTO OUT -> pro-rata to core and trend
 C  CRYPTO OUT -> core only
 D  CRYPTO OUT -> trend only
 E  CORE OUT   -> trend (crypto share stays in cash when OUT)
 F  ANY ENGINE OUT -> pro-rata to the engines that are IN (the trend engine is always 'on', so cash is only held inside it)
More invested days mean more return in good times and more drawdown in bad ones: check both. ~9 years, one crypto cycle: a robustness check, not proof. Writes portfolio3b_summary.txt."""
import os, time, math, statistics as S
import scanner
import backtest_stocks2b as B2
import backtest_portfolio3 as PF
OUT = scanner.HERE; fd = B2.fd; d0 = B2.d0

def main(data=None):
    if data is None:
        data = {"^GSPC": {d: (v, 0) for d, v in B2.fetch("^GSPC", adj=False).items()}, "^IRX": {d: (v, 0) for d, v in B2.fetch("^IRX", adj=False, need=1000).items()}}
        for t in PF.ETF + PF.CRY: data[t] = PF.C2.fetch_v(t, need=900 if t not in PF.CRY else 800)
    X = PF.setup(data); n = X["n"]; days = X["days"]; band = X["band"]; cry = X["cry_in"]; cash = X["cash"]; R = X["R"]
    a0 = next(i for i, d in enumerate(days) if d >= d0(2018, 1, 2)); a1 = next(i for i, d in enumerate(days) if d >= d0(2022, 1, 1))
    cm = S.mean(cash[a0:n])
    def ev(W, a=a0, b=n):
        m = B2.run_w(W, R, cash, a, b); cv = m["curve"]; r = [cv[i] / cv[i - 1] - 1 for i in range(1, len(cv))]
        m["sharpe"] = (S.mean(r) - cm) / S.stdev(r) * math.sqrt(252) if S.stdev(r) > 0 else float("nan"); m["expo"] = S.mean(sum(W[i]) for i in range(a, b)) * 100; return m
    def build(c, t, k, mode):
        W = []
        for i in range(n):
            ci, ki = band[i], cry[i]; cc, tt, kk = c, t, k
            if mode == "A": pass
            elif mode == "B" and not ki: cc, tt, kk = c + k * c / (c + t), t + k * t / (c + t), 0.0
            elif mode == "C" and not ki: cc, kk = c + k, 0.0
            elif mode == "D" and not ki: tt, kk = t + k, 0.0
            elif mode == "E" and not ci: tt, cc = t + c, 0.0
            elif mode == "F":
                on = [(c, ci), (t, True), (k, ki)]; tot_on = sum(x for x, f in on if f); tot = c + t + k
                cc = c * tot / tot_on if ci else 0.0; tt = t * tot / tot_on; kk = k * tot / tot_on if ki else 0.0
            W.append(PF.split_weights(cc, tt, kk, X, i, ci, ki))
        return W
    names = {"A": "A cash when out (baseline)", "B": "B crypto out -> core+trend", "C": "C crypto out -> core", "D": "D crypto out -> trend", "E": "E core out -> trend", "F": "F any out -> engines in"}
    L = ["STEP 3b: REALLOCATE WHEN AN ENGINE IS OUT?", "", f"Data to {fd(days[-1])}, 2018-01-02 to now. Idealised daily rebalancing, T-bills for cash.", ""]
    for c, t, k in ((40, 40, 20), (50, 30, 20), (34, 33, 33)):
        L += [f"== split {c}/{t}/{k} ==", f"{'handling of an OUT engine':<30}{'CAGR%':>7}{'DD%':>6}{'Sharpe':>7}{'expo%':>7} |{'2018-21 CAGR/DD':>17} |{'2022-now CAGR/DD':>18}"]
        for mode in "ABCDEF":
            W = build(c / 100, t / 100, k / 100, mode); m = ev(W); h1 = ev(W, a0, a1); h2 = ev(W, a1, n)
            L.append(f"{names[mode]:<30}{m['cagr']:>7.1f}{m['dd']:>6.0f}{m['sharpe']:>7.2f}{m['expo']:>7.0f} |{h1['cagr']:>9.1f}/{h1['dd']:>4.0f}   |{h2['cagr']:>10.1f}/{h2['dd']:>4.0f}")
        L.append("")
    L.append("Read: a reallocation only helps if return rises WITHOUT the drawdown rising by about as much (Sharpe up, both halves). Reallocating from crypto into stocks when crypto is out also changes what you hold in a stock sell-off, so look at 2022-now.")
    t = "\n".join(L); open(os.path.join(OUT, "portfolio3b_summary.txt"), "w").write(t + "\n"); print(t)

if __name__ == "__main__":
    main()
