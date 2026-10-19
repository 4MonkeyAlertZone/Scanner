#!/usr/bin/env python3
"""Lab 24: let a model hunt for patterns, then judge it ONLY on periods it never saw.
Panel of up to 90 coins x daily bars; on each day only the TOP-K coins by trailing traded value (a stand-in for market-cap rank, K = 10 and 20) are eligible, so the coins change between cycles. Features use data up to the close of day t only. Target = return from the open of day t+1 to the open of day t+11,
minus the average of all coins that day (so 'the whole market went up' does not count). Cost 0.1% per round trip on the picks.
Fit A: train on cycle 2 (Nov 2022 - Aug 2025); test on cycle 1 (Oct 2020 - Nov 2021), bear year (Nov 2021 - Nov 2022), recent (Sep 2025 - now).
Fit B (reverse): train on cycle 1 + bear year; test on cycle 2 and recent. Windows around the split are purged.
Outputs: lab24_summary.txt (single-feature table, model scores with shuffle test, feature importance, readable tree rules)."""
import os, sys, calendar, random
from datetime import datetime, timezone
from multiprocessing import Pool
import numpy as np
import scanner, backtest as B
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.tree import DecisionTreeRegressor, export_text

STABLES = {"USDT", "USDC", "DAI", "TUSD", "FDUSD", "USDE", "USD1", "PYUSD", "USDD", "BUSD", "USDP", "FRAX", "WBTC", "BTC", "STETH", "WSTETH", "WBETH"}
NC = int(os.environ.get("LAB24_COINS", "90")); HOLD = 10; COST = float(os.environ.get("LAB_COST", "0.001")); TOPN = 3
ts = lambda y, m, d: calendar.timegm((y, m, d, 0, 0, 0))
PER = {  # signal-date windows (purged by ~12 days at the edges)
    "cycle 2 (train A)": (ts(2022, 11, 21), ts(2025, 8, 19)),
    "cycle 1": (ts(2020, 10, 1), ts(2021, 11, 1)),
    "bear year": (ts(2021, 11, 23), ts(2022, 11, 8)),
    "recent": (ts(2025, 9, 15), ts(2099, 1, 1)),
}
dstr = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")

def load(sym):
    try:
        rows = B.hist_crypto(sym, "1d", 2800); out = []
        for t, o, h, l, c, v in rows:
            hb, lb = max(o, c), min(o, c); out.append((t, o, min(h, hb * 1.25), max(l, lb / 1.25), c, v))
        return sym, out
    except Exception: return sym, []

def sma(x, n):
    out = np.full_like(x, np.nan); cs = np.nancumsum(np.where(np.isnan(x), 0, x), axis=1); cn = np.cumsum(~np.isnan(x), axis=1)
    s = cs.copy(); k = cn.copy(); s[:, n:] = cs[:, n:] - cs[:, :-n]; k[:, n:] = cn[:, n:] - cn[:, :-n]
    ok = k >= n * 0.9; out[ok] = s[ok] / k[ok]; return out

def lag(x, k):
    out = np.full_like(x, np.nan); out[:, k:] = x[:, :-k] if k else x; return out if k else x.copy()

def roll_std(x, n):
    m = sma(x, n); m2 = sma(x * x, n); return np.sqrt(np.maximum(m2 - m * m, 0))

def rsi14(c):
    d = np.diff(c, axis=1, prepend=np.nan); g = np.where(d > 0, d, 0); l = np.where(d < 0, -d, 0)
    ag, al = sma(g, 14), sma(l, 14); return 100 - 100 / (1 + ag / np.where(al == 0, np.nan, al))

def spearman_days(F, Y, idx):
    """Mean per-day cross-sectional rank correlation between feature matrix F (coins x days) and target Y."""
    out = []
    for j in idx:
        f, y = F[:, j], Y[:, j]; ok = ~np.isnan(f) & ~np.isnan(y)
        if ok.sum() < 6 or np.ptp(f[ok]) == 0: continue   # market-wide features are identical for every coin on a day: no cross-sectional information
        rf = np.argsort(np.argsort(f[ok])); ry = np.argsort(np.argsort(y[ok]))
        c = np.corrcoef(rf, ry)[0, 1]
        if c == c: out.append(c)
    return (np.mean(out), len(out)) if out else (np.nan, 0)

def main():
    btc = dict(load("BTC")[1]) if False else None
    _, brows = load("BTC")
    toks = [t for t in scanner.top100()[:NC + 15] if t.upper() not in STABLES][:NC]
    with Pool(2) as p: res = p.map(load, toks, chunksize=1)
    data = {s: r for s, r in res if len(r) > 450}
    T = np.array([r[0] for r in brows]); nD = len(T); pos = {int(t): i for i, t in enumerate(T)}
    names = list(data); nC = len(names)
    O = np.full((nC, nD), np.nan); H = O.copy(); L = O.copy(); C = O.copy(); V = O.copy()
    for k, s in enumerate(names):
        for t, o, h, l, c, v in data[s]:
            j = pos.get(int(t))
            if j is not None: O[k, j], H[k, j], L[k, j], C[k, j], V[k, j] = o, h, l, c, v
    bO = np.array([[r[1] for r in brows]]); bC = np.array([[r[4] for r in brows]])
    # ---- features (information up to close of day t) ----
    F = {}; ret = lambda x, n: x / lag(x, n) - 1
    for n in (1, 2, 3, 5, 10, 20, 30, 60): F[f"ret_{n}d"] = ret(C, n)
    bret = {n: ret(bC, n) for n in (1, 2, 3, 5, 10, 20, 30, 60)}
    for n in (1, 3, 10, 30): F[f"rel_btc_{n}d"] = F[f"ret_{n}d"] - bret[n]
    for n in (1, 3, 10, 30): F[f"btc_ret_{n}d"] = np.repeat(bret[n], nC, axis=0)
    F["btc_ret_1d_lag1"] = lag(np.repeat(bret[1], nC, axis=0), 1)
    b200, b50 = sma(bC, 200), sma(bC, 50)
    F["btc_vs_200d"] = np.repeat(bC / b200 - 1, nC, axis=0); F["btc_vs_50d"] = np.repeat(bC / b50 - 1, nC, axis=0)
    for n in (20, 50, 200): F[f"vs_ma{n}"] = C / sma(C, n) - 1
    hi60 = np.full_like(C, np.nan); lo60 = hi60.copy()
    for j in range(60, nD): hi60[:, j] = np.nanmax(H[:, j-59:j+1], axis=1); lo60[:, j] = np.nanmin(L[:, j-59:j+1], axis=1)
    F["off_60d_high"] = C / hi60 - 1; F["above_60d_low"] = C / lo60 - 1
    F["rsi14"] = rsi14(C); dr = ret(C, 1)
    F["vol_10d"] = roll_std(dr, 10); F["vol_30d"] = roll_std(dr, 30); F["vol_ratio"] = F["vol_10d"] / F["vol_30d"]
    F["range_today"] = (H - L) / C; rg = np.where(H > L, H - L, np.nan); F["close_loc"] = (C - L) / rg
    F["body_today"] = (C - O) / O
    F["vol_surge"] = V / sma(V, 20); F["vol_5v30"] = sma(V, 5) / sma(V, 30)
    ew = np.nanmean(dr, axis=0, keepdims=True); basket = np.nancumprod(1 + np.nan_to_num(ew, nan=0.0), axis=1)
    for n in (1, 5, 10, 30): F[f"basket_ret_{n}d"] = np.repeat(basket / np.concatenate([np.full((1, n), np.nan), basket[:, :-n]], axis=1) - 1, nC, axis=0)
    ratio = basket / bC
    for n in (10, 30): F[f"basket_vs_btc_{n}d"] = np.repeat(ratio / np.concatenate([np.full((1, n), np.nan), ratio[:, :-n]], axis=1) - 1, nC, axis=0)
    above50 = (C > sma(C, 50)).astype(float); above50[np.isnan(sma(C, 50))] = np.nan
    F["breadth_above_50d"] = np.repeat(np.nanmean(above50, axis=0, keepdims=True), nC, axis=0)
    cor = np.full_like(C, np.nan)
    for j in range(30, nD):
        b = bret[1][0, j-29:j+1]
        for k in range(nC):
            x = dr[k, j-29:j+1]; ok = ~np.isnan(x) & ~np.isnan(b)
            if ok.sum() > 20: cor[k, j] = np.corrcoef(x[ok], b[ok])[0, 1]
    F["corr_btc_30d"] = cor
    F["resid_vs_btc_1d"] = F["ret_1d"] - cor * F["btc_ret_1d"]
    dv = sma(C * V, 60)                                   # trailing 60-day average traded value in USD
    rk = np.full_like(C, np.nan)
    for j in range(nD):
        m = ~np.isnan(dv[:, j])
        if m.sum(): rk[m, j] = np.argsort(np.argsort(-dv[m, j])) + 1
    F["size_rank"] = rk
    fn = list(F); X3 = np.stack([F[k] for k in fn], axis=2)           # coins x days x features
    # ---- target ----
    Oa = np.concatenate([O, np.full((nC, HOLD + 2), np.nan)], axis=1)
    R = np.full((nC, nD), np.nan)
    for j in range(nD - HOLD - 1): R[:, j] = Oa[:, j + 1 + HOLD] / Oa[:, j + 1] - 1
    rnd = random.Random(5)
    out_all = [f"LAB 24  {datetime.now(timezone.utc):%Y-%m-%d}  model hunt, judged on unseen periods. Pool {nC} coins, daily, hold {HOLD}d (open t+1 to open t+11), picks net of {COST:.2%} cost.",
               "Each day only the TOP-K coins by trailing 60-day traded value are eligible (size rank stand-in; true market-cap history is not free). Target = return minus the average of that day's eligible coins.",
               "Pool: " + ", ".join(names), "Missing from the pool: coins that died or were delisted (e.g. LUNA, FTT) - this still flatters 'buy the dip' style rules.", ""]
    for K in (10, 20):
        U = (rk <= K) & ~np.isnan(R); cnt = U.sum(axis=0); need = max(6, int(K * .7))
        mu = np.where(cnt >= need, np.nansum(np.where(U, R, 0), axis=0) / np.maximum(cnt, 1), np.nan); Y = np.where(U, R - mu[None, :], np.nan)
        idx = {k: [j for j in range(220, nD) if lo <= T[j] < hi and cnt[j] >= need] for k, (lo, hi) in PER.items()}
        Lx = [f"################ TOP {K} COINS BY SIZE RANK ################", "Days per period: " + "; ".join(f"{k} {len(v)}" for k, v in idx.items()), ""]
        Lx += ["== 1. One feature at a time: average daily rank correlation (IC) with the 10-day excess return. +ve = high values did better. A real pattern keeps its SIGN in every period. (Market-wide features such as BTC trend cannot be ranked across coins; the model below can still use them.) ==",
               f"{'feature':<20}" + "".join(f"{k[:16]:>18}" for k in PER) + "   consistent?"]
        rows = []
        for fi, name in enumerate(fn):
            vals = [spearman_days(np.where(U, X3[:, :, fi], np.nan), Y, idx[k][::3])[0] for k in PER]; rows.append((name, vals))
        rows = [r for r in rows if r[1][0] == r[1][0]]; rows.sort(key=lambda r: -abs(r[1][0]))
        for name, vals in rows[:20]:
            sg = [np.sign(v) for v in vals if v == v]; cons = len(sg) == len(vals) and len(set(sg)) == 1 and all(abs(v) > .01 for v in vals)
            Lx.append(f"{name:<20}" + "".join(f"{v:>18.3f}" for v in vals) + ("   YES" if cons else ""))
        def rows_of(keys):
            j = np.array(sorted({x for k in keys for x in idx[k]})); sub = X3[:, j, :]; y = Y[:, j]
            m = ~np.isnan(sub).any(axis=2) & ~np.isnan(y); k, d = np.where(m)
            return sub[k, d, :], y[k, d]
        def scores(model):
            S = np.full((nC, nD), np.nan)
            for j in range(220, nD):
                sub = X3[:, j, :]; m = U[:, j] & ~np.isnan(sub).any(axis=1)
                if m.sum() >= 1: S[m, j] = model.predict(sub[m])
            return S
        def topn(S, js, bottom=False):
            e = []
            for j in js:
                m = ~np.isnan(S[:, j]) & U[:, j]
                if m.sum() < need: continue
                o = np.argsort(S[m, j]); r = R[m, j]
                e.append((r[o[:TOPN]].mean() - r.mean()) if bottom else (r[o[-TOPN:]].mean() - COST - r.mean()))
            return np.array(e)
        def evaluate(S, key):
            js = idx[key][::5]; ex = topn(S, js)
            if len(ex) < 10: return None
            bot = topn(S, js, True).mean(); ic = spearman_days(S, Y, idx[key][::3])[0]
            null = []
            for _ in range(200):                              # circular-shift null: keeps each coin's score persistence, breaks alignment with outcomes
                Sh = np.empty_like(S)
                for k in range(nC): Sh[k] = np.roll(S[k], rnd.randrange(40, nD - 40))
                e = topn(Sh, js)
                if len(e): null.append(e.mean())
            p = float(np.mean(np.array(null) >= ex.mean())) if null else float("nan")
            return len(ex), ex.mean(), (ex > 0).mean(), bot, ic, p
        def report(title, trkeys, tekeys, X, y):
            gb = GradientBoostingRegressor(n_estimators=150, max_depth=3, learning_rate=.05, subsample=.7, min_samples_leaf=100, random_state=1).fit(X, y)
            tr = DecisionTreeRegressor(max_depth=3, min_samples_leaf=max(300, len(y) // 40), random_state=1).fit(X, y)
            out = [f"== {title} ==  (fit on {len(y)} coin-days)", f"{'period':<20}{'model':<8}{'trades':>7}{'avg excess/trade':>18}{'win%':>6}{'worst-3 excess':>16}{'IC':>7}{'chance p':>9}"]
            for nm, mdl in (("boost", gb), ("tree", tr)):
                S = scores(mdl)
                for k in trkeys + tekeys:
                    e = evaluate(S, k)
                    if e: out.append(f"{k:<20}{nm:<8}{e[0]:>7}{e[1]:>18.2%}{e[2]:>6.0%}{e[3]:>16.2%}{e[4]:>7.3f}{e[5]:>9.2f}" + ("   (trained here)" if k in trkeys else ""))
            imp = sorted(zip(fn, gb.feature_importances_), key=lambda a: -a[1])[:12]
            out += ["", "Most used features: " + ", ".join(f"{a} {b:.2f}" for a, b in imp), "", "Readable rules (depth-3 tree; value = predicted 10-day excess):", export_text(tr, feature_names=fn, decimals=3), ""]
            return out
        Xa, ya = rows_of(["cycle 2 (train A)"])
        Lx += [""] + report("2. FIT A: train on cycle 2, test on cycle 1 / bear year / recent", ["cycle 2 (train A)"], ["cycle 1", "bear year", "recent"], Xa, ya)
        PER["cycle 2 (test)"] = PER["cycle 2 (train A)"]; idx["cycle 2 (test)"] = idx["cycle 2 (train A)"]
        Xb, yb = rows_of(["cycle 1", "bear year"])
        Lx += report("3. FIT B (reverse): train on cycle 1 + bear year, test on cycle 2 / recent", ["cycle 1", "bear year"], ["cycle 2 (test)", "recent"], Xb, yb)
        del PER["cycle 2 (test)"]
        out_all += Lx
    out_all += ["HOW TO READ: 'avg excess/trade' = top-3 picks (of the top-K by size) vs the average of the top-K, after costs, every 5th day. Only trust a pattern that is positive on EVERY unseen period with chance p below about 0.1.",
                "'worst-3 excess' = the model's lowest-ranked 3 vs average (no cost): a model with real information should show a clearly NEGATIVE number here. 'chance p' = how often a random shift of the model's own scores did as well (keeps score persistence).",
                "With ~35 features, one or two will show YES in the single-feature table by pure chance (checked on random data): only believe a YES whose IC is also meaningfully large (about 0.03+ in every period) and that the model uses.",
                "Size rank is traded value, not market cap, and the pool is survivors, so treat positive results as leads to confirm live, not proof."]
    text = "\n".join(out_all); open(os.path.join(scanner.HERE, "lab24_summary.txt"), "w").write(text + "\n"); print(text)
    try: scanner.notify("Strategy lab 24 finished", "Model hunt done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
